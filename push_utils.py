"""Notificaciones push del navegador (Web Push + VAPID), en el mismo
estilo "no-op sin configurar" que ya usa sentry_utils.py -- si no hay
claves VAPID en el entorno, el resto de la app sigue funcionando igual,
simplemente no se envían pushes.

Generar el par de claves una sola vez (por ejemplo con
`vapid --gen`, del paquete py-vapid) y guardarlas como
VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY en el entorno de despliegue.
"""
import json
import logging
import os

from pywebpush import webpush, WebPushException

logger = logging.getLogger(__name__)

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "mailto:soporte@oposicion-age.com")


def push_disponible():
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)


def enviar_push(suscripcion, titulo, cuerpo, url="/zona-opositor/"):
    """Envía una notificación; devuelve False (sin lanzar) si no hay claves
    configuradas o si la suscripción ya no es válida (navegador desinstaló
    la PWA, permiso revocado, etc.) -- el llamador decide si eso implica
    borrar la suscripción guardada."""
    if not push_disponible():
        return False
    try:
        webpush(
            subscription_info=suscripcion,
            data=json.dumps({"title": titulo, "body": cuerpo, "url": url}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_CLAIMS_EMAIL},
        )
        return True
    except WebPushException as e:
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
