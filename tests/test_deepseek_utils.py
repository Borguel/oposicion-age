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


def test_call_deepseek_api_usa_deepseek_v4_flash_por_defecto(monkeypatch):
    # deepseek-chat/deepseek-reasoner se retiraron el 24/07/2026 sin periodo
    # de gracia; los nombres actuales son deepseek-v4-flash/deepseek-v4-pro.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}])
    assert mock_post.call_args.kwargs["json"]["model"] == "deepseek-v4-flash"


def test_call_deepseek_api_permite_pedir_otro_modelo(monkeypatch):
    # Usado por Tu Tutor para poder probar deepseek-v4-pro sin afectar al
    # resto de la app (ver chat_controller._modelo_tutor).
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}], model="deepseek-v4-pro")
    assert mock_post.call_args.kwargs["json"]["model"] == "deepseek-v4-pro"


def test_call_deepseek_api_incluye_temperature_con_deepseek_v4_flash(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}], temperature=0.5)
    assert mock_post.call_args.kwargs["json"]["temperature"] == 0.5


def test_call_deepseek_api_incluye_temperature_con_deepseek_v4_pro(monkeypatch):
    # A diferencia del antiguo deepseek-reasoner (retirado), deepseek-v4-pro
    # sí admite temperature con normalidad.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}], model="deepseek-v4-pro", temperature=0.5)
    assert mock_post.call_args.kwargs["json"]["temperature"] == 0.5


def test_call_deepseek_api_no_incluye_temperature_con_el_nombre_retirado(monkeypatch):
    # Legado: el antiguo deepseek-reasoner (retirado el 24/07/2026) rechazaba
    # con HTTP 400 ("does not support the parameter temperature") si se
    # incluía este campo -- no lo ignoraba en silencio pese a lo que decía
    # la documentación oficial. Se mantiene esta exclusión por si quedara
    # algún sitio con el nombre antiguo todavía configurado, aunque con los
    # nombres actuales (deepseek-v4-flash/deepseek-v4-pro) nunca se activa.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}], model="deepseek-reasoner")
    assert "temperature" not in mock_post.call_args.kwargs["json"]


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


def _respuesta_finish_reason(contenido, finish_reason):
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"choices": [{"message": {"content": contenido}, "finish_reason": finish_reason}]}
    return mock


def test_reintenta_ante_respuesta_truncada_y_acaba_devolviendo_la_respuesta(monkeypatch):
    # finish_reason=length (DeepSeek cortó al llegar a max_tokens, casi
    # siempre a mitad del JSON pedido) se trata como un fallo transitorio
    # más -- nunca se devuelve el JSON a medias al llamante.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", side_effect=[
        _respuesta_finish_reason('{"pregunta": "a medi', "length"),
        _respuesta_finish_reason('{"pregunta": "completa"}', "stop"),
    ]) as mock_post, patch("deepseek_utils.time.sleep") as mock_sleep:
        resultado = deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}])
    assert resultado == '{"pregunta": "completa"}'
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once()


def test_deja_de_reintentar_tras_agotar_los_intentos_por_truncamiento(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", side_effect=[
        _respuesta_finish_reason('{"pregunta": "a', "length"),
        _respuesta_finish_reason('{"pregunta": "a medi', "length"),
        _respuesta_finish_reason('{"pregunta": "a medias tod', "length"),
    ]) as mock_post, patch("deepseek_utils.time.sleep"):
        resultado = deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}])
    # Nunca se devuelve el JSON truncado -- ni siquiera tras agotar los
    # reintentos: el llamante debe poder tratarlo igual que cualquier otro
    # fallo (None), no como un resultado válido a medio parsear.
    assert resultado is None
    assert mock_post.call_count == 3  # 1 intento inicial + 2 reintentos, nunca más


def test_contexto_se_incluye_en_el_log_de_truncamiento(monkeypatch, caplog):
    import logging
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post",
               return_value=_respuesta_finish_reason('{"a": "b"}', "length")), \
         patch("deepseek_utils.time.sleep"), \
         caplog.at_level(logging.WARNING, logger="deepseek_utils"):
        deepseek_utils.call_deepseek_api(
            messages=[{"role": "user", "content": "hola"}], contexto="tema=bloque_01-tema_02 tipo=generacion"
        )
    assert any("tema=bloque_01-tema_02 tipo=generacion" in r.message for r in caplog.records)


def _respuesta_sse(lineas_sse, status_code=200):
    """Mock de una respuesta en streaming (SSE) para call_deepseek_api con
    stream=True: soporta el uso como context manager
    ('with requests.post(...) as response') que usa
    _leer_respuesta_en_streaming, igual que _respuesta_stream más abajo
    (usada por call_deepseek_api_stream) -- duplicada aquí, no reutilizada,
    porque esa vive más adelante en el archivo y esta zona del archivo
    prueba una función distinta con su propio contrato."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.raise_for_status.return_value = None
    mock.iter_lines.return_value = iter(lineas_sse)
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock


class TestCallDeepseekApiStreamInterno:
    """call_deepseek_api(..., stream=True): la llamada en streaming NO
    cambia el contrato con quien llama (sigue devolviendo el texto
    completo de una vez, no fragmentos) -- solo evita que una respuesta
    larga (más de ~30s generándose) muera con "Error de conexión" por
    tener la conexión muda mientras dura la generación (ver
    _leer_respuesta_en_streaming en deepseek_utils.py, añadido 02/08/2026
    con datos reales de producción)."""

    def test_incluye_stream_true_y_stream_options_en_el_payload(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        lineas = ['data: {"choices": [{"delta": {"content": "hola"}, "finish_reason": "stop"}]}', "data: [DONE]"]
        with patch("deepseek_utils.requests.post", return_value=_respuesta_sse(lineas)) as mock_post:
            deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}], stream=True)
        payload_enviado = mock_post.call_args.kwargs["json"]
        assert payload_enviado["stream"] is True
        assert payload_enviado["stream_options"] == {"include_usage": True}

    def test_sin_stream_el_payload_no_lleva_stream_options(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        with patch("deepseek_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
            deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}])
        payload_enviado = mock_post.call_args.kwargs["json"]
        assert payload_enviado["stream"] is False
        assert "stream_options" not in payload_enviado

    def test_acumula_los_fragmentos_y_devuelve_el_texto_completo(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        lineas = [
            'data: {"choices": [{"delta": {"content": "Hola "}}]}',
            'data: {"choices": [{"delta": {"content": "mundo"}, "finish_reason": "stop"}]}',
            'data: {"choices": [], "usage": {"completion_tokens": 42}}',
            "data: [DONE]",
        ]
        with patch("deepseek_utils.requests.post", return_value=_respuesta_sse(lineas)):
            resultado = deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}], stream=True)
        assert resultado == "Hola mundo"

    def test_reintenta_si_finish_reason_es_length_igual_que_sin_streaming(self, monkeypatch):
        # Mismo criterio de reintento por truncamiento que la llamada
        # clásica: el finish_reason del último chunk con contenido decide,
        # no un status HTTP -- aquí también SIEMPRE es 200.
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        lineas_truncadas = [
            'data: {"choices": [{"delta": {"content": "a medi"}, "finish_reason": "length"}]}',
            "data: [DONE]",
        ]
        lineas_completas = [
            'data: {"choices": [{"delta": {"content": "completa"}, "finish_reason": "stop"}]}',
            "data: [DONE]",
        ]
        with patch("deepseek_utils.requests.post", side_effect=[
            _respuesta_sse(lineas_truncadas), _respuesta_sse(lineas_completas),
        ]) as mock_post, patch("deepseek_utils.time.sleep"):
            resultado = deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}], stream=True)
        assert resultado == "completa"
        assert mock_post.call_count == 2

    def test_captura_el_usage_del_ultimo_chunk_para_on_usage(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        lineas = [
            'data: {"choices": [{"delta": {"content": "x"}, "finish_reason": "stop"}]}',
            'data: {"choices": [], "usage": {"completion_tokens": 99, "total_tokens": 150}}',
            "data: [DONE]",
        ]
        usages_capturados = []
        with patch("deepseek_utils.requests.post", return_value=_respuesta_sse(lineas)):
            deepseek_utils.call_deepseek_api(
                messages=[{"role": "user", "content": "hola"}], stream=True, on_usage=usages_capturados.append
            )
        assert usages_capturados == [{"completion_tokens": 99, "total_tokens": 150}]

    def test_reintenta_ante_fallo_de_conexion_igual_que_sin_streaming(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        lineas = ['data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}', "data: [DONE]"]
        with patch("deepseek_utils.requests.post", side_effect=[
            requests.exceptions.ConnectionError(), _respuesta_sse(lineas),
        ]) as mock_post, patch("deepseek_utils.time.sleep"):
            resultado = deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}], stream=True)
        assert resultado == "ok"
        assert mock_post.call_count == 2


def test_limita_las_llamadas_simultaneas_a_deepseek(monkeypatch):
    # Bug real de producción: sin límite compartido, generar un test de 30
    # preguntas desde PDF puede disparar hasta ~48 llamadas en paralelo (8
    # lotes x 6 verificaciones cada uno, ver test_generator.py), y bajo
    # carga eso parecía saturar a DeepSeek -- en logs reales se vieron
    # llamadas colgadas ~94s (3 intentos de 30s de timeout) antes de fallar
    # con "Error de conexión", justo en las ráfagas de mayor concurrencia.
    # _semaforo_deepseek debe frenar esto sea cual sea el número de hilos
    # que lo intenten a la vez, sin importar qué función de este módulo lo
    # dispare.
    import threading
    import time as time_module

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(deepseek_utils, "_semaforo_deepseek", threading.Semaphore(2))

    en_curso = {"actual": 0, "maximo": 0}
    lock = threading.Lock()

    def fake_post(*args, **kwargs):
        with lock:
            en_curso["actual"] += 1
            en_curso["maximo"] = max(en_curso["maximo"], en_curso["actual"])
        time_module.sleep(0.05)
        with lock:
            en_curso["actual"] -= 1
        return _respuesta_ok()

    with patch("deepseek_utils.requests.post", side_effect=fake_post):
        hilos = [
            threading.Thread(
                target=deepseek_utils.call_deepseek_api,
                kwargs={"messages": [{"role": "user", "content": "hola"}]},
            )
            for _ in range(8)
        ]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join()

    assert en_curso["maximo"] <= 2


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

    def test_reintenta_ante_fallo_transitorio_y_acaba_devolviendo_el_resultado(self, monkeypatch):
        # generar_con_continuacion hace su propia llamada a DeepSeek (no
        # reutiliza call_deepseek_api, que devuelve solo el texto sin
        # finish_reason) -- pero comparte el mismo criterio de reintento
        # ante fallos transitorios vía _post_deepseek_con_reintentos.
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        with patch("deepseek_utils.requests.post", side_effect=[
            requests.exceptions.ConnectionError(),
            _respuesta_con_status("Resumen recuperado.", "stop"),
        ]) as mock_post, patch("deepseek_utils.time.sleep"):
            resultado = deepseek_utils.generar_con_continuacion("system", "user")
        assert resultado == "Resumen recuperado."
        assert mock_post.call_count == 2

    def test_reintenta_ante_5xx_antes_de_pedir_continuacion(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        with patch("deepseek_utils.requests.post", side_effect=[
            _respuesta_con_status("", "stop", status_code=503),
            _respuesta_con_status("Resumen recuperado.", "stop"),
        ]) as mock_post, patch("deepseek_utils.time.sleep"):
            resultado = deepseek_utils.generar_con_continuacion("system", "user")
        assert resultado == "Resumen recuperado."
        assert mock_post.call_count == 2


def _respuesta_stream(status_code, lineas_sse=None):
    mock = MagicMock()
    mock.status_code = status_code
    if status_code >= 400:
        mock.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock)
    else:
        mock.raise_for_status.return_value = None
    mock.iter_lines.return_value = iter(lineas_sse or [])
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock


class TestCallDeepseekApiStream:
    """call_deepseek_api_stream: solo se reintenta la CONEXIÓN inicial
    (antes de ceder ningún fragmento) ante un fallo transitorio -- nunca a
    mitad de un stream que el frontend ya está pintando con efecto de
    escritura."""

    def test_reintenta_la_conexion_inicial_ante_fallo_transitorio(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        lineas = ['data: {"choices": [{"delta": {"content": "Hola"}}]}', "data: [DONE]"]
        with patch("deepseek_utils.requests.post", side_effect=[
            requests.exceptions.ConnectionError(),
            _respuesta_stream(200, lineas),
        ]) as mock_post, patch("deepseek_utils.time.sleep"):
            fragmentos = list(deepseek_utils.call_deepseek_api_stream([{"role": "user", "content": "hola"}]))
        assert fragmentos == ["Hola"]
        assert mock_post.call_count == 2

    def test_no_reintenta_si_el_stream_falla_ya_iniciado(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        mock_response = _respuesta_stream(200)
        mock_response.iter_lines.side_effect = requests.exceptions.ConnectionError()
        with patch("deepseek_utils.requests.post", return_value=mock_response) as mock_post:
            fragmentos = list(deepseek_utils.call_deepseek_api_stream([{"role": "user", "content": "hola"}]))
        assert fragmentos == []
        assert mock_post.call_count == 1

    def test_usa_deepseek_v4_flash_por_defecto(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        with patch("deepseek_utils.requests.post", return_value=_respuesta_stream(200, ["data: [DONE]"])) as mock_post:
            list(deepseek_utils.call_deepseek_api_stream([{"role": "user", "content": "hola"}]))
        assert mock_post.call_args.kwargs["json"]["model"] == "deepseek-v4-flash"

    def test_permite_pedir_otro_modelo(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        with patch("deepseek_utils.requests.post", return_value=_respuesta_stream(200, ["data: [DONE]"])) as mock_post:
            list(deepseek_utils.call_deepseek_api_stream([{"role": "user", "content": "hola"}], model="deepseek-v4-pro"))
        assert mock_post.call_args.kwargs["json"]["model"] == "deepseek-v4-pro"

    def test_incluye_temperature_con_deepseek_v4_flash(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        with patch("deepseek_utils.requests.post", return_value=_respuesta_stream(200, ["data: [DONE]"])) as mock_post:
            list(deepseek_utils.call_deepseek_api_stream([{"role": "user", "content": "hola"}], temperature=0.5))
        assert mock_post.call_args.kwargs["json"]["temperature"] == 0.5

    def test_incluye_temperature_con_deepseek_v4_pro(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        with patch("deepseek_utils.requests.post", return_value=_respuesta_stream(200, ["data: [DONE]"])) as mock_post:
            list(deepseek_utils.call_deepseek_api_stream([{"role": "user", "content": "hola"}], model="deepseek-v4-pro", temperature=0.5))
        assert mock_post.call_args.kwargs["json"]["temperature"] == 0.5

    def test_no_incluye_temperature_con_el_nombre_retirado(self, monkeypatch):
        # Legado (ver test equivalente en call_deepseek_api): el antiguo
        # deepseek-reasoner, retirado el 24/07/2026, respondía HTTP 400 si
        # se incluía temperature en el payload.
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        with patch("deepseek_utils.requests.post", return_value=_respuesta_stream(200, ["data: [DONE]"])) as mock_post:
            list(deepseek_utils.call_deepseek_api_stream([{"role": "user", "content": "hola"}], model="deepseek-reasoner"))
        assert "temperature" not in mock_post.call_args.kwargs["json"]

    def test_ignora_reasoning_content_y_solo_cede_content(self, monkeypatch):
        # deepseek-reasoner emite primero tokens en delta.reasoning_content
        # (el razonamiento interno) antes de delta.content (la respuesta
        # final) -- solo debe llegar al llamante lo segundo.
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        lineas = [
            'data: {"choices": [{"delta": {"reasoning_content": "pensando..."}}]}',
            'data: {"choices": [{"delta": {"content": "Respuesta"}}]}',
            "data: [DONE]",
        ]
        with patch("deepseek_utils.requests.post", return_value=_respuesta_stream(200, lineas)):
            fragmentos = list(deepseek_utils.call_deepseek_api_stream([{"role": "user", "content": "hola"}]))
        assert fragmentos == ["Respuesta"]


class TestTrocearEnParrafos:
    """_trocear_en_parrafos: nunca debe partir un párrafo a la mitad, y debe
    agrupar párrafos consecutivos mientras quepan en el tamaño pedido."""

    def test_texto_corto_no_se_trocea(self):
        assert deepseek_utils._trocear_en_parrafos("Texto corto.", tamano=100) == ["Texto corto."]

    def test_agrupa_parrafos_sin_superar_el_tamano(self):
        parrafos = ["a" * 30, "b" * 30, "c" * 30]
        texto = "\n\n".join(parrafos)
        fragmentos = deepseek_utils._trocear_en_parrafos(texto, tamano=65)
        # Cada fragmento agrupa como mucho 2 párrafos de 30 (30+2+30=62 <= 65);
        # el tercero no cabe con los dos primeros y pasa a su propio fragmento.
        assert len(fragmentos) == 2
        assert "a" * 30 in fragmentos[0] and "b" * 30 in fragmentos[0]
        assert "c" * 30 in fragmentos[1]

    def test_nunca_parte_un_parrafo_a_la_mitad(self):
        parrafos = ["x" * 40, "y" * 40, "z" * 40]
        texto = "\n\n".join(parrafos)
        fragmentos = deepseek_utils._trocear_en_parrafos(texto, tamano=50)
        texto_reconstruido = "\n\n".join(fragmentos)
        for parrafo in parrafos:
            assert parrafo in texto_reconstruido
            # Cada párrafo debe aparecer ENTERO dentro de un único fragmento.
            assert any(parrafo in f for f in fragmentos)


class TestGenerarDocumentoLargoPorPartes:
    """generar_documento_largo_por_partes: documentos que ya caben en un
    único prompt se comportan igual que antes (una sola llamada);
    documentos largos se trocean (map), se resumen por partes en paralelo, y
    se funden en un único resultado coherente (reduce)."""

    def test_documento_corto_una_sola_llamada(self):
        with patch("deepseek_utils.generar_con_continuacion", return_value="resumen completo") as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", "texto corto")
        assert resultado == "resumen completo"
        assert mock_gen.call_count == 1

    def test_documento_largo_trocea_resume_por_partes_y_funde(self):
        # Dos párrafos de ~10.000 caracteres cada uno: por separado caben en
        # un fragmento (tamaño 15.000), pero juntos no, así que se trocean en
        # exactamente 2 fragmentos.
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"
        assert len(deepseek_utils._trocear_en_parrafos(texto_largo)) == 2

        respuestas = ["parcial 1", "parcial 2", "fusión final"]
        with patch("deepseek_utils.generar_con_continuacion", side_effect=respuestas) as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto_largo)

        assert resultado == "fusión final"
        # Al menos una llamada de "map" por fragmento + 1 de fusión al final.
        assert mock_gen.call_count == len(respuestas)
        ultima_llamada = mock_gen.call_args_list[-1]
        assert "parcial 1" in ultima_llamada.args[1]
        assert "parcial 2" in ultima_llamada.args[1]

    def test_documento_largo_donde_todos_los_fragmentos_fallan_devuelve_none(self):
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"
        with patch("deepseek_utils.generar_con_continuacion", return_value=None):
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto_largo)
        assert resultado is None

    def test_documento_largo_con_un_solo_fragmento_valido_no_funde(self):
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"
        with patch("deepseek_utils.generar_con_continuacion",
                   side_effect=[None, "único parcial válido"]) as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto_largo)
        assert resultado == "único parcial válido"
        # No hay llamada extra de fusión cuando solo sobrevive un fragmento.
        assert mock_gen.call_count == 2
