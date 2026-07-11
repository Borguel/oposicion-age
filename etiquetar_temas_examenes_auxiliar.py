"""Añade el campo `tema_id` a las preguntas ya subidas de los exámenes
oficiales de AUXILIAR en Firestore (colección `examenes_oficiales_AUXILIAR`).

Cada pregunta se asignó manualmente a uno de los temas del temario oficial de
Auxiliar (bloque I "Organización pública" o bloque II "Actividad
administrativa y ofimática"), en base al artículo/ley que cita, y esa
asignación vive en datos_examenes/auxiliar_<anio>_ejercicio_unico_temas.json
(mapa "<parte>_<numero>" -> "bloque_XX-tema_XX", p.ej. "primera_1" o
"segunda_37"). Las preguntas psicotécnicas de la primera parte (vocabulario,
aritmética, series...) no pertenecen a ningún tema del temario y por tanto no
aparecen en ese mapa -- no es un error, simplemente no se etiquetan.

Requiere las mismas variables de entorno que el resto del proyecto:
FIREBASE_CREDENTIALS_JSON (o FIREBASE_KEY_PATH).

Uso:
    python etiquetar_temas_examenes_auxiliar.py <anio>
    python etiquetar_temas_examenes_auxiliar.py 2025
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

PARTE_CODIGO = {"primera": "p1", "segunda": "p2"}


def etiquetar(anio):
    ruta_temas = os.path.join(BASE_DIR, "datos_examenes", f"auxiliar_{anio}_ejercicio_unico_temas.json")
    with open(ruta_temas, encoding="utf-8") as f:
        mapa_temas = json.load(f)

    coleccion = coleccion_examenes_oficiales("AUXILIAR")
    actualizadas, sin_mapeo = 0, []
    for clave, tema_id in mapa_temas.items():
        parte, numero_str = clave.rsplit("_", 1)
        numero = int(numero_str)
        doc_id = f"auxiliar_{anio}_eu_{PARTE_CODIGO[parte]}_{numero:03d}"
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
        print("Uso: python etiquetar_temas_examenes_auxiliar.py <anio>")
        sys.exit(1)
    etiquetar(sys.argv[1])
