"""Arranque de Firebase Admin, en su propio módulo para que tanto app.py
como cada blueprint puedan importar `db` sin depender unos de otros
(si viviera dentro de app.py, cualquier blueprint que necesitara `db`
tendría que importar app.py, que a su vez importa los blueprints -> import
circular)."""
import json
import os

import firebase_admin
from firebase_admin import credentials, firestore

# Admite dos formas de dar la clave de servicio: un fichero (FIREBASE_KEY_PATH,
# útil con "Secret Files" de Render) o el JSON completo en una variable de
# entorno (FIREBASE_CREDENTIALS_JSON), útil en plataformas sin subida de ficheros.
if not firebase_admin._apps:
    firebase_credentials_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if firebase_credentials_json:
        cred = credentials.Certificate(json.loads(firebase_credentials_json))
    else:
        firebase_key_path = os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json")
        cred = credentials.Certificate(firebase_key_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()
