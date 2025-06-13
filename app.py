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
from rutas_progreso import (
    registrar_usuario_route,
    actualizar_estadisticas_test_route,
    actualizar_estadisticas_esquema_route,
    registrar_tiempo_estudio_route
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

# Chat con el temario
@app.route("/chat", methods=["POST"])
def chat_route():
    data = request.get_json()
    mensaje = data.get("mensaje")
    temas = data.get("temas", [])
    respuesta = responder_chat(mensaje=mensaje, temas=temas, db=db)
    return jsonify({"respuesta": respuesta})

# Generar test avanzado
@app.route("/generar-test-avanzado", methods=["POST"])
def generar_test_avanzado_route():
    data = request.get_json()
    temas = data.get("temas", [])
    num_preguntas = data.get("num_preguntas", 5)
    resultado = generar_test_avanzado(temas=temas, db=db, num_preguntas=num_preguntas)
    return jsonify({"test": resultado})

# Generar simulacro
@app.route("/simulacro", methods=["POST"])
def generar_simulacro_route():
    data = request.get_json()
    num_preguntas = data.get("num_preguntas", 50)
    resultado = generar_simulacro(db=db, num_preguntas=num_preguntas)
    return jsonify({"simulacro": resultado})

# Generar esquema
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

# NUEVO: rutas de estadísticas
app.add_url_rule("/registrar-usuario", view_func=registrar_usuario_route(db), methods=["POST"])
app.add_url_rule("/actualizar-estadisticas-test", view_func=actualizar_estadisticas_test_route(db), methods=["POST"])
app.add_url_rule("/actualizar-estadisticas-esquema", view_func=actualizar_estadisticas_esquema_route(db), methods=["POST"])
app.add_url_rule("/registrar-tiempo-estudio", view_func=registrar_tiempo_estudio_route(db), methods=["POST"])

# Ejecutar app
if __name__ == "__main__":
    app.run(debug=True)
