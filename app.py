import os
from flask import Flask, request, jsonify
from flask_cors import CORS
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
print("CLAVE:", os.getenv("OPENAI_API_KEY"))

# Inicializar Firebase
firebase_key_path = os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json")
cred = credentials.Certificate(firebase_key_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

# Inicializar Flask
app = Flask(__name__)
CORS(app)

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
    temas = data.get("temas", [])
    num_preguntas = data.get("num_preguntas", 5)
    resultado = generar_test_avanzado(temas=temas, db=db, num_preguntas=num_preguntas)
    return jsonify({"test": resultado})

@app.route("/simulacro", methods=["POST"])
def generar_simulacro_route():
    data = request.get_json()
    num_preguntas = data.get("num_preguntas", 50)
    resultado = generar_simulacro(db=db, num_preguntas=num_preguntas)
    return jsonify({"simulacro": resultado})

@app.route("/generar-esquema", methods=["POST"])
def generar_esquema_route():
    data = request.get_json()
    temas = data.get("temas", [])
    instrucciones = data.get("instrucciones", "Resume los contenidos clave.")
    nivel = data.get("nivel", "general")
    resultado = generar_esquema(temas=temas, db=db, instrucciones=instrucciones, nivel=nivel)
    return jsonify({"esquema": resultado})

# Guardar resultados
app.add_url_rule("/guardar-test", view_func=guardar_test_route(db), methods=["POST"])
app.add_url_rule("/guardar-esquema", view_func=guardar_esquema_route(db), methods=["POST"])

# Registrar rutas de progreso de usuario (incluye /resumen-progreso)
registrar_rutas_progreso(app, db)  # ✅ NUEVO

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))