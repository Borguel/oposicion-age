import os
import random
import requests
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
from PyPDF2 import PdfReader
from io import BytesIO

# Módulos personalizados
from test_generator import generar_test_avanzado
from chat_controller import responder_chat, consultar_asistente_examen_AGE
from esquema_generator import generar_esquema
from save_controller import guardar_test_route, guardar_esquema_route
from rutas_progreso import registrar_rutas_progreso

# Cargar variables de entorno
load_dotenv()
print("🔑 Clave OpenAI:", os.getenv("OPENAI_API_KEY"))
print("🔑 Clave DeepSeek:", "configurada" if os.getenv("DEEPSEEK_API_KEY") else "no configurada")

# Inicializar Firebase
firebase_key_path = os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json")
if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_key_path)
    firebase_admin.initialize_app(cred)
db = firestore.client()

# Inicializar Flask
app = Flask(__name__)
CORS(app, origins=["https://lightslategray-caribou-622401.hostingersite.com"])
print("✅ CORS activado para tu WordPress")


@app.route("/chat", methods=["POST"])
def chat_route():
    data = request.get_json()
    mensaje = data.get("mensaje")
    temas = data.get("temas", [])
    usuario_id = data.get("usuario_id", "anonimo")
    chat_id = data.get("chat_id")
    respuesta, chat_id = responder_chat(
        mensaje=mensaje,
        temas=temas,
        db=db,
        usuario_id=usuario_id,
        chat_id=chat_id
    )
    return jsonify({"respuesta": respuesta, "chat_id": chat_id})


@app.route("/consultar-asistente-examen", methods=["POST"])
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
def guardar_test_oficial():
    data = request.get_json()
    print("💾 Guardando test oficial:", data)
    usuario_id = data.get("usuario_id")
    contenido = data.get("contenido")
    respuestas = data.get("respuestas")
    metadatos = data.get("metadatos", {})
    if not usuario_id or not contenido or not respuestas:
        return jsonify({"error": "Faltan datos requeridos"}), 400
    try:
        doc_ref = db.collection("test_oficiales").document()
        doc_ref.set({
            "usuario_id": usuario_id,
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
def progreso_usuario():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "Falta el parámetro user_id"}), 400
    doc_user = db.collection("usuarios").document(user_id)
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
def obtener_conversaciones_usuario():
    usuario_id = request.args.get("usuario_id")
    if not usuario_id:
        return jsonify({"error": "Falta usuario_id"}), 400
    docs = db.collection("conversaciones_IA") \
             .document(usuario_id) \
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
def obtener_conversacion(conversacion_id):
    usuario_id = request.args.get("usuario_id")
    if not usuario_id:
        return jsonify({"error": "Falta usuario_id"}), 400
    doc = db.collection("conversaciones_IA") \
            .document(usuario_id) \
            .collection("conversaciones") \
            .document(conversacion_id) \
            .get()
    if not doc.exists:
        return jsonify({"error": "Conversación no encontrada"}), 404
    return jsonify(doc.to_dict())


@app.route("/generar-test-fallos", methods=["POST"])
def generar_test_fallos():
    data = request.get_json()
    usuario_id = data.get("usuario_id")
    num_preguntas = data.get("num_preguntas", 10)
    if not usuario_id:
        return jsonify({"error": "Falta usuario_id"}), 400
    tests_ref = db.collection("usuarios").document(usuario_id).collection("tests").stream()
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


@app.route('/generar-esquema-desde-pdf', methods=['POST'])
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
def generar_test_desde_pdf():
    if 'pdf' not in request.files:
        return jsonify({"error": "No se encontró archivo PDF"}), 400
    pdf_file = request.files['pdf']
    if pdf_file.filename == '':
        return jsonify({"error": "Nombre de archivo inválido"}), 400

    # 👉 Leer num_preguntas desde request.form (no JSON)
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
            f"Eres un generador experto de preguntas tipo test para oposiciones. "
            f"Crea EXACTAMENTE {num_preguntas} preguntas claras con 4 opciones (A, B, C, D) y una única respuesta correcta. "
            f"Incluye una explicación breve de por qué la respuesta es correcta. "
            f"Devuelve SOLO un array JSON válido con este formato:\n"
            "[{\"pregunta\": \"...\", \"opciones\": {\"A\": \"...\", \"B\": \"...\", \"C\": \"...\", \"D\": \"...\"}, \"respuesta_correcta\": \"A\", \"explicacion\": \"...\"}]"
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

        # Limpiar y parsear JSON
        inicio = respuesta.find("[")
        fin = respuesta.rfind("]") + 1
        if inicio != -1 and fin > inicio:
            json_str = respuesta[inicio:fin]
        else:
            json_str = respuesta

        try:
            preguntas = json.loads(json_str)
            preguntas_validadas = []
            for p in preguntas:
                if all(k in p for k in ["pregunta", "opciones", "respuesta_correcta"]):
                    if "explicacion" not in p:
                        p["explicacion"] = "Explicación no disponible."
                    preguntas_validadas.append(p)
            if not preguntas_validadas:
                raise ValueError("Ninguna pregunta válida")
            return jsonify({"test": preguntas_validadas})
        except json.JSONDecodeError:
            return jsonify({"error": "La IA no devolvió un JSON válido", "respuesta_cruda": respuesta[:500]}), 500

    except Exception as e:
        return jsonify({"error": f"Error al procesar el PDF: {str(e)}"}), 500


@app.route('/generar-tarjetas-desde-pdf', methods=['POST'])
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
        system_prompt = (
            "Eres un experto en crear tarjetas de memoria para estudiar. "
            "Crea tarjetas con preguntas claras en el anverso y respuestas concisas en el reverso. "
            "Las tarjetas deben cubrir los conceptos más importantes del documento. "
            "Devuelve SOLO un array JSON válido con este formato:\n"
            "[{\"pregunta\": \"...\", \"respuesta\": \"...\"}]"
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
            "max_tokens": 2000
        }
        response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload)
        if response.status_code != 200:
            return jsonify({"error": f"Error en DeepSeek API: {response.status_code}"}), 500
        data = response.json()
        respuesta = data['choices'][0]['message']['content']
        try:
            tarjetas = json.loads(respuesta)
            return jsonify({"tarjetas": tarjetas})
        except json.JSONDecodeError:
            return jsonify({"error": "La IA no devolvió un JSON válido", "respuesta_cruda": respuesta}), 500
    except Exception as e:
        return jsonify({"error": f"Error al procesar el PDF: {str(e)}"}), 500


@app.route("/chat-deepseek", methods=["POST"])
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))