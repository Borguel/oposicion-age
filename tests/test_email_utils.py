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
