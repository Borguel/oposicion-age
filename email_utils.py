"""Envío de correos transaccionales (bienvenida, recuperar contraseña,
cancelación de suscripción, avisos de racha...) usando la API transaccional
de Brevo. Si BREVO_API_KEY no está configurada, o el envío falla, no se
lanza ninguna excepción hacia quien llama: ninguna acción del usuario
(registro, cancelar suscripción, pedir un reset...) debe romperse porque un
email no se haya podido enviar.

Cada correo se manda por una plantilla de Brevo (Campañas -> Plantillas ->
Transaccional; el diseño se edita ahí sin tocar código) si su variable de
entorno BREVO_TEMPLATE_* está configurada (con el ID numérico de la
plantilla); si no, cae al HTML de reserva definido aquí mismo, para que el
envío nunca dependa de haber montado ya las plantillas en Brevo."""
import logging
import os
import requests

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _remitente():
    return {
        "email": os.getenv("BREVO_FROM_EMAIL", "no-reply@dominatuopo.com"),
        "name": os.getenv("BREVO_FROM_NOMBRE", "Domina tu Opo"),
    }


def _enviar(destinatario, motivo, *, asunto=None, html=None, template_id=None, datos=None):
    if not destinatario:
        return
    api_key = os.getenv("BREVO_API_KEY")
    if not api_key:
        logger.warning("BREVO_API_KEY no configurada: no se envía email de %s", motivo)
        return

    payload = {"sender": _remitente(), "to": [{"email": destinatario}]}
    if template_id:
        payload["templateId"] = int(template_id)
        payload["params"] = datos or {}
    else:
        payload["subject"] = asunto
        payload["htmlContent"] = html

    headers = {"api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"}
    try:
        respuesta = requests.post(BREVO_API_URL, headers=headers, json=payload, timeout=10)
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


def _plantilla_html(titulo, cuerpo_html, *, pie_extra=""):
    """Envoltorio común (mismo look en los seis correos) para no repetir el
    encabezado/pie en cada función de envío."""
    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 560px; margin: 0 auto; color: #1b1f2e;">
      <h2 style="color: #1b1f2e; margin-bottom: 4px;">{titulo}</h2>
      {cuerpo_html}
      <p style="margin-top: 32px; font-size: 13px; color: #666; border-top: 1px solid #e5e5e5; padding-top: 16px;">
        Domina tu Opo · dominatuopo.com{pie_extra}
      </p>
    </div>
    """


def enviar_email_bienvenida(destinatario, nombre=""):
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8080")
    saludo = f"Hola{f' {nombre}' if nombre else ''}"

    template_id = os.getenv("BREVO_TEMPLATE_BIENVENIDA")
    if template_id:
        _enviar(destinatario, "bienvenida", template_id=template_id, datos={
            "saludo": saludo,
            "frontend_url": frontend_url,
        })
        return

    cuerpo = f"""
      <p>{saludo}, gracias por registrarte.</p>
      <p>Ya puedes empezar a preparar tu oposición con tests del temario oficial,
      seguimiento de tu progreso por temas y nuestras herramientas de IA para
      generar tests, resúmenes, esquemas y tarjetas de memoria a partir de tus
      propios documentos.</p>
      {_boton("Empezar a estudiar", frontend_url)}
      <p style="margin-top: 20px; font-size: 13px; color: #666;">
        Si no has creado tú esta cuenta, puedes ignorar este correo.
      </p>
    """
    html = _plantilla_html("¡Bienvenido/a a Domina tu Opo!", cuerpo)
    _enviar(destinatario, "bienvenida", asunto="Bienvenido/a a Domina tu Opo", html=html)


def enviar_email_recuperar_contrasena(destinatario, enlace, nombre=""):
    """Correo con el enlace de restablecimiento de contraseña (el enlace lo
    genera Firebase Admin; ver blueprints/auth_publico.py). El enlace ya
    caduca solo (lo controla Firebase), así que aquí no hay que gestionar
    expiración."""
    saludo = f"Hola{f' {nombre}' if nombre else ''}"

    template_id = os.getenv("BREVO_TEMPLATE_RESET_PASSWORD")
    if template_id:
        _enviar(destinatario, "recuperar contraseña", template_id=template_id, datos={
            "saludo": saludo,
            "enlace": enlace,
        })
        return

    cuerpo = f"""
      <p>{saludo}, hemos recibido una solicitud para restablecer la contraseña de tu cuenta.</p>
      {_boton("Restablecer mi contraseña", enlace)}
      <p style="margin-top: 20px; font-size: 13px; color: #666;">
        Si no has pedido tú este cambio, puedes ignorar este correo: tu contraseña seguirá siendo la misma.
        Por seguridad, este enlace caduca pasado un tiempo.
      </p>
    """
    html = _plantilla_html("Restablece tu contraseña", cuerpo)
    _enviar(destinatario, "recuperar contraseña", asunto="Restablece tu contraseña de Domina tu Opo", html=html)


def enviar_email_cancelacion_suscripcion(destinatario, oposicion_nombre, fecha_fin=None, nombre=""):
    """Confirmación de que la baja se ha registrado -- se manda al aceptar
    /cancelar-suscripcion, no al webhook de Stripe (que llega días después,
    al final del periodo): el usuario debe saber YA que su baja ha quedado
    programada, con acceso hasta la fecha indicada."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8080")
    saludo = f"Hola{f' {nombre}' if nombre else ''}"
    linea_fecha = f" hasta el <strong>{fecha_fin}</strong>" if fecha_fin else ""

    template_id = os.getenv("BREVO_TEMPLATE_CANCELACION")
    if template_id:
        _enviar(destinatario, "cancelación de suscripción", template_id=template_id, datos={
            "saludo": saludo,
            "oposicion_nombre": oposicion_nombre,
            "fecha_fin": fecha_fin or "",
            "frontend_url": frontend_url,
        })
        return

    cuerpo = f"""
      <p>{saludo}, confirmamos que hemos programado la baja de tu suscripción a
      <strong>{oposicion_nombre}</strong>.</p>
      <p>Seguirás teniendo acceso completo{linea_fecha}, sin ningún cobro adicional. Después,
      tu cuenta pasará al plan gratuito, pero tu progreso y tus datos se mantienen intactos.</p>
      <p>Si ha sido un error o cambias de opinión, puedes reactivarla en cualquier momento
      antes de esa fecha desde tu cuenta.</p>
      {_boton("Gestionar mi suscripción", f"{frontend_url}/mi-cuenta/")}
    """
    html = _plantilla_html("Tu suscripción se ha cancelado", cuerpo)
    _enviar(destinatario, "cancelación de suscripción", asunto="Confirmación de baja de tu suscripción", html=html)


def enviar_email_racha_en_riesgo(destinatario, racha_actual, nombre=""):
    """Aviso de que la racha de estudio se rompe hoy si no se hace nada:
    se envía a quien estudió ayer pero todavía no hoy."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8080")
    saludo = f"Hola{f' {nombre}' if nombre else ''}"
    racha_dias_texto = f"{racha_actual} día{'s' if racha_actual != 1 else ''}"

    template_id = os.getenv("BREVO_TEMPLATE_RACHA_RIESGO")
    if template_id:
        _enviar(destinatario, "racha en riesgo", template_id=template_id, datos={
            "saludo": saludo,
            "racha_actual": racha_actual,
            "racha_dias_texto": racha_dias_texto,
            "frontend_url": frontend_url,
        })
        return

    cuerpo = f"""
      <p>{saludo}, todavía no has estudiado hoy. Un test corto basta para mantener viva tu racha.</p>
      {_boton("Hacer un test rápido", f"{frontend_url}/zona-opositor/")}
    """
    html = _plantilla_html(f"🔥 Tu racha de {racha_dias_texto} está en juego", cuerpo)
    _enviar(destinatario, "racha en riesgo", asunto=f"No pierdas tu racha de {racha_dias_texto}", html=html)


def enviar_email_reengagement(destinatario, dias_inactivo, nombre=""):
    """Aviso para quien lleva varios días sin actividad y ya perdió la
    racha, para intentar que retome la preparación."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8080")
    saludo = f"Hola{f' {nombre}' if nombre else ''}"

    template_id = os.getenv("BREVO_TEMPLATE_REENGAGEMENT")
    if template_id:
        _enviar(destinatario, "reengagement", template_id=template_id, datos={
            "saludo": saludo,
            "dias_inactivo": dias_inactivo,
            "frontend_url": frontend_url,
        })
        return

    cuerpo = f"""
      <p>{saludo}, tu preparación te está esperando. Retómalo con un test corto o repasa tus temas flojos en las estadísticas.</p>
      {_boton("Volver a estudiar", f"{frontend_url}/zona-opositor/")}
    """
    html = _plantilla_html(f"Llevas {dias_inactivo} días sin estudiar", cuerpo)
    _enviar(destinatario, "reengagement", asunto="Retoma tu preparación de la oposición", html=html)
