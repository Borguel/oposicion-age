from datetime import date, datetime, timedelta
from google.cloud import firestore

from oposiciones import OPOSICION_POR_DEFECTO
from email_utils import enviar_email_bienvenida
from marketing_utils import sincronizar_contacto as sincronizar_contacto_marketing
from planes import DURACION_PRUEBA_DIAS, prueba_activa, resolver_plan_efectivo, resumen_prueba_cuenta, tiene_plan_de_pago_activo
from dominios_desechables import es_dominio_email_desechable
from utils import calcular_resultado_test, ejecutar_en_transaccion

# Ya no hay una prueba gratuita global por cuenta: cada oposición arranca la
# suya al activarse explícitamente (ver activar_oposicion_usuario más abajo),
# no todas de golpe al crear la cuenta -- así una cuenta nueva solo puede
# "gastar" la prueba de 7 días en UNA oposición a la vez salvo que el propio
# usuario decida añadir otra, en vez de tener las 3 activas desde el
# principio (que permitía multiplicar el uso efectivo contra los límites por
# herramienta durante esos 7 días).


def registrar_actividad_racha(db, usuario_id):
    """Suma el día de hoy a la racha de estudio del usuario (para el
    indicador motivacional de Mi Cuenta). Se llama cada vez que guarda algún
    resultado real de estudio (test, esquema, o contenido desde PDF), nunca
    más de una vez por día natural."""
    hoy = date.today()
    ref = db.collection("usuarios").document(usuario_id)
    doc = ref.get()
    datos = (doc.to_dict() or {}).get("racha") or {}
    ultima_fecha_str = datos.get("ultima_fecha")
    racha_actual = datos.get("racha_actual", 0)
    racha_maxima = datos.get("racha_maxima", 0)

    if ultima_fecha_str:
        try:
            ultima_fecha = date.fromisoformat(ultima_fecha_str)
        except ValueError:
            ultima_fecha = None
        if ultima_fecha == hoy:
            return
        if ultima_fecha and (hoy - ultima_fecha).days == 1:
            racha_actual += 1
        else:
            racha_actual = 1
    else:
        racha_actual = 1

    racha_maxima = max(racha_maxima, racha_actual)
    ref.update({
        "racha": {
            "ultima_fecha": hoy.isoformat(),
            "racha_actual": racha_actual,
            "racha_maxima": racha_maxima
        }
    })

def inicializar_estadisticas_usuario(db, usuario_id, email=None, email_verificado=True):
    """Crea el documento usuarios/{uid} la primera vez que se ve a este
    usuario (se llama en cada petición autenticada, ver
    auth_utils.requiere_login, así que en el resto de peticiones no hace
    nada más que la comprobación de existencia). No activa ninguna oposición
    por sí sola -- eso es una acción explícita del usuario, ver
    activar_oposicion_usuario más abajo.

    Bug real (11/08/2026, reportado por el usuario: "le han llegado tres
    mensajes de bienvenida"): al registrarse, el frontend dispara varias
    peticiones autenticadas casi a la vez (GET /mi-perfil desde el listener
    global de auth.js, POST /registrar-usuario del propio formulario de
    alta...), todas pasando por requiere_login -> esta función. La versión
    anterior hacía un simple "snap = doc_ref.get(); if not snap.exists:
    doc_ref.set(...)" -- comprobar-y-actuar sin ninguna atomicidad, así que
    dos o tres de esas peticiones podían leer "no existe" ANTES de que
    ninguna hubiera escrito todavía, y las tres acababan creando el
    documento y mandando el correo de bienvenida. Envolver la comprobación
    y la creación en una única transacción de Firestore (ver
    utils.ejecutar_en_transaccion) hace que, ante ese mismo empate, solo
    una gane y cree el documento de verdad -- las demás, al reintentar
    dentro de la transacción, ya lo encuentran creado y no hacen nada. El
    correo se manda FUERA de la transacción (una función de transacción
    puede reintentarse varias veces ante contención real, y no queremos
    mandar un correo por cada reintento), solo si esta llamada fue
    realmente la que creó el documento."""
    doc_ref = db.collection("usuarios").document(usuario_id)

    def _crear_si_no_existe(transaction):
        snap = doc_ref.get(transaction=transaction)
        if snap.exists:
            return False
        transaction.set(doc_ref, {
            # Estadísticas de tests/esquemas del temario oficial, UNA POR
            # OPOSICIÓN (un usuario que estudia AGE y GACE a la vez quiere ver
            # su progreso de cada una por separado):
            # estadisticas: { "AGE": {tests_realizados, total_aciertos, ...}, "GACE": {...} }
            "estadisticas": {},
            "ultima_actividad": None,
            "notas_personales": "",
            "resumen_mensual": {},
            "recomendaciones_ia": [],
            # Herramientas sobre PDF propio (resumen/test/tarjetas/esquema
            # desde un documento que sube el usuario): esto SÍ es global, no
            # depende de ninguna oposición ni de su temario oficial.
            "tests_pdf_realizados": 0,
            "resumenes_pdf_realizados": 0,
            "esquemas_pdf_realizados": 0,
            "tarjetas_pdf_realizados": 0,
            "total_archivos_procesados": 0,
            # Suma de páginas de todos los PDF distintos que se han subido
            # (se incrementa una sola vez por documento nuevo, en
            # documentos_pdf.obtener_o_crear_documento, no aquí).
            "paginas_analizadas": 0,
            "fecha_creacion": datetime.utcnow().isoformat(),
            # CAMPOS DE IDENTIDAD Y SUSCRIPCIÓN (Firebase Auth + Stripe)
            "email": email,
            "nombre": "",
            "apellidos": "",
            "telefono": "",
            "direccion": "",
            # Un usuario tiene un único cliente de Stripe (global), pero puede
            # tener una suscripción independiente POR OPOSICIÓN, ya que cada
            # oposición se contrata, se prueba y se paga por separado.
            # suscripciones: { "AGE": {plan, prueba_fin, stripe_subscription_id,
            #                          subscription_status, plan_updated_at,
            #                          current_period_end}, "GACE": {...} }
            # Vacío hasta que el usuario active su primera oposición (ver
            # activar_oposicion_usuario) -- una cuenta recién creada no ve
            # ninguna herramienta todavía, solo el selector para elegirla.
            "stripe_customer_id": None,
            "suscripciones": {},
        })
        return True

    creado = ejecutar_en_transaccion(db, _crear_si_no_existe)
    if creado:
        enviar_email_bienvenida(email)
        sincronizar_contacto_marketing(email, estado="prueba")
        return

    # El documento ya existía: si el email se acaba de verificar (o, más
    # raro, se detecta ahora que su dominio no era desechable) y había
    # alguna oposición ya activada pero con la prueba todavía pendiente de
    # arrancar (ver activar_oposicion_usuario), arrancarla ahora en todas
    # ellas -- no se pierde por no haberse verificado el email en el momento
    # de activarla.
    permite_prueba = bool(email_verificado) and not es_dominio_email_desechable(email)
    if not permite_prueba:
        return
    datos = doc_ref.get().to_dict() or {}
    pendientes = [
        oid for oid, sub in (datos.get("suscripciones", {}) or {}).items()
        if (sub or {}).get("plan", "gratis") == "gratis" and not (sub or {}).get("prueba_fin")
    ]
    if pendientes:
        fin = (datetime.utcnow() + timedelta(days=DURACION_PRUEBA_DIAS)).isoformat()
        doc_ref.update({f"suscripciones.{oid}.prueba_fin": fin for oid in pendientes})


def activar_oposicion_usuario(db, usuario_id, oposicion, email=None, email_verificado=True):
    """Da de alta al usuario en una oposición nueva, a petición suya (p. ej.
    el botón "Quiero estudiar esta oposición" de Zona opositor): crea su
    entrada suscripciones.<OP> con plan "gratis" y arranca su prueba
    gratuita de 7 días PARA ESA OPOSICIÓN CONCRETA, si el email ya está
    verificado y su dominio no es de correo desechable conocido (mismas
    comprobaciones antiabuso que antes se hacían una sola vez por cuenta,
    ver inicializar_estadisticas_usuario) -- si no, la deja con
    prueba_fin=None (pendiente) y el siguiente inicializar_estadisticas_usuario
    la arrancará en cuanto proceda.

    Idempotente: si el usuario ya tenía esta oposición activada (aunque solo
    sea con el plan gratis, o con una prueba ya terminada) no la toca, para
    no poder alargar una prueba en marcha ni reiniciar la de alguien a quien
    ya se le terminó -- "activar" solo tiene efecto la primera vez."""
    doc_ref = db.collection("usuarios").document(usuario_id)
    snap = doc_ref.get()
    if not snap.exists:
        inicializar_estadisticas_usuario(db, usuario_id, email=email, email_verificado=email_verificado)
        snap = doc_ref.get()
    datos = snap.to_dict() or {}
    if oposicion in (datos.get("suscripciones", {}) or {}):
        return

    permite_prueba = bool(email_verificado) and not es_dominio_email_desechable(email)
    doc_ref.update({
        f"suscripciones.{oposicion}.plan": "gratis",
        f"suscripciones.{oposicion}.prueba_fin": (datetime.utcnow() + timedelta(days=DURACION_PRUEBA_DIAS)).isoformat() if permite_prueba else None,
        f"suscripciones.{oposicion}.plan_updated_at": datetime.utcnow().isoformat(),
    })

def actualizar_estadisticas_test(db, usuario_id, oposicion, aciertos, fallos, temas, tiempo_en_segundos, tipo="personalizado", puntuacion_final=None, rendimiento_temas=None, blancos=0):
    # Lectura + cálculo + escritura van dentro de una única transacción de
    # Firestore -- varios de los campos de aquí abajo (puntuacion_media_test,
    # historial_tests recortado a 50, rendimiento_por_tema acumulado por
    # tema) no son contadores simples que firestore.Increment pueda
    # expresar, así que la forma segura de evitar que dos tests guardados
    # casi a la vez (dos pestañas, un reintento) se pisen entre sí es hacer
    # atómico el ciclo entero de lectura-cálculo-escritura, no solo la
    # escritura final.
    doc_ref = db.collection("usuarios").document(usuario_id)

    def _actualizar(transaction):
        usuario = doc_ref.get(transaction=transaction).to_dict() or {}
        stats = (usuario.get("estadisticas", {}) or {}).get(oposicion, {}) or {}

        total_tests = stats.get("tests_realizados", 0) + 1
        total_aciertos = stats.get("total_aciertos", 0) + aciertos
        total_fallos = stats.get("total_fallos", 0) + fallos
        temas_test = list(set(stats.get("temas_test", []) + temas))
        tiempo_total = stats.get("tiempo_total", 0) + tiempo_en_segundos

        # Rendimiento acumulado por tema (aciertos/fallos/blancos), para
        # poder mostrar no solo qué temas se han tocado sino en cuáles se
        # rinde mejor o peor -- se acumula sumando sobre lo que ya hubiera
        # guardado.
        rendimiento_por_tema = stats.get("rendimiento_por_tema", {}) or {}
        for tema_id, datos in (rendimiento_temas or {}).items():
            acumulado = rendimiento_por_tema.get(tema_id, {"aciertos": 0, "fallos": 0, "blancos": 0})
            rendimiento_por_tema[tema_id] = {
                "aciertos": acumulado.get("aciertos", 0) + datos.get("aciertos", 0),
                "fallos": acumulado.get("fallos", 0) + datos.get("fallos", 0),
                "blancos": acumulado.get("blancos", 0) + datos.get("blancos", 0),
            }

        puntuacion_calculada, _nota_sobre_10, resultado = calcular_resultado_test(aciertos, fallos, blancos)
        puntuacion = puntuacion_final if puntuacion_final is not None else puntuacion_calculada
        puntuacion_media = round(total_aciertos / total_tests, 2) if total_tests else 0

        aprobados = stats.get("tests_aprobados", 0)
        suspendidos = stats.get("tests_suspendidos", 0)
        if resultado == "aprobado":
            aprobados += 1
        else:
            suspendidos += 1

        historial = stats.get("historial_tests", [])
        historial.append({
            "fecha": datetime.utcnow().isoformat(),
            "aciertos": aciertos,
            "fallos": fallos,
            "blancos": blancos,
            "temas": temas,
            "tiempo": tiempo_en_segundos,
            "tipo": tipo,
            "puntuacion_final": puntuacion,
            "resultado": resultado
        })
        if len(historial) > 50:
            historial = historial[-50:]

        prefijo = f"estadisticas.{oposicion}."
        transaction.update(doc_ref, {
            f"{prefijo}tests_realizados": total_tests,
            f"{prefijo}total_aciertos": total_aciertos,
            f"{prefijo}total_fallos": total_fallos,
            f"{prefijo}tests_aprobados": aprobados,
            f"{prefijo}tests_suspendidos": suspendidos,
            f"{prefijo}temas_test": temas_test,
            f"{prefijo}rendimiento_por_tema": rendimiento_por_tema,
            f"{prefijo}tiempo_total": tiempo_total,
            f"{prefijo}puntuacion_media_test": puntuacion_media,
            f"{prefijo}historial_tests": historial,
            f"{prefijo}ultimo_test": {
                "aciertos": aciertos,
                "fallos": fallos,
                "temas": temas,
                "tiempo": tiempo_en_segundos,
                "tipo": tipo,
                "puntuacion_final": puntuacion,
                "resultado": resultado,
                "fecha": datetime.utcnow().isoformat()
            },
            "ultima_actividad": datetime.utcnow().isoformat()
        })

    ejecutar_en_transaccion(db, _actualizar)

def actualizar_estadisticas_esquema(db, usuario_id, oposicion, temas):
    doc_ref = db.collection("usuarios").document(usuario_id)
    usuario = doc_ref.get().to_dict() or {}
    stats = (usuario.get("estadisticas", {}) or {}).get(oposicion, {}) or {}

    total_esquemas = stats.get("esquemas_realizados", 0) + 1
    temas_esquemas = list(set(stats.get("temas_esquemas", []) + temas))

    prefijo = f"estadisticas.{oposicion}."
    doc_ref.update({
        f"{prefijo}esquemas_realizados": total_esquemas,
        f"{prefijo}temas_esquemas": temas_esquemas,
        "ultima_actividad": datetime.utcnow().isoformat()
    })

def obtener_resumen_progreso(db, usuario_id, oposicion=OPOSICION_POR_DEFECTO):
    doc_ref = db.collection("usuarios").document(usuario_id)
    doc = doc_ref.get()
    if not doc.exists:
        return {}

    datos = doc.to_dict()
    stats = (datos.get("estadisticas", {}) or {}).get(oposicion, {}) or {}

    resumen = {
        "oposicion": oposicion,
        "tests_realizados": stats.get("tests_realizados", 0),
        "tests_aprobados": stats.get("tests_aprobados", 0),
        "tests_suspendidos": stats.get("tests_suspendidos", 0),
        "total_aciertos": stats.get("total_aciertos", 0),
        "total_fallos": stats.get("total_fallos", 0),
        "puntuacion_media_test": stats.get("puntuacion_media_test", 0),
        "esquemas_realizados": stats.get("esquemas_realizados", 0),
        "tiempo_total": stats.get("tiempo_total", 0),
        "temas_test": stats.get("temas_test", []),
        "temas_esquemas": stats.get("temas_esquemas", []),
        "rendimiento_por_tema": stats.get("rendimiento_por_tema", {}),
        "ultimo_test": stats.get("ultimo_test", {}),
        "historial_tests": stats.get("historial_tests", []),
        "ultima_actividad": datos.get("ultima_actividad", None),
        # Herramientas sobre PDF propio: global, no depende de la oposición
        "tests_pdf_realizados": datos.get("tests_pdf_realizados", 0),
        "resumenes_pdf_realizados": datos.get("resumenes_pdf_realizados", 0),
        "esquemas_pdf_realizados": datos.get("esquemas_pdf_realizados", 0),
        "tarjetas_pdf_realizados": datos.get("tarjetas_pdf_realizados", 0),
        "total_archivos_procesados": datos.get("total_archivos_procesados", 0),
        "fecha_creacion": datos.get("fecha_creacion")
    }

    return resumen

# NUEVA FUNCIÓN: Actualizar estadísticas para contenido desde PDF (global,
# no depende de ninguna oposición -- ver nota en inicializar_estadisticas_usuario)
def actualizar_estadisticas_pdf(db, usuario_id, tipo_pdf):
    """Actualizar estadísticas cuando se guarda contenido desde PDF"""
    doc_ref = db.collection("usuarios").document(usuario_id)

    # Verificar si el usuario existe
    if not doc_ref.get().exists:
        inicializar_estadisticas_usuario(db, usuario_id)

    # Preparar actualizaciones según el tipo de contenido PDF
    field_updates = {
        "ultima_actividad": datetime.utcnow().isoformat(),
        "total_archivos_procesados": firestore.Increment(1)
    }

    if tipo_pdf == "test_pdf":
        field_updates["tests_pdf_realizados"] = firestore.Increment(1)
    elif tipo_pdf == "resumen_pdf":
        field_updates["resumenes_pdf_realizados"] = firestore.Increment(1)
    elif tipo_pdf == "esquema_pdf":
        field_updates["esquemas_pdf_realizados"] = firestore.Increment(1)
    elif tipo_pdf == "tarjetas_pdf":
        field_updates["tarjetas_pdf_realizados"] = firestore.Increment(1)

    # Aplicar actualizaciones
    doc_ref.update(field_updates)

def actualizar_suscripcion(db, usuario_id, oposicion, plan=None, stripe_customer_id=None,
                            stripe_subscription_id=None, subscription_status=None,
                            current_period_end=None, cancelar_al_final_periodo=None):
    """Sincroniza en Firestore el estado de la suscripción de Stripe de un
    usuario PARA UNA OPOSICIÓN CONCRETA (cada oposición tiene su propia
    suscripción de Stripe, aunque compartan el mismo Customer). Solo se
    actualizan los campos que se pasan (distintos de None), salvo
    stripe_customer_id, que si se pasa se guarda aunque sea la primera vez."""
    doc_ref = db.collection("usuarios").document(usuario_id)
    if not doc_ref.get().exists:
        inicializar_estadisticas_usuario(db, usuario_id)

    prefijo = f"suscripciones.{oposicion}."
    field_updates = {f"{prefijo}plan_updated_at": datetime.utcnow().isoformat()}
    if stripe_customer_id is not None:
        field_updates["stripe_customer_id"] = stripe_customer_id
    if plan is not None:
        field_updates[f"{prefijo}plan"] = plan
    if stripe_subscription_id is not None:
        field_updates[f"{prefijo}stripe_subscription_id"] = stripe_subscription_id
    if subscription_status is not None:
        field_updates[f"{prefijo}subscription_status"] = subscription_status
    if current_period_end is not None:
        field_updates[f"{prefijo}current_period_end"] = current_period_end
    # Distingue "activa y se renovará" de "activa pero programada para
    # cancelarse al final del periodo ya pagado" (ver /cancelar-suscripcion
    # y /reactivar-suscripcion en blueprints/pagos.py) -- subscription_status
    # se queda en "active" en ambos casos hasta que el periodo termina de
    # verdad, así que sin este campo el frontend no podría distinguirlos.
    if cancelar_al_final_periodo is not None:
        field_updates[f"{prefijo}cancelar_al_final_periodo"] = cancelar_al_final_periodo

    doc_ref.update(field_updates)

def obtener_perfil_usuario(db, usuario_id, oposicion=None, es_admin=False):
    """Datos mínimos de plan/suscripción para pintar la UI del frontend.
    Si se pasa `oposicion`, además de la lista completa de suscripciones se
    incluyen plan/subscription_status/current_period_end de esa oposición
    concreta (para no obligar al frontend a leer el mapa completo).

    `es_admin` reproduce aquí el mismo bypass que ya tiene
    `auth_utils.requiere_plan()` para las rutas protegidas: un
    administrador (custom claim de Firebase, no depende de Firestore) no
    debe ver el banner ni la pantalla de bloqueo de prueba/plan en el
    frontend aunque su cuenta no tenga ninguna suscripción de pago."""
    doc = db.collection("usuarios").document(usuario_id).get()
    if not doc.exists:
        perfil = {
            "suscripciones": {}, "email": None, "nombre": "", "apellidos": "", "telefono": "", "direccion": "",
            "prueba_activa": False, "prueba_fin": None, "tiene_plan_de_pago": False,
        }
        if oposicion:
            perfil.update({
                "oposicion": oposicion,
                "plan": "premium" if es_admin else "gratis",
                "subscription_status": "active" if es_admin else None,
                "current_period_end": None,
                "oposicion_activada": False,
            })
        return perfil

    datos = doc.to_dict() or {}
    suscripciones = datos.get("suscripciones", {}) or {}
    # Sin oposición concreta, "prueba_activa"/"prueba_fin" son un resumen
    # agregado de CUALQUIER oposición que siga en prueba (ver
    # resumen_prueba_cuenta) -- se sobrescriben más abajo con los de la
    # oposición pedida en cuanto se conoce, que es el caso normal (el
    # frontend siempre pide /mi-perfil con ?oposicion=, ver assets/plan.js).
    en_prueba_cuenta, prueba_fin_cuenta = resumen_prueba_cuenta(datos)
    perfil = {
        "email": datos.get("email"),
        "nombre": datos.get("nombre", ""),
        "apellidos": datos.get("apellidos", ""),
        "telefono": datos.get("telefono", ""),
        "direccion": datos.get("direccion", ""),
        "suscripciones": suscripciones,
        # El frontend usa esto para pintar el banner de cuenta atrás y saber
        # si tiene que bloquear la página (ver assets/plan.js).
        "prueba_activa": en_prueba_cuenta,
        "prueba_fin": prueba_fin_cuenta,
        # Si ya paga por otra oposición, el frontend no debe hablarle de
        # "prueba" (ni cuenta atrás ni "ha terminado") al mirar una que
        # todavía no ha contratado -- ver tiene_plan_de_pago_activo en
        # planes.py y su uso en assets/plan.js / assets/auth.js.
        "tiene_plan_de_pago": tiene_plan_de_pago_activo(datos),
    }
    if oposicion:
        sub_oposicion = suscripciones.get(oposicion, {}) or {}
        if es_admin:
            plan, sub = "premium", {"subscription_status": "active"}
        else:
            plan, sub = resolver_plan_efectivo(datos, oposicion=oposicion)
        perfil.update({
            "oposicion": oposicion,
            "plan": plan,
            "subscription_status": sub.get("subscription_status"),
            "current_period_end": sub.get("current_period_end"),
            # Prueba DE ESTA OPOSICIÓN concreta -- ver prueba_activa en
            # planes.py: cada oposición tiene la suya, independiente de las
            # demás. sub (arriba) puede venir ya "aumentado" a trialing por
            # resolver_plan_efectivo; sub_oposicion es siempre el dato crudo
            # guardado, que es lo que hace falta para saber la fecha real.
            "prueba_activa": prueba_activa(sub_oposicion),
            "prueba_fin": sub_oposicion.get("prueba_fin"),
            # ¿Ya tiene esta oposición activada (aunque sea en gratis/prueba)
            # o todavía no ha dado el primer paso en ella? El frontend lo usa
            # para decidir si ofrece "Empieza tu prueba gratis" o ya pasa
            # directo a las opciones de pago (ver planes/script.js).
            "oposicion_activada": oposicion in suscripciones,
        })
    return perfil
