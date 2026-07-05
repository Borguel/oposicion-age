"""Exportación y borrado de cuenta (derecho de acceso y de supresión del
RGPD): reúne en un solo sitio todas las subcolecciones propias de un
usuario, ya que Firestore no tiene "borrado en cascada" ni una forma nativa
de volcar un documento con sus subcolecciones."""
import logging

import stripe
from firebase_admin import auth as firebase_auth

logger = logging.getLogger(__name__)

# Subcolecciones que cuelgan de usuarios/{uid} en todo el proyecto (ver
# guardar_resultado.py, documentos_pdf.py, banco_fallos.py, chat_controller.py).
COLECCIONES_USUARIO = (
    "tests", "documentos", "resumenes_pdf", "esquemas_pdf", "tarjetas_pdf",
    "tests_pdf", "esquemas", "preguntas_falladas", "conversaciones",
)


def exportar_datos_usuario(db, uid):
    """Todo lo que Firestore tiene guardado de este usuario, en un único
    JSON descargable (derecho de acceso/portabilidad)."""
    usuario_ref = db.collection("usuarios").document(uid)
    perfil = usuario_ref.get().to_dict() or {}

    datos = {"perfil": perfil}
    for coleccion in COLECCIONES_USUARIO:
        datos[coleccion] = [
            {"id": doc.id, **(doc.to_dict() or {})}
            for doc in usuario_ref.collection(coleccion).stream()
        ]
    return datos


def eliminar_cuenta_usuario(db, uid):
    """Cancela cualquier suscripción de Stripe activa, borra todas las
    subcolecciones y el documento del usuario, y por último la cuenta de
    Firebase Auth -- en ese orden, para poder seguir leyendo sus datos
    (p. ej. el id de suscripción) mientras todavía hacen falta."""
    usuario_ref = db.collection("usuarios").document(uid)
    usuario = usuario_ref.get().to_dict() or {}

    for datos_suscripcion in (usuario.get("suscripciones") or {}).values():
        subscription_id = datos_suscripcion.get("stripe_subscription_id")
        if not subscription_id:
            continue
        try:
            stripe.Subscription.delete(subscription_id)
        except Exception:
            logger.exception("Error cancelando suscripción de Stripe %s al borrar la cuenta %s", subscription_id, uid)

    for coleccion in COLECCIONES_USUARIO:
        for doc in usuario_ref.collection(coleccion).stream():
            doc.reference.delete()

    usuario_ref.delete()

    try:
        firebase_auth.delete_user(uid)
    except firebase_auth.UserNotFoundError:
        pass
