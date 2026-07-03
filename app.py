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
from datetime import datetime
# Módulos personalizados
from test_generator import generar_test_avanzado
from chat_controller import responder_chat, consultar_asistente_examen_AGE
from esquema_generator import generar_esquema
from save_controller import guardar_test_route, guardar_esquema_route
from rutas_progreso import registrar_rutas_progreso
from guardar_resultado import guardar_resultado_en_firestore
from auth_utils import requiere_login, requiere_plan
from registro_progreso_usuario import actualizar_suscripcion, obtener_perfil_usuario
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
        chat_id=chat_id
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
        respuesta = consultar_asistente_examen_AGE(mensaje)
        return jsonify({"respuesta": respuesta})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route("/generar-test-avanzado", methods=["POST"])
@requiere_plan(db, "basico")
def generar_test_avanzado_route():
    data = request.get_json()
    print(f"📅 Petición recibida en /generar-test-avanzado: {data}")
    temas = data.get("temas", [])
    num_preguntas = data.get("num_preguntas", 5)
    print(f"📋 Temas extraídos: {temas}")
    print(f"🧪 Número de preguntas solicitadas: {num_preguntas}")
    resultado = generar_test_avanzado(temas=temas, db=db, num_preguntas=num_preguntas)
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
    resultado = generar_esquema(temas=temas, db=db, instrucciones=instrucciones, nivel=nivel)
    return jsonify({"esquema": resultado})
@app.route("/generar-test-oficial", methods=["POST"])
@requiere_login(db)
def generar_test_oficial():
    data = request.get_json()
    print("✅ Ruta /generar-test-oficial llamada")
    print("📥 Datos recibidos:", data)
    num_preguntas = data.get("num_preguntas", 10)
    examenes_filtrados = data.get("examenes", [])
    print("🔍 Número de preguntas solicitado:", num_preguntas)
    print("📚 Exámenes filtrados:", examenes_filtrados)
    try:
        docs = db.collection("examenes_oficiales_AGE").stream()
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
            "numero": d.get("numero", 0)
        })
    print(f"✅ Preguntas encontradas tras filtro: {len(preguntas)}")
    if not preguntas:
        return jsonify({"test": [], "mensaje": "No se encontraron preguntas"}), 404
    seleccionadas = random.sample(preguntas, min(num_preguntas, len(preguntas)))
    print(f"🎯 Preguntas seleccionadas aleatoriamente: {len(seleccionadas)}")
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
@app.route("/temas-disponibles", methods=["GET"])
@requiere_login(db)
def obtener_temas_disponibles():
    temas_disponibles = []
    bloques = db.collection("Temario AGE").stream()
    for bloque in bloques:
        bloque_id = bloque.id
        temas_ref = db.collection("Temario AGE").document(bloque_id).collection("temas").stream()
        for tema in temas_ref:
            tema_data = tema.to_dict()
            tema_id = tema.id
            titulo = tema_data.get("titulo", f"{tema_id}")
            temas_disponibles.append({
                "id": f"{bloque_id}-{tema_id}",
                "titulo": titulo
            })
    return jsonify({"temas": temas_disponibles})
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
def traducir_temas_para_IA(lista_codigos):
    traducciones = {
        "bloque_01-tema_01": "Constitución Española",
        "bloque_01-tema_02": "La Jefatura del Estado. La Corona. Funciones constitucionales del Rey. Sucesión y regencia.",
        "bloque_01-tema_03": "Las Cortes Generales. Composición, atribuciones y funcionamiento del Congreso de los Diputados y del Senado.",
        "bloque_01-tema_04": "EL PODER JUDICIAL",
        "bloque_01-tema_05": "EL GOBIERNO Y LA ADMINISTRACIÓN.",
        "bloque_01-tema_06": "El Gobierno Abierto, Agenda 2030 y Digitalización",
        "bloque_01-tema_07": "LA LEY 19/2013, DE 9 DE DICIEMBRE, DE TRANSPARENCIA, ACCESO A LA INFORMACIÓN PÚBLICA Y BUEN GOBIERNO. EL CONSEJO DE TRANSPARENCIA Y BUEN GOBIERNO: FUNCIONES.",
        "bloque_01-tema_08": "Administración General del Estado",
        "bloque_01-tema_09": "LA ORGANIZACIÓN TERRITORIAL DEL ESTADO: LAS COMUNIDADES AUTÓNOMAS. CONSTITUCIÓN Y DISTRIBUCIÓN DE COMPETENCIAS ENTRE EL ESTADO Y LAS COMUNIDADES AUTÓNOMAS. ESTATUTOS DE AUTONOMÍA.",
        "bloque_01-tema_10": "LA ADMINISTRACIÓN LOCAL: ENTIDADES QUE LA INTEGRAN. LA PROVINCIA, EL MUNICIPIO Y LA ISLA.",
        "bloque_01-tema_11": "LA ORGANIZACIÓN DE LA UNIÓN EUROPEA. EL CONSEJO EUROPEO, EL CONSEJO, EL PARLAMENTO EUROPEO, LA COMISIÓN EUROPEA Y EL TRIBUNAL DE JUSTICIA DE LA UNIÓN EUROPEA. EFECTOS DE LA INTEGRACIÓN EUROPEA SOBRE LA ORGANIZACIÓN DEL ESTADO ESPAÑOL.",
        "bloque_02-tema_01": "ATENCION AL PUBLICO",
        "bloque_02-tema_02": "REGISTRO Y ARCHIVO",
        "bloque_02-tema_03": "ADMINISTRACION ELECTRONICA",
        "bloque_02-tema_04": "PROTECCION DE DATOS PERSONALES",
        "bloque_03-tema_01": "FUENTES DEL DERECHO ADMINISTRATIVO",
        "bloque_03-tema_02": "EL ACTO ADMINISTRATIVO",
        "bloque_03-tema_03": "EL PROCEDIMIENTO ADMINISTRATIVO COMÚN",
        "bloque_03-tema_04": "CONTRATOS DEL SECTOR PÚBLICO",
        "bloque_03-tema_05": "LA ACTIVIDAD ADMINISTRATIVA.",
        "bloque_03-tema_06": "RESPONSABILIDAD PATRIMONIAL (VACIO)",
        "bloque_03-tema_07": "IGUALDAD DE GÉNERO (VACIO)"
    }
    return [traducciones.get(codigo, codigo) for codigo in lista_codigos]
@app.route("/generar-test-inteligente", methods=["POST"])
@requiere_plan(db, "basico")
def generar_test_inteligente():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No se ha recibido un cuerpo JSON válido"}), 400
    temas = data.get("temas", [])
    num_preguntas = data.get("num_preguntas", 5)
    if not temas:
        return jsonify({"error": "No se han proporcionado temas"}), 400
    temas_legibles = traducir_temas_para_IA(temas)
    prompt = f"""
Eres un generador experto de preguntas tipo test para oposiciones del Cuerpo General Administrativo del Estado (grupo C1).
Crea {num_preguntas} preguntas tipo test con el estilo oficial de exámenes del INAP: realistas, bien redactadas y con trampas habituales.
Temas seleccionados: {', '.join(temas_legibles)}
Cada pregunta debe tener:
- Enunciado claro
- Opciones A, B, C y D (sin ambigüedades)
- Una única opción correcta
- Explicación técnica o jurídica breve
Devuelve solo un array JSON como este:
[
  {{
    "pregunta": "...",
    "opciones": {{
      "A": "...",
      "B": "...",
      "C": "...",
      "D": "..."
    }},
    "respuesta_correcta": "B",
    "explicacion": "..."
  }}
]
"""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        respuesta = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
        )
        generado = respuesta.choices[0].message.content.strip()
        preguntas = json.loads(generado)
        return jsonify({"test": preguntas})
    except Exception as e:
        print("❌ Error al generar test inteligente:", e)
        return jsonify({"error": str(e)}), 500
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
    tests_ref = db.collection("usuarios").document(g.uid).collection("tests").stream()
    preguntas_falladas = []
    for test_doc in tests_ref:
        test = test_doc.to_dict()
        for pregunta in test.get("preguntas", []):
            if (
                "respuesta_usuario" in pregunta and
                "respuesta_correcta" in pregunta and
                pregunta["respuesta_usuario"] != pregunta["respuesta_correcta"] and
                pregunta["respuesta_usuario"] is not None
            ):
                preguntas_falladas.append(pregunta)
    preguntas_unicas = []
    vistos = set()
    for p in preguntas_falladas:
        clave = p.get("pregunta", "")
        if clave not in vistos:
            preguntas_unicas.append(p)
            vistos.add(clave)
    random.shuffle(preguntas_unicas)
    preguntas_finales = preguntas_unicas[:num_preguntas]
    return jsonify({"test": preguntas_finales})
# ===================================================================
# RUTAS PARA DEEPSEEK (PDFs)
# ===================================================================
@app.route('/resumir-pdf', methods=['POST'])
@requiere_plan(db, "premium")
def resumir_pdf():
    if 'pdf' not in request.files:
        return jsonify({"error": "No se encontró archivo PDF"}), 400
    pdf_file = request.files['pdf']
    if pdf_file.filename == '':
        return jsonify({"error": "Nombre de archivo inválido"}), 400
    try:
        pdf_reader = PdfReader(BytesIO(pdf_file.read()))
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        if not text.strip():
            return jsonify({"error": "El PDF no contiene texto extraíble (puede ser una imagen)"}), 400
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
        data = response.json()
        resumen = data['choices'][0]['message']['content']
        return jsonify({"resumen": resumen})
    except Exception as e:
        return jsonify({"error": f"Error al procesar el PDF: {str(e)}"}), 500
# ✅ NUEVA RUTA: alias para compatibilidad con frontend
@app.route('/resumir-documento', methods=['POST'])
@requiere_plan(db, "premium")
def resumir_documento():
    return resumir_pdf()
@app.route('/generar-esquema-desde-pdf', methods=['POST'])
@requiere_plan(db, "premium")
def generar_esquema_desde_pdf():
    if 'pdf' not in request.files:
        return jsonify({"error": "No se encontró archivo PDF"}), 400
    pdf_file = request.files['pdf']
    if pdf_file.filename == '':
        return jsonify({"error": "Nombre de archivo inválido"}), 400
    try:
        pdf_reader = PdfReader(BytesIO(pdf_file.read()))
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        if not text.strip():
            return jsonify({"error": "El PDF no contiene texto extraíble"}), 400
        max_length = 300000
        if len(text) > max_length:
            text = text[:max_length]
        system_prompt = (
            "Eres un experto en oposiciones. Crea un esquema estructurado y organizado "
            "a partir del siguiente documento. Usa títulos, subtítulos y viñetas claras. "
            "El esquema debe ser útil para estudiar y repasar."
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
        data = response.json()
        esquema = data['choices'][0]['message']['content']
        return jsonify({"esquema": esquema})
    except Exception as e:
        return jsonify({"error": f"Error al procesar el PDF: {str(e)}"}), 500
@app.route('/generar-test-desde-pdf', methods=['POST'])
@requiere_plan(db, "premium")
def generar_test_desde_pdf():
    if 'pdf' not in request.files:
        return jsonify({"error": "No se encontró archivo PDF"}), 400
    pdf_file = request.files['pdf']
    if pdf_file.filename == '':
        return jsonify({"error": "Nombre de archivo inválido"}), 400
    try:
        num_preguntas = int(request.form.get("num_preguntas", 10))
        if num_preguntas < 1 or num_preguntas > 50:
            num_preguntas = 10
    except (ValueError, TypeError):
        num_preguntas = 10
    try:
        pdf_reader = PdfReader(BytesIO(pdf_file.read()))
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        if not text.strip():
            return jsonify({"error": "El PDF no contiene texto extraíble"}), 400
        max_length = 150000
        if len(text) > max_length:
            text = text[:max_length]
        system_prompt = (
            f"Eres un experto en la elaboración de preguntas tipo test para oposiciones oficiales en España. "
            f"Tu tarea es generar EXACTAMENTE {num_preguntas} preguntas de opción múltiple de alta calidad, "
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
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return jsonify({"error": "API key de DeepSeek no configurada"}), 500
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Documento para crear preguntas test:\n{text}"}
            ],
            "temperature": 0.4,
            "max_tokens": min(4000, 300 * num_preguntas)
        }
        response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=60)
        if response.status_code != 200:
            return jsonify({"error": f"Error en DeepSeek API: {response.status_code}"}), 500
        data = response.json()
        respuesta = data['choices'][0]['message']['content']
        start_index = respuesta.find("[")
        end_index = respuesta.rfind("]") + 1
        if start_index == -1 or end_index <= start_index:
            raise ValueError("No se encontró un array JSON en la respuesta.")
        json_str = respuesta[start_index:end_index]
        try:
            preguntas = json.loads(json_str)
        except json.JSONDecodeError:
            json_str_fixed = json_str.replace("'", '"')
            try:
                preguntas = json.loads(json_str_fixed)
            except json.JSONDecodeError:
                return jsonify({
                    "error": "La IA no devolvió un JSON válido para las preguntas. Error técnico.",
                    "respuesta_cruda": respuesta[:500]
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
                "error": "La IA generó preguntas vacías o inválidas.",
                "respuesta_cruda": respuesta[:500]
            }), 500
        return jsonify({"test": preguntas_validadas})
    except Exception as e:
        return jsonify({
            "error": f"Error al procesar el PDF o generar preguntas: {str(e)}",
            "respuesta_cruda": respuesta[:500] if 'respuesta' in locals() else "N/A"
        }), 500
@app.route('/generar-tarjetas-desde-pdf', methods=['POST'])
@requiere_plan(db, "premium")
def generar_tarjetas_desde_pdf():
    if 'pdf' not in request.files:
        return jsonify({"error": "No se encontró archivo PDF"}), 400
    pdf_file = request.files['pdf']
    if pdf_file.filename == '':
        return jsonify({"error": "Nombre de archivo inválido"}), 400
    try:
        pdf_reader = PdfReader(BytesIO(pdf_file.read()))
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        if not text.strip():
            return jsonify({"error": "El PDF no contiene texto extraíble"}), 400
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
        return jsonify({"tarjetas": tarjetas_validadas})
    except Exception as e:
        return jsonify({
            "error": f"Error al procesar el PDF o generar tarjetas: {str(e)}",
            "respuesta_cruda": respuesta[:500] if 'respuesta' in locals() else "N/A"
        }), 500
@app.route("/chat-deepseek", methods=["POST"])
@requiere_plan(db, "premium")
def chat_deepseek():
    data = request.get_json()
    mensaje = data.get("mensaje")
    if not mensaje:
        return jsonify({"error": "Falta el mensaje"}), 400
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
        data = response.json()
        respuesta = data['choices'][0]['message']['content']
        return jsonify({"respuesta": respuesta})
    except Exception as e:
        return jsonify({"error": f"Error en el servicio de chat: {str(e)}"}), 500
# ===================================================================
# NUEVAS RUTAS PARA GUARDAR CONTENIDO DESDE PDF
# ===================================================================
@app.route('/guardar-test-pdf', methods=['POST'])
@requiere_plan(db, "premium")
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
                'num_preguntas': len(preguntas),
                'fecha_procesamiento': datetime.utcnow().isoformat()
            }
        )
        return jsonify({'mensaje': 'Test desde PDF guardado correctamente'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
@app.route('/guardar-resumen-pdf', methods=['POST'])
@requiere_plan(db, "premium")
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
                'longitud': len(resumen),
                'fecha_procesamiento': datetime.utcnow().isoformat()
            }
        )
        return jsonify({'mensaje': 'Resumen desde PDF guardado correctamente'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
@app.route('/guardar-esquema-pdf', methods=['POST'])
@requiere_plan(db, "premium")
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
                'longitud': len(esquema),
                'fecha_procesamiento': datetime.utcnow().isoformat()
            }
        )
        return jsonify({'mensaje': 'Esquema desde PDF guardado correctamente'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
@app.route('/guardar-tarjetas-pdf', methods=['POST'])
@requiere_plan(db, "premium")
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
                'num_tarjetas': len(tarjetas),
                'fecha_procesamiento': datetime.utcnow().isoformat()
            }
        )
        return jsonify({'mensaje': 'Tarjetas desde PDF guardadas correctamente'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
# ===================================================================
# RUTAS DE SUSCRIPCIÓN (STRIPE)
# ===================================================================
@app.route("/mi-perfil", methods=["GET"])
@requiere_login(db)
def mi_perfil():
    return jsonify(obtener_perfil_usuario(db, g.uid))

@app.route("/crear-sesion-checkout", methods=["POST"])
@requiere_login(db)
def crear_sesion_checkout():
    data = request.get_json(silent=True) or {}
    plan = data.get("plan")
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
            actualizar_suscripcion(db, g.uid, stripe_customer_id=stripe_customer_id)
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=stripe_customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{FRONTEND_URL}/mi-cuenta/?checkout=success",
            cancel_url=f"{FRONTEND_URL}/planes/?checkout=cancel",
            client_reference_id=g.uid,
            metadata={"uid": g.uid, "plan": plan}
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
            subscription_id = _sget(objeto, "subscription")
            if uid and subscription_id:
                subscription = stripe.Subscription.retrieve(subscription_id)
                price_id = subscription["items"]["data"][0]["price"]["id"]
                plan = PRECIO_A_PLAN.get(price_id, "gratis")
                periodo_fin = _current_period_end(subscription)
                actualizar_suscripcion(
                    db, uid,
                    plan=plan,
                    stripe_customer_id=_sget(objeto, "customer"),
                    stripe_subscription_id=subscription_id,
                    subscription_status=subscription["status"],
                    current_period_end=datetime.utcfromtimestamp(periodo_fin).isoformat() if periodo_fin else None
                )
        elif tipo == "customer.subscription.updated":
            customer_id = _sget(objeto, "customer")
            docs = list(db.collection("usuarios").where("stripe_customer_id", "==", customer_id).limit(1).stream())
            if docs:
                price_id = objeto["items"]["data"][0]["price"]["id"]
                plan = PRECIO_A_PLAN.get(price_id, "gratis")
                periodo_fin = _current_period_end(objeto)
                actualizar_suscripcion(
                    db, docs[0].id,
                    plan=plan,
                    stripe_subscription_id=_sget(objeto, "id"),
                    subscription_status=_sget(objeto, "status"),
                    current_period_end=datetime.utcfromtimestamp(periodo_fin).isoformat() if periodo_fin else None
                )
        elif tipo == "customer.subscription.deleted":
            customer_id = _sget(objeto, "customer")
            docs = list(db.collection("usuarios").where("stripe_customer_id", "==", customer_id).limit(1).stream())
            if docs:
                actualizar_suscripcion(db, docs[0].id, plan="gratis", subscription_status="canceled")
        elif tipo == "invoice.payment_failed":
            customer_id = _sget(objeto, "customer")
            docs = list(db.collection("usuarios").where("stripe_customer_id", "==", customer_id).limit(1).stream())
            if docs:
                actualizar_suscripcion(db, docs[0].id, subscription_status="past_due")
    except Exception as e:
        print(f"❌ Error procesando webhook de Stripe ({tipo}): {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

    evento_ref.set({"type": tipo, "processed_at": datetime.utcnow().isoformat()})
    return jsonify({"mensaje": "Evento procesado"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))