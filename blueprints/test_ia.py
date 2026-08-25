"""Generación de tests/análisis a partir del TEMARIO oficial (no de un PDF
subido por el usuario -- eso vive en blueprints/pdf_ia.py)."""
import json
import logging
import queue
import random
import threading
import uuid

from flask import Blueprint, Response, g, jsonify, request, stream_with_context

from firebase_setup import db
from auth_utils import requiere_plan, obtener_oposicion_solicitada
from rate_limiter import limiter
from limites_uso import verificar_limite_uso, registrar_uso, devolver_uso, reservar_uso, reservar_uso_multiple
from oposiciones import OPOSICIONES, OPOSICION_POR_DEFECTO, coleccion_temario, coleccion_examenes_oficiales, coleccion_psicotecnico, oposicion_valida
from utils import seleccionar_preguntas_con_cuota, obtener_titulos_temas_reales, calcular_pesos_reales_por_bloque, obtener_preguntas_examenes_oficiales, obtener_preguntas_psicotecnico
from generador_preguntas_verificado import generar_test_verificado
from errores_generacion import registrar_error_generacion
from deepseek_utils import call_deepseek_api
from registro_progreso_usuario import obtener_resumen_progreso
from banco_fallos import ordenar_por_prioridad_repaso as ordenar_fallos_por_prioridad
from banco_favoritas import ordenar_por_prioridad_repaso as ordenar_favoritas_por_prioridad
import generacion_control

logger = logging.getLogger(__name__)

bp = Blueprint("test_ia", __name__)

# El Test Personalizado tiene DOS cupos independientes que se comprueban y
# se cobran a la vez -- un tope diario y un tope mensual adicional sobre el
# mismo consumo en preguntas (ver limites_uso.py) -- para que un básico no
# pueda agotar de golpe el cupo mensual estirando el diario 30 días seguidos.
TIPOS_CUOTA_TEST_PERSONALIZADO = ("test_avanzado_verificado", "test_avanzado_verificado_mensual")


# Test Personalizado en streaming (Server-Sent Events): cada pregunta ancla
# a un artículo real del temario y se verifica con una segunda llamada
# independiente antes de aceptarla (ver generador_preguntas_verificado.py),
# así que generar un test completo tarda bastante más que antes -- SSE deja
# la conexión abierta con progreso REAL ("pregunta 4 de 20") en vez de un
# único fetch bloqueante sin ninguna señal de que sigue en marcha. Mismo
# patrón que ya se usa en /tu-tutor/stream, adaptado aquí con una cola
# porque generar_test_verificado reporta el progreso vía callback (se
# ejecuta en paralelo con un ThreadPoolExecutor) en vez de ser un
# generador Python en sí.
@bp.route("/generar-test-avanzado", methods=["POST"])
@limiter.limit("5 per minute")
@requiere_plan(db, "basico")
def generar_test_avanzado_route():
    data = request.get_json()
    logger.info("Petición recibida en /generar-test-avanzado: %s", data)
    temas = data.get("temas", [])
    try:
        num_preguntas = max(1, min(100, int(data.get("num_preguntas", 5))))
    except (TypeError, ValueError):
        num_preguntas = 5
    # "equitativo" (por defecto, cuota igual entre temas) o "realista" (más
    # preguntas de los bloques que más pesan en los exámenes oficiales ya
    # cargados) -- ver utils.repartir_cupos_por_tema_realista. Cualquier
    # valor no reconocido se trata como "equitativo" (el de siempre).
    modo_reparto = data.get("modo_reparto", "equitativo")
    if modo_reparto not in ("equitativo", "realista"):
        modo_reparto = "equitativo"
    coleccion = coleccion_temario(g.oposicion)
    oposicion = g.oposicion
    uid = g.uid
    plan_actual = g.plan_actual

    # El uso se comprueba Y se cobra AQUÍ, por adelantado, en una única
    # transacción atómica (reservar_uso_multiple) -- no al llegar el evento
    # "fin": la generación corre en un hilo de fondo que sigue gastando en
    # DeepSeek aunque el cliente corte la conexión SSE, y en ese caso el
    # generador de abajo nunca llega a un "registrar_uso" final -- cobrar al
    # final dejaba un hueco para saltarse la cuota abriendo y abortando la
    # petición en bucle. Que la comprobación y el cobro fueran dos pasos
    # separados (verificar_limite_uso sin transacción + registrar_uso aparte)
    # dejaba además una ventana de carrera propia: dos peticiones concurrentes
    # del mismo usuario podían pasar la comprobación las dos a la vez antes de
    # que ninguna llegara a registrar_uso. Si la generación acaba fallando de
    # verdad (0 preguntas), el hilo lo devuelve con devolver_uso.
    #
    # El cupo de este test se mide en PREGUNTAS, no en "número de tests": se
    # cobran tantas unidades como preguntas se piden, así un test de 100 gasta
    # 100 y uno de 10 gasta 10 (consumo justo). El usuario no ve el contador.
    permitido, mensaje_error = reservar_uso_multiple(
        db, uid, TIPOS_CUOTA_TEST_PERSONALIZADO, plan_actual, cantidad=num_preguntas
    )
    if not permitido:
        return jsonify({"error": mensaje_error}), 429

    def generar():
        eventos = queue.Queue()
        # Bug real (24/08/2026): esta generación no tenía NINGÚN mecanismo
        # de cancelación -- a diferencia de las 4 herramientas de PDF (ver
        # generacion_control.py), ni borrar la cuenta a mitad de una
        # generación ni ningún otro camino podían pararla, así que siempre
        # agotaba las preguntas ya cobradas por adelantado (reservar_uso_
        # multiple, arriba). No hay un documento_id real aquí (el test se
        # genera desde el temario, no desde un PDF subido), así que se usa
        # un identificador propio generado en el momento -- solicitar_
        # parada_todas(uid), que ya usan eliminar_cuenta_usuario y el
        # webhook de Stripe, no necesita conocerlo de antemano.
        clave_generacion = uuid.uuid4().hex
        evento_parada = generacion_control.registrar(uid, clave_generacion, "test_avanzado")

        def _en_hilo_de_fondo():
            def on_progreso(evento_progreso):
                # "pregunta" se manda como evento aparte (no como parte de
                # "progreso") para no romper al consumidor actual del
                # evento "progreso", que solo espera completadas/total --
                # así el frontend puede ignorar "pregunta" sin cambios si
                # no le interesa (p.ej. tests con pocas preguntas).
                pregunta = evento_progreso.pop("pregunta", None)
                eventos.put({"tipo": "progreso", **evento_progreso})
                if pregunta:
                    eventos.put({
                        "tipo": "pregunta", "pregunta": pregunta,
                        "completadas": evento_progreso["completadas"], "total": evento_progreso["total"],
                    })
            try:
                resultado = generar_test_verificado(
                    db, temas=temas, num_preguntas=num_preguntas,
                    coleccion=coleccion, oposicion=oposicion, on_progreso=on_progreso,
                    modo_reparto=modo_reparto, uid=uid, evento_parada=evento_parada,
                )
            except Exception:
                logger.exception("Error al generar el test personalizado verificado")
                resultado = {"test": [], "error": "Error inesperado al generar el test"}
            finally:
                generacion_control.desregistrar(uid, clave_generacion, "test_avanzado")
            if not resultado.get("test"):
                for tipo_cuota in TIPOS_CUOTA_TEST_PERSONALIZADO:
                    devolver_uso(db, uid, tipo_cuota, plan_actual, cantidad=num_preguntas)
            eventos.put({"tipo": "fin", **resultado})

        hilo = threading.Thread(target=_en_hilo_de_fondo, daemon=True)
        hilo.start()

        while True:
            evento = eventos.get()
            yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
            if evento["tipo"] == "fin":
                break

    return Response(
        stream_with_context(generar()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
    )


# Ruta PÚBLICA (sin login, sin @requiere_plan) para la demo de la home: deja
# probar el producto a quien llega por SEO antes de registrarse. Sirve
# preguntas reales de exámenes oficiales YA CARGADOS en Firestore -- no
# genera nada con DeepSeek, así que no tiene coste de IA ni cuenta para
# ningún cupo de usuario. El límite general por IP de flask-limiter
# (default_limits en app.py) ya la protege de abuso, igual que a /health.
@bp.route("/demo/test-oficial", methods=["GET"])
def demo_test_oficial():
    oposicion = request.args.get("oposicion") or OPOSICION_POR_DEFECTO
    if not oposicion_valida(oposicion):
        oposicion = OPOSICION_POR_DEFECTO
    try:
        docs_pregunta = obtener_preguntas_examenes_oficiales(db, oposicion)
    except Exception:
        logger.exception("Error accediendo a Firestore en la demo")
        return jsonify({"error": "No se pudo acceder a Firestore"}), 500
    candidatas = [d for d in docs_pregunta if not d.get("psicotecnico")]
    if not candidatas:
        return jsonify({"oposicion": oposicion, "test": []}), 404
    seleccionadas = random.sample(candidatas, min(5, len(candidatas)))
    test = [{
        "pregunta": d.get("pregunta", ""),
        "opciones": {k.upper(): v for k, v in d.get("opciones", {}).items()},
        "respuesta_correcta": d.get("respuesta_correcta", "").upper(),
        "explicacion": d.get("explicacion", ""),
    } for d in seleccionadas]
    return jsonify({"oposicion": oposicion, "test": test})


@bp.route("/generar-test-oficial", methods=["POST"])
@requiere_plan(db, "basico")
def generar_test_oficial():
    data = request.get_json()
    logger.info("Ruta /generar-test-oficial llamada con datos: %s", data)
    # A diferencia del resto de herramientas, aquí NO se usa reservar_uso:
    # la cantidad a cobrar (cuántas preguntas hay realmente disponibles en
    # el banco tras filtrar) solo se conoce después de seleccionarlas, no
    # antes -- así que verificar y registrar siguen siendo dos pasos
    # separados, con la misma ventana de carrera teórica que el resto tenía
    # antes de este cambio. Impacto limitado: esta ruta no llama a ninguna
    # IA (lee de un banco ya cargado), así que no hay coste real de API en
    # juego, solo un contador anti-abuso.
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "test_oficial")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    try:
        # El tope sube a 120 (no 100) porque el simulacro oficial de Auxiliar
        # son 110 preguntas reales (60 primera parte + 50 segunda, ver
        # oposiciones.py) -- el resto de rutas de generación de test se
        # quedan en 100.
        num_preguntas = max(1, min(120, int(data.get("num_preguntas", 10))))
    except (TypeError, ValueError):
        num_preguntas = 10
    examenes_filtrados = data.get("examenes", [])
    temas_filtrados = data.get("temas", [])
    modo_reparto = data.get("modo_reparto", "equitativo")
    if modo_reparto not in ("equitativo", "realista"):
        modo_reparto = "equitativo"
    # Solo tiene efecto real en oposiciones con preguntas psicotécnicas en su
    # examen oficial (hoy, Auxiliar -- ver cargar_examen_oficial_auxiliar.py);
    # en el resto simplemente no hay ninguna pregunta con "psicotecnico": true
    # que excluir, así que el filtro es un no-op inofensivo.
    excluir_psicotecnicas = bool(data.get("excluir_psicotecnicas", False))
    logger.info("Número de preguntas solicitado: %s, exámenes filtrados: %s, temas filtrados: %s", num_preguntas, examenes_filtrados, temas_filtrados)
    coleccion = coleccion_examenes_oficiales(g.oposicion)
    try:
        docs_pregunta = obtener_preguntas_examenes_oficiales(db, g.oposicion)
    except Exception:
        logger.exception("Error accediendo a Firestore")
        return jsonify({"error": "No se pudo acceder a Firestore"}), 500
    preguntas = []
    for d in docs_pregunta:
        if examenes_filtrados:
            if d.get("examen", "").lower() not in [e.lower() for e in examenes_filtrados]:
                continue
        if excluir_psicotecnicas and d.get("psicotecnico"):
            continue
        opciones_originales = d.get("opciones", {})
        opciones_mayus = {k.upper(): v for k, v in opciones_originales.items()}
        preguntas.append({
            "pregunta": d.get("pregunta", ""),
            "opciones": opciones_mayus,
            "respuesta_correcta": d.get("respuesta_correcta", "").upper(),
            "explicacion": d.get("explicacion", ""),
            "examen": d.get("examen", ""),
            "numero": d.get("numero", 0),
            "tema_id": d.get("tema_id", ""),
            "psicotecnico": d.get("psicotecnico", False)
        })
    logger.info("Preguntas encontradas tras filtro en %s: %d", coleccion, len(preguntas))
    if not preguntas:
        return jsonify({"test": [], "mensaje": "Todavía no hay preguntas oficiales cargadas para esta oposición"}), 404
    pesos_por_bloque = calcular_pesos_reales_por_bloque(db, g.oposicion) if modo_reparto == "realista" else None
    seleccionadas = seleccionar_preguntas_con_cuota(preguntas, num_preguntas, temas_filtrados, modo_reparto=modo_reparto, pesos_por_bloque=pesos_por_bloque)
    logger.info("Preguntas seleccionadas: %d", len(seleccionadas))
    # Igual que en el Test Personalizado, el cupo se cobra en PREGUNTAS
    # realmente entregadas (no en el nº pedido, por si hay menos disponibles).
    if seleccionadas:
        registrar_uso(db, g.uid, "test_oficial", g.plan_actual, cantidad=len(seleccionadas))
    return jsonify({"test": seleccionadas})


def _seleccionar_preguntas_psicotecnico_equilibradas(candidatas, num_preguntas):
    """Reparte la selección entre categorías (sinónimos, antónimos, contar
    cubos, matriz Raven...) en vez de un random.sample() liso, que con un
    banco tan desigual (unas categorías tienen 18 preguntas, otras 3) podía
    perfectamente encadenar un montón de preguntas seguidas del mismo tipo
    -- justo lo que se quiere evitar en un test que se practica para pillar
    el truco de cada tipo, no para hacer 20 seguidas de "contar cubos".

    Ronda tipo round-robin con el orden de categorías barajado UNA vez (no
    en cada vuelta): se coge una pregunta de cada categoría por turno y se
    vuelve a empezar. Con un orden fijo por vuelta, dos preguntas de la
    misma categoría nunca quedan seguidas salvo que ya no queden preguntas
    de ninguna otra (p. ej. al pedir más preguntas de las que hay en las
    categorías pequeñas). Preguntas sin categoría se tratan como una
    categoría más ("" agrupa a todas)."""
    por_categoria = {}
    for c in candidatas:
        por_categoria.setdefault(c.get("categoria") or "", []).append(c)
    for grupo in por_categoria.values():
        random.shuffle(grupo)
    orden_categorias = list(por_categoria.keys())
    random.shuffle(orden_categorias)

    seleccionadas = []
    while len(seleccionadas) < num_preguntas and any(por_categoria.values()):
        for cat in orden_categorias:
            if por_categoria[cat]:
                seleccionadas.append(por_categoria[cat].pop())
                if len(seleccionadas) == num_preguntas:
                    break
    return seleccionadas


@bp.route("/generar-test-psicotecnico", methods=["POST"])
@requiere_plan(db, "basico")
def generar_test_psicotecnico():
    """Prueba psicotécnica (razonamiento verbal/espacial) de una oposición
    -- hoy solo Metro, ver oposiciones.coleccion_psicotecnico. A propósito
    NO comparte lógica con /generar-test-oficial: en Metro esta prueba se
    hace siempre UNA prueba completa (verbal O espacial, nunca mezcladas ni
    filtradas por tema), así que aquí no hay selección de temas ni reparto
    ni checkbox de exclusión -- pero, igual que en Test Oficial, el usuario
    sí elige cuántas preguntas quiere (por defecto 25; tope 500, el
    objetivo final de tamaño de banco por prueba -- de momento hay bastante
    menos, así que en la práctica esto casi siempre se recorta al total
    disponible más abajo; el tope es solo un límite de seguridad, no hace
    falta ir subiéndolo cada vez que se amplía el banco)."""
    data = request.get_json()
    prueba = data.get("prueba")
    if prueba not in ("verbal", "espacial"):
        return jsonify({"error": "El parámetro 'prueba' debe ser 'verbal' o 'espacial'"}), 400
    try:
        num_preguntas = max(1, min(500, int(data.get("num_preguntas", 25))))
    except (TypeError, ValueError):
        num_preguntas = 25
    # Ver el mismo comentario en /generar-test-oficial: la cantidad final
    # solo se sabe tras seleccionar, así que sigue sin usar reservar_uso;
    # tampoco llama a IA, así que no hay coste de API en juego.
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "test_oficial")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    try:
        docs_pregunta = obtener_preguntas_psicotecnico(db, g.oposicion)
    except Exception:
        logger.exception("Error accediendo a Firestore")
        return jsonify({"error": "No se pudo acceder a Firestore"}), 500
    candidatas = [d for d in docs_pregunta if d.get("prueba") == prueba]
    if num_preguntas < len(candidatas):
        # Reparto equilibrado entre categorías en vez de random.sample()
        # liso -- ver _seleccionar_preguntas_psicotecnico_equilibradas. El
        # orden ya sale entreverado (no hace falta ni conviene volver a
        # ordenar por número: las categorías tienen rangos de número
        # contiguos, así que ordenar por número deshacía el entreverado).
        seleccionadas = _seleccionar_preguntas_psicotecnico_equilibradas(candidatas, num_preguntas)
    else:
        seleccionadas = sorted(candidatas, key=lambda d: d.get("numero", 0))
    if not seleccionadas:
        return jsonify({"test": [], "mensaje": "Todavía no hay preguntas de esta prueba psicotécnica cargadas"}), 404
    test = [{
        "pregunta": d.get("pregunta", ""),
        "opciones": {k.upper(): v for k, v in d.get("opciones", {}).items()},
        "respuesta_correcta": d.get("respuesta_correcta", "").upper(),
        "explicacion": d.get("explicacion", ""),
        "examen": d.get("examen", ""),
        "numero": d.get("numero", 0),
        "imagen": d.get("imagen", ""),
        "prueba": prueba,
    } for d in seleccionadas]
    registrar_uso(db, g.uid, "test_oficial", g.plan_actual, cantidad=len(test))
    return jsonify({"test": test})


@bp.route("/guardar-test-oficial", methods=["POST"])
@requiere_plan(db, "basico", global_check=False)
def guardar_test_oficial():
    data = request.get_json()
    logger.info("Guardando test oficial: %s", data)
    contenido = data.get("contenido")
    respuestas = data.get("respuestas")
    metadatos = data.get("metadatos", {})
    if not contenido or not respuestas:
        return jsonify({"error": "Faltan datos requeridos"}), 400
    try:
        doc_ref = db.collection("test_oficiales").document()
        doc_ref.set({
            "usuario_id": g.uid,
            "contenido": contenido,
            "respuestas": respuestas,
            "metadatos": metadatos
        })
        logger.info("Test oficial guardado correctamente")
        return jsonify({"mensaje": "Test oficial guardado correctamente"}), 200
    except Exception:
        logger.exception("Error al guardar test oficial")
        return jsonify({"error": "No se pudo guardar el test oficial."}), 500


@bp.route("/analisis-rendimiento", methods=["GET"])
@limiter.limit("10 per minute")
@requiere_plan(db, "basico")
def analisis_rendimiento():
    """Análisis breve generado por IA a partir del rendimiento POR TEMA
    acumulado (rendimiento_por_tema), no de un único test: así puede decir
    con datos reales en qué temas domina el usuario y en cuáles flojea. Se
    pide bajo demanda desde la pantalla de resultados, no automáticamente en
    cada test, para no disparar una llamada a DeepSeek por cada corrección."""
    oposicion = obtener_oposicion_solicitada()
    resumen = obtener_resumen_progreso(db, g.uid, oposicion=oposicion)
    rendimiento = resumen.get("rendimiento_por_tema", {}) or {}

    UMBRAL_MUESTRA_MINIMA = 3
    filas = []
    for tema_id, datos in rendimiento.items():
        total = datos.get("aciertos", 0) + datos.get("fallos", 0) + datos.get("blancos", 0)
        if total < UMBRAL_MUESTRA_MINIMA:
            continue
        porcentaje = round(datos.get("aciertos", 0) / total * 100) if total else 0
        filas.append({"tema_id": tema_id, "total": total, "porcentaje": porcentaje})

    if len(filas) < 2:
        return jsonify({"analisis": None, "mensaje": "Todavía no tienes suficientes tests por tema para un análisis. ¡Sigue practicando y vuelve a intentarlo más adelante!"})

    # Se reserva (comprueba + cobra en una única transacción atómica, ver
    # limites_uso.reservar_uso) ANTES de llamar a la IA, no solo verificar
    # y cobrar aparte después de tenerla -- así dos peticiones concurrentes
    # no pueden pasar la comprobación las dos a la vez. Se reembolsa con
    # devolver_uso si la llamada no llega a producir un análisis.
    permitido, mensaje_error, _usados, _limite = reservar_uso(db, g.uid, "analisis_ia", g.plan_actual)
    if not permitido:
        return jsonify({"analisis": None, "mensaje": mensaje_error}), 429

    coleccion = coleccion_temario(oposicion)
    titulos = obtener_titulos_temas_reales(db, coleccion, [f["tema_id"] for f in filas])
    resumen_temas = "\n".join(
        f"- {titulo}: {fila['porcentaje']}% de acierto ({fila['total']} preguntas contestadas)"
        for fila, titulo in zip(filas, titulos)
    )
    nombre_oposicion = OPOSICIONES.get(oposicion, OPOSICIONES[OPOSICION_POR_DEFECTO])["nombre"]

    prompt = f"""Eres un tutor personal de la oposición al {nombre_oposicion}. Este es el rendimiento acumulado de un alumno por tema, en porcentaje de acierto sobre las preguntas que ha contestado en sus tests:
{resumen_temas}

Escribe un análisis breve (máximo 3-4 frases), cercano y motivador, en español, que destaque el tema o los temas donde mejor rinde y aquellos en los que más necesita reforzar. Cita los nombres de los temas tal cual aparecen arriba. No uses markdown, listas ni encabezados: solo texto corrido, como si se lo dijeras directamente al alumno."""

    try:
        analisis = call_deepseek_api(messages=[{"role": "user", "content": prompt}], temperature=0.5, max_tokens=300)
    except Exception:
        logger.exception("Error al generar análisis de rendimiento")
        analisis = None

    if not analisis:
        devolver_uso(db, g.uid, "analisis_ia", g.plan_actual)
        return jsonify({"analisis": None, "mensaje": "No se ha podido generar el análisis ahora mismo. Inténtalo de nuevo más tarde."})
    return jsonify({"analisis": analisis.strip()})


@bp.route("/preguntas-pendientes-repaso", methods=["GET"])
@requiere_plan(db, "basico", global_check=False)
def preguntas_pendientes_repaso():
    """Solo el conteo (no las preguntas en sí) para el aviso proactivo de
    repaso espaciado en Zona Opositor -- de ahí la agregación .count() en
    vez de traer y contar los documentos completos como sí hace
    /generar-test-fallos (que necesita el contenido real de cada uno)."""
    oposicion = obtener_oposicion_solicitada()
    consulta = db.collection("usuarios").document(g.uid).collection("preguntas_falladas") \
        .where("oposicion", "==", oposicion)
    total = consulta.count().get()[0][0].value
    return jsonify({"total_pendientes": total})


@bp.route("/generar-test-fallos", methods=["POST"])
@requiere_plan(db, "basico", global_check=False)
def generar_test_fallos():
    data = request.get_json()
    try:
        num_preguntas = max(1, min(100, int(data.get("num_preguntas", 10))))
    except (TypeError, ValueError):
        num_preguntas = 10
    temas_filtro = set(data.get("temas", []) or [])
    oposicion = obtener_oposicion_solicitada()

    docs = db.collection("usuarios").document(g.uid).collection("preguntas_falladas") \
        .where("oposicion", "==", oposicion).stream()
    candidatas = [d.to_dict() for d in docs]
    if temas_filtro:
        candidatas = [p for p in candidatas if p.get("tema_id") in temas_filtro]

    total_disponibles = len(candidatas)
    # Repaso espaciado: prioriza las falladas más veces y, a igualdad, las
    # que llevan más tiempo sin volver a intentarse, en vez de un muestreo
    # puramente aleatorio.
    candidatas = ordenar_fallos_por_prioridad(candidatas)
    seleccionadas = candidatas[:num_preguntas]

    if total_disponibles == 0:
        mensaje = "No tienes preguntas falladas pendientes con estos filtros. ¡Buen trabajo!"
    elif total_disponibles < num_preguntas:
        plural = "s" if total_disponibles != 1 else ""
        mensaje = f"Solo hemos encontrado {total_disponibles} pregunta{plural} fallada{plural} con estos filtros (pediste {num_preguntas})."
    else:
        mensaje = None

    return jsonify({"test": seleccionadas, "mensaje": mensaje, "total_disponibles": total_disponibles})


@bp.route("/reportar-pregunta", methods=["POST"])
@requiere_plan(db, "basico", global_check=False)
def reportar_pregunta():
    """Un usuario normal reporta una pregunta con algún error. Se guarda en la
    colección global errores_generacion (fuente="usuario_admin", ver
    errores_generacion.py) para que el panel admin la revise -- comparte
    esquema con los auto-rechazos de la verificación automática de
    generador_preguntas_verificado.py (fuente="auto_verificacion").
    pregunta_id es opcional (los tests generados por IA no tienen id
    estable): siempre se guarda el texto como referencia."""
    from datetime import datetime
    data = request.get_json(silent=True) or {}
    motivo = (data.get("motivo") or "").strip()
    pregunta_texto = (data.get("pregunta_texto") or "").strip()
    if not motivo:
        return jsonify({"error": "Indica el motivo del reporte."}), 400
    if not pregunta_texto:
        return jsonify({"error": "Falta la pregunta reportada."}), 400
    registrar_error_generacion(
        db, tema_id="", fuente="usuario_admin",
        pregunta_texto=pregunta_texto[:1000], detalle=motivo[:1000],
        pregunta_id=(data.get("pregunta_id") or "").strip(),
        oposicion=obtener_oposicion_solicitada(),
        uid=g.uid,
        estado="pendiente",
        fecha=datetime.utcnow().isoformat(),
    )
    return jsonify({"mensaje": "Gracias, hemos recibido tu reporte."}), 201


@bp.route("/generar-test-favoritas", methods=["POST"])
@requiere_plan(db, "basico", global_check=False)
def generar_test_favoritas():
    data = request.get_json()
    try:
        num_preguntas = max(1, min(100, int(data.get("num_preguntas", 10))))
    except (TypeError, ValueError):
        num_preguntas = 10
    temas_filtro = set(data.get("temas", []) or [])
    oposicion = obtener_oposicion_solicitada()

    docs = db.collection("usuarios").document(g.uid).collection("preguntas_favoritas") \
        .where("oposicion", "==", oposicion).stream()
    candidatas = [d.to_dict() for d in docs]
    if temas_filtro:
        candidatas = [p for p in candidatas if p.get("tema_id") in temas_filtro]

    total_disponibles = len(candidatas)
    # Repaso espaciado: prioriza las nunca repasadas y las que llevan más
    # tiempo sin salir en un test de favoritas, para rotar por todo el
    # banco en vez de repetir siempre las mismas al azar.
    candidatas = ordenar_favoritas_por_prioridad(candidatas)
    seleccionadas = candidatas[:num_preguntas]
    # marcar_repasadas ya NO se llama aquí (25/08/2026, bug real de la
    # auditoría): se movió a guardar_resultado.py, al terminar y guardar el
    # test de verdad -- ver el comentario de allí.

    if total_disponibles == 0:
        mensaje = "No tienes preguntas marcadas como favoritas con estos filtros."
    elif total_disponibles < num_preguntas:
        plural = "s" if total_disponibles != 1 else ""
        mensaje = f"Solo tienes {total_disponibles} pregunta{plural} favorita{plural} con estos filtros (pediste {num_preguntas})."
    else:
        mensaje = None

    return jsonify({"test": seleccionadas, "mensaje": mensaje, "total_disponibles": total_disponibles})
