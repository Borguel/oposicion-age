"""Rutas de autenticación relacionadas con correos que Firebase mandaría por
su cuenta (sin marca, en inglés, y a menudo a spam) y que aquí se generan
con Firebase Admin pero se envían por Brevo con la imagen de la web:
recuperar contraseña (sin sesión) y verificar correo (con sesión, para
reenviar el propio correo de verificación)."""
import logging
import os
import re

from firebase_admin import auth as firebase_auth
from flask import Blueprint, jsonify, request

from auth_utils import obtener_identidad_desde_token
from email_utils import enviar_email_recuperar_contrasena, enviar_email_verificacion

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


@bp.route("/enviar-verificacion-email", methods=["POST"])
def enviar_verificacion_email():
    """Genera el enlace de verificación de correo con Firebase Admin y lo
    envía por Brevo. A diferencia de /recuperar-contrasena, esta sí exige
    sesión: solo tiene sentido para reenviar el propio correo, no para que
    cualquiera pida verificar una dirección ajena."""
    ident = obtener_identidad_desde_token(request)
    if not ident or not ident[0]:
        return jsonify({"error": "No autenticado"}), 401
    uid, email, _es_admin = ident
    if not email:
        return jsonify({"error": "Tu cuenta no tiene un correo asociado."}), 400

    try:
        usuario = firebase_auth.get_user(uid)
        if usuario.email_verified:
            return jsonify({"mensaje": "Ese correo ya está verificado."})
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8080")
        ajustes = firebase_auth.ActionCodeSettings(url=f"{frontend_url}/zona-opositor/", handle_code_in_app=False)
        enlace = firebase_auth.generate_email_verification_link(email, action_code_settings=ajustes)
    except Exception:
        logger.exception("Error generando el enlace de verificación de correo")
        return jsonify({"error": "No se pudo enviar el correo de verificación. Inténtalo de nuevo."}), 502

    enviar_email_verificacion(email, enlace, nombre=usuario.display_name or "")
    return jsonify({"mensaje": "Te hemos enviado un correo para verificar tu dirección."})
