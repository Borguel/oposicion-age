"""Generación de tests/esquemas/análisis a partir del TEMARIO oficial (no
de un PDF subido por el usuario -- eso vive en blueprints/pdf_ia.py)."""
import json
import logging
import queue
import threading

from flask import Blueprint, Response, g, jsonify, request, stream_with_context

from firebase_setup import db
from auth_utils import requiere_plan, obtener_oposicion_solicitada
from limites_uso import verificar_limite_uso, registrar_uso, devolver_uso
from oposiciones import OPOSICIONES, OPOSICION_POR_DEFECTO, coleccion_temario, coleccion_examenes_oficiales
from utils import seleccionar_preguntas_con_cuota, obtener_titulos_temas_reales, barajar_opciones_pregunta, calcular_pesos_reales_por_bloque, obtener_preguntas_examenes_oficiales
from test_generator import generar_preguntas_ia_en_lotes
from generador_preguntas_verificado import generar_test_verificado
from esquema_generator import generar_esquema
from deepseek_utils import call_deepseek_api
from registro_progreso_usuario import obtener_resumen_progreso
from banco_fallos import ordenar_por_prioridad_repaso as ordenar_fallos_por_prioridad
from banco_favoritas import ordenar_por_prioridad_repaso as ordenar_favoritas_por_prioridad, marcar_repasadas

logger = logging.getLogger(__name__)

bp = Blueprint("test_ia", __name__)


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
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(
        db, g.uid, g.plan_actual, "test_avanzado_verificado"
    )
    if not permitido:
        return jsonify({"error": mensaje_error}), 429

    coleccion = coleccion_temario(g.oposicion)
    oposicion = g.oposicion
    uid = g.uid
    plan_actual = g.plan_actual

    # El uso se cobra AQUÍ, por adelantado, no al llegar el evento "fin": la
    # generación corre en un hilo de fondo que sigue gastando en DeepSeek
    # aunque el cliente corte la conexión SSE, y en ese caso el generador de
    # abajo nunca llega a su "registrar_uso" final -- cobrar al final dejaba un
    # hueco para saltarse la cuota abriendo y abortando la petición en bucle.
    # Si la generación acaba fallando de verdad (0 preguntas), el hilo lo
    # devuelve con devolver_uso.
    #
    # El cupo de este test se mide en PREGUNTAS, no en "número de tests": se
    # cobran tantas unidades como preguntas se piden, así un test de 100 gasta
    # 100 y uno de 10 gasta 10 (consumo justo). El usuario no ve el contador.
    registrar_uso(db, uid, "test_avanzado_verificado", plan_actual, cantidad=num_preguntas)

    def generar():
        eventos = queue.Queue()

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
                    modo_reparto=modo_reparto, uid=uid
                )
            except Exception:
                logger.exception("Error al generar el test personalizado verificado")
                resultado = {"test": [], "error": "Error inesperado al generar el test"}
            if not resultado.get("test"):
                devolver_uso(db, uid, "test_avanzado_verificado", plan_actual, cantidad=num_preguntas)
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
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@bp.route("/generar-esquema", methods=["POST"])
@requiere_plan(db, "basico")
def generar_esquema_route():
    data = request.get_json(silent=True)
    if not data:
        logger.warning("No se ha recibido JSON en la petición")
        return jsonify({"error": "No se ha recibido un cuerpo JSON válido"}), 400
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "generacion_ia")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    logger.info("Datos recibidos en /generar-esquema: %s", data)
    temas = data.get("temas", [])
    instrucciones = data.get("instrucciones", "Resume los contenidos clave.")
    nivel = data.get("nivel", "general")
    resultado = generar_esquema(temas=temas, db=db, instrucciones=instrucciones, nivel=nivel, coleccion=coleccion_temario(g.oposicion))
    registrar_uso(db, g.uid, "generacion_ia", g.plan_actual)
    return jsonify({"esquema": resultado})


@bp.route("/generar-test-oficial", methods=["POST"])
@requiere_plan(db, "basico")
def generar_test_oficial():
    data = request.get_json()
    logger.info("Ruta /generar-test-oficial llamada con datos: %s", data)
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
    return jsonify({"test": seleccionadas})


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
    except Exception as e:
        logger.exception("Error al guardar test oficial")
        return jsonify({"error": str(e)}), 500


@bp.route("/generar-test-inteligente", methods=["POST"])
@requiere_plan(db, "basico")
def generar_test_inteligente():
    """Decisión intencional: esta ruta está oculta en el frontend (ver
    limites_uso.py, "hoy desactivado en la web") pero se mantiene aquí a
    propósito -- no se ha borrado el endpoint de la API por si algún
    consumidor externo todavía lo usa."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No se ha recibido un cuerpo JSON válido"}), 400
    temas = data.get("temas", [])
    try:
        num_preguntas = max(1, min(100, int(data.get("num_preguntas", 5))))
    except (TypeError, ValueError):
        num_preguntas = 5
    if not temas:
        return jsonify({"error": "No se han proporcionado temas"}), 400
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "generacion_ia")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429

    coleccion = coleccion_temario(g.oposicion)
    temas_legibles = obtener_titulos_temas_reales(db, coleccion, temas)
    nombre_oposicion = OPOSICIONES.get(g.oposicion, OPOSICIONES[OPOSICION_POR_DEFECTO])["nombre"]

    def construir_prompt(n):
        return f"""Actúas como un generador profesional de preguntas tipo test, especializado en la oposición al {nombre_oposicion}.
Crea EXACTAMENTE {n} preguntas tipo test con el nivel y el estilo de un examen oficial real de esta oposición: técnicas, precisas y basadas en la legislación y el temario oficial vigente sobre estos temas.
Temas seleccionados: {', '.join(temas_legibles)}

Sigue estrictamente estas normas:
1. Las preguntas deben ser claras, completas y redactadas en un estilo técnico-formal, citando artículos, leyes o normativa concreta cuando proceda (p. ej. "Según el artículo 62 de la Constitución Española...").
2. NO uses expresiones como "según el texto", "de acuerdo con lo anterior" o "en el contenido proporcionado": las preguntas se basan en tu conocimiento normativo, no en ningún documento.
3. Sustituye todas las siglas por su forma completa la primera vez que aparezcan.
4. Las cuatro opciones deben ser plausibles, basadas en confusiones habituales entre conceptos, plazos, órganos o competencias similares -- evita opciones absurdas o claramente descartables.
5. Evita preguntas triviales o de cultura general: cada pregunta debe exigir conocimiento normativo o técnico específico del tema.
6. Prioriza variedad temática entre los temas seleccionados.
7. La explicación debe repasar TODAS las opciones, una por línea y en orden, con este formato exacto (una frase breve por opción, citando la base normativa si procede): "A) es correcta/incorrecta porque... B) es correcta/incorrecta porque... C) ... D) ...".

Devuelve SOLO un array JSON con este formato exacto, sin texto adicional ni bloques de código:
[
  {{
    "pregunta": "...",
    "opciones": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
    "respuesta_correcta": "B",
    "explicacion": "..."
  }}
]
"""
    try:
        preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, num_preguntas)
        if not preguntas:
            return jsonify({"error": "Sin respuesta de DeepSeek"}), 500
        preguntas = [barajar_opciones_pregunta(p) for p in preguntas]
        resultado = {"test": preguntas}
        if len(preguntas) < num_preguntas:
            resultado["advertencia"] = f"Solo se generaron {len(preguntas)} de {num_preguntas} preguntas."
        registrar_uso(db, g.uid, "generacion_ia", g.plan_actual)
        return jsonify(resultado)
    except Exception as e:
        logger.exception("Error al generar test inteligente")
        return jsonify({"error": str(e)}), 500


@bp.route("/analisis-rendimiento", methods=["GET"])
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

    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "generacion_ia")
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
        return jsonify({"analisis": None, "mensaje": "No se ha podido generar el análisis ahora mismo. Inténtalo de nuevo más tarde."})
    registrar_uso(db, g.uid, "generacion_ia", g.plan_actual)
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
    num_preguntas = data.get("num_preguntas", 10)
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
    colección global reportes_preguntas (estado='pendiente') para que el panel
    admin la revise. pregunta_id es opcional (los tests generados por IA no
    tienen id estable): siempre se guarda el texto como referencia."""
    from datetime import datetime
    data = request.get_json(silent=True) or {}
    motivo = (data.get("motivo") or "").strip()
    pregunta_texto = (data.get("pregunta_texto") or "").strip()
    if not motivo:
        return jsonify({"error": "Indica el motivo del reporte."}), 400
    if not pregunta_texto:
        return jsonify({"error": "Falta la pregunta reportada."}), 400
    db.collection("reportes_preguntas").document().set({
        "pregunta_id": (data.get("pregunta_id") or "").strip(),
        "pregunta_texto": pregunta_texto[:1000],
        "oposicion": obtener_oposicion_solicitada(),
        "uid": g.uid,
        "motivo": motivo[:1000],
        "estado": "pendiente",
        "fecha": datetime.utcnow().isoformat(),
    })
    return jsonify({"mensaje": "Gracias, hemos recibido tu reporte."}), 201


@bp.route("/generar-test-favoritas", methods=["POST"])
@requiere_plan(db, "basico", global_check=False)
def generar_test_favoritas():
    data = request.get_json()
    num_preguntas = data.get("num_preguntas", 10)
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
    if seleccionadas:
        marcar_repasadas(db, g.uid, oposicion, seleccionadas)

    if total_disponibles == 0:
        mensaje = "No tienes preguntas marcadas como favoritas con estos filtros."
    elif total_disponibles < num_preguntas:
        plural = "s" if total_disponibles != 1 else ""
        mensaje = f"Solo tienes {total_disponibles} pregunta{plural} favorita{plural} con estos filtros (pediste {num_preguntas})."
    else:
        mensaje = None

    return jsonify({"test": seleccionadas, "mensaje": mensaje, "total_disponibles": total_disponibles})
