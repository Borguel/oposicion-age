"""Añade el campo `tema_id` a las preguntas ya subidas de los exámenes
oficiales de AGE en Firestore (colección `examenes_oficiales_AGE`).

Cada pregunta se asignó manualmente a uno de los temas del temario oficial
de AGE (ver cargar_temario_boe.py / completar_temario_age.py), en base al
artículo/ley que cita, y esa asignación vive en
datos_examenes/age_<anio>_ejercicio_unico_temas.json (mapa "numero" ->
"bloque_XX-tema_XX").

Requiere las mismas variables de entorno que el resto del proyecto:
FIREBASE_CREDENTIALS_JSON (o FIREBASE_KEY_PATH).

Uso:
    python etiquetar_temas_examenes_age.py <anio>
    python etiquetar_temas_examenes_age.py 2025
"""
import os
import sys
import json

import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

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


def etiquetar(anio):
    ruta_temas = os.path.join(BASE_DIR, "datos_examenes", f"age_{anio}_ejercicio_unico_temas.json")
    with open(ruta_temas, encoding="utf-8") as f:
        mapa_temas = json.load(f)

    coleccion = coleccion_examenes_oficiales("AGE")
    actualizadas, sin_mapeo = 0, []
    for numero_str, tema_id in mapa_temas.items():
        numero = int(numero_str)
        doc_id = f"age_{anio}_eu_{numero:03d}"
        ref = db.collection(coleccion).document(doc_id)
        if not ref.get().exists:
            sin_mapeo.append(doc_id)
            continue
        ref.update({"tema_id": tema_id})
        actualizadas += 1

    print(f"{actualizadas}/{len(mapa_temas)} preguntas de {anio} etiquetadas con tema_id.")
    if sin_mapeo:
        print("AVISO: no encontrados en Firestore:", sin_mapeo)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python etiquetar_temas_examenes_age.py <anio>")
        sys.exit(1)
    etiquetar(sys.argv[1])
