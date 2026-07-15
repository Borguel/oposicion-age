"""Envío de correos transaccionales (bienvenida, recuperar contraseña,
cancelación de suscripción, avisos de racha...) usando la API transaccional
de Brevo. Si BREVO_API_KEY no está configurada, o el envío falla, no se
lanza ninguna excepción hacia quien llama: ninguna acción del usuario
(registro, cancelar suscripción, pedir un reset...) debe romperse porque un
email no se haya podido enviar.

Cada correo se manda por una plantilla de Brevo (Campañas -> Plantillas ->
Transaccional; el diseño se edita ahí sin tocar código) si su variable de
entorno BREVO_TEMPLATE_* está configurada (con el ID numérico de la
plantilla); si no, cae al HTML de reserva definido aquí mismo (_plantilla_html),
con la misma imagen de marca que el resto de la web (colores y logo de
theme.css/favicon), para que el envío nunca dependa de haber montado ya las
plantillas en Brevo."""
import logging
import os
import requests

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"

# Paleta de marca (idéntica a las variables --age-* de frontend/assets/theme.css,
# modo claro -- el correo siempre se manda en claro: no todos los clientes de
# email respetan prefers-color-scheme, y un fondo oscuro mal soportado es
# ilegible en más sitios de los que ayuda).
_COLOR_NAVY = "#1b1f2e"
_COLOR_PRIMARY = "#ffa633"
_COLOR_INK = "#16181d"
_COLOR_INK_SOFT = "#6b7280"
_COLOR_BG = "#f6f7f9"


def _remitente():
    return {
        "email": os.getenv("BREVO_FROM_EMAIL", "dominatuopo@gmail.com"),
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


def _url_logo():
    # El mismo icono que el favicon/la marca de la barra de navegación
    # (frontend/assets/favicon-192.png), servido por el propio frontend.
    # Se usa el PNG (no el SVG del favicon) porque Outlook de escritorio no
    # renderiza SVG en <img>, y el PNG sí funciona en todos los clientes.
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8080")
    return f"{frontend_url}/assets/favicon-192.png"


def _boton(texto, url):
    # Mismo estilo que .age-btn-primary en theme.css (fondo naranja, texto
    # marino, esquinas de 10px, negrita) -- en tabla en vez de en el propio
    # <a>, porque Outlook de escritorio (motor Word) ignora border-radius en
    # elementos inline y así al menos el fondo sí queda como un botón.
    return f"""
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin: 26px 0 6px;">
      <tr>
        <td style="background:{_COLOR_PRIMARY}; border-radius:10px;">
          <a href="{url}"
             style="display:inline-block; padding:13px 26px; font-family:Arial,Helvetica,sans-serif;
                    font-size:15px; font-weight:700; color:{_COLOR_NAVY}; text-decoration:none;">
            {texto}
          </a>
        </td>
      </tr>
    </table>
    """


def _aviso(texto):
    """Línea secundaria en gris, más pequeña -- para las notas de "si no has
    sido tú, ignora este correo" y similares."""
    return f"""
      <p style="margin: 20px 0 0; font-size: 13px; line-height: 1.6; color: {_COLOR_INK_SOFT};">
        {texto}
      </p>
    """


def _plantilla_html(titulo, cuerpo_html, *, emoji=""):
    """Envoltorio común de marca para los seis correos: cabecera marino con
    el logo y el nombre, tarjeta blanca con el contenido, pie de página.
    Maquetado con tablas y estilos inline (en vez de CSS en <style> o
    flexbox/grid) porque es lo único que se renderiza de forma fiable en
    todos los clientes de correo, incluido Outlook de escritorio."""
    logo = _url_logo()
    titulo_completo = f"{emoji} {titulo}" if emoji else titulo
    return f"""<!DOCTYPE html>
<html lang="es">
  <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
  <body style="margin:0; padding:0; background:{_COLOR_BG};">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_COLOR_BG};">
      <tr>
        <td align="center" style="padding: 32px 16px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px; font-family: Arial, Helvetica, sans-serif;">
            <tr>
              <td style="background:{_COLOR_NAVY}; border-radius:20px 20px 0 0; padding:22px 32px; text-align:center;">
                <img src="{logo}" width="36" height="36" alt="" style="display:inline-block; vertical-align:middle; border-radius:8px;">
                <span style="display:inline-block; vertical-align:middle; margin-left:10px; color:#ffffff; font-size:17px; font-weight:700;">Domina tu Opo</span>
              </td>
            </tr>
            <tr>
              <td style="background:#ffffff; padding:36px 32px; border-radius:0 0 20px 20px; box-shadow: 0 6px 20px rgba(20,24,34,0.06);">
                <h1 style="margin:0 0 16px; color:{_COLOR_NAVY}; font-size:21px; font-weight:800; line-height:1.3;">{titulo_completo}</h1>
                <div style="color:{_COLOR_INK}; font-size:15px; line-height:1.65;">
                  {cuerpo_html}
                </div>
              </td>
            </tr>
            <tr>
              <td style="text-align:center; padding:20px 12px; color:#9aa0ac; font-size:12px; font-family: Arial, Helvetica, sans-serif;">
                Domina tu Opo &middot; dominatuopo.com
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


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
      <p style="margin:0;">{saludo}, gracias por registrarte.</p>
      <p>Ya puedes empezar a preparar tu oposición con tests del temario oficial,
      seguimiento de tu progreso por temas y nuestras herramientas de IA para
      generar tests, resúmenes, esquemas y tarjetas de memoria a partir de tus
      propios documentos.</p>
      {_boton("Empezar a estudiar", frontend_url)}
      {_aviso("Si no has creado tú esta cuenta, puedes ignorar este correo.")}
    """
    html = _plantilla_html("¡Bienvenido/a a Domina tu Opo!", cuerpo, emoji="🎉")
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
      <p style="margin:0;">{saludo}, hemos recibido una solicitud para restablecer la contraseña de tu cuenta.</p>
      {_boton("Restablecer mi contraseña", enlace)}
      {_aviso("Si no has pedido tú este cambio, puedes ignorar este correo: tu contraseña seguirá siendo la misma. "
              "Por seguridad, este enlace caduca pasado un tiempo.")}
    """
    html = _plantilla_html("Restablece tu contraseña", cuerpo, emoji="🔑")
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
      <p style="margin:0;">{saludo}, confirmamos que hemos programado la baja de tu suscripción a
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
      <p style="margin:0;">{saludo}, todavía no has estudiado hoy. Un test corto basta para mantener viva tu racha.</p>
      {_boton("Hacer un test rápido", f"{frontend_url}/zona-opositor/")}
    """
    html = _plantilla_html(f"Tu racha de {racha_dias_texto} está en juego", cuerpo, emoji="🔥")
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
      <p style="margin:0;">{saludo}, tu preparación te está esperando. Retómalo con un test corto o repasa tus temas flojos en las estadísticas.</p>
      {_boton("Volver a estudiar", f"{frontend_url}/zona-opositor/")}
    """
    html = _plantilla_html(f"Llevas {dias_inactivo} días sin estudiar", cuerpo, emoji="📚")
    _enviar(destinatario, "reengagement", asunto="Retoma tu preparación de la oposición", html=html)
