"""Pruebas de email_utils.py: la integración con la API transaccional de
Brevo. Se mockea requests.post -- lo que se comprueba es que cada función
arma el payload correcto (plantilla vs HTML de reserva) y que un fallo de
red o de configuración nunca se propaga hacia quien llama (ninguna acción
del usuario debe romperse porque un email no se haya podido enviar)."""
from unittest.mock import MagicMock, patch

import email_utils


def _respuesta_ok():
    mock = MagicMock()
    mock.status_code = 201
    mock.text = ""
    return mock


def test_sin_api_key_no_llama_a_requests(monkeypatch):
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    with patch("email_utils.requests.post") as mock_post:
        email_utils.enviar_email_bienvenida("u@example.com")
    mock_post.assert_not_called()


def test_sin_destinatario_no_llama_a_requests(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    with patch("email_utils.requests.post") as mock_post:
        email_utils.enviar_email_bienvenida("")
    mock_post.assert_not_called()


def test_bienvenida_manda_html_de_reserva_sin_plantilla(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_BIENVENIDA", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_bienvenida("u@example.com", nombre="Ana")

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["api-key"] == "clave"
    payload = kwargs["json"]
    assert payload["to"] == [{"email": "u@example.com"}]
    assert "templateId" not in payload
    assert "Ana" in payload["htmlContent"]
    assert payload["subject"]


def test_bienvenida_escapa_html_del_nombre_en_el_saludo(monkeypatch):
    # nombre viene de un campo que el propio usuario controla (ver
    # validacion_perfil.py, que ya restringe el campo a letras/espacios en
    # /registrar-usuario) -- pero el saludo se interpola directo en el HTML
    # del correo, así que escapar aquí también es defensa en profundidad
    # por si algún día se añade otra vía de escritura sin esa validación.
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_BIENVENIDA", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_bienvenida("u@example.com", nombre="<img src=x onerror=alert(1)>")

    payload = mock_post.call_args.kwargs["json"]
    assert "onerror=alert(1)>" not in payload["htmlContent"]
    assert "&lt;img src=x onerror=alert(1)&gt;" in payload["htmlContent"]


def test_bienvenida_usa_plantilla_de_brevo_si_esta_configurada(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.setenv("BREVO_TEMPLATE_BIENVENIDA", "42")
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_bienvenida("u@example.com", nombre="Ana")

    payload = mock_post.call_args.kwargs["json"]
    assert payload["templateId"] == 42
    assert payload["params"]["saludo"] == "Hola Ana"
    assert "subject" not in payload


def test_recuperar_contrasena_incluye_el_enlace(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_RESET_PASSWORD", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_recuperar_contrasena("u@example.com", "https://dominatuopo.com/reset?oobCode=x")

    payload = mock_post.call_args.kwargs["json"]
    assert "https://dominatuopo.com/reset?oobCode=x" in payload["htmlContent"]


def test_verificacion_email_incluye_el_enlace(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_VERIFICACION", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_verificacion("u@example.com", "https://dominatuopo.com/__/auth/action?mode=verifyEmail")

    payload = mock_post.call_args.kwargs["json"]
    assert "https://dominatuopo.com/__/auth/action?mode=verifyEmail" in payload["htmlContent"]
    assert payload["to"] == [{"email": "u@example.com"}]


def test_cancelacion_suscripcion_incluye_oposicion_y_fecha(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_CANCELACION", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_cancelacion_suscripcion(
            "u@example.com", "Cuerpo General Administrativo del Estado (AGE, C1)", fecha_fin="01/01/2030"
        )

    payload = mock_post.call_args.kwargs["json"]
    assert "Cuerpo General Administrativo del Estado (AGE, C1)" in payload["htmlContent"]
    assert "01/01/2030" in payload["htmlContent"]


def test_cancelacion_suscripcion_adapta_el_parrafo_al_motivo(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_CANCELACION", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_cancelacion_suscripcion("u@example.com", "AGE", motivo="aprobado")
    assert "Enhorabuena" in mock_post.call_args.kwargs["json"]["htmlContent"]

    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_cancelacion_suscripcion("u@example.com", "AGE", motivo="precio")
    assert "plan Básico" in mock_post.call_args.kwargs["json"]["htmlContent"]

    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_cancelacion_suscripcion("u@example.com", "AGE", motivo="motivo_desconocido")
    assert "podríamos haber hecho mejor" in mock_post.call_args.kwargs["json"]["htmlContent"]


def test_reactivacion_suscripcion_incluye_oposicion(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_REACTIVACION", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_reactivacion_suscripcion("u@example.com", "GACE", nombre="Ana")

    payload = mock_post.call_args.kwargs["json"]
    assert "GACE" in payload["htmlContent"]
    assert "reactivado" in payload["htmlContent"]


def test_pago_fallido_incluye_oposicion_y_cta_de_actualizar_pago(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.setenv("FRONTEND_URL", "https://dominatuopo.com")
    monkeypatch.delenv("BREVO_TEMPLATE_PAGO_FALLIDO", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_pago_fallido("u@example.com", "AGE")

    payload = mock_post.call_args.kwargs["json"]
    assert "AGE" in payload["htmlContent"]
    assert "https://dominatuopo.com/mi-cuenta/" in payload["htmlContent"]
    assert "AGE" in payload["subject"]


def test_activar_oposicion_incluye_el_enlace_a_zona_opositor(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.setenv("FRONTEND_URL", "https://dominatuopo.com")
    monkeypatch.delenv("BREVO_TEMPLATE_ACTIVAR_OPOSICION", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_activar_oposicion("u@example.com", nombre="Virginia")

    payload = mock_post.call_args.kwargs["json"]
    assert "templateId" not in payload
    assert "https://dominatuopo.com/zona-opositor/" in payload["htmlContent"]
    assert "Virginia" in payload["htmlContent"]
    assert payload["subject"]


def test_activar_oposicion_usa_plantilla_de_brevo_si_esta_configurada(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.setenv("BREVO_TEMPLATE_ACTIVAR_OPOSICION", "88")
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_activar_oposicion("u@example.com", nombre="Virginia")

    payload = mock_post.call_args.kwargs["json"]
    assert payload["templateId"] == 88
    assert payload["params"]["saludo"] == "Hola Virginia"
    assert "subject" not in payload


def test_aviso_oficial_manda_html_de_reserva_con_enlaces_boe_e_inap(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_AVISO_OFICIAL", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_aviso_oficial(
            "u@example.com", "Convocatoria del Cuerpo General Administrativo del Estado",
            "Convocatoria", "https://www.boe.es/x", "https://www.inap.es/y", "AGE", nombre="Ana",
        )

    payload = mock_post.call_args.kwargs["json"]
    assert "templateId" not in payload
    assert "Convocatoria del Cuerpo General Administrativo del Estado" in payload["htmlContent"]
    assert "https://www.boe.es/x" in payload["htmlContent"]
    assert "https://www.inap.es/y" in payload["htmlContent"]
    assert "AGE" in payload["htmlContent"]
    assert "AGE" in payload["subject"]
    assert "Convocatoria" in payload["subject"]


def test_aviso_oficial_sin_url_no_manda_boton_roto(monkeypatch):
    # href="" en un botón parece un enlace roto ("no deja pinchar en
    # nada") -- si no hay URL, mejor no mostrar el botón/enlace en vez de
    # uno que no lleva a ningún sitio.
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_AVISO_OFICIAL", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_aviso_oficial(
            "u@example.com", "Llamamiento extraordinario", "Llamamiento extraordinario",
            "", "", "AGE",
        )

    payload = mock_post.call_args.kwargs["json"]
    assert 'href=""' not in payload["htmlContent"]


def test_aviso_oficial_usa_plantilla_de_brevo_si_esta_configurada(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.setenv("BREVO_TEMPLATE_AVISO_OFICIAL", "77")
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_aviso_oficial(
            "u@example.com", "Lista de admitidos", "Lista de admitidos",
            "https://www.boe.es/x", "https://www.inap.es/y", "GACE",
        )

    payload = mock_post.call_args.kwargs["json"]
    assert payload["templateId"] == 77
    assert payload["params"]["titulo"] == "Lista de admitidos"
    assert payload["params"]["url_boe"] == "https://www.boe.es/x"
    assert payload["params"]["url_inap"] == "https://www.inap.es/y"
    assert payload["params"]["oposicion_nombre"] == "GACE"
    assert "subject" not in payload


def test_password_cambiada_manda_html_de_reserva_sin_plantilla(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_PASSWORD_CAMBIADA", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_password_cambiada("u@example.com", nombre="Ana")

    payload = mock_post.call_args.kwargs["json"]
    assert "templateId" not in payload
    assert "contraseña" in payload["htmlContent"].lower()
    assert "Ana" in payload["htmlContent"]


def test_password_cambiada_usa_plantilla_de_brevo_si_esta_configurada(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.setenv("BREVO_TEMPLATE_PASSWORD_CAMBIADA", "18")
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_password_cambiada("u@example.com", nombre="Ana")

    payload = mock_post.call_args.kwargs["json"]
    assert payload["templateId"] == 18
    assert payload["params"]["saludo"] == "Hola Ana"
    assert "subject" not in payload


def test_cuenta_eliminada_manda_html_de_reserva_sin_plantilla(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_CUENTA_ELIMINADA", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_cuenta_eliminada("u@example.com", nombre="Ana")

    payload = mock_post.call_args.kwargs["json"]
    assert "templateId" not in payload
    assert "eliminado" in payload["htmlContent"].lower()
    assert payload["subject"]


def test_cuenta_eliminada_usa_plantilla_de_brevo_si_esta_configurada(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.setenv("BREVO_TEMPLATE_CUENTA_ELIMINADA", "17")
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_cuenta_eliminada("u@example.com")

    payload = mock_post.call_args.kwargs["json"]
    assert payload["templateId"] == 17
    assert "subject" not in payload


def test_pago_confirmado_incluye_oposicion_y_plan(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.setenv("FRONTEND_URL", "https://dominatuopo.com")
    monkeypatch.delenv("BREVO_TEMPLATE_PAGO_CONFIRMADO", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_pago_confirmado("u@example.com", "AGE", "premium", nombre="Ana")

    payload = mock_post.call_args.kwargs["json"]
    assert "templateId" not in payload
    assert "AGE" in payload["htmlContent"]
    assert "Premium" in payload["htmlContent"]
    assert "AGE" in payload["subject"]


def test_pago_confirmado_usa_plantilla_de_brevo_si_esta_configurada(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.setenv("BREVO_TEMPLATE_PAGO_CONFIRMADO", "16")
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_pago_confirmado("u@example.com", "GACE", "basico")

    payload = mock_post.call_args.kwargs["json"]
    assert payload["templateId"] == 16
    assert payload["params"]["oposicion_nombre"] == "GACE"
    assert payload["params"]["plan_nombre"] == "Básico"
    assert "subject" not in payload


def test_error_http_de_brevo_no_lanza_excepcion(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    mock_error = MagicMock()
    mock_error.status_code = 400
    mock_error.text = "Bad Request"
    with patch("email_utils.requests.post", return_value=mock_error):
        email_utils.enviar_email_bienvenida("u@example.com")  # no debe lanzar


def test_excepcion_de_red_no_se_propaga(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    with patch("email_utils.requests.post", side_effect=ConnectionError("caído")):
        email_utils.enviar_email_bienvenida("u@example.com")  # no debe lanzar


# --- Reportes de preguntas: recibido / corregida / sin cambios ---

_PREGUNTA_COMPLETA = {
    "pregunta": "Señale cómo se retribuye la peligrosidad o penosidad de un puesto de trabajo:",
    "opciones": {
        "A": "Complemento de productividad.",
        "B": "Complemento específico.",
        "C": "Complemento de destino.",
        "D": "Gratificación por servicios extraordinarios.",
    },
    "respuesta_correcta": "B",
    "explicacion": "El art. 23.3.b) de la Ley 30/1984 lo atribuye al complemento específico.",
}


def test_pregunta_reportada_manda_html_con_la_pregunta_y_el_motivo(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_PREGUNTA_REPORTADA", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_pregunta_reportada("u@example.com", "¿Pregunta?", "La C también vale", nombre="Ana")

    payload = mock_post.call_args.kwargs["json"]
    assert payload["to"] == [{"email": "u@example.com"}]
    assert "templateId" not in payload
    assert "¿Pregunta?" in payload["htmlContent"]
    assert "La C también vale" in payload["htmlContent"]
    assert "Hola Ana" in payload["htmlContent"]
    assert payload["subject"]


def test_pregunta_reportada_escapa_el_texto_del_usuario(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_PREGUNTA_REPORTADA", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_pregunta_reportada(
            "u@example.com", "<b>pregunta</b>", "<script>alert(1)</script>", nombre="<i>Ana</i>",
        )

    html = mock_post.call_args.kwargs["json"]["htmlContent"]
    assert "<script>" not in html
    assert "<b>pregunta</b>" not in html
    assert "<i>Ana</i>" not in html
    assert "&lt;script&gt;" in html


def test_pregunta_reportada_usa_plantilla_de_brevo_si_esta_configurada(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.setenv("BREVO_TEMPLATE_PREGUNTA_REPORTADA", "31")
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_pregunta_reportada("u@example.com", "¿Pregunta?", "motivo")

    payload = mock_post.call_args.kwargs["json"]
    assert payload["templateId"] == 31
    assert payload["params"]["pregunta_texto"] == "¿Pregunta?"
    assert "subject" not in payload


def test_pregunta_corregida_resume_los_cambios_e_incluye_la_pregunta_completa(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_PREGUNTA_CORREGIDA", raising=False)
    cambios = [
        {"campo": "respuesta_correcta", "antes": "C", "despues": "B"},
        {"campo": "explicacion", "antes": "vieja", "despues": "nueva"},
    ]
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_pregunta_corregida(
            "u@example.com", _PREGUNTA_COMPLETA, cambios, nombre="Ana", nota="Gracias por la precisión",
        )

    html = mock_post.call_args.kwargs["json"]["htmlContent"]
    assert "Respuesta correcta: de C a B." in html
    assert "Explicación actualizada." in html
    assert "Complemento específico. ✓" in html  # la correcta, resaltada
    assert "Complemento de destino." in html  # las otras opciones también salen
    assert "Ley 30/1984" in html  # explicación
    assert "Gracias por la precisión" in html  # nota del administrador
    assert "Mensaje del equipo" in html


def test_pregunta_corregida_sin_nota_no_incluye_el_bloque_de_mensaje(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_PREGUNTA_CORREGIDA", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_pregunta_corregida(
            "u@example.com", _PREGUNTA_COMPLETA, [{"campo": "enunciado", "antes": "a", "despues": "b"}],
        )

    html = mock_post.call_args.kwargs["json"]["htmlContent"]
    assert "Mensaje del equipo" not in html
    assert "Enunciado reformulado." in html


def test_pregunta_corregida_usa_plantilla_de_brevo_si_esta_configurada(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.setenv("BREVO_TEMPLATE_PREGUNTA_CORREGIDA", "32")
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_pregunta_corregida(
            "u@example.com", _PREGUNTA_COMPLETA, [{"campo": "respuesta_correcta", "antes": "C", "despues": "B"}],
        )

    payload = mock_post.call_args.kwargs["json"]
    assert payload["templateId"] == 32
    assert payload["params"]["respuesta_correcta"] == "B"
    assert payload["params"]["opcion_b"] == "Complemento específico."
    assert payload["params"]["resumen_cambios"] == "Respuesta correcta: de C a B."


def test_pregunta_sin_cambios_dice_que_esta_bien_formulada_e_incluye_la_pregunta(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_PREGUNTA_SIN_CAMBIOS", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_pregunta_sin_cambios("u@example.com", _PREGUNTA_COMPLETA, nombre="Ana", nota="Un saludo")

    html = mock_post.call_args.kwargs["json"]["htmlContent"]
    assert "correctamente formulada" in html
    assert "Complemento específico. ✓" in html
    assert "Un saludo" in html


def test_pregunta_sin_cambios_tolera_una_pregunta_minima_sin_banco(monkeypatch):
    # Pregunta generada por IA: no está en el banco oficial, solo se cita el enunciado.
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("BREVO_TEMPLATE_PREGUNTA_SIN_CAMBIOS", raising=False)
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_pregunta_sin_cambios("u@example.com", {"pregunta": "¿Pregunta de IA?"})

    html = mock_post.call_args.kwargs["json"]["htmlContent"]
    assert "¿Pregunta de IA?" in html
    assert "✓" not in html
    assert "Explicación:" not in html


def test_pregunta_sin_cambios_usa_plantilla_de_brevo_si_esta_configurada(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.setenv("BREVO_TEMPLATE_PREGUNTA_SIN_CAMBIOS", "33")
    with patch("email_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        email_utils.enviar_email_pregunta_sin_cambios("u@example.com", _PREGUNTA_COMPLETA)

    payload = mock_post.call_args.kwargs["json"]
    assert payload["templateId"] == 33
    assert "subject" not in payload
