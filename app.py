
from flask import Flask, request, jsonify
from firebase_admin import credentials, firestore, initialize_app
from test_generator import generar_test_avanzado
import os

app = Flask(__name__)

cred = credentials.Certificate("clave-firebase.json")
initialize_app(cred)
db = firestore.client()

@app.route("/generar-test-avanzado", methods=["POST"])
def generar_test_avanzado_route():
    data = request.get_json()
    temas = [t["id"] if isinstance(t, dict) else t for t in data.get("temas", [])]
    num_preguntas = int(data.get("num_preguntas", 5))
    preguntas = generar_test_avanzado(db, temas, num_preguntas)
    return jsonify({"test": preguntas})

if __name__ == "__main__":
    app.run(debug=True, port=10000)
