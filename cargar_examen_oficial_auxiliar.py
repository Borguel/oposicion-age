"""Carga el Ejercicio Único de una convocatoria del Cuerpo General Auxiliar de
la Administración del Estado (Auxiliar, Ingreso Libre) en Firestore, bajo la
colección de exámenes oficiales de AUXILIAR.

A diferencia de AGE/GACE, en Auxiliar las DOS partes del ejercicio único son
cuestionarios tipo test (no hay supuesto práctico), así que ambas se suben:
Primera parte (60 preguntas + 5 de reserva, sobre el bloque I del temario y
preguntas psicotécnicas) y Segunda parte (50 preguntas + 5 de reserva, sobre
el bloque II del temario -- actividad administrativa y ofimática). Cada
pregunta lleva un campo "parte" ("primera" o "segunda") y su "numero" reinicia
en 1 en cada parte, tal y como numera la propia Plantilla oficial.

Las preguntas deben estar ya extraídas y revisadas en
datos_examenes/auxiliar_<anio>_ejercicio_unico.json. La explicación de cada
respuesta correcta se toma de
datos_examenes/auxiliar_<anio>_ejercicio_unico_explicaciones.json si existe
(clave = "<parte>_<numero>", p.ej. "primera_1" o "segunda_37"); si no existe o
falta alguna pregunta, se genera con DeepSeek en el momento de la subida.

Requiere las mismas variables de entorno que el resto del proyecto (ver
app.py / .env): FIREBASE_CREDENTIALS_JSON (o FIREBASE_KEY_PATH apuntando a
clave-firebase.json) y, si hace falta generar alguna explicación con IA,
DEEPSEEK_API_KEY.

Uso:
    python cargar_examen_oficial_auxiliar.py <anio>
    python cargar_examen_oficial_auxiliar.py 2025
"""
import os
import sys
import json
import time

import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

from deepseek_utils import call_deepseek_api
from oposiciones import coleccion_examenes_oficiales

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

PARTE_CODIGO = {"primera": "p1", "segunda": "p2"}


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


def cargar_examen(anio):
    ruta_datos = os.path.join(BASE_DIR, "datos_examenes", f"auxiliar_{anio}_ejercicio_unico.json")
    ruta_explicaciones = os.path.join(
        BASE_DIR, "datos_examenes", f"auxiliar_{anio}_ejercicio_unico_explicaciones.json"
    )
    nombre_examen = f"AUXILIAR {anio} - Ejercicio único (ingreso libre)"

    with open(ruta_datos, encoding="utf-8") as f:
        preguntas = json.load(f)

    explicaciones = {}
    if os.path.exists(ruta_explicaciones):
        with open(ruta_explicaciones, encoding="utf-8") as f:
            explicaciones = json.load(f)

    coleccion = coleccion_examenes_oficiales("AUXILIAR")
    print(f"Subiendo {len(preguntas)} preguntas de {anio} a Firestore -> colección '{coleccion}'")

    for p in preguntas:
        clave = f"{p['parte']}_{p['numero']}"

        if p.get("anulada"):
            print(f"  Pregunta {clave}... ANULADA, se omite.")
            continue

        print(f"  Pregunta {clave}...", end=" ", flush=True)
        explicacion = explicaciones.get(clave, "").strip()
        if not explicacion:
            explicacion = generar_explicacion(p["pregunta"], p["opciones"], p["respuesta_correcta"])
            if not explicacion:
                print("(sin explicación, no disponible ni generable)", end=" ")
            time.sleep(0.3)  # margen prudente frente al límite de tasa de DeepSeek

        doc_id = f"auxiliar_{anio}_eu_{PARTE_CODIGO[p['parte']]}_{p['numero']:03d}"
        db.collection(coleccion).document(doc_id).set({
            "tipo": "pregunta",
            "examen": nombre_examen,
            "parte": p["parte"],
            "numero": p["numero"],
            "pregunta": p["pregunta"],
            "opciones": p["opciones"],
            "respuesta_correcta": p["respuesta_correcta"],
            "explicacion": explicacion,
            "reserva": p.get("reserva", False),
            "psicotecnico": p.get("psicotecnico", False),
        })
        print("OK")

    print("Carga completada.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python cargar_examen_oficial_auxiliar.py <anio>")
        sys.exit(1)
    cargar_examen(sys.argv[1])
