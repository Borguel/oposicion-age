"""Pruebas de deepseek_utils.call_deepseek_api: el modo JSON nativo (nunca
usado hasta ahora) y los reintentos acotados ante fallos TRANSITORIOS
(timeout/conexión/5xx) -- nunca ante errores 4xx, que no se arreglan
reintentando."""
import threading
import time
from concurrent.futures import as_completed
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


def _as_completed_sin_timeout(fs, timeout=None):
    """Sustituto de concurrent.futures.as_completed para pruebas que mockean
    time.monotonic(): la implementación real, al recibir un `timeout`,
    consulta time.monotonic() ella misma internamente (para calcular su
    propio plazo) -- lo que consumiría, de forma no determinista según el
    scheduling real de threads, valores extra del side_effect mockeado en el
    módulo bajo prueba. Este sustituto delega en la implementación real pero
    IGNORANDO el timeout, para que las únicas llamadas a time.monotonic()
    durante la prueba sean las explícitas de generar_documento_largo_por_partes,
    y así el número de llamadas mockeadas necesarias sea exacto y estable."""
    return as_completed(fs)


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
    # _REINTENTOS_TRUNCAMIENTO (1) es deliberadamente más corto que
    # _REINTENTOS_TRANSITORIOS (2): cada reintento aquí cuesta una
    # generación entera, así que un hueco atascado en un bucle de
    # repetición debe ceder el turno pronto al bucle EXTERIOR (que sí
    # prueba con una ancla/tipo de pregunta distintos) en vez de agotar el
    # mismo presupuesto que un simple parpadeo de red.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", side_effect=[
        _respuesta_finish_reason('{"pregunta": "a', "length"),
        _respuesta_finish_reason('{"pregunta": "a medi', "length"),
    ]) as mock_post, patch("deepseek_utils.time.sleep"):
        resultado = deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}])
    # Nunca se devuelve el JSON truncado -- ni siquiera tras agotar los
    # reintentos: el llamante debe poder tratarlo igual que cualquier otro
    # fallo (None), no como un resultado válido a medio parsear.
    assert resultado is None
    assert mock_post.call_count == 2  # 1 intento inicial + 1 reintento, nunca más


def test_max_reintentos_truncamiento_permite_bajar_el_presupuesto_por_llamada(monkeypatch):
    # Usado por la generación EN LOTE (ver TAMANO_LOTE_GENERACION en
    # generador_preguntas_verificado.py): con max_tokens ya varias veces
    # mayor que una llamada normal, un reintento de lote es muy caro --
    # max_reintentos_truncamiento=0 hace que un truncamiento se rinda de
    # inmediato (0 reintentos) en vez de usar el _REINTENTOS_TRUNCAMIENTO
    # por defecto del módulo.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post",
               return_value=_respuesta_finish_reason('{"a": "b medi', "length")) as mock_post, \
         patch("deepseek_utils.time.sleep") as mock_sleep:
        resultado = deepseek_utils.call_deepseek_api(
            messages=[{"role": "user", "content": "hola"}], max_reintentos_truncamiento=0
        )
    assert resultado is None
    assert mock_post.call_count == 1  # ni un solo reintento
    mock_sleep.assert_not_called()


def test_reintento_por_truncamiento_sube_la_temperature(monkeypatch):
    # Con temperature=0.0 (verificación), reintentar con la MISMA petición
    # es casi inútil: es determinista, así que reproduce el mismo bucle de
    # repetición y vuelve a truncarse en el mismo punto (visto en
    # producción el 02/08/2026 -- mismo input, dos intentos seguidos,
    # ambos truncados exactamente en el mismo número de tokens). Subir la
    # temperature SOLO en el reintento le da una probabilidad real de
    # tomar un camino de generación distinto que sí termine solo.
    #
    # payload es el MISMO dict mutado entre reintentos (no una copia por
    # llamada), así que hay que capturar la temperature en el momento
    # exacto de cada llamada real -- inspeccionar mock_post.call_args_list
    # DESPUÉS de que todo termine vería siempre el valor final mutado en
    # las dos entradas, no la evolución real.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    temperaturas_por_llamada = []
    respuestas = iter([
        _respuesta_finish_reason('{"a": "b medi', "length"),
        _respuesta_finish_reason('{"a": "b completa"}', "stop"),
    ])

    def fake_post(*args, **kwargs):
        temperaturas_por_llamada.append(kwargs["json"]["temperature"])
        return next(respuestas)

    with patch("deepseek_utils.requests.post", side_effect=fake_post), patch("deepseek_utils.time.sleep"):
        deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}], temperature=0.0)
    assert temperaturas_por_llamada[0] == 0.0
    assert temperaturas_por_llamada[1] > 0.0


def test_frequency_penalty_se_incluye_en_el_payload_si_se_pasa(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}], frequency_penalty=0.4)
    assert mock_post.call_args.kwargs["json"]["frequency_penalty"] == 0.4


def test_sin_frequency_penalty_no_se_incluye_en_el_payload(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}])
    assert "frequency_penalty" not in mock_post.call_args.kwargs["json"]


def test_deepseek_v4_flash_desactiva_el_thinking_por_defecto(monkeypatch):
    # deepseek-v4-flash trae "thinking" activado por defecto (nivel
    # "high") -- ver datos reales en el comentario junto a payload["thinking"]
    # en deepseek_utils.py. Se desactiva explícitamente porque toda la
    # generación/verificación de preguntas gasta el razonamiento invisible
    # sin usarlo nunca, y eso es lo que causaba tanto la lentitud como los
    # truncamientos.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}], model="deepseek-v4-flash")
    assert mock_post.call_args.kwargs["json"]["thinking"] == {"type": "disabled"}


def test_deepseek_v4_pro_mantiene_el_thinking_activado(monkeypatch):
    # "deepseek-v4-pro" es el modelo de razonamiento, usado a propósito
    # (Tu Tutor) -- no se le debe desactivar el thinking.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        deepseek_utils.call_deepseek_api(messages=[{"role": "user", "content": "hola"}], model="deepseek-v4-pro")
    assert "thinking" not in mock_post.call_args.kwargs["json"]


def test_thinking_enabled_true_fuerza_el_thinking_incluso_en_deepseek_v4_flash(monkeypatch):
    # generador_preguntas_verificado usa esto en la llamada de
    # VERIFICACIÓN (02/08/2026, decisión explícita del negocio): ahí sí
    # interesa mantener el razonamiento encendido pese a que el modelo
    # sea deepseek-v4-flash, porque es la tarea que se juega la precisión
    # legal del test.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch("deepseek_utils.requests.post", return_value=_respuesta_ok()) as mock_post:
        deepseek_utils.call_deepseek_api(
            messages=[{"role": "user", "content": "hola"}], model="deepseek-v4-flash", thinking_enabled=True)
    assert "thinking" not in mock_post.call_args.kwargs["json"]


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

    def test_sin_dobles_saltos_de_linea_cae_a_saltos_simples(self):
        # Bug real (10/08/2026): pypdf.extract_text() de un PDF real (BOE)
        # no dejó ni un solo "\n\n" en 51.000 caracteres -- con SOLO "\n\n"
        # como separador, texto.split("\n\n") devolvía el documento entero
        # como un único "párrafo", así que ni siquiera se intentaba
        # trocear por mucho que superara TAMANO_CHUNK_CARACTERES, y se
        # mandaba entero en un solo prompt a la IA (que lo desbordaba y
        # devolvía un resultado catastróficamente incompleto). Ahora, si
        # "\n\n" no aparece, se cae a "\n" como separador.
        lineas = [f"Línea {i}: " + ("palabra " * 20) for i in range(30)]
        texto = "\n".join(lineas)
        assert "\n\n" not in texto
        fragmentos = deepseek_utils._trocear_en_parrafos(texto, tamano=500)
        assert len(fragmentos) > 1
        for fragmento in fragmentos:
            assert len(fragmento) <= 500
        assert "\n".join(fragmentos) == texto

    def test_sin_ningun_separador_corta_por_caracteres_como_ultimo_recurso(self):
        # Caso extremo: ni "\n\n", ni "\n", ni siquiera un espacio -- no debe
        # devolver nunca un único fragmento gigante sin trocear.
        texto = "a" * 1000
        fragmentos = deepseek_utils._trocear_en_parrafos(texto, tamano=300)
        assert len(fragmentos) == 4
        assert all(len(f) <= 300 for f in fragmentos)
        assert "".join(fragmentos) == texto

    def test_un_parrafo_de_un_solo_bloque_se_subdivide_por_lineas(self):
        # Mezcla de ambos niveles: un documento con ALGÚN "\n\n" (por lo que
        # el separador principal sí se usa), pero donde uno de los bloques
        # resultantes sigue siendo, por sí solo, más largo que 'tamano' --
        # ese bloque en concreto debe subdividirse por "\n" en vez de
        # quedarse tal cual como antes de este fix.
        bloque_corto = "Bloque corto."
        lineas_largas = "\n".join(f"Línea {i} con algo de texto de relleno." for i in range(20))
        texto = f"{bloque_corto}\n\n{lineas_largas}"
        fragmentos = deepseek_utils._trocear_en_parrafos(texto, tamano=200)
        assert len(fragmentos) > 2
        assert all(len(f) <= 200 for f in fragmentos)


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

    def test_documento_sin_trocear_respuesta_corta_se_reintenta_y_se_recupera(self):
        # Bug real (10/08/2026): al subir TAMANO_CHUNK_CARACTERES a 90000,
        # la inmensa mayoría de documentos pasan por el camino de UNA sola
        # llamada (sin MAP ni fusión) -- que, a diferencia del camino de
        # varios fragmentos, no tenía ninguna comprobación de que la
        # respuesta cubriera de verdad el documento. Visto con un caso real:
        # una llamada se cortaba a media palabra sin marcar finish_reason=
        # length, muy por debajo de max_tokens -- el mismo "el modelo se
        # rinde antes de tiempo" que ya se detectaba en el MAP, pero sin
        # ningún control aquí. Con texto de sobra para que quepa en un solo
        # fragmento (por debajo de TAMANO_CHUNK_CARACTERES) pero demasiado
        # grande para que una respuesta corta sea creíble.
        texto = "contenido real del documento. " * 400  # ~12.400 caracteres
        respuesta_corta = "# Se corta aquí a media pala"
        respuesta_completa = "# Documento completo\n" + ("contenido real generado. " * 300)
        with patch("deepseek_utils.generar_con_continuacion", side_effect=[respuesta_corta, respuesta_completa]) as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto)
        assert resultado == respuesta_completa
        assert mock_gen.call_count == 2

    def test_documento_sin_trocear_respuesta_corta_tras_reintentar_devuelve_con_aviso(self):
        texto = "contenido real del documento. " * 400
        respuesta_corta = "# Se corta aquí a media pala"
        with patch("deepseek_utils.generar_con_continuacion", return_value=respuesta_corta) as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto)
        assert resultado is not None
        assert "Aviso" in resultado
        assert respuesta_corta in resultado
        assert mock_gen.call_count == 2

    def test_documento_sin_trocear_fallo_total_tras_reintentar_devuelve_none(self):
        texto = "contenido real del documento. " * 400
        with patch("deepseek_utils.generar_con_continuacion", return_value=None) as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto)
        assert resultado is None
        assert mock_gen.call_count == 2

    def test_tamano_chunk_personalizado_trocea_mas_fino(self):
        # 10/08/2026, bug real: para texto legal (mapa de artículos, que
        # exige cubrir cada artículo sin omitir ninguno) el tamaño de trozo
        # por defecto podía dejar demasiados artículos por fragmento -- un
        # tamano_chunk más pequeño debe respetarse y producir más
        # fragmentos, cada uno con menos que cubrir.
        parrafo = "a" * 5000
        texto_largo = "\n\n".join([parrafo] * 3)  # 15.000 caracteres + separadores
        respuestas = ["parcial. " * 100] * 3 + ["fusión. " * 300]
        with patch("deepseek_utils.generar_con_continuacion", side_effect=respuestas) as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes(
                "system", texto_largo, tamano_chunk=5000,
            )
        assert resultado == respuestas[-1]
        # 3 fragmentos (uno por párrafo de 5000) + 1 fusión = 4 llamadas --
        # con el tamaño por defecto (15000) habría cabido en 1 sola llamada.
        assert mock_gen.call_count == 4

    def test_documento_largo_trocea_resume_por_partes_y_funde(self):
        # Dos párrafos de ~10.000 caracteres cada uno: por separado caben en
        # un fragmento de tamaño 15.000 (el que se pasa explícitamente en
        # este test para poder ejercitar el trocear/fundir -- el tamaño por
        # defecto real, TAMANO_CHUNK_CARACTERES, se subió a 90000 a
        # petición del usuario, ver el comentario largo junto a su
        # definición), pero juntos no, así que se trocean en exactamente 2.
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"
        assert len(deepseek_utils._trocear_en_parrafos(texto_largo, tamano=15000)) == 2

        # Los parciales y la fusión final se dejan largos a propósito -- por
        # debajo de _FRACCION_MINIMA_MAP/_FRACCION_MINIMA_FUSION del tamaño
        # de entrada correspondiente, las comprobaciones de colapso (ver más
        # abajo en esta clase) los reintentarían, algo que este test no
        # quiere ejercitar.
        parcial_1 = "parcial uno. " * 150
        parcial_2 = "parcial dos. " * 150
        fusion_final = "fusión final. " * 300
        respuestas = [parcial_1, parcial_2, fusion_final]
        with patch("deepseek_utils.generar_con_continuacion", side_effect=respuestas) as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto_largo, tamano_chunk=15000)

        assert resultado == fusion_final
        # Al menos una llamada de "map" por fragmento + 1 de fusión al final.
        assert mock_gen.call_count == len(respuestas)
        ultima_llamada = mock_gen.call_args_list[-1]
        assert parcial_1 in ultima_llamada.args[1]
        assert parcial_2 in ultima_llamada.args[1]

    def test_documento_largo_donde_todos_los_fragmentos_fallan_devuelve_none(self):
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"
        with patch("deepseek_utils.generar_con_continuacion", return_value=None):
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto_largo, tamano_chunk=15000)
        assert resultado is None

    def test_documento_largo_reintenta_fragmento_fallido_y_lo_recupera(self):
        # Bug real (10/08/2026): un fallo transitorio de red en SOLO UNO de
        # varios fragmentos del MAP no debe hacer perder ese trozo del
        # documento -- se reintenta antes de rendirse, y si el reintento
        # tiene éxito, se funde igual que si hubiera funcionado a la
        # primera.
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"
        # Los parciales y la fusión final se dejan largos a propósito (no
        # frases sueltas): por debajo de _FRACCION_MINIMA_MAP/
        # _FRACCION_MINIMA_FUSION del tamaño de entrada correspondiente, las
        # comprobaciones de colapso (ver más abajo) los reintentarían, algo
        # que este test no quiere ejercitar -- aquí solo se quiere probar el
        # reintento por fallo REAL (None), no por colapso de contenido.
        parcial_2 = "parcial dos. " * 150
        parcial_1_reintentado = "parcial uno reintentado. " * 100
        fusion_final = "fusión final. " * 300
        respuestas = [None, parcial_2, parcial_1_reintentado, fusion_final]
        with patch("deepseek_utils.generar_con_continuacion", side_effect=respuestas) as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto_largo, tamano_chunk=15000)
        assert resultado == fusion_final
        assert mock_gen.call_count == 4

    def test_documento_largo_fragmento_fallido_tras_reintentar_devuelve_lo_disponible_con_aviso(self):
        # ANTES de este fix (versión intermedia, 10/08/2026): si solo
        # sobrevivía un fragmento, se devolvía tal cual como si fuera el
        # documento completo -- pasaba la validación de formato porque sí
        # traía un encabezado "# ", pero le faltaba el resto del documento
        # SIN NINGÚN AVISO (así es como un usuario real acabó con un
        # "resumen" de 14 páginas que solo tenía un párrafo). La primera
        # versión de este fix pasó al otro extremo: si un fragmento seguía
        # fallando tras reintentar, se abandonaba TODO el documento, aunque
        # el resto se hubiera generado bien -- con documentos de varios
        # fragmentos esto significaba quedarse sin nada una y otra vez.
        # AHORA: se devuelve lo que sí se generó bien, con un aviso VISIBLE
        # (no silencioso) de que falta contenido y hay que regenerar --ni
        # el fallo silencioso de antes, ni tirar contenido bueno ya pagado.
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"
        # El parcial que SÍ sobrevive se deja largo a propósito, para que no
        # dispare también él la comprobación de colapso del MAP -- este
        # test solo quiere ejercitar el fragmento que sigue fallando de
        # verdad (None) tras el reintento.
        parcial_valido = "único parcial válido. " * 100
        respuestas = [None, parcial_valido, None]
        with patch("deepseek_utils.generar_con_continuacion", side_effect=respuestas) as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto_largo, tamano_chunk=15000)
        assert resultado is not None
        assert "Aviso" in resultado
        assert "1 de 2" in resultado
        assert parcial_valido in resultado
        # Sin emoji (10/08/2026, bug real: rompía el PDF descargado -- las
        # fuentes estándar de jsPDF (WinAnsi/Latin-1) no tienen esos glifos
        # y el texto del aviso salía cortado a mitad de palabra en vez de
        # ajustarse al recuadro). Los acentos y « » sí son Latin-1 válido
        # -- solo se comprueba que no haya nada por encima de ese rango.
        assert all(ord(c) <= 255 for c in resultado.split("\n\n", 1)[0])
        # 2 llamadas del MAP inicial + 1 del reintento (que también falla).
        # Con un único fragmento aprovechable no hay fusión que intentar.
        assert mock_gen.call_count == 3

    def test_documento_largo_todos_los_fragmentos_fallan_devuelve_none(self):
        # Contraprueba del anterior: si NINGÚN fragmento sobrevive ni
        # siquiera tras reintentar, no hay nada aprovechable -- ahí sí se
        # sigue devolviendo None, como cualquier otro fallo total.
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"
        respuestas = [None, None, None, None]
        with patch("deepseek_utils.generar_con_continuacion", side_effect=respuestas) as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto_largo, tamano_chunk=15000)
        assert resultado is None
        assert mock_gen.call_count == 4

    def test_documento_largo_agota_el_tiempo_maximo_antes_de_la_fusion(self):
        # Bug real (10/08/2026): un usuario reportó una generación que se
        # quedó "Generando..." más de 10 minutos sin terminar nunca --
        # antes no había ningún tope conjunto entre las hasta 4 rondas
        # secuenciales (MAP, reintento del MAP, fusión, reintento de la
        # fusión). Con los 2 fragmentos del MAP ya generados bien (sin
        # necesitar reintento), si para cuando tocaría fundir ya se agotó
        # el tiempo máximo, se devuelven sin fundir (con aviso) en vez de
        # tirar dos fragmentos ya generados y pagados.
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"
        parcial_1 = "# Parcial uno\n" + ("contenido real del fragmento uno. " * 50)
        parcial_2 = "# Parcial dos\n" + ("contenido real del fragmento dos. " * 50)
        respuestas = [parcial_1, parcial_2]
        # time.monotonic(): 1ª llamada arma el límite (T0), 2ª llamada es la
        # ronda inicial del MAP calculando el tiempo que le queda (de sobra,
        # T0+1 -- debe completarse con éxito), 3ª llamada es la comprobación
        # justo antes de fundir, ya muy por encima de T0 + el tope. Se
        # sustituye as_completed por una versión que ignora el `timeout` (la
        # real, al recibirlo, consulta time.monotonic() ella misma
        # internamente de forma no determinista según el scheduling de
        # threads, lo que descuadraría este side_effect de longitud exacta).
        with patch("deepseek_utils.generar_con_continuacion", side_effect=respuestas) as mock_gen, \
             patch("deepseek_utils.as_completed", side_effect=_as_completed_sin_timeout), \
             patch("deepseek_utils.time.monotonic", side_effect=[0, 1, 10_000]):
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto_largo, tamano_chunk=15000)
        # No hubo fragmentos fallidos (los 2 se generaron bien) -- sin
        # fundir por falta de tiempo, pero SIN aviso de sección faltante,
        # solo sin la fusión de coherencia.
        assert parcial_1 in resultado
        assert parcial_2 in resultado
        assert "Aviso" not in resultado
        # Solo las 2 llamadas del MAP -- nunca llega a intentar la fusión.
        assert mock_gen.call_count == 2

    def test_documento_largo_agota_el_tiempo_maximo_antes_de_reintentar_un_fragmento(self):
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"
        parcial_valido = "único parcial válido. " * 100
        respuestas = [None, parcial_valido]
        with patch("deepseek_utils.generar_con_continuacion", side_effect=respuestas) as mock_gen, \
             patch("deepseek_utils.as_completed", side_effect=_as_completed_sin_timeout), \
             patch("deepseek_utils.time.monotonic", side_effect=[0, 1, 10_000]):
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto_largo, tamano_chunk=15000)
        assert parcial_valido in resultado
        assert "Aviso" in resultado
        # 2 llamadas del MAP inicial -- se agota el tiempo antes de
        # reintentar el fragmento fallido, así que no hay una 3ª llamada.
        assert mock_gen.call_count == 2

    def test_documento_largo_ronda_inicial_no_espera_mas_alla_del_tiempo_maximo(self):
        # Bug real (10/08/2026), visto en logs de producción: el tiempo total
        # (221s) superó el límite pactado (150s) porque la ronda inicial del
        # MAP, a diferencia del reintento y de la fusión, no tenía ningún
        # tope de tiempo propio -- solo se comprobaba el límite DESPUÉS de
        # esa primera ronda. Aquí se simulan fragmentos que tardan claramente
        # más que el presupuesto total: la función no debe quedarse
        # esperándolos, sino tratarlos como fallidos en cuanto se agota el
        # tiempo y (al no quedar presupuesto para reintentar) rendirse sin
        # devolver un documento incompleto -- con tiempo real de ejecución
        # acotado al presupuesto, no a la duración de los fragmentos lentos.
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"

        def _lento(*_args, **_kwargs):
            time.sleep(0.4)
            return "# Parcial\n" + ("contenido real y suficientemente largo. " * 50)

        with patch("deepseek_utils.generar_con_continuacion", side_effect=_lento), \
             patch("deepseek_utils._TIEMPO_MAXIMO_GENERACION_SEGUNDOS", 0.1):
            inicio = time.monotonic()
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto_largo, tamano_chunk=15000)
            duracion = time.monotonic() - inicio
        assert resultado is None
        # No debe esperar los 0.4s completos de los fragmentos -- se
        # abandona en cuanto se agota el presupuesto (0.1s), con margen
        # amplio para el resto de comprobaciones (reintento saltado, etc.).
        assert duracion < 0.3

    def test_ronda_inicial_lanza_mas_de_4_fragmentos_a_la_vez(self):
        # Bug real (10/08/2026): con max_workers fijo en 4, un documento de
        # más de 4 fragmentos (nada raro en modo legal con tamano_chunk=8000
        # -- un documento de ~51.000 caracteres da 7) se partía en tandas
        # secuenciales de 4+3, duplicando el tiempo de pared necesario sin
        # ninguna ventaja real: el semáforo global _MAX_LLAMADAS_SIMULTANEAS_
        # DEEPSEEK ya limita la concurrencia hacia DeepSeek de toda la app.
        # Con 6 fragmentos (más de los 4 de antes, por debajo de las 8
        # llamadas simultáneas que ya permite ese semáforo) deben arrancar
        # todos a la vez, no en dos tandas.
        parrafo = "a" * 5000
        texto_largo = "\n\n".join([parrafo] * 6)
        maximo_concurrentes = {"valor": 0}
        concurrentes_ahora = {"valor": 0}
        lock = threading.Lock()

        def _generar(*_args, **_kwargs):
            with lock:
                concurrentes_ahora["valor"] += 1
                maximo_concurrentes["valor"] = max(maximo_concurrentes["valor"], concurrentes_ahora["valor"])
            time.sleep(0.05)
            with lock:
                concurrentes_ahora["valor"] -= 1
            return "# Parcial\n" + ("contenido real y suficientemente largo. " * 50)

        with patch("deepseek_utils.generar_con_continuacion", side_effect=_generar):
            deepseek_utils.generar_documento_largo_por_partes("system", texto_largo, tamano_chunk=5000)
        assert maximo_concurrentes["valor"] > 4

    def test_documento_largo_fusion_colapsada_se_reintenta_y_se_recupera(self):
        # Bug real (10/08/2026), distinto del de fragmentos fallidos de
        # arriba: con TODOS los fragmentos del MAP generados y válidos por
        # separado, la llamada de FUSIÓN en sí a veces colapsaba -- el
        # modelo respondía con solo una fracción mínima del contenido y
        # paraba de forma NATURAL (sin marcar finish_reason=length, así que
        # generar_con_continuacion no lo detecta como truncado). Como el
        # resultado sí tenía un encabezado Markdown válido, pasaba la
        # validación de formato sin levantar sospecha -- así es como un
        # usuario real acabó con un "resumen" de 14 páginas reducido a un
        # solo párrafo. Se reintenta la fusión una vez antes de rendirse.
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"
        parcial_1 = "# Parcial uno\n" + ("contenido real del fragmento uno. " * 50)
        parcial_2 = "# Parcial dos\n" + ("contenido real del fragmento dos. " * 50)
        fusion_colapsada = "# Solo esto"
        fusion_completa = "# Fusión completa\n" + ("todo el contenido fusionado. " * 80)
        respuestas = [parcial_1, parcial_2, fusion_colapsada, fusion_completa]
        with patch("deepseek_utils.generar_con_continuacion", side_effect=respuestas) as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto_largo, tamano_chunk=15000)
        assert resultado == fusion_completa
        assert mock_gen.call_count == 4

    def test_documento_largo_fusion_colapsada_tras_reintentar_devuelve_los_parciales_sin_fundir(self):
        # Si la fusión sigue colapsando tras reintentar, los DOS parciales
        # ya se generaron bien por separado -- tirarlos sería desperdiciar
        # contenido bueno y ya pagado solo porque el paso de FUSIÓN (que
        # solo reordena/dedup, no genera contenido nuevo) falló. Se
        # devuelven sin fundir en vez de nada.
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"
        parcial_1 = "# Parcial uno\n" + ("contenido real del fragmento uno. " * 50)
        parcial_2 = "# Parcial dos\n" + ("contenido real del fragmento dos. " * 50)
        fusion_colapsada = "# Solo esto"
        respuestas = [parcial_1, parcial_2, fusion_colapsada, fusion_colapsada]
        with patch("deepseek_utils.generar_con_continuacion", side_effect=respuestas) as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto_largo, tamano_chunk=15000)
        assert parcial_1 in resultado
        assert parcial_2 in resultado
        assert "Aviso" not in resultado
        assert mock_gen.call_count == 4

    def test_documento_largo_fragmento_map_colapsado_se_reintenta_y_se_recupera(self):
        # Bug real (10/08/2026), distinto de la fusión colapsada de arriba:
        # con un documento real de 4 fragmentos de ~15.000 caracteres cada
        # uno, el colapso no siempre pasaba en la fusión -- a veces el
        # propio fragmento (el que contenía las disposiciones adicionales
        # del final de la ley) ya venía degenerado del MAP, cubriendo solo
        # su último apartado en vez de todo su contenido. La comprobación
        # de la fusión no lo detectaba porque compara la fusión contra la
        # SUMA de los parciales recibidos -- si un parcial YA era pequeño,
        # la fusión podía "conservarlo fielmente" y aun así pasar esa
        # comprobación. Ahora cada parcial se compara también contra el
        # tamaño de SU PROPIO fragmento de entrada.
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"
        parcial_1_colapsado = "# Solo esto"
        parcial_1_recuperado = "# Parcial uno recuperado\n" + ("contenido real del fragmento uno. " * 50)
        parcial_2 = "# Parcial dos\n" + ("contenido real del fragmento dos. " * 50)
        fusion_completa = "# Fusión completa\n" + ("todo el contenido fusionado. " * 80)
        respuestas = [parcial_1_colapsado, parcial_2, parcial_1_recuperado, fusion_completa]
        with patch("deepseek_utils.generar_con_continuacion", side_effect=respuestas) as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto_largo, tamano_chunk=15000)
        assert resultado == fusion_completa
        assert mock_gen.call_count == 4

    def test_documento_largo_fragmento_map_colapsado_tras_reintentar_devuelve_lo_disponible_con_aviso(self):
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"
        parcial_1_colapsado = "# Solo esto"
        parcial_2 = "# Parcial dos\n" + ("contenido real del fragmento dos. " * 50)
        respuestas = [parcial_1_colapsado, parcial_2, parcial_1_colapsado]
        with patch("deepseek_utils.generar_con_continuacion", side_effect=respuestas) as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto_largo, tamano_chunk=15000)
        assert parcial_2 in resultado
        assert "Aviso" in resultado
        assert "1 de 2" in resultado
        # 2 llamadas del MAP inicial + 1 del reintento del fragmento
        # colapsado (que sigue devolviendo lo mismo) -- con un único
        # fragmento aprovechable no hay fusión que intentar, así que no hay
        # una 4ª llamada.
        assert mock_gen.call_count == 3

    def test_fraccion_minima_personalizada_acepta_un_resultado_compacto_pero_completo(self):
        # Bug real (10/08/2026): un esquema (árbol de epígrafes en viñetas,
        # sin prosa) es, por diseño, mucho más compacto que su fuente
        # incluso estando completo y bien hecho -- con los umbrales por
        # defecto (calibrados para un resumen narrativo) un esquema así se
        # marcaba como "colapsado" y acababa abandonándose. Con un umbral
        # más bajo pasado explícitamente (el mismo que usa la ruta real de
        # /generar-esquema-desde-pdf), el mismo resultado compacto se acepta
        # sin reintentar.
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"
        # Cada parcial cubre ~9% de su fragmento de entrada (10.000
        # caracteres) -- por debajo de _FRACCION_MINIMA_MAP (0.15) pero por
        # encima de FRACCION_MINIMA_MAP_ESQUEMA (0.08).
        parcial_compacto_1 = "# Uno\n" + ("- **Art. 1.** contenido breve.\n" * 30)
        parcial_compacto_2 = "# Dos\n" + ("- **Art. 2.** contenido breve.\n" * 30)
        fusion_compacta = "# Fusión\n" + ("- **Art. 1.** contenido breve.\n" * 55)
        respuestas = [parcial_compacto_1, parcial_compacto_2, fusion_compacta]
        with patch("deepseek_utils.generar_con_continuacion", side_effect=respuestas) as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes(
                "system", texto_largo, tamano_chunk=15000,
                fraccion_minima_map=deepseek_utils.FRACCION_MINIMA_MAP_ESQUEMA,
                fraccion_minima_fusion=deepseek_utils.FRACCION_MINIMA_FUSION_ESQUEMA,
            )
        assert resultado == fusion_compacta
        # Sin reintentos: ni el MAP ni la fusión se consideraron sospechosos.
        assert mock_gen.call_count == 3

    def test_fraccion_minima_por_defecto_rechaza_ese_mismo_resultado_compacto(self):
        # Contraprueba de la anterior: el MISMO par de parciales, con los
        # umbrales GENERALES (los que usa /resumir-pdf), sí se considera
        # sospechoso -- confirma que el umbral más bajo del esquema es lo
        # que marca la diferencia, no un cambio de comportamiento general.
        parrafo = "a" * 10000
        texto_largo = f"{parrafo}\n\n{parrafo}"
        parcial_compacto_1 = "# Uno\n" + ("- **Art. 1.** contenido breve.\n" * 30)
        parcial_compacto_2 = "# Dos\n" + ("- **Art. 2.** contenido breve.\n" * 30)
        # Reintentos del MAP: devuelven lo mismo (igual de compacto), así
        # que siguen sospechosos y la función se rinde sin llegar a fundir.
        respuestas = [parcial_compacto_1, parcial_compacto_2, parcial_compacto_1, parcial_compacto_2]
        with patch("deepseek_utils.generar_con_continuacion", side_effect=respuestas) as mock_gen:
            resultado = deepseek_utils.generar_documento_largo_por_partes("system", texto_largo, tamano_chunk=15000)
        assert resultado is None
        assert mock_gen.call_count == 4


class TestDetectarTextoLegal:
    # detectar_texto_legal (05/08/2026): heurística por regex, SIN llamar a
    # DeepSeek, para que /resumir-pdf y /generar-esquema-desde-pdf puedan
    # aplicar un formato de "mapa de artículos" a texto legal en vez del
    # resumen/esquema narrativo de siempre. Exige densidad de coincidencias
    # (por 1.000 caracteres), al menos dos TIPOS de patrón distintos y un
    # suelo absoluto de coincidencias -- ver el comentario largo junto a
    # _PATRONES_TEXTO_LEGAL para el porqué de cada uno.
    _EXTRACTO_LEGAL = (
        "Artículo 1. Objeto y ámbito de aplicación.\n"
        "La presente Ley 39/2015 regula los requisitos de validez y eficacia de los "
        "actos administrativos, el procedimiento administrativo común y los principios "
        "a los que se ha de ajustar el ejercicio de la iniciativa legislativa y la "
        "potestad reglamentaria.\n\n"
        "Artículo 2. Ámbito subjetivo de aplicación.\n"
        "Esta ley se aplica al sector público, que comprende la Administración General "
        "del Estado, las Administraciones de las Comunidades Autónomas y las Entidades "
        "que integran la Administración Local.\n\n"
        "Artículo 3. Principios generales.\n"
        "Las Administraciones Públicas sirven con objetividad los intereses generales "
        "y actúan de acuerdo con los principios de eficacia, jerarquía, "
        "descentralización, desconcentración y coordinación.\n\n"
        "Artículo 4. Interesados en el procedimiento.\n"
        "Se consideran interesados en el procedimiento administrativo quienes lo "
        "promuevan como titulares de derechos o intereses legítimos.\n\n"
        "Disposición adicional primera. Especialidades por razón de materia.\n"
        "Las previsiones de esta Ley se aplicarán sin perjuicio de las especialidades "
        "que resulten de su legislación específica en las materias que así lo "
        "requieran.\n\n"
        "Disposición final primera. Título competencial.\n"
        "Esta Ley se dicta al amparo del artículo 149.1.18ª de la Constitución "
        "Española, que atribuye al Estado la competencia sobre las bases del régimen "
        "jurídico de las Administraciones Públicas.\n\n"
        "El Real Decreto 203/2021, de 30 de marzo, aprueba el Reglamento de actuación "
        "y funcionamiento del sector público por medios electrónicos, desarrollando lo "
        "previsto en el artículo 14 de esta misma norma."
    )
    _EXTRACTO_NARRATIVO = (
        "El proceso de construcción europea comenzó tras la Segunda Guerra Mundial, con "
        "el objetivo de garantizar la paz y la prosperidad en el continente a través de "
        "la cooperación económica. Los llamados Padres Fundadores de Europa, entre los "
        "que destacan Jean Monnet y Robert Schuman, impulsaron la creación de la "
        "Comunidad Europea del Carbón y del Acero en 1951, germen de lo que hoy "
        "conocemos como la Unión Europea.\n\n"
        "A lo largo de las décadas siguientes, el proyecto europeo fue ampliándose tanto "
        "en número de países miembros como en ámbitos de actuación. España se incorporó "
        "a la entonces Comunidad Económica Europea en 1986, un hito que marcó un antes y "
        "un después en la modernización de su economía y sus instituciones."
    ) * 3

    def test_texto_legal_real_se_detecta_como_legal(self):
        assert deepseek_utils.detectar_texto_legal(self._EXTRACTO_LEGAL) is True

    def test_texto_narrativo_normal_no_se_detecta_como_legal(self):
        assert deepseek_utils.detectar_texto_legal(self._EXTRACTO_NARRATIVO) is False

    def test_texto_vacio_no_es_legal(self):
        assert deepseek_utils.detectar_texto_legal("") is False
        assert deepseek_utils.detectar_texto_legal(None) is False

    def test_una_mencion_incidental_corta_no_basta_por_el_suelo_absoluto(self):
        # Solo 3 coincidencias en total (una por tipo) -- por debajo de
        # _UMBRAL_MATCHES_ABSOLUTOS_LEGAL aunque la DENSIDAD por ser un
        # texto corto sea alta. Sin el suelo absoluto, este extracto se
        # marcaría como legal solo por tener pocos caracteres.
        texto = (
            "La reforma de la Administración Pública ha sido un proceso constante. "
            "Recientemente, el Real Decreto 203/2021 aprobó el reglamento de "
            "actuación por medios electrónicos, consolidando lo que ya apuntaba el "
            "artículo 14 de la Ley 39/2015 sobre relación electrónica con las "
            "Administraciones Públicas."
        )
        assert deepseek_utils.detectar_texto_legal(texto) is False

    def test_un_unico_tipo_de_patron_repetido_no_basta_por_falta_de_diversidad(self):
        # Muchas coincidencias, pero todas del MISMO tipo ("artículo N") --
        # _UMBRAL_TIPOS_DISTINTOS_LEGAL exige al menos dos tipos de patrón
        # distintos, para no disparar el modo legal solo porque un temario
        # general cita bastante la palabra "artículo".
        texto = " ".join(f"El artículo {n} trata un aspecto distinto del tema." for n in range(1, 20))
        assert deepseek_utils.detectar_texto_legal(texto) is False
