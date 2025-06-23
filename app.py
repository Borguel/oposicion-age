from flask import Flask, request, jsonify
from firebase_admin import credentials, firestore, initialize_app
from test_generator import generar_test_avanzado
from utils import obtener_temas_disponibles

app = Flask(__name__)
cred = credentials.Certificate("clave-firebase.json")
initialize_app(cred)
db = firestore.client()

@app.route("/temas-disponibles", methods=["GET"])
def temas_disponibles():
    temas = obtener_temas_disponibles(db)
    return jsonify(temas=temas)

@app.route("/generar-test-avanzado", methods=["POST"])
def generar_test():
    datos = request.get_json()
    temas = [tema["id"] for tema in datos.get("temas", [])]
    num_preguntas = datos.get("num_preguntas", 10)
    test = generar_test_avanzado(db, temas, num_preguntas)
    return jsonify(test=test)

if __name__ == "__main__":
    app.run(debug=True)