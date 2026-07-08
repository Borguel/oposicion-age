"""Pruebas de deepseek_utils.call_deepseek_api: el modo JSON nativo (nunca
usado hasta ahora) y los reintentos acotados ante fallos TRANSITORIOS
(timeout/conexión/5xx) -- nunca ante errores 4xx, que no se arreglan
reintentando."""
from unittest.mock import MagicMock, patch

import requests

import deepseek_utils


def _respuesta_ok(contenido="ok"):
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"choices": [{"message": {"content": contenido}}]}
    return mock


def _respuesta_http_error(status_code):
    mock_respuesta = MagicMock()
    mock_respuesta.status_code = status_code
    error = requests.exceptions.HTTPError(response=mock_respuesta)
    mock = MagicMock()
    mock.raise_for_status.side_effect = error
    return mock


def test_response_format_json_se_incluye_en_el_payload(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        deepseek_utils.call_deepseek_api(
            messages=[{"role": "user", "content": "hola"}], response_format_json=True
        )
    payload_enviado = mock_post.call_args.kwargs["json"]
    assert payload_enviado["response_format"] == {"type": "json_object"}


def test_sin_response_format_json_no_se_incluye_el_campo(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}])
    payload_enviado = mock_post.call_args.kwargs["json"]
    assert "response_format" not in payload_enviado


def test_reintenta_ante_timeout_y_acaba_devolviendo_la_respuesta(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", side_effect=[
        requests.exceptions.Timeout(), requests.exceptions.Timeout(), _respuesta_ok("tercer intento")
    ]) as mock_post, patch("deepseek_utils.time.sleep"):
        resultado = deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}])
    assert resultado == "tercer intento"
    assert mock_post.call_count == 3


def test_deja_de_reintentar_tras_agotar_los_intentos(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", side_effect=[
        requests.exceptions.ConnectionError(),
        requests.exceptions.ConnectionError(),
        requests.exceptions.ConnectionError(),
    ]) as mock_post, patch("deepseek_utils.time.sleep"):
        resultado = deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}])
    assert resultado is None
    assert mock_post.call_count == 3  # 1 intento inicial + 2 reintentos, nunca más


def test_no_reintenta_ante_error_4xx(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", return_value=_respuesta_http_error(401)) as mock_post, \
         patch("deepseek_utils.time.sleep") as mock_sleep:
        resultado = deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}])
    assert resultado is None
    assert mock_post.call_count == 1  # un 401 no se arregla reintentando
    mock_sleep.assert_not_called()


def test_reintenta_ante_error_5xx(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", side_effect=[
        _respuesta_http_error(503), _respuesta_ok("recuperado")
    ]) as mock_post, patch("deepseek_utils.time.sleep"):
        resultado = deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}])
    assert resultado == "recuperado"
    assert mock_post.call_count == 2


def _respuesta_con_status(contenido, finish_reason, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = {
        "choices": [{"message": {"content": contenido}, "finish_reason": finish_reason}]
    }
    return mock


class TestGenerarConContinuacion:
    """generar_con_continuacion: usada por /resumir-documento y
    /generar-esquema-desde-pdf para que un documento largo no se quede a
    medias -- antes una única llamada con tope fijo de tokens simplemente
    cortaba el resumen sin ningún aviso ni reintento."""

    def test_una_sola_llamada_si_no_se_corta(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        with patch("deepseek_utils.requests.post",
                   return_value=_respuesta_con_status("Resumen completo.", "stop")) as mock_post:
            resultado = deepseek_utils.generar_con_continuacion("system", "user")
        assert resultado == "Resumen completo."
        assert mock_post.call_count == 1

    def test_pide_continuacion_si_se_corta_por_longitud(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        with patch("deepseek_utils.requests.post", side_effect=[
            _respuesta_con_status("Parte 1 del resumen... ", "length"),
            _respuesta_con_status("parte 2 y final.", "stop"),
        ]) as mock_post:
            resultado = deepseek_utils.generar_con_continuacion("system", "user")
        assert resultado == "Parte 1 del resumen... parte 2 y final."
        assert mock_post.call_count == 2
        # La segunda llamada debe pedir explícitamente que continúe, no repetir el prompt original.
        segunda_llamada_mensajes = mock_post.call_args_list[1].kwargs["json"]["messages"]
        assert segunda_llamada_mensajes[-1]["role"] == "user"
        assert "continúa" in segunda_llamada_mensajes[-1]["content"].lower()

    def test_nunca_pide_mas_de_max_continuaciones(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        # Se corta SIEMPRE por longitud -- no debe reintentar indefinidamente.
        with patch("deepseek_utils.requests.post",
                   return_value=_respuesta_con_status("trozo ", "length")) as mock_post:
            resultado = deepseek_utils.generar_con_continuacion("system", "user", max_continuaciones=2)
        assert mock_post.call_count == 3  # 1 inicial + 2 continuaciones, nunca más
        assert resultado == "trozo trozo trozo "

    def test_devuelve_none_si_falla_la_primera_llamada(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        with patch("deepseek_utils.requests.post", return_value=_respuesta_con_status("", "stop", status_code=500)):
            resultado = deepseek_utils.generar_con_continuacion("system", "user")
        assert resultado is None

    def test_sin_api_key_devuelve_none_sin_llamar(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with patch("deepseek_utils.requests.post") as mock_post:
            resultado = deepseek_utils.generar_con_continuacion("system", "user")
        assert resultado is None
        mock_post.assert_not_called()
