import os
import random
import requests
import json
import traceback
import stripe
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
from PyPDF2 import PdfReader
from io import BytesIO
from datetime import datetime, date
# Módulos personalizados
from test_generator import generar_test_avanzado, generar_preguntas_ia_en_lotes
from chat_controller import responder_chat, consultar_asistente_examen
from deepseek_utils import call_deepseek_api
from esquema_generator import generar_esquema
from save_controller import guardar_test_route, guardar_esquema_route
from rutas_progreso import registrar_rutas_progreso
from guardar_resultado import guardar_resultado_en_firestore
from auth_utils import requiere_login, requiere_plan, obtener_oposicion_solicitada
from registro_progreso_usuario import actualizar_suscripcion, obtener_perfil_usuario, obtener_resumen_progreso
from oposiciones import OPOSICIONES, OPOSICION_POR_DEFECTO, oposicion_valida, coleccion_temario, coleccion_examenes_oficiales
from limites_uso import max_paginas_para_plan, verificar_limite_uso, registrar_uso
from documentos_pdf import obtener_o_crear_documento, obtener_documento, listar_documentos, actualizar_carpeta
from utils import seleccionar_preguntas_con_cuota
# Cargar variables de entorno
load_dotenv()
print("🔑 Clave OpenAI:", "configurada" if os.getenv("OPENAI_API_KEY") else "no configurada")
print("🔑 Clave DeepSeek:", "configurada" if os.getenv("DEEPSEEK_API_KEY") else "no configurada")
# Inicializar Firebase
# Admite dos formas de dar la clave de servicio: un fichero (FIREBASE_KEY_PATH,
# útil con "Secret Files" de Render) o el JSON completo en una variable de
# entorno (FIREBASE_CREDENTIALS_JSON), útil en plataformas sin subida de ficheros.
if not firebase_admin._apps:
    firebase_credentials_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if firebase_credentials_json:
        cred = credentials.Certificate(json.loads(firebase_credentials_json))
    else:
        firebase_key_path = os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json")
        cred = credentials.Certificate(firebase_key_path)
    firebase_admin.initialize_app(cred)
db = firestore.client()
# Inicializar Flask
app = Flask(__name__)
cors_origins_env = os.getenv("CORS_ORIGINS", "")
cors_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
if not cors_origins:
    cors_origins = ["http://localhost:8080", "http://127.0.0.1:8080"]
CORS(app, origins=cors_origins)
print(f"✅ CORS activado para: {cors_origins}")

# Tamaño máximo de subida (20 MB): un PDF de exámenes normal pesa unos pocos
# MB incluso con muchas páginas, así que esto solo frena subidas anómalas
# (ficheros gigantes) antes de que lleguen a ocupar memoria del servidor.
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024


@app.errorhandler(413)
def fichero_demasiado_grande(_error):
    return jsonify({"error": "El archivo es demasiado grande (máximo 20 MB)."}), 413

# Protección por API key: se activa automáticamente en cuanto se defina
# API_SECRET_KEY en el entorno. Mientras no exista, el comportamiento no
# cambia respecto a antes (rutas abiertas), para no romper el despliegue
# actual hasta que el frontend envíe la cabecera X-API-Key.
API_SECRET_KEY = os.getenv("API_SECRET_KEY")
if API_SECRET_KEY:
    print("🔒 Protección por API key activada")
else:
    print("⚠️ API_SECRET_KEY no configurada: las rutas quedan abiertas sin autenticación")

@app.before_request
def verificar_api_key():
    if not API_SECRET_KEY:
        return
    if request.method == "OPTIONS":
        return
    if request.path in ("/", "/webhook-stripe"):
        return
    if request.headers.get("X-API-Key") != API_SECRET_KEY:
        return jsonify({"error": "No autorizado"}), 401

# Configuración de Stripe (pagos y suscripciones)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_IDS = {
    "basico": os.getenv("STRIPE_PRICE_ID_BASICO"),
    "premium": os.getenv("STRIPE_PRICE_ID_PREMIUM"),
}
PRECIO_A_PLAN = {v: k for k, v in STRIPE_PRICE_IDS.items() if v}
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8080")

# === Todas tus rutas existentes aquí ===
@app.route("/chat", methods=["POST"])
@requiere_plan(db, "premium")
def chat_route():
    data = request.get_json()
    mensaje = data.get("mensaje")
    temas = data.get("temas", [])
    chat_id = data.get("chat_id")
    respuesta, chat_id = responder_chat(
        mensaje=mensaje,
        temas=temas,
        db=db,
        usuario_id=g.uid,
        chat_id=chat_id,
        coleccion=coleccion_temario(g.oposicion)
    )
    return jsonify({"respuesta": respuesta, "chat_id": chat_id})
@app.route("/consultar-asistente-examen", methods=["POST"])
@requiere_plan(db, "premium")
def ruta_asistente_examen():
    data = request.get_json()
    mensaje = data.get("mensaje", "")
    if not mensaje:
        return jsonify({"error": "Falta el mensaje"}), 400
    try:
        respuesta = consultar_asistente_examen(mensaje, oposicion=g.oposicion)
        return jsonify({"respuesta": respuesta})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route("/generar-test-avanzado", methods=["POST"])
@requiere_plan(db, "basico")
def generar_test_avanzado_route():
    data = request.get_json()
    print(f"📅 Petición recibida en /generar-test-avanzado: {data}")
    temas = data.get("temas", [])
    try:
        num_preguntas = max(1, min(100, int(data.get("num_preguntas", 5))))
    except (TypeError, ValueError):
        num_preguntas = 5
    print(f"📋 Temas extraídos: {temas}")
    print(f"🧪 Número de preguntas solicitadas: {num_preguntas}")
    resultado = generar_test_avanzado(temas=temas, db=db, num_preguntas=num_preguntas, coleccion=coleccion_temario(g.oposicion), oposicion=g.oposicion)
    print(f"📄 Resultado del test: {resultado}")
    return jsonify(resultado)
@app.route("/generar-esquema", methods=["POST"])
@requiere_plan(db, "basico")
def generar_esquema_route():
    data = request.get_json(silent=True)
    if not data:
        print("❌ No se ha recibido JSON en la petición")
        return jsonify({"error": "No se ha recibido un cuerpo JSON válido"}), 400
    print("📩 Datos recibidos en /generar-esquema:", data)
    temas = data.get("temas", [])
    instrucciones = data.get("instrucciones", "Resume los contenidos clave.")
    nivel = data.get("nivel", "general")
    resultado = generar_esquema(temas=temas, db=db, instrucciones=instrucciones, nivel=nivel, coleccion=coleccion_temario(g.oposicion))
    return jsonify({"esquema": resultado})
@app.route("/generar-test-oficial", methods=["POST"])
@requiere_plan(db, "basico")
def generar_test_oficial():
    data = request.get_json()
    print("✅ Ruta /generar-test-oficial llamada")
    print("📥 Datos recibidos:", data)
    try:
        num_preguntas = max(1, min(100, int(data.get("num_preguntas", 10))))
    except (TypeError, ValueError):
        num_preguntas = 10
    examenes_filtrados = data.get("examenes", [])
    temas_filtrados = data.get("temas", [])
    print("🔍 Número de preguntas solicitado:", num_preguntas)
    print("📚 Exámenes filtrados:", examenes_filtrados)
    print("🏷️ Temas filtrados:", temas_filtrados)
    coleccion = coleccion_examenes_oficiales(g.oposicion)
    try:
        docs = db.collection(coleccion).stream()
    except Exception as e:
        print("❌ Error accediendo a Firestore:", e)
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
    print(f"✅ Preguntas encontradas tras filtro en {coleccion}: {len(preguntas)}")
    if not preguntas:
        return jsonify({"test": [], "mensaje": "Todavía no hay preguntas oficiales cargadas para esta oposición"}), 404
    seleccionadas = seleccionar_preguntas_con_cuota(preguntas, num_preguntas, temas_filtrados)
    print(f"🎯 Preguntas seleccionadas: {len(seleccionadas)}")
    return jsonify({"test": seleccionadas})
@app.route("/guardar-test-oficial", methods=["POST"])
@requiere_login(db)
def guardar_test_oficial():
    data = request.get_json()
    print("💾 Guardando test oficial:", data)
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
        print("✅ Test oficial guardado correctamente")
        return jsonify({"mensaje": "Test oficial guardado correctamente"}), 200
    except Exception as e:
        print("❌ Error al guardar test oficial:", e)
        return jsonify({"error": str(e)}), 500
# Guardado y progreso
app.add_url_rule("/guardar-test", view_func=guardar_test_route(db), methods=["POST"])
app.add_url_rule("/guardar-esquema", view_func=guardar_esquema_route(db), methods=["POST"])
registrar_rutas_progreso(app, db)
@app.route("/oposiciones-disponibles", methods=["GET"])
def obtener_oposiciones_disponibles():
    return jsonify({
        "oposiciones": [{"id": oid, "nombre": datos["nombre"]} for oid, datos in OPOSICIONES.items()]
    })
@app.route("/temas-disponibles", methods=["GET"])
@requiere_login(db)
def obtener_temas_disponibles():
    oposicion = obtener_oposicion_solicitada()
    coleccion = coleccion_temario(oposicion)
    temas_disponibles = []
    bloques = db.collection(coleccion).stream()
    for bloque in bloques:
        bloque_id = bloque.id
        temas_ref = db.collection(coleccion).document(bloque_id).collection("temas").stream()
        for tema in temas_ref:
            tema_data = tema.to_dict()
            tema_id = tema.id
            titulo = tema_data.get("titulo", f"{tema_id}")
            temas_disponibles.append({
                "id": f"{bloque_id}-{tema_id}",
                "titulo": titulo
            })
    return jsonify({"temas": temas_disponibles, "oposicion": oposicion})
@app.route("/progreso-usuario", methods=["GET"])
@requiere_login(db)
def progreso_usuario():
    doc_user = db.collection("usuarios").document(g.uid)
    progreso = doc_user.get().to_dict()
    if not progreso:
        return jsonify({"error": "Usuario no encontrado"}), 404
    return jsonify({
        "tests_realizados": progreso.get("tests_realizados", 0),
        "puntuacion_media_test": progreso.get("puntuacion_media_test", 0),
        "ultimo_test": progreso.get("ultimo_test", {}),
        "total_aciertos": progreso.get("total_aciertos", 0),
        "esquemas_generados": progreso.get("esquemas_generados", 0)
    })
@app.route("/", methods=["GET"])
def listar_rutas():
    rutas = [rule.rule for rule in app.url_map.iter_rules()]
    return jsonify({"rutas_disponibles": rutas})
# Traducción de temas (para IA)
def obtener_titulos_temas_reales(db, coleccion, lista_codigos):
    """Traduce códigos "bloque-tema" (p. ej. "bloque_01-tema_02") a sus
    títulos reales guardados en Firestore -- la misma fuente que usa
    /temas-disponibles -- en vez de una lista fija en el código que solo
    cubría los temas de AGE y no servía para el resto de oposiciones."""
    titulos = []
    for codigo in lista_codigos:
        partes = codigo.split("-", 1)
        if len(partes) < 2:
            titulos.append(codigo)
            continue
        bloque_id, tema_id = partes
        doc = db.collection(coleccion).document(bloque_id).collection("temas").document(tema_id).get()
        titulos.append(doc.to_dict().get("titulo", codigo) if doc.exists else codigo)
    return titulos
@app.route("/generar-test-inteligente", methods=["POST"])
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
        return jsonify(resultado)
    except Exception as e:
        print("❌ Error al generar test inteligente:", e)
        return jsonify({"error": str(e)}), 500
@app.route("/analisis-rendimiento", methods=["GET"])
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
    except Exception as e:
        print("❌ Error al generar análisis de rendimiento:", e)
        analisis = None

    if not analisis:
        return jsonify({"analisis": None, "mensaje": "No se ha podido generar el análisis ahora mismo. Inténtalo de nuevo más tarde."})
    return jsonify({"analisis": analisis.strip()})
@app.route("/conversaciones", methods=["GET"])
@requiere_plan(db, "premium")
def obtener_conversaciones_usuario():
    docs = db.collection("conversaciones_IA") \
             .document(g.uid) \
             .collection("conversaciones") \
             .order_by("timestamp_inicio", direction=firestore.Query.DESCENDING) \
             .stream()
    resultado = []
    for doc in docs:
        data = doc.to_dict()
        resultado.append({
            "id": doc.id,
            "titulo": data.get("titulo", "Sin título"),
            "timestamp_inicio": data.get("timestamp_inicio")
        })
    return jsonify({"conversaciones": resultado})
@app.route("/conversacion/<conversacion_id>", methods=["GET"])
@requiere_plan(db, "premium")
def obtener_conversacion(conversacion_id):
    doc = db.collection("conversaciones_IA") \
            .document(g.uid) \
            .collection("conversaciones") \
            .document(conversacion_id) \
            .get()
    if not doc.exists:
        return jsonify({"error": "Conversación no encontrada"}), 404
    return jsonify(doc.to_dict())
@app.route("/generar-test-fallos", methods=["POST"])
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
# ===================================================================
# RUTAS PARA DEEPSEEK (PDFs)
# ===================================================================

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


@app.route('/resumir-pdf', methods=['POST'])
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
            "Eres un experto en oposiciones. Resume este documento en puntos clave, "
            "destacando conceptos fundamentales, leyes importantes y fechas relevantes. "
            "Usa viñetas claras y estructura organizada. El resumen debe ser útil para un opositor."
        )
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return jsonify({"error": "API key de DeepSeek no configurada"}), 500
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Documento para resumir:\n{text}"}
            ],
            "temperature": 0.3,
            "max_tokens": 2000
        }
        response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload)
        if response.status_code != 200:
            return jsonify({"error": f"Error en DeepSeek API: {response.status_code}"}), 500
        registrar_uso(db, g.uid, "pdf_ia", g.plan_actual)
        data = response.json()
        resumen = data['choices'][0]['message']['content']
        return jsonify({"resumen": resumen, "documento_id": documento_id, "nombre_archivo": nombre_archivo})
    except Exception as e:
        return jsonify({"error": f"Error al procesar el PDF: {str(e)}"}), 500
# ✅ NUEVA RUTA: alias para compatibilidad con frontend
@app.route('/resumir-documento', methods=['POST'])
@requiere_plan(db, "gratis", global_check=True)
def resumir_documento():
    return resumir_pdf()
@app.route('/generar-esquema-desde-pdf', methods=['POST'])
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
            "Eres un experto en oposiciones. Crea un esquema de estudio estructurado y "
            "visual a partir del siguiente documento, útil para repasar. Usa EXACTAMENTE "
            "este formato Markdown, sin desviarte de él:\n"
            "- Encabezados de nivel 1 con \"# \" para las secciones principales del temario.\n"
            "- Encabezados de nivel 2 con \"## \" para subsecciones.\n"
            "- Texto en **negrita** para términos clave, nombres de leyes o artículos, la "
            "primera vez que aparecen.\n"
            "- Listas con \"- \" para viñetas normales.\n"
            "- Listas numeradas con \"1. \", \"2. \", etc. cuando el orden importe (por "
            "ejemplo, pasos de un procedimiento o fases de un proceso).\n"
            "- Cuando definas formalmente un concepto, usa el prefijo \"> \" para esa línea, "
            "de forma que se pueda destacar como una caja de definición aparte.\n"
            "No uses tablas, bloques de código, ni HTML. No anides más de un nivel de viñetas. "
            "Cada línea de texto debe ir en su propio párrafo o viñeta, sin mezclar varias "
            "ideas en una misma línea larga."
        )
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return jsonify({"error": "API key de DeepSeek no configurada"}), 500
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Documento para crear esquema:\n{text}"}
            ],
            "temperature": 0.3,
            "max_tokens": 2000
        }
        response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload)
        if response.status_code != 200:
            return jsonify({"error": f"Error en DeepSeek API: {response.status_code}"}), 500
        registrar_uso(db, g.uid, "pdf_ia", g.plan_actual)
        data = response.json()
        esquema = data['choices'][0]['message']['content']
        return jsonify({"esquema": esquema, "documento_id": documento_id, "nombre_archivo": nombre_archivo})
    except Exception as e:
        return jsonify({"error": f"Error al procesar el PDF: {str(e)}"}), 500
@app.route('/generar-test-desde-pdf', methods=['POST'])
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
                f"6. **Explicación**: incluye una justificación breve que cite o se base en el contenido del documento.\n"
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
                preguntas_validadas.append(p)
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
@app.route('/generar-tarjetas-desde-pdf', methods=['POST'])
@requiere_plan(db, "gratis", global_check=True)
def generar_tarjetas_desde_pdf():
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
        response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload)
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
            "respuesta_cruda": respuesta[:500] if 'respuesta' in locals() else "N/A"
        }), 500

# Nº de caracteres del PDF que se guardan para poder chatear sobre él. Se
# recorta más que en resumen/esquema porque este texto se reenvía en el
# prompt de CADA mensaje del chat (no una sola vez), así que hay que
# mantenerlo comedido para no disparar el coste por conversación.
MAX_CARACTERES_CHAT_PDF = 12000

@app.route('/subir-pdf-chat', methods=['POST'])
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

@app.route('/chat-pdf-mensaje', methods=['POST'])
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

@app.route("/chat-deepseek", methods=["POST"])
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
        response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload)
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
@app.route('/guardar-test-pdf', methods=['POST'])
@requiere_plan(db, "gratis", global_check=True)
def guardar_test_pdf():
    try:
        data = request.get_json()
        test_data = data.get('test_data', {})
        preguntas = test_data.get('preguntas', [])
        nombre_archivo = data.get('nombre_archivo', 'documento.pdf')
        resultado = guardar_resultado_en_firestore(
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
                print(f"⚠️ No se pudo borrar el borrador de test en progreso {test_id}: {e}")
        return jsonify({'mensaje': 'Test desde PDF guardado correctamente'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
@app.route('/guardar-resumen-pdf', methods=['POST'])
@requiere_plan(db, "gratis", global_check=True)
def guardar_resumen_pdf():
    try:
        data = request.get_json()
        resumen = data.get('resumen', '')
        nombre_archivo = data.get('nombre_archivo', 'documento.pdf')
        resultado = guardar_resultado_en_firestore(
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
@app.route('/guardar-esquema-pdf', methods=['POST'])
@requiere_plan(db, "gratis", global_check=True)
def guardar_esquema_pdf():
    try:
        data = request.get_json()
        esquema = data.get('esquema', '')
        nombre_archivo = data.get('nombre_archivo', 'documento.pdf')
        resultado = guardar_resultado_en_firestore(
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
@app.route('/guardar-tarjetas-pdf', methods=['POST'])
@requiere_plan(db, "gratis", global_check=True)
def guardar_tarjetas_pdf():
    try:
        data = request.get_json()
        tarjetas = data.get('tarjetas', [])
        nombre_archivo = data.get('nombre_archivo', 'documento.pdf')
        resultado = guardar_resultado_en_firestore(
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
@app.route('/mis-documentos', methods=['GET'])
@requiere_login(db)
def mis_documentos():
    return jsonify({"documentos": listar_documentos(db, g.uid)})

@app.route('/documento/<documento_id>/carpeta', methods=['POST'])
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


@app.route('/documento/<documento_id>/resumen', methods=['GET'])
@requiere_login(db)
def documento_resumen(documento_id):
    datos = _ultimo_por_documento("resumenes_pdf", documento_id, g.uid)
    if not datos:
        return jsonify({"error": "Este documento todavía no tiene un resumen generado."}), 404
    return jsonify({"resumen": datos.get("resumen"), "nombre_archivo": datos.get("nombre_archivo"), "fecha": datos.get("fecha")})


@app.route('/documento/<documento_id>/esquema', methods=['GET'])
@requiere_login(db)
def documento_esquema(documento_id):
    datos = _ultimo_por_documento("esquemas_pdf", documento_id, g.uid)
    if not datos:
        return jsonify({"error": "Este documento todavía no tiene un esquema generado."}), 404
    return jsonify({"esquema": datos.get("esquema"), "nombre_archivo": datos.get("nombre_archivo"), "fecha": datos.get("fecha")})


@app.route('/documento/<documento_id>/test', methods=['GET'])
@requiere_login(db)
def documento_test(documento_id):
    datos = _ultimo_por_documento("tests_pdf", documento_id, g.uid)
    if not datos:
        return jsonify({"error": "Este documento todavía no tiene un test generado."}), 404
    return jsonify({"test": datos.get("preguntas", []), "nombre_archivo": datos.get("nombre_archivo"), "fecha": datos.get("fecha")})


@app.route('/documento/<documento_id>/tarjetas', methods=['GET'])
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
# ===================================================================
# RUTAS DE SUSCRIPCIÓN (STRIPE)
# ===================================================================
@app.route("/mi-perfil", methods=["GET"])
@requiere_login(db)
def mi_perfil():
    oposicion = obtener_oposicion_solicitada()
    return jsonify(obtener_perfil_usuario(db, g.uid, oposicion=oposicion))

@app.route("/mi-racha", methods=["GET"])
@requiere_login(db)
def mi_racha():
    doc = db.collection("usuarios").document(g.uid).get()
    racha = (doc.to_dict() or {}).get("racha") or {}
    racha_actual = racha.get("racha_actual", 0)
    ultima_fecha_str = racha.get("ultima_fecha")
    # Si la última actividad fue hace más de un día, la racha ya está rota
    # aunque en Firestore no se "confirme" hasta la próxima actividad: se
    # calcula al vuelo para no mostrar un número desfasado.
    if ultima_fecha_str:
        try:
            dias_sin_actividad = (datetime.utcnow().date() - date.fromisoformat(ultima_fecha_str)).days
            if dias_sin_actividad > 1:
                racha_actual = 0
        except ValueError:
            pass
    return jsonify({
        "racha_actual": racha_actual,
        "racha_maxima": racha.get("racha_maxima", 0),
        "ultima_fecha": ultima_fecha_str
    })

@app.route("/crear-sesion-checkout", methods=["POST"])
@requiere_login(db)
def crear_sesion_checkout():
    data = request.get_json(silent=True) or {}
    plan = data.get("plan")
    oposicion = data.get("oposicion", OPOSICION_POR_DEFECTO)
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    price_id = STRIPE_PRICE_IDS.get(plan)
    if not price_id:
        return jsonify({"error": "Plan no válido"}), 400
    try:
        doc_ref = db.collection("usuarios").document(g.uid)
        usuario = doc_ref.get().to_dict() or {}
        stripe_customer_id = usuario.get("stripe_customer_id")
        if not stripe_customer_id:
            customer = stripe.Customer.create(email=g.email, metadata={"uid": g.uid})
            stripe_customer_id = customer.id
            actualizar_suscripcion(db, g.uid, oposicion, stripe_customer_id=stripe_customer_id)
        # La oposición viaja tanto en la metadata de la sesión de checkout
        # (solo disponible en el evento checkout.session.completed) como en
        # subscription_data.metadata, para que quede grabada en la propia
        # Subscription de Stripe y así los eventos posteriores
        # (customer.subscription.updated/deleted) también sepan a qué
        # oposición pertenecen.
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=stripe_customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{FRONTEND_URL}/mi-cuenta/?checkout=success&oposicion={oposicion}",
            cancel_url=f"{FRONTEND_URL}/planes/?checkout=cancel&oposicion={oposicion}",
            client_reference_id=g.uid,
            metadata={"uid": g.uid, "plan": plan, "oposicion": oposicion},
            subscription_data={"metadata": {"uid": g.uid, "plan": plan, "oposicion": oposicion}}
        )
        return jsonify({"url": session.url})
    except Exception as e:
        print("❌ Error creando sesión de Stripe Checkout:", e)
        return jsonify({"error": str(e)}), 500

@app.route("/crear-sesion-portal", methods=["POST"])
@requiere_login(db)
def crear_sesion_portal():
    usuario = db.collection("usuarios").document(g.uid).get().to_dict() or {}
    stripe_customer_id = usuario.get("stripe_customer_id")
    if not stripe_customer_id:
        return jsonify({"error": "Todavía no tienes ninguna suscripción"}), 400
    try:
        session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=f"{FRONTEND_URL}/mi-cuenta/"
        )
        return jsonify({"url": session.url})
    except Exception as e:
        print("❌ Error creando sesión del portal de Stripe:", e)
        return jsonify({"error": str(e)}), 500

def _sget(obj, key, default=None):
    """Equivalente a dict.get() pero que también funciona con los objetos
    de la librería de Stripe: en la versión que usamos, esos objetos
    soportan obj["clave"] pero NO tienen un método .get() real (lo
    resuelven vía __getattr__ y acaban lanzando AttributeError)."""
    try:
        valor = obj[key]
        return default if valor is None else valor
    except (KeyError, TypeError):
        return default


def _current_period_end(subscription_obj):
    """Extrae 'current_period_end' de una Subscription de Stripe.
    En versiones recientes de la API (>= 2025) ese campo ya no está en la
    propia suscripción, sino en cada "item" de la suscripción."""
    valor = _sget(subscription_obj, "current_period_end")
    if valor is None:
        items = _sget(_sget(subscription_obj, "items", {}), "data", [])
        if items:
            valor = _sget(items[0], "current_period_end")
    return valor


@app.route("/webhook-stripe", methods=["POST"])
def webhook_stripe():
    payload = request.get_data()
    firma = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, firma, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        print("❌ Webhook de Stripe con firma inválida:", e)
        return jsonify({"error": "Firma inválida"}), 400

    evento_ref = db.collection("stripe_events").document(event["id"])
    if evento_ref.get().exists:
        return jsonify({"mensaje": "Evento ya procesado"}), 200

    tipo = event["type"]
    objeto = event["data"]["object"]

    try:
        if tipo == "checkout.session.completed":
            metadata = _sget(objeto, "metadata", {}) or {}
            uid = _sget(objeto, "client_reference_id") or _sget(metadata, "uid")
            oposicion = _sget(metadata, "oposicion") or OPOSICION_POR_DEFECTO
            subscription_id = _sget(objeto, "subscription")
            if uid and subscription_id:
                subscription = stripe.Subscription.retrieve(subscription_id)
                price_id = subscription["items"]["data"][0]["price"]["id"]
                plan = PRECIO_A_PLAN.get(price_id, "gratis")
                periodo_fin = _current_period_end(subscription)
                actualizar_suscripcion(
                    db, uid, oposicion,
                    plan=plan,
                    stripe_customer_id=_sget(objeto, "customer"),
                    stripe_subscription_id=subscription_id,
                    subscription_status=subscription["status"],
                    current_period_end=datetime.utcfromtimestamp(periodo_fin).isoformat() if periodo_fin else None
                )
        elif tipo == "customer.subscription.updated":
            customer_id = _sget(objeto, "customer")
            # La oposición viaja en la metadata de la propia Subscription
            # (puesta ahí al crear el checkout). Si falta -- suscripciones
            # creadas antes de que existiera esta metadata -- se asume AGE,
            # que era la única oposición que existía entonces.
            metadata = _sget(objeto, "metadata", {}) or {}
            oposicion = _sget(metadata, "oposicion") or OPOSICION_POR_DEFECTO
            docs = list(db.collection("usuarios").where("stripe_customer_id", "==", customer_id).limit(1).stream())
            if docs:
                price_id = objeto["items"]["data"][0]["price"]["id"]
                plan = PRECIO_A_PLAN.get(price_id, "gratis")
                periodo_fin = _current_period_end(objeto)
                actualizar_suscripcion(
                    db, docs[0].id, oposicion,
                    plan=plan,
                    stripe_subscription_id=_sget(objeto, "id"),
                    subscription_status=_sget(objeto, "status"),
                    current_period_end=datetime.utcfromtimestamp(periodo_fin).isoformat() if periodo_fin else None
                )
        elif tipo == "customer.subscription.deleted":
            customer_id = _sget(objeto, "customer")
            metadata = _sget(objeto, "metadata", {}) or {}
            oposicion = _sget(metadata, "oposicion") or OPOSICION_POR_DEFECTO
            docs = list(db.collection("usuarios").where("stripe_customer_id", "==", customer_id).limit(1).stream())
            if docs:
                actualizar_suscripcion(db, docs[0].id, oposicion, plan="gratis", subscription_status="canceled")
        elif tipo == "invoice.payment_failed":
            customer_id = _sget(objeto, "customer")
            subscription_id = _sget(objeto, "subscription")
            oposicion = OPOSICION_POR_DEFECTO
            if subscription_id:
                try:
                    sub_obj = stripe.Subscription.retrieve(subscription_id)
                    oposicion = _sget(_sget(sub_obj, "metadata", {}) or {}, "oposicion") or OPOSICION_POR_DEFECTO
                except Exception:
                    pass
            docs = list(db.collection("usuarios").where("stripe_customer_id", "==", customer_id).limit(1).stream())
            if docs:
                actualizar_suscripcion(db, docs[0].id, oposicion, subscription_status="past_due")
    except Exception as e:
        print(f"❌ Error procesando webhook de Stripe ({tipo}): {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

    evento_ref.set({"type": tipo, "processed_at": datetime.utcnow().isoformat()})
    return jsonify({"mensaje": "Evento procesado"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))