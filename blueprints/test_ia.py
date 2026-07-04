"""Generación de tests/esquemas/análisis a partir del TEMARIO oficial (no
de un PDF subido por el usuario -- eso vive en blueprints/pdf_ia.py)."""
import logging
import random

from flask import Blueprint, g, jsonify, request

from firebase_setup import db
from auth_utils import requiere_login, requiere_plan, obtener_oposicion_solicitada
from limites_uso import verificar_limite_uso, registrar_uso
from oposiciones import OPOSICIONES, OPOSICION_POR_DEFECTO, coleccion_temario, coleccion_examenes_oficiales
from utils import seleccionar_preguntas_con_cuota, obtener_titulos_temas_reales
from test_generator import generar_test_avanzado, generar_preguntas_ia_en_lotes
from esquema_generator import generar_esquema
from deepseek_utils import call_deepseek_api
from registro_progreso_usuario import obtener_resumen_progreso

logger = logging.getLogger(__name__)

bp = Blueprint("test_ia", __name__)


@bp.route("/generar-test-avanzado", methods=["POST"])
@requiere_plan(db, "basico")
def generar_test_avanzado_route():
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "generacion_ia")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    data = request.get_json()
    logger.info("Petición recibida en /generar-test-avanzado: %s", data)
    temas = data.get("temas", [])
    try:
        num_preguntas = max(1, min(100, int(data.get("num_preguntas", 5))))
    except (TypeError, ValueError):
        num_preguntas = 5
    logger.info("Temas extraídos: %s", temas)
    logger.info("Número de preguntas solicitadas: %s", num_preguntas)
    resultado = generar_test_avanzado(temas=temas, db=db, num_preguntas=num_preguntas, coleccion=coleccion_temario(g.oposicion), oposicion=g.oposicion)
    logger.info("Resultado del test: %s", resultado)
    registrar_uso(db, g.uid, "generacion_ia", g.plan_actual)
    return jsonify(resultado)


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
        num_preguntas = max(1, min(100, int(data.get("num_preguntas", 10))))
    except (TypeError, ValueError):
        num_preguntas = 10
    examenes_filtrados = data.get("examenes", [])
    temas_filtrados = data.get("temas", [])
    logger.info("Número de preguntas solicitado: %s, exámenes filtrados: %s, temas filtrados: %s", num_preguntas, examenes_filtrados, temas_filtrados)
    coleccion = coleccion_examenes_oficiales(g.oposicion)
    try:
        docs = db.collection(coleccion).stream()
    except Exception:
        logger.exception("Error accediendo a Firestore")
        return jsonify({"error": "No se pudo acceder a Firestore"}), 500
    preguntas = []
    for doc in docs:
        d = doc.to_dict()
        if d.get("tipo") != "pregunta":
            continue
        if examenes_filtrados:
            if d.get("examen", "").lower() not in [e.lower() for e in examenes_filtrados]:
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
            "tema_id": d.get("tema_id", "")
        })
    logger.info("Preguntas encontradas tras filtro en %s: %d", coleccion, len(preguntas))
    if not preguntas:
        return jsonify({"test": [], "mensaje": "Todavía no hay preguntas oficiales cargadas para esta oposición"}), 404
    seleccionadas = seleccionar_preguntas_con_cuota(preguntas, num_preguntas, temas_filtrados)
    logger.info("Preguntas seleccionadas: %d", len(seleccionadas))
    return jsonify({"test": seleccionadas})


@bp.route("/guardar-test-oficial", methods=["POST"])
@requiere_login(db)
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
7. La explicación debe justificar brevemente (2-3 frases) por qué la respuesta es correcta, citando la base normativa si procede.

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


@bp.route("/generar-test-fallos", methods=["POST"])
@requiere_login(db)
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
    random.shuffle(candidatas)
    seleccionadas = candidatas[:num_preguntas]

    if total_disponibles == 0:
        mensaje = "No tienes preguntas falladas pendientes con estos filtros. ¡Buen trabajo!"
    elif total_disponibles < num_preguntas:
        plural = "s" if total_disponibles != 1 else ""
        mensaje = f"Solo hemos encontrado {total_disponibles} pregunta{plural} fallada{plural} con estos filtros (pediste {num_preguntas})."
    else:
        mensaje = None

    return jsonify({"test": seleccionadas, "mensaje": mensaje, "total_disponibles": total_disponibles})
