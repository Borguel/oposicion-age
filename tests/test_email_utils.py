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
