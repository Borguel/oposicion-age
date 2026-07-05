"""Genera un par de claves VAPID para las notificaciones push (ver
push_utils.py). Se ejecuta una sola vez; el resultado se guarda como
VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY en el entorno de despliegue (nunca
en el repositorio).

Uso: python generar_claves_vapid.py
"""
import base64

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def _b64url(datos):
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")


if __name__ == "__main__":
    clave_privada = ec.generate_private_key(ec.SECP256R1())
    numeros_privados = clave_privada.private_numbers()
    escalar_privado = numeros_privados.private_value.to_bytes(32, "big")
    clave_publica = clave_privada.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)

    print("VAPID_PUBLIC_KEY=" + _b64url(clave_publica))
    print("VAPID_PRIVATE_KEY=" + _b64url(escalar_privado))
