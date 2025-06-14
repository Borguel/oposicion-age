import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

from chat_controller import responder_chat
from test_generator import generar_test_avanzado, generar_simulacro
from save_controller import guardar_test_route, guardar_esquema_route
from esquema_generator import generar_esquema
from rutas_progreso import (
    obtener_resumen_progreso_route,
    registrar_tiempo_dedicado_route,
    registrar_resultado_test_route,
    registrar_resultado_esquema_route
)

# Cargar variables de entorno
load_dotenv()
print("CLAVE:", os.getenv("OPENAI_API_KEY"))

# Inicializar Firebase
firebase_key_path = "/etc/secrets/clave-firebase.json" if os.getenv("RENDER") else "clave-firebase.json"
cred = credentials.Certificate(firebase_key_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

# Inicializar Flask
app = Flask(__name__)
CORS(app)

# Rutas principales
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

# Guardado de tests y esquemas
app.add_url_rule("/guardar-test", view_func=guardar_test_route(db), methods=["POST"])
app.add_url_rule("/guardar-esquema", view_func=guardar_esquema_route(db), methods=["POST"])

# Rutas para métricas y progreso del usuario
app.add_url_rule("/progreso/resumen", view_func=obtener_resumen_progreso_route(db), methods=["GET"])
app.add_url_rule("/progreso/tiempo", view_func=registrar_tiempo_dedicado_route(db), methods=["POST"])
app.add_url_rule("/progreso/test", view_func=registrar_resultado_test_route(db), methods=["POST"])
app.add_url_rule("/progreso/esquema", view_func=registrar_resultado_esquema_route(db), methods=["POST"])

# Ejecutar la app
if __name__ == "__main__":
    app.run(debug=True)