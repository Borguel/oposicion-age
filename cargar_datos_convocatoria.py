"""Sube a Firestore los datos oficiales de la convocatoria vigente de una
oposición (plazas, estructura de los ejercicios, tiempos, penalización,
calificación), para que Tu Tutor los use en vez de inventar estas cifras.

El contenido debe estar ya transcrito y revisado en
datos_examenes/datos_convocatoria_<OPOSICION>.json, con las claves
"oposicion", "anio", "fuente" y "texto" (el bloque de texto que se inyecta
tal cual en el prompt del chat -- ver utils.obtener_datos_convocatoria y
chat_controller.responder_tutor).

Sube un único documento a la colección "datos_convocatoria", con el código
de la oposición como id (sobrescribe el anterior si ya existía, para poder
actualizarlo cuando salga una convocatoria nueva).

Requiere las mismas variables de entorno que el resto del proyecto (ver
app.py / .env): FIREBASE_CREDENTIALS_JSON (o FIREBASE_KEY_PATH apuntando a
clave-firebase.json).

Uso:
    python cargar_datos_convocatoria.py <OPOSICION>
    python cargar_datos_convocatoria.py GACE
"""
import os
import sys
import json

import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

from oposiciones import oposicion_valida

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


def main():
    if len(sys.argv) < 2:
        print("Uso: python cargar_datos_convocatoria.py <OPOSICION>  (p. ej. GACE)")
        sys.exit(1)

    oposicion = sys.argv[1].upper()
    if not oposicion_valida(oposicion):
        print(f"⚠️  '{oposicion}' no está en el catálogo de oposiciones (oposiciones.py). Revisa el código antes de subir.")
        sys.exit(1)

    ruta = os.path.join(BASE_DIR, "datos_examenes", f"datos_convocatoria_{oposicion}.json")
    if not os.path.exists(ruta):
        print(f"❌ No se encuentra {ruta}")
        sys.exit(1)

    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)

    if not datos.get("texto"):
        print("❌ El JSON no tiene el campo 'texto' relleno.")
        sys.exit(1)

    db.collection("datos_convocatoria").document(oposicion).set(datos)
    print(f"✅ Datos de la convocatoria {oposicion} ({datos.get('anio', '?')}) subidos a Firestore.")
    print(f"   Fuente: {datos.get('fuente', '(sin especificar)')}")


if __name__ == "__main__":
    main()
