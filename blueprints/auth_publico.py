"""Rutas de autenticación que NO requieren sesión. Viven aparte del resto
porque son las únicas del backend pensadas para alguien que todavía no está
logueado (recuperar contraseña)."""
import logging
import os
import re

from firebase_admin import auth as firebase_auth
from flask import Blueprint, jsonify, request

from email_utils import enviar_email_recuperar_contrasena

logger = logging.getLogger(__name__)

bp = Blueprint("auth_publico", __name__)

_PATRON_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.route("/recuperar-contrasena", methods=["POST"])
def recuperar_contrasena():
    """Genera el enlace de restablecimiento de contraseña con Firebase Admin
    y lo envía por Brevo (antes lo mandaba Firebase directamente desde el
    cliente con sendPasswordResetEmail; ahora pasa por aquí para que tenga la
    misma imagen de marca que el resto de correos transaccionales).

    Por seguridad SIEMPRE responde con el mismo mensaje, exista o no ese
    email entre los usuarios registrados -- igual que hacía antes el
    comportamiento de Firebase -- así nadie puede usar esta ruta para
    averiguar qué correos están dados de alta."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    respuesta_generica = jsonify({
        "mensaje": "Si ese correo está registrado, recibirás un enlace para restablecer tu contraseña."
    })

    if not email or not _PATRON_EMAIL.match(email):
        return respuesta_generica

    try:
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8080")
        ajustes = firebase_auth.ActionCodeSettings(url=f"{frontend_url}/login/", handle_code_in_app=False)
        enlace = firebase_auth.generate_password_reset_link(email, action_code_settings=ajustes)
    except firebase_auth.UserNotFoundError:
        return respuesta_generica
    except Exception:
        logger.exception("Error generando el enlace de restablecimiento de contraseña")
        return respuesta_generica

    enviar_email_recuperar_contrasena(email, enlace)
    return respuesta_generica
