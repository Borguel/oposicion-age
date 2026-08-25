"""Notificaciones push del navegador (Web Push + VAPID), en el mismo
estilo "no-op sin configurar" que ya usa la integración de Sentry en
app.py -- si no hay claves VAPID en el entorno, el resto de la app sigue
funcionando igual, simplemente no se envían pushes.

Implementado a mano con librerías que este proyecto ya usa en producción
(cryptography, PyJWT, requests) en vez de con "pywebpush": esa librería
arrastra "http-ece" (un paquete sin wheel, solo distribuido como fuente
con un setup.py antiguo) y "aiohttp" (con extensiones en C), y ambas
fallaron al compilar en el entorno de build de Render. El cifrado
"aes128gcm" (RFC 8291) y el token VAPID (RFC 8292) son formatos
estándar y pequeños; implementarlos aquí evita esa dependencia frágil
por completo.

Las claves VAPID se generan con generar_claves_vapid.py (en la raíz del
proyecto) y se guardan como VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY, cada
una en base64url sin relleno: la pública es el punto EC sin comprimir
(65 bytes) tal cual espera `PushManager.subscribe()` en el navegador, la
privada es el escalar crudo (32 bytes).
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import urlsplit

import jwt
import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

logger = logging.getLogger(__name__)

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "mailto:soporte@oposicion-age.com")


def push_disponible():
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)


def _b64url_decode(texto):
    relleno = "=" * (-len(texto) % 4)
    return base64.urlsafe_b64decode(texto + relleno)


def _clave_privada_vapid():
    escalar = _b64url_decode(VAPID_PRIVATE_KEY)
    return ec.derive_private_key(int.from_bytes(escalar, "big"), ec.SECP256R1())


def _token_vapid(endpoint):
    origen = urlsplit(endpoint)
    audiencia = f"{origen.scheme}://{origen.netloc}"
    payload = {
        "aud": audiencia,
        "exp": int(time.time()) + 12 * 3600,
        "sub": VAPID_CLAIMS_EMAIL,
    }
    return jwt.encode(payload, _clave_privada_vapid(), algorithm="ES256")


def _hkdf_extract(sal, ikm):
    return hmac.new(sal, ikm, hashlib.sha256).digest()


def _hkdf_expand(prk, info, longitud):
    return HKDFExpand(algorithm=hashes.SHA256(), length=longitud, info=info).derive(prk)


def _cifrar_aes128gcm(clave_publica_navegador, secreto_auth, texto_plano):
    """Cifra el payload según RFC 8291 (aes128gcm) para el navegador
    receptor, identificado por su clave pública P-256 y su "auth secret"
    (ambos vienen en subscription.keys al suscribirse)."""
    clave_navegador = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), clave_publica_navegador)
    clave_efimera = ec.generate_private_key(ec.SECP256R1())
    clave_efimera_publica = clave_efimera.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)

    secreto_ecdh = clave_efimera.exchange(ec.ECDH(), clave_navegador)

    info_clave = b"WebPush: info\x00" + clave_publica_navegador + clave_efimera_publica
    prk_clave = _hkdf_extract(secreto_auth, secreto_ecdh)
    ikm = _hkdf_expand(prk_clave, info_clave, 32)

    sal = os.urandom(16)
    prk = _hkdf_extract(sal, ikm)
    clave_contenido = _hkdf_expand(prk, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf_expand(prk, b"Content-Encoding: nonce\x00", 12)

    tamano_registro = 4096
    cabecera = (
        sal
        + tamano_registro.to_bytes(4, "big")
        + len(clave_efimera_publica).to_bytes(1, "big")
        + clave_efimera_publica
    )
    # Delimitador 0x02 = último (y único) registro, según el formato de
    # contenido "aes128gcm" de RFC 8188.
    cifrado = AESGCM(clave_contenido).encrypt(nonce, texto_plano + b"\x02", None)
    return cabecera + cifrado


def enviar_push(suscripcion, titulo, cuerpo, url="/zona-opositor/"):
    """Envía una notificación. Devuelve:
    - True si se envió correctamente.
    - None si la suscripción ya no es válida -- el servicio de push
      respondió 404/410 ("gone"), la señal estándar de que el navegador
      desinstaló la PWA o revocó el permiso. El llamante debe borrar esta
      suscripción con borrar_suscripcion; seguir usándola solo generaría
      más llamadas que nunca van a entregarse.
    - False para cualquier otro fallo (sin claves configuradas, formato de
      suscripción inesperado, error de red, 5xx del servicio de push...) --
      puede ser transitorio, así que NO implica borrar la suscripción."""
    if not push_disponible():
        return False

    endpoint = suscripcion.get("endpoint")
    claves = suscripcion.get("keys") or {}
    if not endpoint or not claves.get("p256dh") or not claves.get("auth"):
        return False

    try:
        cuerpo_cifrado = _cifrar_aes128gcm(
            _b64url_decode(claves["p256dh"]),
            _b64url_decode(claves["auth"]),
            json.dumps({"title": titulo, "body": cuerpo, "url": url}).encode("utf-8"),
        )
        token = _token_vapid(endpoint)
        respuesta = requests.post(
            endpoint,
            data=cuerpo_cifrado,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Encoding": "aes128gcm",
                "TTL": "86400",
                "Authorization": f"vapid t={token}, k={VAPID_PUBLIC_KEY}",
            },
            timeout=10,
        )
        if respuesta.status_code in (404, 410):
            logger.info("Suscripción push caducada (%s): %s", respuesta.status_code, endpoint)
            return None
        if respuesta.status_code not in (200, 201, 202):
            logger.warning("Push rechazado (%s): %s", respuesta.status_code, respuesta.text[:200])
            return False
        return True
    except Exception as e:
        logger.warning("Error enviando notificación push: %s", e)
        return False


def guardar_suscripcion(db, usuario_id, suscripcion):
    """Añade la suscripción a usuarios/{uid}.push_subscriptions, sin
    duplicarla si el navegador ya la había mandado antes (misma
    "endpoint" -- un mismo dispositivo/navegador puede volver a llamar a
    subscribe() y obtener la misma suscripción)."""
    endpoint = suscripcion.get("endpoint")
    if not endpoint:
        return
    ref = db.collection("usuarios").document(usuario_id)
    datos = ref.get().to_dict() or {}
    actuales = [s for s in datos.get("push_subscriptions", []) if s.get("endpoint") != endpoint]
    actuales.append(suscripcion)
    ref.set({"push_subscriptions": actuales}, merge=True)


def borrar_suscripcion(db, usuario_id, endpoint):
    ref = db.collection("usuarios").document(usuario_id)
    datos = ref.get().to_dict() or {}
    actuales = [s for s in datos.get("push_subscriptions", []) if s.get("endpoint") != endpoint]
    ref.set({"push_subscriptions": actuales}, merge=True)
