"""Arranque de Firebase Admin, en su propio módulo para que tanto app.py
como cada blueprint puedan importar `db` sin depender unos de otros
(si viviera dentro de app.py, cualquier blueprint que necesitara `db`
tendría que importar app.py, que a su vez importa los blueprints -> import
circular)."""
import json
import os


def propagar_proxy_saliente(entorno=os.environ):
    """Si hay un proxy de salida con IP estática configurado (QuotaGuard o
    Fixie, para esquivar el bloqueo de Google a las IPs de salida
    compartidas del plan gratuito de Render -- ver incidencia de
    CertificateFetchError / PermissionDenied 403), lo propaga a las
    variables de entorno estándar que leen tanto `requests` (verificación
    de tokens de Firebase) como gRPC (llamadas a Firestore): así basta con
    fijar la variable del proveedor que uses para cubrir las dos, sin
    configurar cada librería por separado.

    Admite dos proveedores con el mismo formato de URL (http://user:pass@host:puerto):
    FIXIE_URL (usado ahora, gratis en fase de desarrollo) y QUOTAGUARDSTATIC_URL
    (usado antes en producción). Si ambas están fijadas -- p.ej. al migrar de
    una a otra sin haber borrado todavía la antigua -- gana FIXIE_URL. Sin
    ninguna de las dos, no hace nada (comportamiento actual intacto). Debe
    llamarse ANTES de crear cualquier cliente de Firebase/Firestore, para
    que la propagación surta efecto."""
    proxy_saliente = entorno.get("FIXIE_URL") or entorno.get("QUOTAGUARDSTATIC_URL")
    if not proxy_saliente:
        return
    for variable in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        entorno.setdefault(variable, proxy_saliente)


propagar_proxy_saliente()

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
