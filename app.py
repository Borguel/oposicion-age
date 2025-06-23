# 💣 COMPROBACIÓN DE DEPLOY v3.1
import os
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

load_dotenv()
print("🆕 DEPLOY ACTUALIZADO: v3.1")
print("🔑 Clave OpenAI:", os.getenv("OPENAI_API_KEY"))

firebase_key_path = os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json")

if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_key_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()

app = Flask(__name__)
CORS(app, origins=["https://lightslategray-caribou-622401.hostingersite.com"])
print("✅ CORS activado para tu WordPress")

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

# Resto igual
