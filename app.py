import os
import random
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# Módulos personalizados
from test_generator import generar_test_avanzado
from chat_controller import responder_chat
from esquema_generator import generar_esquema
from save_controller import guardar_test_route, guardar_esquema_route
from rutas_progreso import registrar_rutas_progreso

# Cargar variables de entorno
load_dotenv()
print("🔑 Clave OpenAI:", os.getenv("OPENAI_API_KEY"))

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
    respuesta = responder_chat(mensaje=mensaje, temas=temas, db=db)
    return jsonify({"respuesta": respuesta})

@app.route("/generar-test-avanzado", methods=["POST"])
def generar_test_avanzado_route():
    data = request.get_json()
    print(f"📥 Petición recibida en /generar-test-avanzado: {data}")

    temas = data.get("temas", [])
    num_preguntas = data.get("num_preguntas", 5)

    print(f"📋 Temas extraídos: {temas}")
    print(f"🧪 Número de preguntas solicitadas: {num_preguntas}")

    resultado = generar_test_avanzado(temas=temas, db=db, num_preguntas=num_preguntas)
    print(f"📤 Resultado del test: {resultado}")
    return jsonify(resultado)

@app.route("/generar-esquema", methods=["POST"])
def generar_esquema_route():
    data = request.get_json()
    temas = data.get("temas", [])
    instrucciones = data.get("instrucciones", "Resume los contenidos clave.")
    nivel = data.get("nivel", "general")
    resultado = generar_esquema(temas=temas, db=db, instrucciones=instrucciones, nivel=nivel)
    return jsonify({"esquema": resultado})

@app.route("/generar-test-oficial", methods=["POST"])
def generar_test_oficial():
    data = request.get_json()
    num_preguntas = data.get("num_preguntas", 10)
    examenes_filtrados = data.get("examenes", [])  # opcional

    print(f"📥 Petición recibida en /generar-test-oficial: {data}")
    docs = db.collection("examenes_oficiales_AGE").stream()

    preguntas = []
    for doc in docs:
        d = doc.to_dict()
        if d.get("tipo") != "pregunta":
            continue
        
        if examenes_filtrados:
            print(f"Filtrando examen: campo examen='{d.get('examen')}', examenes_filtrados={examenes_filtrados}")
            if d.get("examen", "").lower().replace(" ", "_") not in [e.lower() for e in examenes_filtrados]:
                continue
        
        opciones_originales = d.get("opciones", {})
        opciones_mayus = {k.upper(): v for k, v in opciones_originales.items()}

        preguntas.append({
            "pregunta": d.get("pregunta", ""),
            "opciones": opciones_mayus,
            "respuesta_correcta": d.get("respuesta_correcta", "").upper(),
            "explicacion": d.get("explicacion", ""),
            "examen": d.get("examen", ""),
            "numero": d.get("numero", 0)  # sin tilde
        })

    print(f"📚 Preguntas encontradas: {len(preguntas)}")
    if not preguntas:
        return jsonify({"test": [], "mensaje": "No se encontraron preguntas"}), 404

    seleccionadas = random.sample(preguntas, min(num_preguntas, len(preguntas)))
    return jsonify({"test": seleccionadas})

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

from flask import jsonify

@app.route("/", methods=["GET"])
def listar_rutas():
    rutas = [rule.rule for rule in app.url_map.iter_rules()]
    return jsonify({"rutas_disponibles": rutas})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))



