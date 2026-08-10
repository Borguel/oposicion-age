"""Piezas compartidas por varias herramientas de PDF (subida/parseo del
archivo, validación de lo que devuelve la IA, constantes de prompt) --
sacadas aparte para que cada módulo de herramienta (resumenes.py,
esquemas.py, tests.py, tarjetas.py) solo importe lo que de verdad usa, en
vez de que todas compartan un único archivo de 1500 líneas."""
import json
import logging
from io import BytesIO

from flask import g, jsonify, request
from pypdf import PdfReader

from firebase_setup import db
from documentos_pdf import obtener_o_crear_documento, obtener_documento
from limites_uso import max_paginas_para_plan
from deepseek_utils import generar_documento_largo_por_partes
from utils import barajar_opciones_pregunta

logger = logging.getLogger(__name__)

# Cupos que se comprueban y cobran juntos al generar un banco de preguntas/
# tarjetas desde PDF: el diario "pdf_ia" (compartido con el resto de
# herramientas de PDF) y el mensual "banco_pdf_mensual" (tope de documentos
# procesados al mes, ver limites_uso.py), mismo patrón que
# TIPOS_CUOTA_TEST_PERSONALIZADO en blueprints/test_ia.py.
TIPOS_CUOTA_BANCO_PDF = ("pdf_ia", "banco_pdf_mensual")

# Cláusula de fidelidad compartida por los prompts de resumen/esquema (los
# 3 modos: narrativo general, narrativo legal-mapa-de-artículos, esquema) --
# factorizada aquí el 05/08/2026 al añadir el modo legal para no
# cuadruplicar el mismo párrafo palabra por palabra en el archivo.
_CLAUSULA_FIDELIDAD_DOCUMENTO = (
    "IMPORTANTE -- fidelidad al documento: basa tu respuesta ÚNICAMENTE en el "
    "contenido del documento proporcionado. No añadas información externa, no "
    "completes huecos con conocimiento propio, y no inventes datos, fechas, "
    "artículos, cifras o nombres que no aparezcan literalmente en el texto. Si el "
    "documento no aporta un dato que normalmente se esperaría, no lo inventes: "
    "sencillamente no lo incluyas. Antes de dar tu respuesta por buena, revisa "
    "mentalmente que cada dato concreto que has escrito (fecha, cifra, ley, "
    "artículo, plazo) aparezca efectivamente en el documento que se te ha dado."
)


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


def _leer_override_texto_legal():
    """Override manual de tipo_contenido para /resumir-pdf y
    /generar-esquema-desde-pdf (ver resolver_tipo_contenido en
    documentos_pdf.py): "true"/"false" fuerza legal/general, cualquier
    otro valor (incluido ausente) deja la decisión en automático."""
    valor = request.form.get("es_texto_legal")
    if valor is None:
        return None
    return valor.strip().lower() == "true"


def _parece_documento_generado_valido(texto):
    """Filtro barato (sin gastar IA) contra un fallo real reportado por un
    usuario (06/08/2026): al pedir un esquema, el modelo devolvió UNA sola
    frase de METACOMENTARIO sobre el propio resultado ("El esquema ya está
    completo: cubre todas las secciones del documento... No hay ningún
    epígrafe pendiente de desarrollo...") en vez del esquema en Markdown
    pedido -- y esa frase se guardó y se mostró tal cual, sin ningún aviso
    de que la generación había fallado.

    Los CUATRO system_prompt de /resumir-pdf y /generar-esquema-desde-pdf
    (narrativo y mapa de artículos, resumen y esquema) exigen SIEMPRE al
    menos un encabezado de nivel 1 ("# ") como parte del formato -- su
    ausencia es una señal barata y fiable de que la respuesta no es el
    documento pedido, sea cual sea la causa exacta (metacomentario,
    respuesta vacía, texto cortado de forma rara). No hace falta detectar
    la frase de metacomentario en sí -- eso sería frágil ante la próxima
    reformulación distinta del mismo problema -- basta con comprobar que
    se cumplió el contrato de formato que el propio prompt exige."""
    if not texto:
        return False
    return any(linea.strip().startswith("# ") for linea in texto.splitlines())


def _generar_documento_validado(*args, **kwargs):
    """Envoltorio de generar_documento_largo_por_partes que reintenta UNA
    vez si el resultado no supera _parece_documento_generado_valido, en vez
    de dar por buena una respuesta que no es el documento pedido -- ver el
    comentario largo de esa función. Si el reintento TAMBIÉN falla el
    formato, se rinde (devuelve None), igual que ante cualquier otro fallo
    de generación -- el llamante ya sabe convertir un None en el mensaje de
    error habitual y devolver la cuota consumida."""
    resultado = generar_documento_largo_por_partes(*args, **kwargs)
    if resultado and not _parece_documento_generado_valido(resultado):
        logger.warning(
            "generar_documento_largo_por_partes devolvió una respuesta sin encabezado "
            "Markdown válido, reintentando una vez: %r", resultado[:200],
        )
        resultado = generar_documento_largo_por_partes(*args, **kwargs)
        if resultado and not _parece_documento_generado_valido(resultado):
            logger.warning("Segundo intento tampoco tiene un encabezado Markdown válido, se abandona.")
            return None
    return resultado


def _normalizar_pregunta_pdf(p):
    """Deja una pregunta cruda de generar_preguntas_ia_en_lotes/
    generar_banco_preguntas_adaptativo lista para mostrarse o guardarse:
    rellena campos opcionales que falten, homogeneiza tipos y baraja las
    opciones (para que la correcta no caiga siempre en la misma letra).
    Devuelve None si la pregunta no trae lo mínimo imprescindible."""
    if not all(k in p for k in ["pregunta", "opciones", "respuesta_correcta"]):
        return None
    if "explicacion" not in p:
        p["explicacion"] = "Explicación no disponible."
    p["pregunta"] = str(p["pregunta"]).strip() if p["pregunta"] else "Pregunta no disponible"
    p["explicacion"] = str(p["explicacion"]).strip() if p["explicacion"] else "Explicación no disponible"
    if not isinstance(p["opciones"], dict):
        p["opciones"] = {}
    for key in list(p["opciones"].keys()):
        p["opciones"][key] = str(p["opciones"][key]).strip() if p["opciones"][key] else "Opción no disponible"
    p["respuesta_correcta"] = str(p["respuesta_correcta"]).upper() if p["respuesta_correcta"] else "A"
    return barajar_opciones_pregunta(p)


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


def _ultimo_por_documento(coleccion, documento_id, uid):
    """Última entrada guardada de una subcolección de contenido generado
    (resumenes_pdf/esquemas_pdf/tests_pdf) para un documento -- usada por
    los GET /documento/<id>/resumen|esquema|test de cada módulo de
    herramienta correspondiente."""
    docs = list(
        db.collection("usuarios").document(uid).collection(coleccion)
        .where("documento_id", "==", documento_id)
        .stream()
    )
    if not docs:
        return None
    docs.sort(key=lambda d: d.to_dict().get("fecha") or "", reverse=True)
    return docs[0].to_dict()
