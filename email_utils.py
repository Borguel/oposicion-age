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

from planes import DURACION_PRUEBA_DIAS

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
            "dias_prueba": DURACION_PRUEBA_DIAS,
        })
        return

    cuerpo = f"""
      <p style="margin:0;">{saludo}, gracias por registrarte.</p>
      <p>Para que puedas probarlo todo sin límites, hemos activado tu <strong>prueba
      gratuita de Premium de {DURACION_PRUEBA_DIAS} días</strong>: tests ilimitados
      del temario oficial, Tu Tutor IA y las herramientas de PDF (resúmenes,
      esquemas, tarjetas de memoria y tests a partir de tus propios documentos).</p>
      <p style="margin: 20px 0 8px; font-weight:700;">Para empezar con buen pie:</p>
      <ol style="margin:0 0 4px; padding-left:20px;">
        <li style="margin-bottom:8px;">Haz tu primer test del temario oficial desde tu Zona Opositor.</li>
        <li style="margin-bottom:8px;">Pregúntale a Tu Tutor cualquier duda del temario, como si fuera tu profesor particular.</li>
        <li>Sube un PDF tuyo (apuntes, un tema suelto) y saca de él un resumen, un esquema o un test.</li>
      </ol>
      {_boton("Empezar a estudiar", f"{frontend_url}/zona-opositor/")}
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


def enviar_email_verificacion(destinatario, enlace, nombre=""):
    """Correo con el enlace para verificar la dirección de correo (el enlace
    lo genera Firebase Admin; ver blueprints/auth_publico.py). Antes lo
    mandaba Firebase directamente desde el cliente con sendEmailVerification:
    llegaba en inglés, sin marca y desde noreply@<proyecto>.firebaseapp.com,
    un remitente que varios proveedores de correo (Gmail incluido) acaban
    marcando como spam."""
    saludo = f"Hola{f' {nombre}' if nombre else ''}"

    template_id = os.getenv("BREVO_TEMPLATE_VERIFICACION")
    if template_id:
        _enviar(destinatario, "verificación de correo", template_id=template_id, datos={
            "saludo": saludo,
            "enlace": enlace,
        })
        return

    cuerpo = f"""
      <p style="margin:0;">{saludo}, confirma tu dirección de correo para terminar de activar tu cuenta.</p>
      {_boton("Verificar mi correo", enlace)}
      {_aviso("Si no has creado tú esta cuenta, puedes ignorar este correo.")}
    """
    html = _plantilla_html("Verifica tu correo electrónico", cuerpo, emoji="✅")
    _enviar(destinatario, "verificación de correo", asunto="Verifica tu correo en Domina tu Opo", html=html)


_PARRAFO_POR_MOTIVO_BAJA = {
    # Coincide con MOTIVOS_BAJA_VALIDOS de blueprints/pagos.py. Sin ningún
    # motivo reconocido (o sin motivo, para llamadas antiguas) se usa el
    # mensaje de "otro": invitar a que nos cuenten qué ha fallado, sin dar
    # por hecho ningún motivo concreto.
    "aprobado": (
        "¡Enhorabuena por haber llegado hasta aquí! Te deseamos toda la suerte "
        "en tu proceso selectivo -- te lo has ganado."
    ),
    "precio": (
        "Si el precio ha sido el motivo, recuerda que también tenemos el plan "
        "Básico, con tests ilimitados a un precio más ajustado. Puedes cambiarte "
        "a él en cualquier momento antes de que termine tu acceso actual, desde tu cuenta."
    ),
    "no_lo_uso": (
        "Si te ha faltado tiempo más que ganas, tu cuenta y tu progreso seguirán "
        "aquí intactos por si te apetece retomarlo más adelante."
    ),
    "faltan_funciones": (
        "Si te ha faltado alguna función, nos ayuda muchísimo que nos cuentes cuál "
        "respondiendo a este correo -- lo tenemos en cuenta para mejorar."
    ),
    "otro": (
        "Si hay algo que podríamos haber hecho mejor, nos ayuda muchísimo que nos "
        "lo cuentes respondiendo a este correo."
    ),
}


def enviar_email_cancelacion_suscripcion(destinatario, oposicion_nombre, fecha_fin=None, nombre="", motivo=None):
    """Confirmación de que la baja se ha registrado -- se manda al aceptar
    /cancelar-suscripcion, no al webhook de Stripe (que llega días después,
    al final del periodo): el usuario debe saber YA que su baja ha quedado
    programada, con acceso hasta la fecha indicada. `motivo` es el que el
    propio usuario eligió al cancelar (ver MOTIVOS_BAJA_VALIDOS en
    blueprints/pagos.py); adapta el segundo párrafo a ese motivo en vez de
    dar el mismo mensaje genérico a quien aprobó que a quien se va por el precio."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8080")
    saludo = f"Hola{f' {nombre}' if nombre else ''}"
    linea_fecha = f" hasta el <strong>{fecha_fin}</strong>" if fecha_fin else ""
    parrafo_motivo = _PARRAFO_POR_MOTIVO_BAJA.get(motivo, _PARRAFO_POR_MOTIVO_BAJA["otro"])

    template_id = os.getenv("BREVO_TEMPLATE_CANCELACION")
    if template_id:
        _enviar(destinatario, "cancelación de suscripción", template_id=template_id, datos={
            "saludo": saludo,
            "oposicion_nombre": oposicion_nombre,
            "fecha_fin": fecha_fin or "",
            "frontend_url": frontend_url,
            "parrafo_motivo": parrafo_motivo,
        })
        return

    cuerpo = f"""
      <p style="margin:0;">{saludo}, confirmamos que hemos programado la baja de tu suscripción a
      <strong>{oposicion_nombre}</strong>.</p>
      <p>Seguirás teniendo acceso completo{linea_fecha}, sin ningún cobro adicional. Después,
      tu cuenta pasará al plan gratuito, pero tu progreso y tus datos se mantienen intactos.</p>
      <p>{parrafo_motivo}</p>
      <p>Si ha sido un error o cambias de opinión, puedes reactivarla en cualquier momento
      antes de esa fecha desde tu cuenta.</p>
      {_boton("Gestionar mi suscripción", f"{frontend_url}/mi-cuenta/")}
    """
    html = _plantilla_html("Tu suscripción se ha cancelado", cuerpo)
    _enviar(destinatario, "cancelación de suscripción", asunto="Confirmación de baja de tu suscripción", html=html)


def enviar_email_reactivacion_suscripcion(destinatario, oposicion_nombre, nombre=""):
    """Confirmación de que se ha deshecho una baja programada
    (/reactivar-suscripcion) -- la contrapartida de
    enviar_email_cancelacion_suscripcion: quien cambia de opinión antes de
    que la baja llegue a hacerse efectiva merece la misma confirmación
    explícita que quien se da de baja, no silencio."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8080")
    saludo = f"Hola{f' {nombre}' if nombre else ''}"

    template_id = os.getenv("BREVO_TEMPLATE_REACTIVACION")
    if template_id:
        _enviar(destinatario, "reactivación de suscripción", template_id=template_id, datos={
            "saludo": saludo,
            "oposicion_nombre": oposicion_nombre,
            "frontend_url": frontend_url,
        })
        return

    cuerpo = f"""
      <p style="margin:0;">{saludo}, confirmamos que hemos reactivado tu suscripción a
      <strong>{oposicion_nombre}</strong>.</p>
      <p>Se renovará con normalidad al final de tu periodo actual, sin ninguna interrupción
      de tu acceso. Gracias por seguir confiando en nosotros para tu preparación.</p>
      {_boton("Ir a mi cuenta", f"{frontend_url}/mi-cuenta/")}
    """
    html = _plantilla_html("Tu suscripción se ha reactivado", cuerpo, emoji="✅")
    _enviar(destinatario, "reactivación de suscripción", asunto="Tu suscripción sigue activa", html=html)


def enviar_email_pago_fallido(destinatario, oposicion_nombre, nombre=""):
    """Aviso de que Stripe no ha podido cobrar la renovación (webhook
    invoice.payment_failed) -- hasta ahora este evento solo marcaba
    subscription_status="past_due" en Firestore en silencio, sin que el
    usuario se enterase de nada hasta perder el acceso. Stripe reintenta el
    cobro automáticamente varias veces antes de darse por vencido y cancelar
    la suscripción del todo (customer.subscription.deleted), así que aquí
    solo se pide actualizar el método de pago a tiempo, no se anuncia
    ninguna pérdida de acceso inminente."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8080")
    saludo = f"Hola{f' {nombre}' if nombre else ''}"

    template_id = os.getenv("BREVO_TEMPLATE_PAGO_FALLIDO")
    if template_id:
        _enviar(destinatario, "pago fallido", template_id=template_id, datos={
            "saludo": saludo,
            "oposicion_nombre": oposicion_nombre,
            "frontend_url": frontend_url,
        })
        return

    cuerpo = f"""
      <p style="margin:0;">{saludo}, no hemos podido cobrar la renovación de tu suscripción a
      <strong>{oposicion_nombre}</strong>.</p>
      <p>Suele deberse a una tarjeta caducada, fondos insuficientes o un banco que ha bloqueado
      el cobro. Vamos a reintentarlo automáticamente en los próximos días, pero para no perder
      el acceso te recomendamos actualizar tu método de pago cuanto antes.</p>
      {_boton("Actualizar método de pago", f"{frontend_url}/mi-cuenta/")}
      {_aviso("Si ya has actualizado tu tarjeta, puedes ignorar este aviso: el próximo cobro se hará con normalidad.")}
    """
    html = _plantilla_html("No hemos podido cobrar tu suscripción", cuerpo, emoji="⚠️")
    _enviar(destinatario, "pago fallido", asunto=f"Problema con el pago de tu suscripción a {oposicion_nombre}", html=html)


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


def enviar_email_prueba_terminando(destinatario, dias_restantes, nombre=""):
    """Aviso de que quedan pocos días de la prueba gratuita Premium (ver
    planes.py): se envía una única vez, al cruzar los 2 días restantes."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8080")
    saludo = f"Hola{f' {nombre}' if nombre else ''}"
    dias_texto = f"{dias_restantes} día{'s' if dias_restantes != 1 else ''}"

    template_id = os.getenv("BREVO_TEMPLATE_PRUEBA_TERMINANDO")
    if template_id:
        _enviar(destinatario, "prueba terminando", template_id=template_id, datos={
            "saludo": saludo,
            "dias_restantes": dias_restantes,
            "dias_texto": dias_texto,
            "frontend_url": frontend_url,
        })
        return

    cuerpo = f"""
      <p style="margin:0;">{saludo}, tu prueba gratuita de Premium termina en <strong>{dias_texto}</strong>.</p>
      <p>Cuando termine, si no eliges un plan, perderás el acceso a las herramientas de PDF, a Tu Tutor
      y a los tests ya generados que sean de Premium. Elige ahora Básico o Premium para no perder nada.</p>
      {_boton("Ver planes", f"{frontend_url}/planes/")}
    """
    html = _plantilla_html(f"Tu prueba termina en {dias_texto}", cuerpo, emoji="⏳")
    _enviar(destinatario, "prueba terminando", asunto=f"Tu prueba gratuita termina en {dias_texto}", html=html)


def enviar_email_prueba_terminada(destinatario, nombre=""):
    """Aviso de que la prueba gratuita Premium ya ha terminado sin que el
    usuario haya contratado ningún plan: se envía el primer día tras
    expirar (ver blueprints/tareas_programadas.py)."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8080")
    saludo = f"Hola{f' {nombre}' if nombre else ''}"

    template_id = os.getenv("BREVO_TEMPLATE_PRUEBA_TERMINADA")
    if template_id:
        _enviar(destinatario, "prueba terminada", template_id=template_id, datos={
            "saludo": saludo,
            "frontend_url": frontend_url,
        })
        return

    cuerpo = f"""
      <p style="margin:0;">{saludo}, tu prueba gratuita de Premium ha terminado.</p>
      <p>Tu cuenta ha quedado bloqueada hasta que elijas un plan: tus datos y los tests que ya hiciste
      siguen a salvo y los recuperas en cuanto te suscribas a Básico o Premium.</p>
      {_boton("Elegir un plan", f"{frontend_url}/planes/")}
    """
    html = _plantilla_html("Tu prueba gratuita ha terminado", cuerpo, emoji="🔒")
    _enviar(destinatario, "prueba terminada", asunto="Tu prueba gratuita en Domina tu Opo ha terminado", html=html)


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


def enviar_email_aviso_oficial(destinatario, titulo, tipo_legible, url_boe, url_inap, oposicion_nombre, nombre=""):
    """Aviso de que se ha publicado algo oficial relevante (convocatoria,
    lista de admitidos, fecha de examen...) para una oposición concreta --
    ver vigilancia_boe.py + publicacion_estatica_boe.py. Se manda solo a
    quien ya tiene esa oposición entre sus suscripciones o su actividad."""
    saludo = f"Hola{f' {nombre}' if nombre else ''}"

    template_id = os.getenv("BREVO_TEMPLATE_AVISO_OFICIAL")
    if template_id:
        _enviar(destinatario, "aviso oficial", template_id=template_id, datos={
            "saludo": saludo,
            "titulo": titulo,
            "tipo_legible": tipo_legible,
            "url_boe": url_boe,
            "url_inap": url_inap,
            "oposicion_nombre": oposicion_nombre,
        })
        return

    # Sin URL no hay botón que valga -- un href="" solo parece un botón
    # roto ("no deja pinchar en nada"), así que mejor no mostrarlo.
    boton_resolucion = _boton("Ver la resolución oficial", url_boe) if url_boe else ""
    enlace_inap = (
        f'<p style="margin:14px 0 0; font-size:13.5px;"><a href="{url_inap}" style="color:{_COLOR_INK_SOFT};">Ver también en INAP →</a></p>'
        if url_inap else ""
    )
    cuerpo = f"""
      <p style="margin:0;">{saludo}, se ha publicado una novedad oficial para tu oposición
      (<strong>{oposicion_nombre}</strong>):</p>
      <p><strong>{tipo_legible}:</strong> {titulo}</p>
      {boton_resolucion}
      {enlace_inap}
    """
    html = _plantilla_html(f"{tipo_legible}: {oposicion_nombre}", cuerpo, emoji="📢")
    _enviar(destinatario, "aviso oficial", asunto=f"{tipo_legible} publicada para {oposicion_nombre}", html=html)


def enviar_email_alerta_coste_ia(destinatario, gasto_hoy, media_historica):
    """Aviso interno (no es un email de marca para un usuario) de que el
    gasto en IA de hoy se ha disparado respecto a la media reciente --
    posible abuso o bug, para enterarse antes de que llegue como sorpresa
    en la factura de DeepSeek (ver blueprints/tareas_programadas.py)."""
    cuerpo = f"""
      <p style="margin:0;">El gasto estimado en IA de hoy es de <strong>{gasto_hoy:.2f} €</strong>,
      muy por encima de la media reciente ({media_historica:.2f} €/día).</p>
      <p>Puede ser uso normal (más gente generando tests) o una señal de abuso/bug -- conviene
      echarle un vistazo al panel de administración.</p>
    """
    html = _plantilla_html("Pico de gasto en IA detectado", cuerpo, emoji="⚠️")
    _enviar(destinatario, "alerta de gasto en IA", asunto=f"⚠️ Pico de gasto en IA: {gasto_hoy:.2f} € hoy", html=html)
