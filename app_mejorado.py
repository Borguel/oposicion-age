# ✅ app.py mejorado

import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from utils import obtener_contexto_por_temas
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

from chat_controller import responder_chat
from test_generator import generar_test_avanzado, generar_simulacro
from esquema_generator import generar_esquema
from save_controller import guardar_test_route, guardar_esquema_route
from rutas_progreso import registrar_rutas_progreso  # ✅ CORREGIDO

# Cargar variables de entorno
load_dotenv()
print("🔑 CLAVE cargada:", os.getenv("OPENAI_API_KEY"))

# Inicializar Firebase
firebase_key_path = os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json")
cred = credentials.Certificate(firebase_key_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

# Inicializar Flask
app = Flask(__name__)
CORS(app, origins=["https://lightslategray-caribou-622401.hostingersite.com"])
print("✅ CORS configurado correctamente para WordPress")

# 🔹 ENDPOINT: Chat libre con IA
@app.route("/chat", methods=["POST"])
def chat_route():
    data = request.get_json()
    mensaje = data.get("mensaje")
    temas = data.get("temas", [])
    respuesta = responder_chat(mensaje=mensaje, temas=temas, db=db)
    return jsonify({"respuesta": respuesta})

# 🔹 ENDPOINT: Generador de test avanzado
@app.route("/generar-test-avanzado", methods=["POST"])
def generar_test_avanzado_route():
    data = request.get_json()
    temas = data.get("temas", [])
    num_preguntas = data.get("num_preguntas", 5)
    resultado = generar_test_avanzado(temas=temas, db=db, num_preguntas=num_preguntas)
    return jsonify(resultado)

# 🔹 ENDPOINT: Simulacro de examen completo
@app.route("/simulacro", methods=["POST"])
def generar_simulacro_route():
    data = request.get_json()
    num_preguntas = data.get("num_preguntas", 50)
    resultado = generar_simulacro(db=db, num_preguntas=num_preguntas)
    return jsonify({"simulacro": resultado})

# 🔹 ENDPOINT: Generador de esquemas
@app.route("/generar-esquema", methods=["POST"])
def generar_esquema_route():
    data = request.get_json()
    temas = data.get("temas", [])
    instrucciones = data.get("instrucciones", "Resume los contenidos clave.")
    nivel = data.get("nivel", "general")
    resultado = generar_esquema(temas=temas, db=db, instrucciones=instrucciones, nivel=nivel)
    return jsonify({"esquema": resultado})

# 🔹 ENDPOINT: Guardar test y esquemas
app.add_url_rule("/guardar-test", view_func=guardar_test_route(db), methods=["POST"])
app.add_url_rule("/guardar-esquema", view_func=guardar_esquema_route(db), methods=["POST"])

# 🔹 ENDPOINT: Rutas de progreso del usuario
registrar_rutas_progreso(app, db)

# 🔹 ENDPOINT: Obtener temas disponibles
@app.route("/temas-disponibles", methods=["GET"])
def obtener_temas_disponibles():
    temas = []
    docs = db.collection("temario").stream()
    for doc in docs:
        data = doc.to_dict()
        temas.append({
            "id": doc.id,
            "titulo": data.get("titulo", doc.id)
        })
    return jsonify({"temas": temas})

# 🔹 ENDPOINT: Ver contexto generado (debug)
@app.route("/debug-contexto", methods=["POST"])
def debug_contexto():
    try:
        data = request.get_json()
        temas = data.get("temas", [])
        contexto = obtener_contexto_por_temas(db, temas)
        return jsonify({"contexto": contexto[:3000]})
    except Exception as e:
        print(f"❌ Error en /debug-contexto: {e}")
        return jsonify({"error": str(e)}), 500

# 🔹 ENDPOINT: Obtener test oficial
@app.route('/test/oficiales', methods=['GET'])
def obtener_test_oficial():
    año = request.args.get('año')
    turno = request.args.get('turno', 'libre').lower()

    if not año:
        return jsonify({"error": "Falta el parámetro 'año'"}), 400

    exam_ref = db.collection('examenes_oficiales_AGE')
    query = exam_ref.where('año', '==', int(año)).where('turno', '==', turno).limit(1)
    resultados = query.stream()

    for doc in resultados:
        datos = doc.to_dict()
        preguntas = datos.get("preguntas", [])
        return jsonify({"test": preguntas})

    return jsonify({"error": "No se encontró el examen"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
