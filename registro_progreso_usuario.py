from datetime import datetime
from google.cloud import firestore

from oposiciones import OPOSICION_POR_DEFECTO
from email_utils import enviar_email_bienvenida

def inicializar_estadisticas_usuario(db, usuario_id, email=None):
    doc_ref = db.collection("usuarios").document(usuario_id)
    if not doc_ref.get().exists:
        doc_ref.set({
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
            "fecha_creacion": datetime.utcnow().isoformat(),
            # CAMPOS DE IDENTIDAD Y SUSCRIPCIÓN (Firebase Auth + Stripe)
            "email": email,
            "nombre": "",
            "apellidos": "",
            "telefono": "",
            "direccion": "",
            # Un usuario tiene un único cliente de Stripe (global), pero puede
            # tener una suscripción independiente POR OPOSICIÓN, ya que cada
            # oposición se contrata y se paga por separado.
            # suscripciones: { "AGE": {plan, stripe_subscription_id, subscription_status,
            #                          plan_updated_at, current_period_end}, "GACE": {...} }
            "stripe_customer_id": None,
            "suscripciones": {},
        })
        enviar_email_bienvenida(email)

def actualizar_estadisticas_test(db, usuario_id, oposicion, aciertos, fallos, temas, tiempo_en_segundos, tipo="personalizado", puntuacion_final=None, rendimiento_temas=None):
    doc_ref = db.collection("usuarios").document(usuario_id)
    usuario = doc_ref.get().to_dict() or {}
    stats = (usuario.get("estadisticas", {}) or {}).get(oposicion, {}) or {}

    total_tests = stats.get("tests_realizados", 0) + 1
    total_aciertos = stats.get("total_aciertos", 0) + aciertos
    total_fallos = stats.get("total_fallos", 0) + fallos
    temas_test = list(set(stats.get("temas_test", []) + temas))
    tiempo_total = stats.get("tiempo_total", 0) + tiempo_en_segundos

    # Rendimiento acumulado por tema (aciertos/fallos/blancos), para poder
    # mostrar no solo qué temas se han tocado sino en cuáles se rinde mejor
    # o peor -- se acumula sumando sobre lo que ya hubiera guardado.
    rendimiento_por_tema = stats.get("rendimiento_por_tema", {}) or {}
    for tema_id, datos in (rendimiento_temas or {}).items():
        acumulado = rendimiento_por_tema.get(tema_id, {"aciertos": 0, "fallos": 0, "blancos": 0})
        rendimiento_por_tema[tema_id] = {
            "aciertos": acumulado.get("aciertos", 0) + datos.get("aciertos", 0),
            "fallos": acumulado.get("fallos", 0) + datos.get("fallos", 0),
            "blancos": acumulado.get("blancos", 0) + datos.get("blancos", 0),
        }

    total_preguntas = aciertos + fallos
    puntuacion = puntuacion_final if puntuacion_final is not None else round(aciertos / total_preguntas, 2) if total_preguntas else 0
    puntuacion_media = round(total_aciertos / total_tests, 2) if total_tests else 0

    aprobados = stats.get("tests_aprobados", 0)
    suspendidos = stats.get("tests_suspendidos", 0)
    if puntuacion >= 0.5:
        aprobados += 1
        resultado = "aprobado"
    else:
        suspendidos += 1
        resultado = "suspendido"

    historial = stats.get("historial_tests", [])
    historial.append({
        "fecha": datetime.utcnow().isoformat(),
        "aciertos": aciertos,
        "fallos": fallos,
        "temas": temas,
        "tiempo": tiempo_en_segundos,
        "tipo": tipo,
        "puntuacion_final": puntuacion,
        "resultado": resultado
    })
    if len(historial) > 50:
        historial = historial[-50:]

    prefijo = f"estadisticas.{oposicion}."
    doc_ref.update({
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
                            current_period_end=None):
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

    doc_ref.update(field_updates)

def obtener_perfil_usuario(db, usuario_id, oposicion=None):
    """Datos mínimos de plan/suscripción para pintar la UI del frontend.
    Si se pasa `oposicion`, además de la lista completa de suscripciones se
    incluyen plan/subscription_status/current_period_end de esa oposición
    concreta (para no obligar al frontend a leer el mapa completo)."""
    doc = db.collection("usuarios").document(usuario_id).get()
    if not doc.exists:
        perfil = {"suscripciones": {}, "email": None, "nombre": "", "apellidos": "", "telefono": "", "direccion": ""}
        if oposicion:
            perfil.update({"oposicion": oposicion, "plan": "gratis", "subscription_status": None, "current_period_end": None})
        return perfil

    datos = doc.to_dict() or {}
    suscripciones = datos.get("suscripciones", {}) or {}
    perfil = {
        "email": datos.get("email"),
        "nombre": datos.get("nombre", ""),
        "apellidos": datos.get("apellidos", ""),
        "telefono": datos.get("telefono", ""),
        "direccion": datos.get("direccion", ""),
        "suscripciones": suscripciones,
    }
    if oposicion:
        sub = suscripciones.get(oposicion, {}) or {}
        perfil.update({
            "oposicion": oposicion,
            "plan": sub.get("plan", "gratis"),
            "subscription_status": sub.get("subscription_status"),
            "current_period_end": sub.get("current_period_end"),
        })
    return perfil
