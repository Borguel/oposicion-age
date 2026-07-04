"""Envío de correos transaccionales (bienvenida + recordatorio de racha)
usando la API de SendGrid. Si SENDGRID_API_KEY no está configurada, o el
envío falla, no se lanza ninguna excepción hacia quien llama: ninguna
acción del usuario (registro, guardado de progreso...) debe romperse
porque un email no se haya podido enviar."""
import logging
import os
import requests

logger = logging.getLogger(__name__)

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


def _remitente():
    return {
        "email": os.getenv("SENDGRID_FROM_EMAIL", "no-reply@oposicion-age.com"),
        "name": "Oposición AGE",
    }


def _enviar(destinatario, asunto, html, motivo):
    if not destinatario:
        return
    api_key = os.getenv("SENDGRID_API_KEY")
    if not api_key:
        logger.warning("SENDGRID_API_KEY no configurada: no se envía email de %s", motivo)
        return

    payload = {
        "personalizations": [{"to": [{"email": destinatario}]}],
        "from": _remitente(),
        "subject": asunto,
        "content": [{"type": "text/html", "value": html}],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        respuesta = requests.post(SENDGRID_API_URL, headers=headers, json=payload, timeout=10)
        if respuesta.status_code >= 300:
            logger.warning("Error enviando email de %s (%s): %s", motivo, respuesta.status_code, respuesta.text[:300])
    except Exception:
        logger.exception("Excepción enviando email de %s", motivo)


def _boton(texto, url):
    return f"""
    <p style="margin-top: 24px;">
      <a href="{url}"
         style="background:#FFA633;color:#1b1f2e;padding:12px 22px;border-radius:8px;
                text-decoration:none;font-weight:bold;display:inline-block;">
        {texto}
      </a>
    </p>
    """


def enviar_email_bienvenida(destinatario, nombre=""):
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8080")
    saludo = f"Hola{f' {nombre}' if nombre else ''}"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 560px; margin: 0 auto; color: #1b1f2e;">
      <h2 style="color: #1b1f2e;">¡Bienvenido/a a Oposición AGE!</h2>
      <p>{saludo}, gracias por registrarte.</p>
      <p>Ya puedes empezar a preparar tu oposición con tests del temario oficial,
      seguimiento de tu progreso por temas y nuestras herramientas de IA para
      generar tests, resúmenes, esquemas y tarjetas de memoria a partir de tus
      propios documentos.</p>
      {_boton("Empezar a estudiar", frontend_url)}
      <p style="margin-top: 32px; font-size: 13px; color: #666;">
        Si no has creado tú esta cuenta, puedes ignorar este correo.
      </p>
    </div>
    """
    _enviar(destinatario, "Bienvenido/a a Oposición AGE", html, motivo="bienvenida")


def enviar_email_racha_en_riesgo(destinatario, racha_actual, nombre=""):
    """Aviso de que la racha de estudio se rompe hoy si no se hace nada:
    se envía a quien estudió ayer pero todavía no hoy."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8080")
    saludo = f"Hola{f' {nombre}' if nombre else ''}"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 560px; margin: 0 auto; color: #1b1f2e;">
      <h2 style="color: #1b1f2e;">🔥 Tu racha de {racha_actual} día{'s' if racha_actual != 1 else ''} está en juego</h2>
      <p>{saludo}, todavía no has estudiado hoy. Un test corto basta para mantener viva tu racha.</p>
      {_boton("Hacer un test rápido", f"{frontend_url}/zona-opositor/")}
    </div>
    """
    _enviar(destinatario, f"No pierdas tu racha de {racha_actual} días", html, motivo="racha en riesgo")


def enviar_email_reengagement(destinatario, dias_inactivo, nombre=""):
    """Aviso para quien lleva varios días sin actividad y ya perdió la
    racha, para intentar que retome la preparación."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8080")
    saludo = f"Hola{f' {nombre}' if nombre else ''}"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 560px; margin: 0 auto; color: #1b1f2e;">
      <h2 style="color: #1b1f2e;">Llevas {dias_inactivo} días sin estudiar</h2>
      <p>{saludo}, tu preparación te está esperando. Retómalo con un test corto o repasa tus temas flojos en las estadísticas.</p>
      {_boton("Volver a estudiar", f"{frontend_url}/zona-opositor/")}
    </div>
    """
    _enviar(destinatario, "Retoma tu preparación de la oposición", html, motivo="reengagement")
