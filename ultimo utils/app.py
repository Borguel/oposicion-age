import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# Importaciones de tus módulos personalizados
from utils import obtener_contexto_por_temas
from chat_controller import responder_chat
from test_generator import generar_test_avanzado
from esquema_generator import generar_esquema
from save_controller import guardar_test_route, guardar_esquema_route
from rutas_progreso import registrar_rutas_progreso

# Cargar variables de entorno
load_dotenv()
print("🔑 Clave OpenAI:", os.getenv("OPENAI_API_KEY"))

# Inicializar Firebase
firebase_key_path = os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json")
cred = credentials.Certificate(firebase_key_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

# Inicializar la aplicación Flask
app = Flask(__name__)
CORS(app, origins=["https://lightslategray-caribou-622401.hostingersite.com"])
print("✅ CORS activado para tu WordPress")

# Ruta para el chat
@app.route("/chat", methods=["POST"])
def chat_route():
    data = request.get_json()
    mensaje = data.get("mensaje")
    temas = data.get("temas", [])
    respuesta = responder_chat(mensaje=mensaje, temas=temas, db=db)
    return jsonify({"respuesta": respuesta})

# Ruta para generar test avanzado
@app.route("/generar-test-avanzado", methods=["POST"])
def generar_test_avanzado_route():
    data = request.get_json()
    temas = data.get("temas", [])
    num_preguntas = data.get("num_preguntas", 5)
    resultado = generar_test_avanzado(temas=temas, db=db, num_preguntas=num_preguntas)
    return jsonify(resultado)

# Ruta para generar esquemas
@app.route("/generar-esquema", methods=["POST"])
def generar_esquema_route():
    data = request.get_json()
    temas = data.get("temas", [])
    instrucciones = data.get("instrucciones", "Resume los contenidos clave.")
    nivel = data.get("nivel", "general")
    resultado = generar_esquema(temas=temas, db=db, instrucciones=instrucciones, nivel=nivel)
    return jsonify({"esquema": resultado})

# Guardar test y esquema
app.add_url_rule("/guardar-test", view_func=guardar_test_route(db), methods=["POST"])
app.add_url_rule("/guardar-esquema", view_func=guardar_esquema_route(db), methods=["POST"])

# Registrar las rutas de progreso de usuario
registrar_rutas_progreso(app, db)

# Ruta para obtener lista de temas disponibles
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

# Ruta de depuración para ver el contexto generado
@app.route("/debug-contexto", methods=["POST"])
def debug_contexto():
    try:
        data = request.get_json()
        temas = data.get("temas", [])
        contexto = obtener_contexto_por_temas(db, temas)
        return jsonify({"contexto": contexto[:3000]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Ruta para Render (debe estar al final)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
