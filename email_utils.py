"""Envío de correos transaccionales (por ahora, solo el de bienvenida al
registrarse) usando la API de SendGrid. Si SENDGRID_API_KEY no está
configurada, o el envío falla, no se lanza ninguna excepción hacia quien
llama: el registro del usuario nunca debe romperse porque el email de
bienvenida no se haya podido enviar."""
import os
import requests

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


def _remitente():
    return {
        "email": os.getenv("SENDGRID_FROM_EMAIL", "no-reply@oposicion-age.com"),
        "name": "Oposición AGE",
    }


def enviar_email_bienvenida(destinatario, nombre=""):
    if not destinatario:
        return
    api_key = os.getenv("SENDGRID_API_KEY")
    if not api_key:
        print("⚠️ SENDGRID_API_KEY no configurada: no se envía email de bienvenida")
        return

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
      <p style="margin-top: 24px;">
        <a href="{frontend_url}"
           style="background:#FFA633;color:#1b1f2e;padding:12px 22px;border-radius:8px;
                  text-decoration:none;font-weight:bold;display:inline-block;">
          Empezar a estudiar
        </a>
      </p>
      <p style="margin-top: 32px; font-size: 13px; color: #666;">
        Si no has creado tú esta cuenta, puedes ignorar este correo.
      </p>
    </div>
    """

    payload = {
        "personalizations": [{"to": [{"email": destinatario}]}],
        "from": _remitente(),
        "subject": "Bienvenido/a a Oposición AGE",
        "content": [{"type": "text/html", "value": html}],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        respuesta = requests.post(SENDGRID_API_URL, headers=headers, json=payload, timeout=10)
        if respuesta.status_code >= 300:
            print(f"⚠️ Error enviando email de bienvenida ({respuesta.status_code}): {respuesta.text[:300]}")
    except Exception as e:
        print(f"⚠️ Excepción enviando email de bienvenida: {e}")
