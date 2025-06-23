import os
from flask import Flask, request, jsonify
from firebase_admin import credentials, firestore, initialize_app
from test_generator import generar_test_avanzado
from utils import obtener_temas_disponibles

# Inicializar Flask
app = Flask(__name__)

# Inicializar Firebase
cred = credentials.Certificate("clave-firebase.json")
initialize_app(cred)
db = firestore.client()

# Ruta para obtener los temas disponibles desde Firestore
@app.route('/temas-disponibles', methods=['GET'])
def temas_disponibles():
    temas = obtener_temas_disponibles(db)
    return jsonify({"temas": temas})

# Ruta para generar un test avanzado con IA
@app.route('/generar-test-avanzado', methods=['POST'])
def generar_test():
    datos = request.get_json()
    temas = datos.get('temas', [])
    num_preguntas = datos.get('num_preguntas', 10)
    preguntas = generar_test_avanzado(db, temas, num_preguntas)
    return jsonify({"test": preguntas})

# 🔧 Especificar puerto dinámico que Render espera
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=True)
