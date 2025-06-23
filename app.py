import os
from flask import Flask, request, jsonify
from test_generator import generar_test_avanzado
from utils import obtener_temas_disponibles

app = Flask(__name__)

@app.route('/generar-test-avanzado', methods=['POST'])
def generar_test():
    data = request.get_json()
    temas = data.get("temas", [])
    num_preguntas = int(data.get("num_preguntas", 10))
    db = obtener_db()
    test = generar_test_avanzado(db, temas, num_preguntas)
    return jsonify({"test": test})

@app.route('/temas-disponibles', methods=['GET'])
def temas_disponibles():
    db = obtener_db()
    temas = obtener_temas_disponibles(db)
    return jsonify({"temas": temas})

def obtener_db():
    import firebase_admin
    from firebase_admin import credentials, firestore
    if not firebase_admin._apps:
        cred = credentials.Certificate("clave-firebase.json")
        firebase_admin.initialize_app(cred)
    return firestore.client()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))  # 🔥 Este es el truco para Render
    app.run(debug=True, host='0.0.0.0', port=port)
