"""Herramientas de IA sobre un PDF subido por el propio usuario: resumen,
esquema, test, tarjetas y chat sobre el documento, más "Mis documentos"
(la biblioteca de lo ya generado)."""
import json
import logging
import os
import queue
import random
import threading
from datetime import datetime
from io import BytesIO

import requests
from flask import Blueprint, Response, g, jsonify, request, stream_with_context
from pypdf import PdfReader

from firebase_setup import db
from auth_utils import requiere_plan, obtener_oposicion_solicitada
from limites_uso import max_paginas_para_plan, verificar_limite_uso, registrar_uso, devolver_uso
from documentos_pdf import (
    obtener_o_crear_documento, obtener_documento, listar_documentos, actualizar_carpeta,
    listar_carpetas, crear_carpeta, eliminar_carpeta, actualizar_titulo
)
from guardar_resultado import guardar_resultado_en_firestore
from test_generator import generar_preguntas_ia_en_lotes
from utils import barajar_opciones_pregunta
from deepseek_utils import generar_documento_largo_por_partes
from coste_ia import AcumuladorTokens
from tarjetas_generator import generar_tarjetas_verificadas

logger = logging.getLogger(__name__)

bp = Blueprint("pdf_ia", __name__)


def _resolver_texto_documento(plan_actual):
    """Punto de entrada común de las 4 rutas de generación desde PDF: o bien
    viene un 'documento_id' (contenido ya subido antes, de la biblioteca de
    "Mis documentos"), o bien viene un archivo 'pdf' nuevo. Devuelve
    (texto, documento_id, nombre_archivo, respuesta_error_o_None); si el
    último elemento no es None, la ruta debe devolverlo tal cual."""
    documento_id = request.form.get("documento_id")
    if documento_id:
        documento = obtener_documento(db, g.uid, documento_id)
        if not documento:
            return None, None, None, (jsonify({"error": "No se encontró el documento indicado."}), 404)
        return documento["texto"], documento_id, documento.get("nombre_archivo", "documento.pdf"), None

    if 'pdf' not in request.files:
        return None, None, None, (jsonify({"error": "No se encontró archivo PDF"}), 400)
    pdf_file = request.files['pdf']
    if pdf_file.filename == '':
        return None, None, None, (jsonify({"error": "Nombre de archivo inválido"}), 400)
    try:
        pdf_reader = PdfReader(BytesIO(pdf_file.read()))
        numero_paginas = len(pdf_reader.pages)
    except Exception:
        return None, None, None, (jsonify({"error": "El archivo no es un PDF válido o está dañado. Comprueba que sea un PDF real e inténtalo de nuevo."}), 400)
    limite_paginas = max_paginas_para_plan(plan_actual, db)
    if numero_paginas > limite_paginas:
        return None, None, None, (jsonify({"error": f"El PDF tiene demasiadas páginas para tu plan (máx. {limite_paginas}). Divide el documento en partes más pequeñas o mejora de plan."}), 400)
    # La extracción también va protegida: un PDF estructuralmente válido puede
    # tener páginas con contenido corrupto que revientan extract_text().
    try:
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    except Exception:
        return None, None, None, (jsonify({"error": "El archivo no es un PDF válido o está dañado. Comprueba que sea un PDF real e inténtalo de nuevo."}), 400)
    if not text.strip():
        return None, None, None, (jsonify({"error": "El PDF no contiene texto extraíble (puede ser una imagen)"}), 400)
    documento_id, documento = obtener_o_crear_documento(db, g.uid, text, pdf_file.filename, numero_paginas)
    return text, documento_id, pdf_file.filename, None


def _extraer_json_array(texto):
    """Extrae y parsea el array JSON que debería devolver la IA, tolerando
    que venga envuelto en texto explicativo alrededor (el LLM a veces
    añade una frase antes o después pese a que el prompt le pide "SOLO el
    JSON") y que use comillas simples en vez de dobles (JSON inválido
    estricto, pero un fallo común de generación). Lanza ValueError si no
    se puede recuperar un array JSON válido de ninguna de las dos formas."""
    start_index = texto.find("[")
    end_index = texto.rfind("]") + 1
    if start_index == -1 or end_index <= start_index:
        raise ValueError("No se encontró un array JSON en la respuesta.")
    json_str = texto[start_index:end_index]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(json_str.replace("'", '"'))
    except json.JSONDecodeError as e:
        raise ValueError("El texto entre corchetes no es un JSON válido.") from e


@bp.route('/resumir-pdf', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def resumir_pdf():
    # En streaming (SSE, mismo patrón que /generar-test-desde-pdf) para dar
    # progreso real por fragmento en vez de los mensajes rotativos
    # cosméticos que tenía antes.
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "pdf_ia")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    text, documento_id, nombre_archivo, error = _resolver_texto_documento(g.plan_actual)
    if error:
        return error
    if not os.getenv("DEEPSEEK_API_KEY"):
        return jsonify({"error": "API key de DeepSeek no configurada"}), 500

    max_length = 300000
    if len(text) > max_length:
        text = text[:max_length]
    system_prompt = (
        "Eres un experto en oposiciones. Crea un resumen de estudio claro y bien "
        "estructurado a partir del siguiente documento, destacando conceptos "
        "fundamentales, leyes importantes y fechas relevantes. Usa EXACTAMENTE este "
        "formato Markdown, sin desviarte de él:\n"
        "- Encabezados de nivel 1 con \"# \" para los bloques temáticos principales.\n"
        "- Encabezados de nivel 2 con \"## \" para subapartados.\n"
        "- Texto en **negrita** para términos clave, leyes, artículos o fechas, la "
        "primera vez que aparecen.\n"
        "- Listas con \"- \" para viñetas normales.\n"
        "- Listas numeradas con \"1. \", \"2. \", etc. cuando el orden importe (por "
        "ejemplo, fases de un procedimiento).\n"
        "- Cuando definas formalmente un concepto clave, usa el prefijo \"> \" para esa "
        "línea, de forma que se pueda destacar como una caja de definición aparte.\n"
        "No uses tablas, bloques de código, ni HTML. Cada línea de texto debe ir en su "
        "propio párrafo o viñeta, sin mezclar varias ideas en una misma línea larga. El "
        "resumen debe ser útil para un opositor.\n"
        "IMPORTANTE -- fidelidad al documento: basa el resumen ÚNICAMENTE en el "
        "contenido del documento proporcionado. No añadas información externa, no "
        "completes huecos con conocimiento propio, y no inventes datos, fechas, "
        "artículos, cifras o nombres que no aparezcan literalmente en el texto. Si el "
        "documento no aporta un dato que normalmente se esperaría, no lo inventes: "
        "sencillamente no lo incluyas. Antes de dar tu respuesta por buena, revisa "
        "mentalmente que cada dato concreto que has escrito (fecha, cifra, ley, "
        "artículo, plazo) aparezca efectivamente en el documento que se te ha dado."
    )

    uid = g.uid
    plan_actual = g.plan_actual
    # Uso cobrado por adelantado (no al llegar "fin"): el hilo de fondo sigue
    # generando y gastando en DeepSeek aunque el cliente corte la conexión
    # SSE (mismo motivo que /generar-test-desde-pdf).
    registrar_uso(db, uid, "pdf_ia", plan_actual)

    def generar():
        eventos = queue.Queue()
        acumulador_tokens = AcumuladorTokens()

        def _en_hilo_de_fondo():
            def on_progreso(evento_progreso):
                eventos.put({"tipo": "progreso", **evento_progreso})
            try:
                resumen = generar_documento_largo_por_partes(
                    system_prompt, text, etiqueta_documento="Documento para resumir",
                    on_usage=acumulador_tokens.add, on_progreso=on_progreso,
                )
                resultado = {"resumen": resumen, "documento_id": documento_id, "nombre_archivo": nombre_archivo} if resumen \
                    else {"error": "Error en DeepSeek API"}
            except Exception:
                logger.exception("Error en /resumir-pdf")
                resultado = {"error": "Error al procesar el PDF."}
            if not resultado.get("resumen"):
                devolver_uso(db, uid, "pdf_ia", plan_actual)
            acumulador_tokens.volcar_directo(db, uid)
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


# ✅ NUEVA RUTA: alias para compatibilidad con frontend
@bp.route('/resumir-documento', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def resumir_documento():
    return resumir_pdf()


@bp.route('/generar-esquema-desde-pdf', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def generar_esquema_desde_pdf():
    # En streaming (SSE, mismo patrón que /generar-test-desde-pdf/
    # /resumir-pdf) para dar progreso real por fragmento.
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "pdf_ia")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    text, documento_id, nombre_archivo, error = _resolver_texto_documento(g.plan_actual)
    if error:
        return error
    if not os.getenv("DEEPSEEK_API_KEY"):
        return jsonify({"error": "API key de DeepSeek no configurada"}), 500

    max_length = 300000
    if len(text) > max_length:
        text = text[:max_length]
    system_prompt = (
        "Eres un experto en oposiciones. Crea un ESQUEMA de estudio: no es un resumen "
        "en prosa, es un árbol jerárquico de epígrafes y sub-epígrafes que refleje la "
        "estructura real del documento (título > capítulo > artículo > apartado, o el "
        "equivalente en el documento dado), pensado para repasar de un vistazo. Usa "
        "EXACTAMENTE este formato Markdown, sin desviarte de él:\n"
        "- Encabezados de nivel 1 con \"# \" para las secciones principales del temario "
        "(p. ej. cada título o bloque grande).\n"
        "- Encabezados de nivel 2 con \"## \" para subsecciones dentro de cada sección "
        "(p. ej. cada capítulo o epígrafe).\n"
        "- Encabezados de nivel 3 con \"### \" cuando dentro de una subsección haya que "
        "bajar un nivel más (p. ej. cada artículo o punto concreto dentro de un "
        "capítulo). Usa este tercer nivel siempre que el documento tenga esa "
        "profundidad real: NO lo omitas ni lo aplanes al nivel 2 de forma artificial.\n"
        "- Texto en **negrita** para términos clave, nombres de leyes o artículos, la "
        "primera vez que aparecen.\n"
        "- Listas con \"- \" para viñetas normales. IMPORTANTE: anida las viñetas todo lo "
        "que haga falta para reflejar la jerarquía real (una idea que detalla o depende "
        "de la viñeta anterior va debajo de ella, indentada con 2 espacios más por cada "
        "nivel de profundidad, exactamente igual que una lista anidada de Markdown). Un "
        "esquema con viñetas anidadas es MEJOR que uno plano: no limites la profundidad "
        "de anidación.\n"
        "- Listas numeradas con \"1. \", \"2. \", etc. cuando el orden importe (por "
        "ejemplo, pasos de un procedimiento o fases de un proceso). También pueden "
        "anidarse igual que las viñetas.\n"
        "- Cuando definas formalmente un concepto, usa el prefijo \"> \" para esa línea, "
        "de forma que se pueda destacar como una caja de definición aparte.\n"
        "REGLA CLAVE contra la duplicación: cada tema o epígrafe del documento debe "
        "aparecer UNA SOLA VEZ en el esquema, en el nivel de profundidad que le "
        "corresponda. Si el documento vuelve a tratar el mismo epígrafe más adelante con "
        "más detalle (por ejemplo, un índice o resumen inicial y luego un desarrollo "
        "artículo por artículo del mismo título), NO crees una segunda sección "
        "independiente para ese mismo epígrafe: integra ese detalle como sub-viñetas "
        "anidadas bajo el encabezado ya existente de ese epígrafe. Todas las secciones "
        "del esquema deben acabar con un nivel de detalle similar entre sí -- evita que "
        "una sección quede muy desarrollada y las demás apenas esbozadas.\n"
        "No uses tablas, bloques de código, ni HTML. Cada línea de texto debe ir en su "
        "propio párrafo o viñeta, sin mezclar varias ideas en una misma línea larga.\n"
        "IMPORTANTE -- fidelidad al documento: basa el esquema ÚNICAMENTE en el "
        "contenido del documento proporcionado. No añadas información externa, no "
        "completes huecos con conocimiento propio, y no inventes datos, fechas, "
        "artículos, cifras o nombres que no aparezcan literalmente en el texto. Si el "
        "documento no aporta un dato que normalmente se esperaría, no lo inventes: "
        "sencillamente no lo incluyas. Antes de dar tu respuesta por buena, revisa "
        "mentalmente que cada dato concreto que has escrito (fecha, cifra, ley, "
        "artículo, plazo) aparezca efectivamente en el documento que se te ha dado."
    )
    instrucciones_fusion_esquema = (
        "Al fusionar los fragmentos, presta especial atención a que un mismo epígrafe o "
        "sección del documento no aparezca dos veces a distinta profundidad (por "
        "ejemplo, una versión breve tipo índice en un fragmento y luego un desarrollo "
        "mucho más detallado del MISMO epígrafe en otro fragmento): en ese caso, fusiona "
        "ambas versiones en una única sección, usando la más detallada como base y "
        "anidando el resto como sub-viñetas, en vez de dejar las dos como secciones "
        "independientes. Vigila también que la profundidad de detalle quede equilibrada "
        "entre secciones -- si una sección terminó mucho más desarrollada que el resto "
        "por venir de un fragmento distinto, resúmela ligeramente para igualar el nivel "
        "de detalle general del esquema."
    )

    uid = g.uid
    plan_actual = g.plan_actual
    registrar_uso(db, uid, "pdf_ia", plan_actual)

    def generar():
        eventos = queue.Queue()
        acumulador_tokens = AcumuladorTokens()

        def _en_hilo_de_fondo():
            def on_progreso(evento_progreso):
                eventos.put({"tipo": "progreso", **evento_progreso})
            try:
                esquema = generar_documento_largo_por_partes(
                    system_prompt,
                    text,
                    etiqueta_documento="Documento para crear esquema",
                    instrucciones_fusion_extra=instrucciones_fusion_esquema,
                    on_usage=acumulador_tokens.add,
                    on_progreso=on_progreso,
                )
                resultado = {"esquema": esquema, "documento_id": documento_id, "nombre_archivo": nombre_archivo} if esquema \
                    else {"error": "Error en DeepSeek API"}
            except Exception:
                logger.exception("Error en /generar-esquema-desde-pdf")
                resultado = {"error": "Error al procesar el PDF."}
            if not resultado.get("esquema"):
                devolver_uso(db, uid, "pdf_ia", plan_actual)
            acumulador_tokens.volcar_directo(db, uid)
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


@bp.route('/generar-test-desde-pdf', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def generar_test_desde_pdf():
    # En streaming (SSE, mismo patrón que /generar-test-avanzado en
    # blueprints/test_ia.py) para poder retransmitir progreso real por lote
    # en vez de los mensajes rotativos cosméticos que tenía antes -- generar
    # varios lotes en paralelo con IA tarda bastante más que una respuesta
    # instantánea, sobre todo con num_preguntas alto.
    try:
        num_preguntas = int(request.form.get("num_preguntas", 10))
        if num_preguntas < 1 or num_preguntas > 100:
            num_preguntas = 10
    except (ValueError, TypeError):
        num_preguntas = 10
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "pdf_ia")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    text, documento_id, nombre_archivo, error = _resolver_texto_documento(g.plan_actual)
    if error:
        return error

    max_length = 150000
    if len(text) > max_length:
        text = text[:max_length]

    def construir_prompt(n):
        system_prompt = (
            f"Eres un experto en la elaboración de preguntas tipo test para oposiciones oficiales en España. "
            f"Tu tarea es generar EXACTAMENTE {n} preguntas de opción múltiple de alta calidad, "
            f"basadas únicamente en el documento proporcionado. Cada pregunta debe cumplir lo siguiente:\n"
            f"1. **Formato**: pregunta clara y directa, seguida de cuatro opciones (A, B, C, D).\n"
            f"2. **Precisión**: si el documento menciona leyes, artículos, plazos, funciones, definiciones, principios o procedimientos, la pregunta debe reflejarlos con exactitud. Si citas un número de artículo, di TAMBIÉN en la misma frase el nombre de la ley o norma a la que pertenece (tal como aparece en el documento) -- un artículo mencionado sin decir de qué norma es deja a quien lo lee sin poder ubicarlo.\n"
            f"3. **Respuesta correcta**: debe ser inequívoca y extraída directamente del texto.\n"
            f"4. **Distractores**: deben ser técnicamente plausibles, basados en confusiones comunes, errores típicos o elementos similares del propio documento.\n"
            f"5. **Neutralidad**: evita lenguaje coloquial, ambigüedades, opiniones o preguntas triviales.\n"
            f"6. **Explicación**: repasa TODAS las opciones, una por línea y en orden, con este formato exacto: \"A) es correcta/incorrecta porque... B) es correcta/incorrecta porque... C) ... D) ...\", citando o basándote en el contenido del documento.\n"
            f"7. **Autocontenida**: quien responde el test NUNCA ve el documento de origen, solo la pregunta. Nunca remitas a \"el documento\", \"el contenido\", \"el texto\" o \"lo mencionado/anterior\" (p. ej. \"¿qué tienen en común los X mencionados en el contenido?\") -- nombra tú mismo, explícitamente, de qué elementos concretos hablas.\n"
            f"8. **Sin siglas**: nunca abrevies el nombre de una ley o norma con siglas (\"CE\", \"TREBEP\", \"LPAC\"...) ni escribas \"art.\" en vez de \"artículo\" -- los exámenes oficiales de esta oposición escriben siempre el nombre completo, tal como aparece en el documento. Esto incluye también abreviar el tipo de norma delante de su número (\"LO 3/2007\", \"RD 203/2021\"...) en vez de escribirlo entero (\"Ley Orgánica 3/2007\", \"Real Decreto 203/2021\").\n"
            f"Devuelve SOLO un array JSON válido con este formato exacto:\n"
            f"[{{\"pregunta\": \"...\", \"opciones\": {{\"A\": \"...\", \"B\": \"...\", \"C\": \"...\", \"D\": \"...\"}}, \"respuesta_correcta\": \"A\", \"explicacion\": \"...\"}}]\n"
            f"NO añadas texto adicional antes ni después del array JSON."
        )
        return f"{system_prompt}\n\nDocumento para crear preguntas test:\n{text}"

    uid = g.uid
    plan_actual = g.plan_actual

    # Uso cobrado por adelantado (no al llegar "fin"): el hilo de fondo sigue
    # generando y gastando en DeepSeek aunque el cliente corte la conexión SSE,
    # así que cobrar al final permitía saltarse la cuota abortando la petición
    # en bucle. Si la generación falla de verdad (0 preguntas), se devuelve.
    registrar_uso(db, uid, "pdf_ia", plan_actual)

    def generar():
        eventos = queue.Queue()
        acumulador_tokens = AcumuladorTokens()

        def _en_hilo_de_fondo():
            def on_progreso(evento_progreso):
                # "pregunta" se manda como evento aparte (no como parte de
                # "progreso") para que el frontend pueda empezar el test en
                # cuanto lleguen las primeras N preguntas aceptadas, sin
                # esperar a que termine todo el test -- mismo patrón que
                # /generar-test-avanzado usa para Test Personalizado (ver
                # blueprints/test_ia.py).
                pregunta = evento_progreso.pop("pregunta", None)
                eventos.put({"tipo": "progreso", **evento_progreso})
                if pregunta:
                    eventos.put({
                        "tipo": "pregunta", "pregunta": pregunta,
                        "completadas": evento_progreso["completadas"], "total": evento_progreso["total"],
                    })
            try:
                preguntas, errores_lotes = generar_preguntas_ia_en_lotes(
                    construir_prompt, num_preguntas, text, on_progreso=on_progreso,
                    on_usage=acumulador_tokens.add,
                )
                if not preguntas:
                    # Si TODOS los errores de lote son de verificación (no de
                    # generación), ninguna pregunta llegó a fallar por un
                    # problema técnico de DeepSeek: el documento sencillamente
                    # no tenía suficiente contenido distinto para las
                    # preguntas pedidas, y decirlo así evita el mensaje
                    # confuso de "error técnico" (ver test_generator.py,
                    # _pedir_lote_verificado).
                    if errores_lotes and all(e.startswith("Ninguna de las") for e in errores_lotes):
                        mensaje_error = (
                            f"No se pudo generar ninguna pregunta que superase la verificación de calidad "
                            f"a partir de este documento para las {num_preguntas} preguntas solicitadas. "
                            f"El PDF puede ser demasiado corto o repetitivo para tantas preguntas distintas "
                            f"-- prueba a pedir menos preguntas o sube un documento más extenso."
                        )
                    else:
                        mensaje_error = "La IA no devolvió un JSON válido para las preguntas. Error técnico."
                    resultado = {
                        "test": [],
                        "error": mensaje_error,
                        "respuesta_cruda": "; ".join(errores_lotes)[:500]
                    }
                else:
                    preguntas_validadas = []
                    for p in preguntas:
                        if all(k in p for k in ["pregunta", "opciones", "respuesta_correcta"]):
                            if "explicacion" not in p:
                                p["explicacion"] = "Explicación no disponible."
                            p["pregunta"] = str(p["pregunta"]).strip() if p["pregunta"] else "Pregunta no disponible"
                            p["explicacion"] = str(p["explicacion"]).strip() if p["explicacion"] else "Explicación no disponible"
                            if not isinstance(p["opciones"], dict):
                                p["opciones"] = {}
                            for key in list(p["opciones"].keys()):
                                p["opciones"][key] = str(p["opciones"][key]).strip() if p["opciones"][key] else "Opción no disponible"
                            p["respuesta_correcta"] = str(p["respuesta_correcta"]).upper() if p["respuesta_correcta"] else "A"
                            preguntas_validadas.append(barajar_opciones_pregunta(p))
                    if not preguntas_validadas:
                        resultado = {"test": [], "error": "La IA generó preguntas vacías o inválidas."}
                    else:
                        resultado = {"test": preguntas_validadas, "documento_id": documento_id, "nombre_archivo": nombre_archivo}
                        if len(preguntas_validadas) < num_preguntas:
                            resultado["advertencia"] = f"Solo se generaron {len(preguntas_validadas)} de {num_preguntas} preguntas."
            except Exception:
                logger.exception("Error en /generar-test-desde-pdf")
                resultado = {"test": [], "error": "Error al procesar el PDF o generar preguntas."}
            if not resultado.get("test"):
                devolver_uso(db, uid, "pdf_ia", plan_actual)
            # Este hilo corre desligado de la petición (igual que el generador
            # de Test Personalizado, ver generador_preguntas_verificado.py) --
            # flask.g no está disponible aquí, así que se vuelca directo a
            # Firestore en vez de a través del teardown_request habitual.
            acumulador_tokens.volcar_directo(db, uid)
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


@bp.route('/generar-tarjetas-desde-pdf', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def generar_tarjetas_desde_pdf():
    # En streaming (SSE, mismo patrón que /generar-test-desde-pdf/
    # /resumir-pdf/generar-esquema-desde-pdf) para dar progreso real por
    # tarjeta verificada en vez de mensajes rotativos cosméticos.
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "pdf_ia")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    text, documento_id, nombre_archivo, error = _resolver_texto_documento(g.plan_actual)
    if error:
        return error
    if not os.getenv("DEEPSEEK_API_KEY"):
        return jsonify({"error": "API key de DeepSeek no configurada"}), 500

    max_length = 150000
    if len(text) > max_length:
        text = text[:max_length]
    try:
        num_tarjetas = int(request.form.get("num_tarjetas", 10))
    except (TypeError, ValueError):
        num_tarjetas = 10
    num_tarjetas = max(1, min(num_tarjetas, 50))

    uid = g.uid
    plan_actual = g.plan_actual
    # Se cobra por adelantado (mismo motivo que /generar-test-desde-pdf: el
    # hilo de fondo sigue gastando en DeepSeek aunque el cliente corte la
    # conexión SSE, así que cobrar solo al final permitiría saltarse la
    # cuota abortando la petición en bucle) y se devuelve si no se genera
    # ninguna tarjeta válida.
    registrar_uso(db, uid, "pdf_ia", plan_actual)

    def generar():
        eventos = queue.Queue()
        acumulador_tokens = AcumuladorTokens()

        def _en_hilo_de_fondo():
            def on_progreso(evento_progreso):
                eventos.put({"tipo": "progreso", **evento_progreso})
            try:
                resultado_generacion = generar_tarjetas_verificadas(
                    text, num_tarjetas, on_usage=acumulador_tokens.add, on_progreso=on_progreso,
                )
                if not resultado_generacion["tarjetas"]:
                    resultado = {"error": "La IA no generó ninguna tarjeta válida a partir del documento."}
                else:
                    resultado = {
                        "tarjetas": resultado_generacion["tarjetas"],
                        "documento_id": documento_id,
                        "nombre_archivo": nombre_archivo,
                    }
                    if "advertencia" in resultado_generacion:
                        resultado["advertencia"] = resultado_generacion["advertencia"]
            except Exception:
                logger.exception("Error en /generar-tarjetas-desde-pdf")
                resultado = {"error": "Error al procesar el PDF o generar tarjetas."}
            if not resultado.get("tarjetas"):
                devolver_uso(db, uid, "pdf_ia", plan_actual)
            acumulador_tokens.volcar_directo(db, uid)
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


# Nº de caracteres del PDF que se guardan para poder chatear sobre él. Se
# recorta más que en resumen/esquema porque este texto se reenvía en el
# prompt de CADA mensaje del chat (no una sola vez), así que hay que
# mantenerlo comedido para no disparar el coste por conversación.
MAX_CARACTERES_CHAT_PDF = 12000


@bp.route('/subir-pdf-chat', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def subir_pdf_chat():
    if 'pdf' not in request.files:
        return jsonify({"error": "No se encontró archivo PDF"}), 400
    pdf_file = request.files['pdf']
    if pdf_file.filename == '':
        return jsonify({"error": "Nombre de archivo inválido"}), 400
    # Parseo y extracción separados del resto: un archivo que no sea un PDF
    # de verdad es un error del usuario (400 con mensaje claro), no un error
    # del servidor (500), y su mensaje interno no debe llegar al cliente.
    try:
        pdf_reader = PdfReader(BytesIO(pdf_file.read()))
        numero_paginas = len(pdf_reader.pages)
    except Exception:
        return jsonify({"error": "El archivo no es un PDF válido o está dañado. Comprueba que sea un PDF real e inténtalo de nuevo."}), 400
    limite_paginas = max_paginas_para_plan(g.plan_actual, db)
    if numero_paginas > limite_paginas:
        return jsonify({"error": f"El PDF tiene demasiadas páginas para tu plan (máx. {limite_paginas}). Divide el documento en partes más pequeñas o mejora de plan."}), 400
    try:
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    except Exception:
        return jsonify({"error": "El archivo no es un PDF válido o está dañado. Comprueba que sea un PDF real e inténtalo de nuevo."}), 400
    if not text.strip():
        return jsonify({"error": "El PDF no contiene texto extraíble (puede ser una imagen)"}), 400
    try:
        db.collection("usuarios").document(g.uid).update({
            "chat_pdf_activo": {
                "texto": text[:MAX_CARACTERES_CHAT_PDF],
                "nombre_archivo": pdf_file.filename,
                "fecha": datetime.utcnow().isoformat()
            }
        })
        return jsonify({
            "mensaje": "PDF cargado correctamente",
            "nombre_archivo": pdf_file.filename,
            "paginas": numero_paginas
        })
    except Exception:
        logger.exception("Error en /subir-pdf-chat")
        return jsonify({"error": "No se pudo guardar el documento. Inténtalo de nuevo en unos segundos."}), 500


@bp.route('/chat-pdf-mensaje', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def chat_pdf_mensaje():
    datos = request.get_json(silent=True) or {}
    mensaje = (datos.get("mensaje") or "").strip()
    if not mensaje:
        return jsonify({"error": "Falta el mensaje"}), 400
    historial = datos.get("historial") or []
    if not isinstance(historial, list):
        historial = []

    doc = db.collection("usuarios").document(g.uid).get()
    sesion = (doc.to_dict() or {}).get("chat_pdf_activo") or {}
    texto_pdf = sesion.get("texto")
    if not texto_pdf:
        return jsonify({"error": "Primero sube un PDF para poder chatear sobre él."}), 400

    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "chat_pdf")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429

    try:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return jsonify({"error": "API key de DeepSeek no configurada"}), 500
        system_prompt = (
            "Eres un asistente que ayuda a un opositor a entender un documento que ha subido. "
            "Responde SOLO basándote en el contenido de este documento. Si la respuesta no está "
            "en el documento, dilo claramente en vez de inventar información.\n\n"
            f"Documento ({sesion.get('nombre_archivo', 'sin nombre')}):\n{texto_pdf}"
        )
        mensajes = [{"role": "system", "content": system_prompt}]
        # Últimos turnos de la conversación, para que la IA recuerde el
        # contexto sin dejar que el prompt crezca sin límite en chats largos.
        for turno in historial[-12:]:
            role = turno.get("role")
            content = turno.get("content")
            if role in ("user", "assistant") and content:
                mensajes.append({"role": role, "content": str(content)[:2000]})
        mensajes.append({"role": "user", "content": mensaje})

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "deepseek-v4-flash",
            "messages": mensajes,
            "temperature": 0.4,
            "max_tokens": 800
        }
        response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=60)
        if response.status_code != 200:
            return jsonify({"error": f"Error en DeepSeek API: {response.status_code}"}), 500
        registrar_uso(db, g.uid, "chat_pdf", g.plan_actual)
        data_resp = response.json()
        respuesta = data_resp['choices'][0]['message']['content']
        return jsonify({"respuesta": respuesta})
    except Exception as e:
        logger.exception("Error en /chat-pdf-mensaje")
        return jsonify({"error": f"Error en el chat: {str(e)}"}), 500


@bp.route("/chat-deepseek", methods=["POST"])
@requiere_plan(db, "premium", global_check=True)
def chat_deepseek():
    data = request.get_json()
    mensaje = data.get("mensaje")
    if not mensaje:
        return jsonify({"error": "Falta el mensaje"}), 400
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "chat_pdf")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    try:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return jsonify({"error": "API key de DeepSeek no configurada"}), 500
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": "Eres un asistente especializado en oposiciones. Responde de manera clara, concisa y útil."},
                {"role": "user", "content": mensaje}
            ],
            "temperature": 0.7,
            "max_tokens": 1000
        }
        response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=60)
        if response.status_code != 200:
            return jsonify({"error": f"Error en DeepSeek API: {response.status_code}"}), 500
        registrar_uso(db, g.uid, "chat_pdf", g.plan_actual)
        data = response.json()
        respuesta = data['choices'][0]['message']['content']
        return jsonify({"respuesta": respuesta})
    except Exception as e:
        logger.exception("Error en /chat-deepseek")
        return jsonify({"error": f"Error en el servicio de chat: {str(e)}"}), 500


# ===================================================================
# NUEVAS RUTAS PARA GUARDAR CONTENIDO DESDE PDF
# ===================================================================
@bp.route('/guardar-test-pdf', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def guardar_test_pdf():
    try:
        data = request.get_json()
        test_data = data.get('test_data', {})
        preguntas = test_data.get('preguntas', [])
        respuestas = test_data.get('respuestas', [])
        metadatos_entrada = test_data.get('metadatos', {})
        nombre_archivo = data.get('nombre_archivo', 'documento.pdf')
        documento_id = data.get('documento_id')

        # Se guarda en dos sitios con propósitos distintos:
        # - "test_pdf" (colección tests_pdf): el banco de preguntas ya
        #   generadas de este documento, para "Generar más"/"Ver" desde Mis
        #   Documentos sin volver a llamar a la IA. Ya existía.
        # - "test" (colección tests, mismo tipo que usan test-personalizado/
        #   test-oficial/etc.): el INTENTO en sí -- respuestas del usuario,
        #   aciertos/fallos, nota -- que antes no se guardaba en absoluto
        #   para tests desde PDF, así que nunca aparecían en Mis Tests ni en
        #   las estadísticas. Reutiliza el mismo test_id que el autoguardado
        #   "en_progreso" de la propia página, así el borrador se convierte
        #   en el registro final en vez de quedar duplicado o huérfano.
        guardar_resultado_en_firestore(
            db=db,
            tipo="test_pdf",
            contenido=preguntas,
            usuario_id=g.uid,
            metadatos={
                'nombre_archivo': nombre_archivo,
                'documento_id': documento_id,
                'num_preguntas': len(preguntas),
                'fecha_procesamiento': datetime.utcnow().isoformat()
            }
        )
        guardar_resultado_en_firestore(
            db=db,
            tipo="test",
            contenido=preguntas,
            usuario_id=g.uid,
            metadatos={
                "tipo": "test_pdf",
                "respuestas": respuestas,
                "tiempo": metadatos_entrada.get("tiempo", 0),
            },
            oposicion=obtener_oposicion_solicitada(),
            test_id=data.get('test_id'),
            marcadas_duda=data.get('marcadas_duda', []),
        )
        return jsonify({'mensaje': 'Test desde PDF guardado correctamente'})
    except Exception as e:
        logger.exception("Error en /guardar-test-pdf")
        return jsonify({'error': str(e)}), 500


@bp.route('/guardar-resumen-pdf', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def guardar_resumen_pdf():
    try:
        data = request.get_json()
        resumen = data.get('resumen', '')
        nombre_archivo = data.get('nombre_archivo', 'documento.pdf')
        guardar_resultado_en_firestore(
            db=db,
            tipo="resumen_pdf",
            contenido=resumen,
            usuario_id=g.uid,
            metadatos={
                'nombre_archivo': nombre_archivo,
                'documento_id': data.get('documento_id'),
                'longitud': len(resumen),
                'fecha_procesamiento': datetime.utcnow().isoformat()
            }
        )
        return jsonify({'mensaje': 'Resumen desde PDF guardado correctamente'})
    except Exception as e:
        logger.exception("Error en /guardar-resumen-pdf")
        return jsonify({'error': str(e)}), 500


@bp.route('/guardar-esquema-pdf', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def guardar_esquema_pdf():
    try:
        data = request.get_json()
        esquema = data.get('esquema', '')
        nombre_archivo = data.get('nombre_archivo', 'documento.pdf')
        guardar_resultado_en_firestore(
            db=db,
            tipo="esquema_pdf",
            contenido=esquema,
            usuario_id=g.uid,
            metadatos={
                'nombre_archivo': nombre_archivo,
                'documento_id': data.get('documento_id'),
                'longitud': len(esquema),
                'fecha_procesamiento': datetime.utcnow().isoformat()
            }
        )
        return jsonify({'mensaje': 'Esquema desde PDF guardado correctamente'})
    except Exception as e:
        logger.exception("Error en /guardar-esquema-pdf")
        return jsonify({'error': str(e)}), 500


@bp.route('/guardar-tarjetas-pdf', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def guardar_tarjetas_pdf():
    try:
        data = request.get_json()
        tarjetas = data.get('tarjetas', [])
        nombre_archivo = data.get('nombre_archivo', 'documento.pdf')
        guardar_resultado_en_firestore(
            db=db,
            tipo="tarjetas_pdf",
            contenido=tarjetas,
            usuario_id=g.uid,
            metadatos={
                'nombre_archivo': nombre_archivo,
                'documento_id': data.get('documento_id'),
                'num_tarjetas': len(tarjetas),
                'fecha_procesamiento': datetime.utcnow().isoformat()
            }
        )
        return jsonify({'mensaje': 'Tarjetas desde PDF guardadas correctamente'})
    except Exception as e:
        logger.exception("Error en /guardar-tarjetas-pdf")
        return jsonify({'error': str(e)}), 500


# ===================================================================
# "MIS DOCUMENTOS": biblioteca de PDFs subidos, para repasar más tarde el
# contenido de IA ya generado (resumen/esquema/tarjetas/test) sin tener que
# volver a subir el archivo ni volver a generarlo.
# ===================================================================
@bp.route('/mis-documentos', methods=['GET'])
@requiere_plan(db, "premium", global_check=True)
def mis_documentos():
    return jsonify({
        "documentos": listar_documentos(db, g.uid),
        "carpetas": listar_carpetas(db, g.uid),
    })


@bp.route('/carpetas-documentos', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def crear_carpeta_documentos():
    datos = request.get_json(silent=True) or {}
    nombre = crear_carpeta(db, g.uid, datos.get("nombre"))
    if not nombre:
        return jsonify({"error": "El nombre de la carpeta no puede estar vacío."}), 400
    return jsonify({"mensaje": "ok", "nombre": nombre})


@bp.route('/carpetas-documentos', methods=['DELETE'])
@requiere_plan(db, "premium", global_check=True)
def eliminar_carpeta_documentos():
    datos = request.get_json(silent=True) or {}
    eliminar_carpeta(db, g.uid, datos.get("nombre") or "")
    return jsonify({"mensaje": "ok"})


@bp.route('/documento/<documento_id>/carpeta', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def documento_carpeta(documento_id):
    datos = request.get_json(silent=True) or {}
    ok = actualizar_carpeta(db, g.uid, documento_id, datos.get("carpeta", ""))
    if not ok:
        return jsonify({"error": "No se encontró el documento indicado."}), 404
    return jsonify({"mensaje": "Carpeta actualizada"})


@bp.route('/documento/<documento_id>/titulo', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def documento_titulo(documento_id):
    datos = request.get_json(silent=True) or {}
    titulo = (datos.get("titulo") or "").strip()
    if not titulo:
        return jsonify({"error": "El nombre no puede estar vacío."}), 400
    ok = actualizar_titulo(db, g.uid, documento_id, titulo)
    if not ok:
        return jsonify({"error": "No se encontró el documento indicado."}), 404
    return jsonify({"mensaje": "Nombre actualizado", "titulo": titulo[:120]})


def _ultimo_por_documento(coleccion, documento_id, uid):
    docs = list(
        db.collection("usuarios").document(uid).collection(coleccion)
        .where("documento_id", "==", documento_id)
        .stream()
    )
    if not docs:
        return None
    docs.sort(key=lambda d: d.to_dict().get("fecha") or "", reverse=True)
    return docs[0].to_dict()


@bp.route('/documento/<documento_id>/resumen', methods=['GET'])
@requiere_plan(db, "premium", global_check=True)
def documento_resumen(documento_id):
    datos = _ultimo_por_documento("resumenes_pdf", documento_id, g.uid)
    if not datos:
        return jsonify({"error": "Este documento todavía no tiene un resumen generado."}), 404
    return jsonify({"resumen": datos.get("resumen"), "nombre_archivo": datos.get("nombre_archivo"), "fecha": datos.get("fecha")})


@bp.route('/documento/<documento_id>/esquema', methods=['GET'])
@requiere_plan(db, "premium", global_check=True)
def documento_esquema(documento_id):
    datos = _ultimo_por_documento("esquemas_pdf", documento_id, g.uid)
    if not datos:
        return jsonify({"error": "Este documento todavía no tiene un esquema generado."}), 404
    return jsonify({"esquema": datos.get("esquema"), "nombre_archivo": datos.get("nombre_archivo"), "fecha": datos.get("fecha")})


@bp.route('/documento/<documento_id>/test', methods=['GET'])
@requiere_plan(db, "premium", global_check=True)
def documento_test(documento_id):
    datos = _ultimo_por_documento("tests_pdf", documento_id, g.uid)
    if not datos:
        return jsonify({"error": "Este documento todavía no tiene un test generado."}), 404
    return jsonify({"test": datos.get("preguntas", []), "nombre_archivo": datos.get("nombre_archivo"), "fecha": datos.get("fecha")})


@bp.route('/documento/<documento_id>/tarjetas', methods=['GET'])
@requiere_plan(db, "premium", global_check=True)
def documento_tarjetas(documento_id):
    docs = (
        db.collection("usuarios").document(g.uid).collection("tarjetas_pdf")
        .where("documento_id", "==", documento_id)
        .stream()
    )
    todas = []
    for d in docs:
        todas.extend((d.to_dict() or {}).get("tarjetas", []))
    if not todas:
        return jsonify({"error": "Este documento todavía no tiene tarjetas generadas."}), 404
    modo = request.args.get("modo", "todas")
    if modo == "aleatorias":
        try:
            cantidad = int(request.args.get("cantidad", 10))
        except (TypeError, ValueError):
            cantidad = 10
        cantidad = max(1, min(cantidad, len(todas)))
        todas = random.sample(todas, cantidad)
    return jsonify({"tarjetas": todas})
