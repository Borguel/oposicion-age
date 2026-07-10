"""Herramientas de IA sobre un PDF subido por el propio usuario: resumen,
esquema, test, tarjetas y chat sobre el documento, más "Mis documentos"
(la biblioteca de lo ya generado)."""
import json
import logging
import os
import random
from datetime import datetime
from io import BytesIO

import requests
from flask import Blueprint, g, jsonify, request
from PyPDF2 import PdfReader

from firebase_setup import db
from auth_utils import requiere_login, requiere_plan
from limites_uso import max_paginas_para_plan, verificar_limite_uso, registrar_uso
from documentos_pdf import (
    obtener_o_crear_documento, obtener_documento, listar_documentos, actualizar_carpeta,
    listar_carpetas, crear_carpeta, eliminar_carpeta
)
from guardar_resultado import guardar_resultado_en_firestore
from test_generator import generar_preguntas_ia_en_lotes
from utils import barajar_opciones_pregunta
from deepseek_utils import generar_documento_largo_por_partes

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
    pdf_reader = PdfReader(BytesIO(pdf_file.read()))
    limite_paginas = max_paginas_para_plan(plan_actual)
    if len(pdf_reader.pages) > limite_paginas:
        return None, None, None, (jsonify({"error": f"El PDF tiene demasiadas páginas para tu plan (máx. {limite_paginas}). Divide el documento en partes más pequeñas o mejora de plan."}), 400)
    text = ""
    for page in pdf_reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    if not text.strip():
        return None, None, None, (jsonify({"error": "El PDF no contiene texto extraíble (puede ser una imagen)"}), 400)
    documento_id, documento = obtener_o_crear_documento(db, g.uid, text, pdf_file.filename, len(pdf_reader.pages))
    return text, documento_id, pdf_file.filename, None


@bp.route('/resumir-pdf', methods=['POST'])
@requiere_plan(db, "gratis", global_check=True)
def resumir_pdf():
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "pdf_ia")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    text, documento_id, nombre_archivo, error = _resolver_texto_documento(g.plan_actual)
    if error:
        return error
    try:
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
            "resumen debe ser útil para un opositor."
        )
        if not os.getenv("DEEPSEEK_API_KEY"):
            return jsonify({"error": "API key de DeepSeek no configurada"}), 500
        resumen = generar_documento_largo_por_partes(system_prompt, text, etiqueta_documento="Documento para resumir")
        if not resumen:
            return jsonify({"error": "Error en DeepSeek API"}), 500
        registrar_uso(db, g.uid, "pdf_ia", g.plan_actual)
        return jsonify({"resumen": resumen, "documento_id": documento_id, "nombre_archivo": nombre_archivo})
    except Exception as e:
        return jsonify({"error": f"Error al procesar el PDF: {str(e)}"}), 500


# ✅ NUEVA RUTA: alias para compatibilidad con frontend
@bp.route('/resumir-documento', methods=['POST'])
@requiere_plan(db, "gratis", global_check=True)
def resumir_documento():
    return resumir_pdf()


@bp.route('/generar-esquema-desde-pdf', methods=['POST'])
@requiere_plan(db, "gratis", global_check=True)
def generar_esquema_desde_pdf():
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "pdf_ia")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    text, documento_id, nombre_archivo, error = _resolver_texto_documento(g.plan_actual)
    if error:
        return error
    try:
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
            "propio párrafo o viñeta, sin mezclar varias ideas en una misma línea larga."
        )
        if not os.getenv("DEEPSEEK_API_KEY"):
            return jsonify({"error": "API key de DeepSeek no configurada"}), 500
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
        esquema = generar_documento_largo_por_partes(
            system_prompt,
            text,
            etiqueta_documento="Documento para crear esquema",
            instrucciones_fusion_extra=instrucciones_fusion_esquema,
        )
        if not esquema:
            return jsonify({"error": "Error en DeepSeek API"}), 500
        registrar_uso(db, g.uid, "pdf_ia", g.plan_actual)
        return jsonify({"esquema": esquema, "documento_id": documento_id, "nombre_archivo": nombre_archivo})
    except Exception as e:
        return jsonify({"error": f"Error al procesar el PDF: {str(e)}"}), 500


@bp.route('/generar-test-desde-pdf', methods=['POST'])
@requiere_plan(db, "gratis", global_check=True)
def generar_test_desde_pdf():
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
    try:
        max_length = 150000
        if len(text) > max_length:
            text = text[:max_length]

        def construir_prompt(n):
            system_prompt = (
                f"Eres un experto en la elaboración de preguntas tipo test para oposiciones oficiales en España. "
                f"Tu tarea es generar EXACTAMENTE {n} preguntas de opción múltiple de alta calidad, "
                f"basadas únicamente en el documento proporcionado. Cada pregunta debe cumplir lo siguiente:\n"
                f"1. **Formato**: pregunta clara y directa, seguida de cuatro opciones (A, B, C, D).\n"
                f"2. **Precisión**: si el documento menciona leyes, artículos, plazos, funciones, definiciones, principios o procedimientos, la pregunta debe reflejarlos con exactitud.\n"
                f"3. **Respuesta correcta**: debe ser inequívoca y extraída directamente del texto.\n"
                f"4. **Distractores**: deben ser técnicamente plausibles, basados en confusiones comunes, errores típicos o elementos similares del propio documento.\n"
                f"5. **Neutralidad**: evita lenguaje coloquial, ambigüedades, opiniones o preguntas triviales.\n"
                f"6. **Explicación**: repasa TODAS las opciones, una por línea y en orden, con este formato exacto: \"A) es correcta/incorrecta porque... B) es correcta/incorrecta porque... C) ... D) ...\", citando o basándote en el contenido del documento.\n"
                f"Devuelve SOLO un array JSON válido con este formato exacto:\n"
                f"[{{\"pregunta\": \"...\", \"opciones\": {{\"A\": \"...\", \"B\": \"...\", \"C\": \"...\", \"D\": \"...\"}}, \"respuesta_correcta\": \"A\", \"explicacion\": \"...\"}}]\n"
                f"NO añadas texto adicional antes ni después del array JSON."
            )
            return f"{system_prompt}\n\nDocumento para crear preguntas test:\n{text}"

        preguntas, errores_lotes = generar_preguntas_ia_en_lotes(construir_prompt, num_preguntas)
        registrar_uso(db, g.uid, "pdf_ia", g.plan_actual)
        if not preguntas:
            return jsonify({
                "error": "La IA no devolvió un JSON válido para las preguntas. Error técnico.",
                "respuesta_cruda": "; ".join(errores_lotes)[:500]
            }), 500
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
            return jsonify({
                "error": "La IA generó preguntas vacías o inválidas."
            }), 500
        resultado = {"test": preguntas_validadas, "documento_id": documento_id, "nombre_archivo": nombre_archivo}
        if len(preguntas_validadas) < num_preguntas:
            resultado["advertencia"] = f"Solo se generaron {len(preguntas_validadas)} de {num_preguntas} preguntas."
        return jsonify(resultado)
    except Exception as e:
        return jsonify({
            "error": f"Error al procesar el PDF o generar preguntas: {str(e)}"
        }), 500


@bp.route('/generar-tarjetas-desde-pdf', methods=['POST'])
@requiere_plan(db, "gratis", global_check=True)
def generar_tarjetas_desde_pdf():
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "pdf_ia")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    text, documento_id, nombre_archivo, error = _resolver_texto_documento(g.plan_actual)
    if error:
        return error
    respuesta = None
    try:
        max_length = 150000
        if len(text) > max_length:
            text = text[:max_length]
        try:
            num_tarjetas = int(request.form.get("num_tarjetas", 10))
        except (TypeError, ValueError):
            num_tarjetas = 10
        num_tarjetas = max(1, min(num_tarjetas, 50))
        system_prompt = (
            "Eres un experto en metodologías de estudio para oposiciones en España. Tu tarea es crear tarjetas de memoria (flashcards) "
            "de alta calidad a partir de un documento normativo o temario. Cada tarjeta debe cumplir lo siguiente:\n"
            "1. **Formato**: una pregunta clara y específica en el anverso; una respuesta concisa, precisa y completa en el reverso.\n"
            "2. **Tipos de tarjetas**: combina diferentes formatos:\n"
            "   - Definiciones: \"¿Qué es...?\"\n"
            "   - Enumeraciones: \"¿Cuáles son los principios de...?\", \"¿Qué plazos establece la ley para...?\"\n"
            "   - Comparaciones: \"¿Cuál es la diferencia entre X e Y?\"\n"
            "   - Funciones/competencias: \"¿A quién corresponde...?\", \"¿Qué órgano es competente para...?\"\n"
            "   - Supuestos prácticos breves: \"Si un funcionario hace X, ¿qué tipo de falta comete?\"\n"
            "   - Excepciones o límites: \"¿En qué casos NO se aplica...?\"\n"
            "3. **Profundidad, no repetición**: evita generar múltiples tarjetas del mismo artículo. En su lugar, extrae los conceptos clave y formula preguntas distintas.\n"
            "4. **Precisión normativa**: si el texto menciona leyes, artículos, reales decretos, etc., inclúyelos en la respuesta, pero no como copia literal.\n"
            "5. **Evita**: preguntas vagas, respuestas largas, frases incompletas o contenido redundante.\n"
            f"Genera EXACTAMENTE {num_tarjetas} tarjetas (ni más ni menos), como un array JSON con este formato:\n"
            "[{\"pregunta\": \"...\", \"respuesta\": \"...\"}]\n"
            "NO añadas texto adicional antes ni después del JSON."
        )
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return jsonify({"error": "API key de DeepSeek no configurada"}), 500
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Documento para crear tarjetas de memoria:\n{text}"}
            ],
            "temperature": 0.3,
            # Margen amplio por tarjeta para que no se corte la respuesta a
            # medias (antes era un límite fijo de 2000, insuficiente para
            # bastantes tarjetas y provocaba un JSON incompleto).
            "max_tokens": min(8000, 200 + num_tarjetas * 220)
        }
        response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=60)
        if response.status_code != 200:
            return jsonify({"error": f"Error en DeepSeek API: {response.status_code}"}), 500
        registrar_uso(db, g.uid, "pdf_ia", g.plan_actual)
        data = response.json()
        respuesta = data['choices'][0]['message']['content']
        start_index = respuesta.find("[")
        end_index = respuesta.rfind("]") + 1
        if start_index == -1 or end_index <= start_index:
            raise ValueError("No se encontró un array JSON en la respuesta.")
        json_str = respuesta[start_index:end_index]
        try:
            tarjetas = json.loads(json_str)
        except json.JSONDecodeError:
            json_str_fixed = json_str.replace("'", '"')
            try:
                tarjetas = json.loads(json_str_fixed)
            except json.JSONDecodeError:
                return jsonify({
                    "error": "La IA no devolvió un JSON válido. Error técnico.",
                    "respuesta_cruda": respuesta[:500]
                }), 500
        tarjetas_validadas = []
        for t in tarjetas:
            if isinstance(t, dict) and "pregunta" in t and "respuesta" in t:
                t["pregunta"] = str(t["pregunta"]).strip() if t["pregunta"] else "Pregunta no disponible"
                t["respuesta"] = str(t["respuesta"]).strip() if t["respuesta"] else "Respuesta no disponible"
                tarjetas_validadas.append(t)
        if not tarjetas_validadas:
            return jsonify({
                "error": "La IA generó tarjetas vacías o inválidas.",
                "respuesta_cruda": respuesta[:500]
            }), 500
        return jsonify({"tarjetas": tarjetas_validadas, "documento_id": documento_id, "nombre_archivo": nombre_archivo})
    except Exception as e:
        return jsonify({
            "error": f"Error al procesar el PDF o generar tarjetas: {str(e)}",
            "respuesta_cruda": respuesta[:500] if respuesta is not None else "N/A"
        }), 500


# Nº de caracteres del PDF que se guardan para poder chatear sobre él. Se
# recorta más que en resumen/esquema porque este texto se reenvía en el
# prompt de CADA mensaje del chat (no una sola vez), así que hay que
# mantenerlo comedido para no disparar el coste por conversación.
MAX_CARACTERES_CHAT_PDF = 12000


@bp.route('/subir-pdf-chat', methods=['POST'])
@requiere_plan(db, "basico", global_check=True)
def subir_pdf_chat():
    if 'pdf' not in request.files:
        return jsonify({"error": "No se encontró archivo PDF"}), 400
    pdf_file = request.files['pdf']
    if pdf_file.filename == '':
        return jsonify({"error": "Nombre de archivo inválido"}), 400
    try:
        pdf_reader = PdfReader(BytesIO(pdf_file.read()))
        limite_paginas = max_paginas_para_plan(g.plan_actual)
        if len(pdf_reader.pages) > limite_paginas:
            return jsonify({"error": f"El PDF tiene demasiadas páginas para tu plan (máx. {limite_paginas}). Divide el documento en partes más pequeñas o mejora de plan."}), 400
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        if not text.strip():
            return jsonify({"error": "El PDF no contiene texto extraíble (puede ser una imagen)"}), 400
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
            "paginas": len(pdf_reader.pages)
        })
    except Exception as e:
        return jsonify({"error": f"Error al procesar el PDF: {str(e)}"}), 500


@bp.route('/chat-pdf-mensaje', methods=['POST'])
@requiere_plan(db, "basico", global_check=True)
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
            "model": "deepseek-chat",
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
            "model": "deepseek-chat",
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
        return jsonify({"error": f"Error en el servicio de chat: {str(e)}"}), 500


# ===================================================================
# NUEVAS RUTAS PARA GUARDAR CONTENIDO DESDE PDF
# ===================================================================
@bp.route('/guardar-test-pdf', methods=['POST'])
@requiere_plan(db, "gratis", global_check=True)
def guardar_test_pdf():
    try:
        data = request.get_json()
        test_data = data.get('test_data', {})
        preguntas = test_data.get('preguntas', [])
        nombre_archivo = data.get('nombre_archivo', 'documento.pdf')
        guardar_resultado_en_firestore(
            db=db,
            tipo="test_pdf",
            contenido=preguntas,
            usuario_id=g.uid,
            metadatos={
                'nombre_archivo': nombre_archivo,
                'documento_id': data.get('documento_id'),
                'num_preguntas': len(preguntas),
                'fecha_procesamiento': datetime.utcnow().isoformat()
            }
        )
        # Si este test se autoguardó "en_progreso" mientras se hacía (mismo
        # mecanismo que usan test-generator/repetir-test/preguntas-falladas),
        # se borra ese borrador -- ya quedó guardado como test_pdf de verdad,
        # no debe seguir apareciendo como "en progreso" en ningún sitio.
        test_id = data.get('test_id')
        if test_id:
            try:
                db.collection("usuarios").document(g.uid).collection("tests").document(test_id).delete()
            except Exception as e:
                logger.warning("No se pudo borrar el borrador de test en progreso %s: %s", test_id, e)
        return jsonify({'mensaje': 'Test desde PDF guardado correctamente'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/guardar-resumen-pdf', methods=['POST'])
@requiere_plan(db, "gratis", global_check=True)
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
        return jsonify({'error': str(e)}), 500


@bp.route('/guardar-esquema-pdf', methods=['POST'])
@requiere_plan(db, "gratis", global_check=True)
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
        return jsonify({'error': str(e)}), 500


@bp.route('/guardar-tarjetas-pdf', methods=['POST'])
@requiere_plan(db, "gratis", global_check=True)
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
        return jsonify({'error': str(e)}), 500


# ===================================================================
# "MIS DOCUMENTOS": biblioteca de PDFs subidos, para repasar más tarde el
# contenido de IA ya generado (resumen/esquema/tarjetas/test) sin tener que
# volver a subir el archivo ni volver a generarlo.
# ===================================================================
@bp.route('/mis-documentos', methods=['GET'])
@requiere_login(db)
def mis_documentos():
    return jsonify({
        "documentos": listar_documentos(db, g.uid),
        "carpetas": listar_carpetas(db, g.uid),
    })


@bp.route('/carpetas-documentos', methods=['POST'])
@requiere_login(db)
def crear_carpeta_documentos():
    datos = request.get_json(silent=True) or {}
    nombre = crear_carpeta(db, g.uid, datos.get("nombre"))
    if not nombre:
        return jsonify({"error": "El nombre de la carpeta no puede estar vacío."}), 400
    return jsonify({"mensaje": "ok", "nombre": nombre})


@bp.route('/carpetas-documentos', methods=['DELETE'])
@requiere_login(db)
def eliminar_carpeta_documentos():
    datos = request.get_json(silent=True) or {}
    eliminar_carpeta(db, g.uid, datos.get("nombre") or "")
    return jsonify({"mensaje": "ok"})


@bp.route('/documento/<documento_id>/carpeta', methods=['POST'])
@requiere_login(db)
def documento_carpeta(documento_id):
    datos = request.get_json(silent=True) or {}
    ok = actualizar_carpeta(db, g.uid, documento_id, datos.get("carpeta", ""))
    if not ok:
        return jsonify({"error": "No se encontró el documento indicado."}), 404
    return jsonify({"mensaje": "Carpeta actualizada"})


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
@requiere_login(db)
def documento_resumen(documento_id):
    datos = _ultimo_por_documento("resumenes_pdf", documento_id, g.uid)
    if not datos:
        return jsonify({"error": "Este documento todavía no tiene un resumen generado."}), 404
    return jsonify({"resumen": datos.get("resumen"), "nombre_archivo": datos.get("nombre_archivo"), "fecha": datos.get("fecha")})


@bp.route('/documento/<documento_id>/esquema', methods=['GET'])
@requiere_login(db)
def documento_esquema(documento_id):
    datos = _ultimo_por_documento("esquemas_pdf", documento_id, g.uid)
    if not datos:
        return jsonify({"error": "Este documento todavía no tiene un esquema generado."}), 404
    return jsonify({"esquema": datos.get("esquema"), "nombre_archivo": datos.get("nombre_archivo"), "fecha": datos.get("fecha")})


@bp.route('/documento/<documento_id>/test', methods=['GET'])
@requiere_login(db)
def documento_test(documento_id):
    datos = _ultimo_por_documento("tests_pdf", documento_id, g.uid)
    if not datos:
        return jsonify({"error": "Este documento todavía no tiene un test generado."}), 404
    return jsonify({"test": datos.get("preguntas", []), "nombre_archivo": datos.get("nombre_archivo"), "fecha": datos.get("fecha")})


@bp.route('/documento/<documento_id>/tarjetas', methods=['GET'])
@requiere_login(db)
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
