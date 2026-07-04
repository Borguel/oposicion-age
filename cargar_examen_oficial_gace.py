"""Carga el Primer Ejercicio de la convocatoria GACE 2025 (Cuerpo de Gestión
de la Administración Civil del Estado, Ingreso Libre) en Firestore, bajo
la colección de exámenes oficiales de GACE, generando además con DeepSeek
una explicación de la respuesta correcta para cada pregunta.

Las 105 preguntas (100 + 5 de reserva) ya están extraídas y revisadas en
datos_examenes/gacel_2025_1er_ejercicio.json -- este script solo genera la
explicación de cada una y las sube.

Requiere las mismas variables de entorno que el resto del proyecto (ver
app.py / .env): FIREBASE_CREDENTIALS_JSON (o FIREBASE_KEY_PATH apuntando a
clave-firebase.json) y DEEPSEEK_API_KEY.

Uso:
    python cargar_examen_oficial_gace.py
"""
import os
import json
import time

import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

from deepseek_utils import call_deepseek_api
from oposiciones import coleccion_examenes_oficiales

load_dotenv()

RUTA_DATOS = os.path.join(os.path.dirname(__file__), "datos_examenes", "gacel_2025_1er_ejercicio.json")
NOMBRE_EXAMEN = "GACE 2025 - 1er ejercicio"

if not firebase_admin._apps:
    firebase_credentials_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if firebase_credentials_json:
        cred = credentials.Certificate(json.loads(firebase_credentials_json))
    else:
        firebase_key_path = os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json")
        cred = credentials.Certificate(firebase_key_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()


def generar_explicacion(pregunta, opciones, respuesta_correcta):
    opciones_texto = "\n".join(f"{letra}) {texto}" for letra, texto in opciones.items())
    prompt = (
        "Eres un experto en oposiciones y en legislación española. A continuación tienes una "
        "pregunta real de un examen oficial de oposición, con su respuesta correcta ya conocida. "
        "Explica de forma breve (2-4 frases), técnica y precisa por qué esa opción es la correcta, "
        "citando el artículo o la norma en la que se basa (la propia pregunta casi siempre ya la "
        "menciona). No repitas el enunciado ni la lista de opciones, ve directo a la explicación.\n\n"
        f"Pregunta: {pregunta}\n\n{opciones_texto}\n\n"
        f"Respuesta correcta: {respuesta_correcta}) {opciones.get(respuesta_correcta, '')}"
    )
    respuesta = call_deepseek_api(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=300
    )
    return (respuesta or "").strip()


def cargar_examen():
    with open(RUTA_DATOS, encoding="utf-8") as f:
        preguntas = json.load(f)

    coleccion = coleccion_examenes_oficiales("GACE")
    print(f"Subiendo {len(preguntas)} preguntas a Firestore -> colección '{coleccion}'")

    for p in preguntas:
        print(f"  Pregunta {p['numero']}...", end=" ", flush=True)
        explicacion = generar_explicacion(p["pregunta"], p["opciones"], p["respuesta_correcta"])
        if not explicacion:
            print("(sin explicación, DeepSeek no respondió; se sube igualmente)", end=" ")
        doc_id = f"gacel_2025_1ej_{p['numero']:03d}"
        db.collection(coleccion).document(doc_id).set({
            "tipo": "pregunta",
            "examen": NOMBRE_EXAMEN,
            "numero": p["numero"],
            "pregunta": p["pregunta"],
            "opciones": p["opciones"],
            "respuesta_correcta": p["respuesta_correcta"],
            "explicacion": explicacion,
            "reserva": p.get("reserva", False),
        })
        print("OK")
        time.sleep(0.3)  # margen prudente frente al límite de tasa de DeepSeek

    print("Carga completada.")


if __name__ == "__main__":
    cargar_examen()
