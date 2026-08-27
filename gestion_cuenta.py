"""Exportación y borrado de cuenta (derecho de acceso y de supresión del
RGPD): reúne en un solo sitio todas las subcolecciones propias de un
usuario, ya que Firestore no tiene "borrado en cascada" ni una forma nativa
de volcar un documento con sus subcolecciones."""
import logging
import os
from datetime import datetime

import stripe
from firebase_admin import auth as firebase_auth

import generacion_control
from email_utils import enviar_email_alerta_cancelacion_stripe_fallida
from planes import mejor_plan

logger = logging.getLogger(__name__)

# Subcolecciones que cuelgan de usuarios/{uid} en todo el proyecto (ver
# guardar_resultado.py, documentos_pdf.py, banco_fallos.py, banco_favoritas.py,
# blueprints/pagos.py). Bug real (24/08/2026): banco_preguntas_pdf,
# banco_tarjetas_pdf, preguntas_favoritas y bajas_motivos faltaban aquí --
# ni se exportaban (derecho de acceso incompleto) ni se borraban al
# eliminar la cuenta (derecho de supresión incompleto): quedaban huérfanas
# en Firestore para siempre, sin que ningún camino pudiera volver a
# alcanzarlas.
COLECCIONES_USUARIO = (
    "tests", "documentos", "resumenes_pdf", "esquemas_pdf", "tarjetas_pdf",
    "tests_pdf", "esquemas", "preguntas_falladas", "preguntas_favoritas",
    "banco_preguntas_pdf", "banco_tarjetas_pdf", "bajas_motivos",
)

# Colecciones a nivel RAÍZ (no cuelgan de usuarios/{uid}, así que no las
# cubre COLECCIONES_USUARIO) que también guardan datos personales de un
# usuario, cada una identificada por su propio nombre de campo. Bug real
# (25/08/2026, auditoría): mensajes_soporte (mensajes de "Contactar con
# soporte", con email y texto escrito por el usuario) y test_oficiales
# (contenido y respuestas de un examen oficial guardado) tampoco se
# exportaban ni se borraban -- mismo patrón que el bug ya arreglado el
# 24/08/2026 para las subcolecciones de arriba, quedaban huérfanas en
# Firestore para siempre sin que ningún camino pudiera volver a alcanzarlas.
COLECCIONES_RAIZ_USUARIO = (
    ("mensajes_soporte", "uid"),
    ("test_oficiales", "usuario_id"),
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

    # Las conversaciones de Tu Tutor NO cuelgan de usuarios/{uid} sino de una
    # colección propia a nivel raíz (ver chat_controller.py: crear_conversacion),
    # por eso se tratan aparte en vez de con COLECCIONES_USUARIO.
    conversaciones_ref = db.collection("conversaciones_IA").document(uid).collection("conversaciones")
    datos["conversaciones"] = [
        {"id": doc.id, **(doc.to_dict() or {})}
        for doc in conversaciones_ref.stream()
    ]

    for coleccion, campo_uid in COLECCIONES_RAIZ_USUARIO:
        datos[coleccion] = [
            {"id": doc.id, **(doc.to_dict() or {})}
            for doc in db.collection(coleccion).where(campo_uid, "==", uid).stream()
        ]
    return datos


def eliminar_cuenta_usuario(db, uid):
    """Cancela cualquier suscripción de Stripe activa, borra la cuenta de
    Firebase Auth y por último todas las subcolecciones y el documento del
    usuario en Firestore -- en ese orden. Si el borrado en Firebase Auth
    fallara por algo que no sea "ya no existe" (p. ej. un error transitorio
    de red), los datos de Firestore siguen intactos y un reintento puede
    completar el borrado sin dejar una cuenta de Auth huérfana con datos ya
    perdidos en Firestore.

    Deja además un registro en cuentas_eliminadas SIN ningún dato personal
    (25/08/2026, a petición del usuario: una cuenta desapareció del panel
    sin dejar ningún rastro, y no había forma de distinguir "el usuario se
    borró él mismo" de "algo falló") -- ni email, ni nombre, ni uid, solo
    la fecha y qué tenía contratado, para poder diferenciar una baja
    voluntaria real de cualquier otra cosa sin comprometer el derecho al
    olvido que es precisamente lo que esta función cumple."""
    usuario_ref = db.collection("usuarios").document(uid)
    usuario = usuario_ref.get().to_dict() or {}

    for datos_suscripcion in (usuario.get("suscripciones") or {}).values():
        subscription_id = datos_suscripcion.get("stripe_subscription_id")
        if not subscription_id:
            continue
        try:
            stripe.Subscription.delete(subscription_id)
        except Exception:
            # El borrado de la cuenta sigue adelante de todas formas (es un
            # derecho RGPD, no puede quedar bloqueado por un fallo
            # transitorio de un tercero) -- pero sin más que este log, la
            # suscripción podía quedar cobrando indefinidamente a una cuenta
            # que ya no existe, sin que nadie se enterase hasta que Stripe
            # avisara de un impago meses después. Un email directo al dueño
            # es la señal que de verdad se atiende, no solo el log/Sentry.
            logger.exception("Error cancelando suscripción de Stripe %s al borrar la cuenta %s", subscription_id, uid)
            destinatario_alerta = os.getenv("ADMIN_ALERT_EMAIL") or os.getenv("BREVO_FROM_EMAIL")
            enviar_email_alerta_cancelacion_stripe_fallida(destinatario_alerta, uid, subscription_id)

    try:
        firebase_auth.delete_user(uid)
    except firebase_auth.UserNotFoundError:
        pass

    # Bug real (24/08/2026): si el usuario tenía una generación en curso
    # (resumen/esquema/banco de preguntas o tarjetas) al borrar la cuenta,
    # el hilo de fondo seguía gastando llamadas a DeepSeek (ya cobradas por
    # adelantado, ver reservar_uso) sobre una cuenta que ya no existe --
    # mismo mecanismo que ya usan eliminar_documento_route y el webhook de
    # Stripe al perder el acceso (ver generacion_control.py).
    generacion_control.solicitar_parada_todas(uid)

    for coleccion in COLECCIONES_USUARIO:
        for doc in usuario_ref.collection(coleccion).stream():
            doc.reference.delete()

    conversaciones_ref = db.collection("conversaciones_IA").document(uid).collection("conversaciones")
    for doc in conversaciones_ref.stream():
        doc.reference.delete()
    db.collection("conversaciones_IA").document(uid).delete()

    for coleccion, campo_uid in COLECCIONES_RAIZ_USUARIO:
        for doc in db.collection(coleccion).where(campo_uid, "==", uid).stream():
            doc.reference.delete()

    usuario_ref.delete()

    try:
        suscripciones = usuario.get("suscripciones") or {}
        plan_mas_alto, _ = mejor_plan(suscripciones)
        db.collection("cuentas_eliminadas").document().set({
            "fecha": datetime.utcnow().isoformat(),
            "oposiciones": list(suscripciones.keys()),
            "plan_mas_alto": plan_mas_alto,
            "tenia_suscripcion_activa": any(
                (sub or {}).get("subscription_status") in ("active", "trialing")
                for sub in suscripciones.values()
            ),
        })
    except Exception:
        # Nunca debe romper el borrado -- es un registro informativo, no
        # parte del derecho de supresión en sí.
        logger.warning("No se pudo registrar la baja de cuenta en cuentas_eliminadas", exc_info=True)
