"""Dominios de correo desechable/temporal conocidos: una cuenta creada con
uno de ellos no recibe la prueba gratuita de 7 días (ver
registro_progreso_usuario.inicializar_estadisticas_usuario) -- el objetivo
no es impedir el registro en sí (el email en última instancia lo crea
Firebase, no nosotros), sino que farmear cuentas para conseguir acceso
Premium gratis deje de ser gratis: haría falta un dominio propio.

No pretende ser una lista exhaustiva (nacen servicios nuevos constantemente),
solo cubrir los proveedores de "correo de usar y tirar" más conocidos y de
mayor volumen."""

DOMINIOS_DESECHABLES = {
    "mailinator.com", "10minutemail.com", "10minutemail.net", "guerrillamail.com",
    "guerrillamail.info", "guerrillamail.biz", "guerrillamail.de", "guerrillamail.org",
    "temp-mail.org", "temp-mail.io", "tempmail.com", "throwawaymail.com",
    "yopmail.com", "yopmail.fr", "yopmail.net", "trashmail.com", "getnada.com",
    "maildrop.cc", "dispostable.com", "fakeinbox.com", "mintemail.com",
    "sharklasers.com", "spamgourmet.com", "mailnesia.com", "moakt.com",
    "emailondeck.com", "mohmal.com", "tempinbox.com", "mail-temporaire.fr",
    "burnermail.io", "1secmail.com", "discard.email", "spambog.com",
    "mailcatch.com", "correotemporal.org", "einrot.com", "mytemp.email",
}


def es_dominio_email_desechable(email):
    """True si el dominio del email está en la lista conocida de correo
    desechable/temporal. Comparación insensible a mayúsculas; un email sin
    "@" (o vacío/None) se trata como NO desechable -- no es este el sitio
    para validar el formato del email, solo para detectar dominios
    conocidos."""
    if not email or "@" not in email:
        return False
    dominio = email.rsplit("@", 1)[-1].strip().lower()
    return dominio in DOMINIOS_DESECHABLES
