"""Carga la prueba psicotécnica (aptitudinal) del Metro de Madrid, convocatoria
2023, en Firestore, bajo la colección propia de la prueba psicotécnica de
Metro (ver oposiciones.coleccion_psicotecnico).

A diferencia de las preguntas "psicotecnico" de Auxiliar (que viven mezcladas
con el resto del examen oficial en examenes_oficiales_AUXILIAR y se pueden
excluir con un checkbox en /test-oficial/), en Metro esta prueba tiene su
propia página (/test-psicotecnico/): 25 preguntas de razonamiento verbal y 25
de razonamiento espacial, cada una como un examen completo y separado -- así
que se guardan en una colección aparte, nunca mezclada con temario.

Las preguntas viven en datos_examenes/metro_2023_psicotecnico.json. Dos
orígenes distintos, cada uno marcado con su propio campo "examen" en el
JSON:
  - Las 50 originales, extraídas y revisadas de la "Prueba Tipo Examen,
    Convocatoria 2023 Metro de Madrid" (Empleo Maquinistas).
  - 100 preguntas propias añadidas después para ampliar el banco de
    práctica (50 de razonamiento verbal redactadas a mano; 50 de
    razonamiento espacial generadas por código con la respuesta calculada,
    no adivinada -- ver frontend/assets/psicotecnico-metro/gen_*.py en el
    histórico de esta carga).
Las preguntas de razonamiento espacial llevan un campo "imagen" con la
ruta de la figura recortada/generada en frontend/assets/psicotecnico-metro/.

Requiere las mismas variables de entorno que el resto del proyecto (ver
app.py / .env): FIREBASE_CREDENTIALS_JSON (o FIREBASE_KEY_PATH apuntando a
clave-firebase.json).

Uso:
    python cargar_psicotecnico_metro.py
"""
import os
import json

import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

from oposiciones import coleccion_psicotecnico

load_dotenv()

BASE_DIR = os.path.dirname(__file__)

if not firebase_admin._apps:
    firebase_credentials_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if firebase_credentials_json:
        cred = credentials.Certificate(json.loads(firebase_credentials_json))
    else:
        firebase_key_path = os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json")
        cred = credentials.Certificate(firebase_key_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()

NOMBRE_EXAMEN_POR_DEFECTO = "METRO 2023 - Prueba tipo examen, parte aptitudinal (Empleo Maquinistas)"
PRUEBA_CODIGO = {"verbal": "v", "espacial": "e"}


def cargar():
    ruta_datos = os.path.join(BASE_DIR, "datos_examenes", "metro_2023_psicotecnico.json")
    with open(ruta_datos, encoding="utf-8") as f:
        preguntas = json.load(f)

    coleccion = coleccion_psicotecnico("METRO")
    print(f"Subiendo {len(preguntas)} preguntas a Firestore -> colección '{coleccion}'")

    for p in preguntas:
        # :02d es solo un ANCHO MÍNIMO (no trunca): numero=5 -> "05",
        # numero=100 -> "100" -- a propósito el mismo formato que la carga
        # original, para que sobrescriba los documentos ya existentes en
        # vez de duplicarlos.
        doc_id = f"metro_2023_psico_{PRUEBA_CODIGO[p['prueba']]}_{p['numero']:02d}"
        datos = {
            "tipo": "pregunta",
            "examen": p.get("examen") or NOMBRE_EXAMEN_POR_DEFECTO,
            "prueba": p["prueba"],
            "numero": p["numero"],
            "pregunta": p["pregunta"],
            "opciones": p["opciones"],
            "respuesta_correcta": p["respuesta_correcta"],
            "explicacion": p.get("explicacion", ""),
        }
        if p.get("imagen"):
            datos["imagen"] = p["imagen"]
        db.collection(coleccion).document(doc_id).set(datos)
        print(f"  Pregunta {p['numero']} ({p['prueba']})... OK")

    print("Carga completada.")


if __name__ == "__main__":
    cargar()
