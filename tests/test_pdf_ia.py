"""Pruebas de blueprints/pdf_ia.py: _extraer_json_array (la reparación de
JSON de la respuesta de la IA, antes sin ningún test) y las rutas HTTP
más críticas -- las 4 de /guardar-*-pdf (persisten contenido y actualizan
estadísticas) y un test de humo de /resumir-pdf y /generar-test-desde-pdf
con DeepSeek mockeado. El resto de las ~20 rutas de este blueprint queda
fuera de esta tanda (desproporcionado para el alcance aprobado)."""
import itertools
import json
import re
import pytest
from unittest.mock import patch

from blueprints.pdf_ia import _extraer_json_array
from conftest import sembrar_usuario_activo


def _con_sesion(cliente, uid="u1", email="u1@example.com"):
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email})
    parche.start()
    return parche


def _eventos_sse(cuerpo_respuesta):
    return [
        json.loads(linea[len("data: "):])
        for linea in cuerpo_respuesta.split("\n\n")
        if linea.startswith("data: ")
    ]


class TestExtraerJsonArray:
    def test_json_valido(self):
        assert _extraer_json_array('[{"a": 1}]') == [{"a": 1}]

    def test_json_con_comillas_simples(self):
        assert _extraer_json_array("[{'a': 1}]") == [{"a": 1}]

    def test_array_envuelto_en_texto_explicativo(self):
        texto = 'Aquí tienes el resultado:\n[{"a": 1}, {"b": 2}]\n¡Espero que te sirva!'
        assert _extraer_json_array(texto) == [{"a": 1}, {"b": 2}]

    def test_sin_corchetes_lanza_value_error(self):
        with pytest.raises(ValueError):
            _extraer_json_array("esto no tiene ningún array")

    def test_json_irrecuperable_lanza_value_error(self):
        with pytest.raises(ValueError):
            _extraer_json_array("[esto no es json ni con comillas arregladas]")


@pytest.fixture
def documento_sembrado(db):
    # Se siembra también "usuarios/u1" (con un plan de pago activo, ya que
    # las herramientas de PDF exigen Premium) para que requiere_login no
    # dispare el email de bienvenida de un usuario "nuevo" en cada test
    # (ruido de red real hacia Brevo sin mockear, sin afectar al resultado
    # del test pero sí ensuciando la salida).
    sembrar_usuario_activo(db, "u1", plan="premium")
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {
        "texto": "Texto del documento de prueba.",
        "nombre_archivo": "doc.pdf",
    })
    return "d1"


class TestRutasGuardarPdf:
    """Las 4 rutas /guardar-*-pdf: persisten el contenido ya generado (no
    vuelven a llamar a DeepSeek) y actualizan las estadísticas del
    usuario vía guardar_resultado_en_firestore."""

    def test_guardar_test_pdf(self, client, db, documento_sembrado):
        # Bug real: el intento (respuestas del usuario, aciertos/fallos) no
        # se guardaba en ningún sitio -- solo se incrementaba el contador de
        # uso de la herramienta -- así que un test desde PDF nunca aparecía
        # en Mis Tests ni en las estadísticas. Ahora debe quedar guardado en
        # la MISMA colección "tests" que usan test-personalizado/oficial/etc,
        # con las respuestas y el acierto ya calculado por pregunta.
        parche = _con_sesion(client)
        try:
            resp = client.post("/guardar-test-pdf", json={
                "test_data": {
                    "preguntas": [
                        {"pregunta": "?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"}, "respuesta_correcta": "A"},
                        {"pregunta": "??", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"}, "respuesta_correcta": "B"},
                    ],
                    "respuestas": ["A", "C"],
                    "metadatos": {"tiempo": 42},
                },
                "documento_id": documento_sembrado,
                "nombre_archivo": "doc.pdf",
                "oposicion": "AGE",
                "test_id": "t1",
            }, headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        assert db.leer(("usuarios", "u1"))["tests_pdf_realizados"] == 1

        test_guardado = db.leer(("usuarios", "u1", "tests", "t1"))
        assert test_guardado is not None
        assert test_guardado["tipo"] == "test_pdf"
        assert test_guardado["estado"] == "finalizado"
        assert test_guardado["aciertos"] == 1
        assert test_guardado["fallos"] == 1
        assert test_guardado["preguntas"][0]["respuesta_usuario"] == "A"
        assert test_guardado["preguntas"][0]["acierto"] is True
        assert test_guardado["preguntas"][1]["respuesta_usuario"] == "C"
        assert test_guardado["preguntas"][1]["acierto"] is False

    def test_guardar_resumen_pdf(self, client, db, documento_sembrado):
        parche = _con_sesion(client)
        try:
            resp = client.post("/guardar-resumen-pdf", json={
                "resumen": "# Resumen\n- Punto 1",
                "documento_id": documento_sembrado,
                "nombre_archivo": "doc.pdf",
            }, headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        assert db.leer(("usuarios", "u1"))["resumenes_pdf_realizados"] == 1

    def test_guardar_esquema_pdf(self, client, db, documento_sembrado):
        parche = _con_sesion(client)
        try:
            resp = client.post("/guardar-esquema-pdf", json={
                "esquema": "# Esquema\n- Punto 1",
                "documento_id": documento_sembrado,
                "nombre_archivo": "doc.pdf",
            }, headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        assert db.leer(("usuarios", "u1"))["esquemas_pdf_realizados"] == 1

    def test_guardar_tarjetas_pdf(self, client, db, documento_sembrado):
        parche = _con_sesion(client)
        try:
            resp = client.post("/guardar-tarjetas-pdf", json={
                "tarjetas": [{"pregunta": "?", "respuesta": "!"}],
                "documento_id": documento_sembrado,
                "nombre_archivo": "doc.pdf",
            }, headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        assert db.leer(("usuarios", "u1"))["tarjetas_pdf_realizados"] == 1

    def test_guardar_resumen_pdf_requiere_login(self, client):
        resp = client.post("/guardar-resumen-pdf", json={"resumen": "x"})
        assert resp.status_code == 401


class TestSubidaArchivoInvalido:
    """Un archivo que no es un PDF real (p. ej. un ejecutable renombrado a
    .pdf) debe rechazarse con un 400 y un mensaje claro para el usuario --
    antes reventaba el parseo y salía un 500 genérico (y en el chat-PDF,
    con el texto interno de la excepción filtrado al cliente)."""

    ARCHIVO_FALSO = b"MZ\x90\x00\x03esto no es un PDF de verdad"

    def test_resumir_pdf_con_archivo_no_pdf_da_400_claro(self, client, documento_sembrado):
        from io import BytesIO
        parche = _con_sesion(client)
        try:
            resp = client.post("/resumir-pdf",
                                data={"pdf": (BytesIO(self.ARCHIVO_FALSO), "falso.pdf")},
                                headers={"Authorization": "Bearer x"},
                                content_type="multipart/form-data")
        finally:
            parche.stop()
        assert resp.status_code == 400
        assert "no es un PDF válido" in resp.get_json()["error"]

    def test_subir_pdf_chat_con_archivo_no_pdf_da_400_claro(self, client, documento_sembrado):
        from io import BytesIO
        parche = _con_sesion(client)
        try:
            resp = client.post("/subir-pdf-chat",
                                data={"pdf": (BytesIO(self.ARCHIVO_FALSO), "falso.pdf")},
                                headers={"Authorization": "Bearer x"},
                                content_type="multipart/form-data")
        finally:
            parche.stop()
        assert resp.status_code == 400
        assert "no es un PDF válido" in resp.get_json()["error"]


class TestResumirPdfYGenerarTestDesdePdf:
    """Test de humo: la ruta llega hasta el punto de generación con IA
    (mockeada) y devuelve el resultado esperado, sin ejercer aquí toda la
    lógica interna de deepseek_utils (ya cubierta en test_deepseek_utils.py)."""

    def test_resumir_pdf(self, client, documento_sembrado):
        # En streaming (SSE, mismo patrón que /generar-test-desde-pdf): el
        # resultado llega en el evento "fin" del cuerpo, no como JSON directo.
        parche = _con_sesion(client)
        try:
            with patch("blueprints.pdf_ia.generar_documento_largo_por_partes", return_value="# Resumen generado"), \
                 patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}):
                resp = client.post("/resumir-pdf", data={"documento_id": documento_sembrado},
                                    headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        eventos = _eventos_sse(resp.get_data(as_text=True))
        assert eventos[-1]["tipo"] == "fin"
        assert eventos[-1]["resumen"] == "# Resumen generado"

    def test_resumir_pdf_sin_api_key_da_error_500(self, client, documento_sembrado, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        parche = _con_sesion(client)
        try:
            resp = client.post("/resumir-pdf", data={"documento_id": documento_sembrado},
                                headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 500

    def test_generar_test_desde_pdf(self, client, db, documento_sembrado):
        # En streaming (SSE, mismo patrón que /generar-test-avanzado): el
        # resultado llega en el evento "fin" del cuerpo, no como JSON directo
        # -- el status HTTP es 200 tanto en éxito como en fallo de generación.
        preguntas_generadas = [{
            "pregunta": "¿Pregunta?",
            "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
            "respuesta_correcta": "A",
            "explicacion": "porque sí",
        }]
        parche = _con_sesion(client)
        try:
            with patch("blueprints.pdf_ia.generar_preguntas_ia_en_lotes", return_value=(preguntas_generadas, [])):
                resp = client.post("/generar-test-desde-pdf", data={
                    "documento_id": documento_sembrado, "num_preguntas": "1"
                }, headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        eventos = _eventos_sse(resp.get_data(as_text=True))
        assert eventos[-1]["tipo"] == "fin"
        assert len(eventos[-1]["test"]) == 1
        # También se factura el uso solo cuando la generación tuvo éxito.
        assert db.leer(("usuarios", "u1"))["limites_uso"]["pdf_ia"]["contador"] == 1

    def test_generar_test_desde_pdf_sin_preguntas_no_factura_uso(self, client, db, documento_sembrado):
        parche = _con_sesion(client)
        try:
            with patch("blueprints.pdf_ia.generar_preguntas_ia_en_lotes", return_value=([], ["fallo de la IA"])):
                resp = client.post("/generar-test-desde-pdf", data={"documento_id": documento_sembrado},
                                    headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        eventos = _eventos_sse(resp.get_data(as_text=True))
        assert eventos[-1]["tipo"] == "fin"
        assert eventos[-1]["test"] == []
        assert "error" in eventos[-1]
        # Fallo técnico real (no de verificación) -- se mantiene el mensaje
        # genérico existente.
        assert "Error técnico" in eventos[-1]["error"]
        # El uso se cobra por adelantado (antes de abrir el stream) y, como la
        # generación no produjo ni una pregunta, el hilo de fondo lo devuelve:
        # el neto debe quedar en 0 (no se consume cuota por una generación
        # fallida, pero el contador ya existe por el cobro+devolución).
        assert db.leer(("usuarios", "u1"))["limites_uso"]["pdf_ia"]["contador"] == 0

    def test_generar_test_desde_pdf_documento_corto_da_mensaje_honesto(self, client, db, documento_sembrado):
        # Si el PDF no tiene contenido suficiente para las preguntas pedidas,
        # TODAS las candidatas pueden fallar la verificación de calidad sin
        # que haya habido ningún fallo técnico de DeepSeek (ver
        # test_generator.py, _pedir_lote_verificado) -- el mensaje debe
        # explicar esto en vez de hablar de un "error técnico" de JSON.
        errores_verificacion = ["Ninguna de las 15 preguntas candidatas de un lote superó la verificación de calidad"]
        parche = _con_sesion(client)
        try:
            with patch("blueprints.pdf_ia.generar_preguntas_ia_en_lotes", return_value=([], errores_verificacion)):
                resp = client.post("/generar-test-desde-pdf", data={
                    "documento_id": documento_sembrado, "num_preguntas": "40"
                }, headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        eventos = _eventos_sse(resp.get_data(as_text=True))
        assert eventos[-1]["test"] == []
        assert "Error técnico" not in eventos[-1]["error"]
        assert "40" in eventos[-1]["error"]
        assert "demasiado corto" in eventos[-1]["error"]


class TestGenerarEsquemaDesdePdf:
    """Mismo patrón de test de humo que TestResumirPdfYGenerarTestDesdePdf --
    hasta ahora esta ruta no tenía ningún test."""

    def test_generar_esquema_desde_pdf(self, client, db, documento_sembrado):
        # En streaming (SSE): el resultado llega en el evento "fin".
        parche = _con_sesion(client)
        try:
            with patch("blueprints.pdf_ia.generar_documento_largo_por_partes", return_value="# Esquema generado"), \
                 patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}):
                resp = client.post("/generar-esquema-desde-pdf", data={"documento_id": documento_sembrado},
                                    headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        eventos = _eventos_sse(resp.get_data(as_text=True))
        assert eventos[-1]["tipo"] == "fin"
        assert eventos[-1]["esquema"] == "# Esquema generado"
        assert db.leer(("usuarios", "u1"))["limites_uso"]["pdf_ia"]["contador"] == 1

    def test_generar_esquema_desde_pdf_sin_api_key_da_error_500(self, client, documento_sembrado, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        parche = _con_sesion(client)
        try:
            resp = client.post("/generar-esquema-desde-pdf", data={"documento_id": documento_sembrado},
                                headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 500

    def test_generar_esquema_desde_pdf_error_deepseek_no_factura_uso(self, client, db, documento_sembrado):
        # Ahora en streaming: un fallo de generación llega como evento "fin"
        # con error, con status HTTP 200 igual que en éxito (ver
        # test_generar_test_desde_pdf_sin_preguntas_no_factura_uso). El uso
        # se cobra por adelantado y se devuelve al fallar, así que el
        # contador neto queda en 0 (no ausente).
        parche = _con_sesion(client)
        try:
            with patch("blueprints.pdf_ia.generar_documento_largo_por_partes", return_value=None), \
                 patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}):
                resp = client.post("/generar-esquema-desde-pdf", data={"documento_id": documento_sembrado},
                                    headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        eventos = _eventos_sse(resp.get_data(as_text=True))
        assert eventos[-1]["tipo"] == "fin"
        assert "error" in eventos[-1]
        assert db.leer(("usuarios", "u1"))["limites_uso"]["pdf_ia"]["contador"] == 0


class TestGenerarTarjetasDesdePdf:
    """Ruta rediseñada sobre tarjetas_generator.generar_tarjetas_verificadas
    (pipeline generar->verificar->reintentar) -- hasta ahora sin ningún
    test. El pipeline en sí (verificación, reparto, dedup) se prueba en
    tests/test_tarjetas_generator.py; aquí solo se comprueba que la ruta
    HTTP conecta bien con él (parseo de num_tarjetas, facturación de cupo,
    manejo de errores)."""

    def test_generar_tarjetas_desde_pdf(self, client, db, documento_sembrado):
        # En streaming (SSE): el resultado llega en el evento "fin".
        resultado = {"tarjetas": [{"pregunta": "¿?", "respuesta": "!"}], "descartadas": 0}
        parche = _con_sesion(client)
        try:
            with patch("blueprints.pdf_ia.generar_tarjetas_verificadas", return_value=resultado), \
                 patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}):
                resp = client.post("/generar-tarjetas-desde-pdf",
                                    data={"documento_id": documento_sembrado, "num_tarjetas": "1"},
                                    headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        eventos = _eventos_sse(resp.get_data(as_text=True))
        datos = eventos[-1]
        assert datos["tipo"] == "fin"
        assert datos["tarjetas"] == [{"pregunta": "¿?", "respuesta": "!"}]
        assert "advertencia" not in datos
        assert db.leer(("usuarios", "u1"))["limites_uso"]["pdf_ia"]["contador"] == 1

    def test_generar_tarjetas_desde_pdf_con_advertencia_por_recorte(self, client, documento_sembrado):
        resultado = {"tarjetas": [{"pregunta": "¿?", "respuesta": "!"}], "descartadas": 2,
                     "advertencia": "Se generaron 1 de 3 tarjetas -- el resto no llegó a superar la verificación."}
        parche = _con_sesion(client)
        try:
            with patch("blueprints.pdf_ia.generar_tarjetas_verificadas", return_value=resultado), \
                 patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}):
                resp = client.post("/generar-tarjetas-desde-pdf",
                                    data={"documento_id": documento_sembrado, "num_tarjetas": "3"},
                                    headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        eventos = _eventos_sse(resp.get_data(as_text=True))
        assert eventos[-1]["advertencia"] == resultado["advertencia"]

    def test_generar_tarjetas_desde_pdf_sin_tarjetas_no_factura_uso(self, client, db, documento_sembrado):
        # Ahora en streaming: fallo real llega como evento "fin" con error,
        # con status HTTP 200 (no 500). El uso se cobra por adelantado y se
        # devuelve al fallar, así que el contador neto queda en 0 (no ausente).
        resultado = {"tarjetas": [], "descartadas": 1, "advertencia": "No se pudo verificar ninguna tarjeta."}
        parche = _con_sesion(client)
        try:
            with patch("blueprints.pdf_ia.generar_tarjetas_verificadas", return_value=resultado), \
                 patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}):
                resp = client.post("/generar-tarjetas-desde-pdf", data={"documento_id": documento_sembrado},
                                    headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        eventos = _eventos_sse(resp.get_data(as_text=True))
        assert "error" in eventos[-1]
        assert db.leer(("usuarios", "u1"))["limites_uso"]["pdf_ia"]["contador"] == 0

    def test_generar_tarjetas_desde_pdf_sin_api_key_da_error_500(self, client, documento_sembrado, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        parche = _con_sesion(client)
        try:
            resp = client.post("/generar-tarjetas-desde-pdf", data={"documento_id": documento_sembrado},
                                headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 500

    def test_generar_tarjetas_desde_pdf_num_tarjetas_se_acota_entre_1_y_50(self, client, documento_sembrado):
        parche = _con_sesion(client)
        try:
            with patch("blueprints.pdf_ia.generar_tarjetas_verificadas",
                       return_value={"tarjetas": [], "descartadas": 0}) as mock_generar, \
                 patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}):
                resp = client.post("/generar-tarjetas-desde-pdf",
                                    data={"documento_id": documento_sembrado, "num_tarjetas": "500"},
                                    headers={"Authorization": "Bearer x"})
                # Drena el stream SSE (dentro del "with patch") para asegurar
                # que el hilo de fondo ya llamó al mock antes de comprobarlo.
                resp.get_data()
        finally:
            parche.stop()
        assert mock_generar.call_args.args[1] == 50


class _FakeRespuestaDeepSeek:
    """Simula el objeto que devuelve requests.post: lo mínimo que
    _post_deepseek_con_reintentos y call_deepseek_api necesitan
    (status_code, raise_for_status, json())."""
    def __init__(self, contenido, usage):
        self._contenido = contenido
        self._usage = usage
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {
            "choices": [{"message": {"content": self._contenido}, "finish_reason": "stop"}],
            "usage": self._usage,
        }


class TestCosteIaEnHerramientasPdf:
    """El audit detectó que el coste de IA se perdía en silencio en las 4
    herramientas de PDF, por 3 motivos de hilos distintos -- estas pruebas
    documentan que, tras el arreglo (AcumuladorTokens + on_usage), el coste
    SÍ llega a usuarios/{uid}.coste_ia para cada una."""

    def _mes_actual(self):
        from datetime import datetime
        return datetime.utcnow().strftime("%Y-%m")

    def test_resumen_chunked_no_pierde_el_coste_del_map(self, client, db):
        # 3 párrafos de 8000 caracteres cada uno (24000 en total): con el
        # tamaño de trozo real (15000), ningún par de párrafos consecutivos
        # cabe junto en un mismo fragmento (8000+8000+2 > 15000), así que
        # cada uno acaba en su propio fragmento -- el MAP corre de verdad
        # dentro del ThreadPoolExecutor (el caso que antes perdía el coste).
        sembrar_usuario_activo(db, "u1", plan="premium")
        texto = ("A" * 8000) + "\n\n" + ("B" * 8000) + "\n\n" + ("C" * 8000)
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {"texto": texto, "nombre_archivo": "doc.pdf"})

        def fake_post(url, headers=None, json=None, timeout=None, stream=False):
            return _FakeRespuestaDeepSeek("Resumen parcial.", {"prompt_tokens": 100, "completion_tokens": 50})

        parche = _con_sesion(client)
        try:
            with patch("deepseek_utils.requests.post", side_effect=fake_post), \
                 patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}):
                resp = client.post("/resumir-pdf", data={"documento_id": "d1"},
                                    headers={"Authorization": "Bearer x"})
                # /resumir-pdf va en streaming SSE: hay que drenar el cuerpo
                # (dentro del "with patch") para asegurar que el hilo de
                # fondo ya terminó antes de leer los costes de Firestore
                # (mismo motivo que test_generar_test_desde_pdf_con_varios_lotes_registra_coste).
                resp.get_data()
        finally:
            parche.stop()

        assert resp.status_code == 200
        # 3 fragmentos (MAP) + 1 fusión (REDUCE) = 4 llamadas -- si el coste
        # del MAP se perdiera (el bug original), solo se contarían 100/50.
        coste = db.leer(("usuarios", "u1"))["coste_ia"][self._mes_actual()]
        assert coste["tokens_in"] == 400
        assert coste["tokens_out"] == 200
        assert coste["llamadas"] == 4

    def test_generar_test_desde_pdf_con_varios_lotes_registra_coste(self, client, db, documento_sembrado):
        contador = itertools.count()

        def fake_call(messages, on_usage=None, **kwargs):
            if on_usage:
                on_usage({"prompt_tokens": 20, "completion_tokens": 10})
            # La verificación EN BLOQUE (ver test_generator._verificar_lote)
            # manda system+user con "PREGUNTAS A VERIFICAR:" (plural) --
            # se distingue así de la generación (un único mensaje "user").
            if len(messages) == 2 and messages[0]["role"] == "system":
                textos = re.findall(r'"pregunta":\s*"([^"]*)"', messages[1]["content"])
                return json.dumps({"resultados": [
                    {"indice": i, "valido": True, "problemas": []} for i in range(len(textos))
                ]})
            # Cada lote genera tantas preguntas (únicas) como se le pidieron
            # -- así se completan las 20 solicitadas sin relleno, que
            # multiplicaría las llamadas de forma impredecible para este
            # test de conteo de coste (ver test_test_generator.py para el
            # comportamiento de relleno en sí).
            match = re.search(r"generar EXACTAMENTE (\d+) preguntas", messages[0]["content"])
            n = int(match.group(1)) if match else 1
            return json.dumps([
                {"pregunta": f"¿P{next(contador)}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."}
                for _ in range(n)
            ])

        parche = _con_sesion(client)
        try:
            with patch("test_generator.call_deepseek_api", side_effect=fake_call):
                # /generar-test-desde-pdf va en streaming SSE: el hilo de fondo
                # sigue generando lotes en paralelo mientras el cliente todavía
                # está leyendo eventos, y Werkzeug no drena el generador entero
                # dentro de client.post() (solo el primer trozo) -- el resto se
                # consume al llamar a get_data(). Si esa llamada queda fuera del
                # "with patch", el hilo de fondo puede seguir corriendo ya sin
                # mock (con DeepSeek real, sin API key) y perder alguna llamada
                # de un lote que todavía no había terminado, dando un recuento
                # de coste intermitente por debajo de lo esperado.
                resp = client.post("/generar-test-desde-pdf", data={
                    "documento_id": documento_sembrado, "num_preguntas": "20"
                }, headers={"Authorization": "Bearer x"})
                eventos = _eventos_sse(resp.get_data(as_text=True))
        finally:
            parche.stop()

        assert resp.status_code == 200
        assert eventos[-1]["tipo"] == "fin"
        # num_preguntas=20 con tamano_lote=5 (valor por defecto) -> 4 lotes
        # (5+5+5+5); cada lote hace 1 llamada de generación + 1 de
        # verificación EN BLOQUE (todas las candidatas del lote de una vez,
        # ver test_generator._verificar_lote) = 2 llamadas por lote, 8 en
        # total -- antes de la verificación en bloque eran 6 por lote (24
        # en total): la reducción de llamadas es el propio objetivo de este
        # cambio (bug real: un test de 30 preguntas podía disparar más de
        # 50 llamadas). Este hilo de fondo vuelca DIRECTO a Firestore
        # (volcar_directo), sin depender de flask.g -- el caso que antes
        # perdía el coste por completo.
        coste = db.leer(("usuarios", "u1"))["coste_ia"][self._mes_actual()]
        assert coste["tokens_in"] == 160
        assert coste["tokens_out"] == 80
        assert coste["llamadas"] == 8
        # Las preguntas aceptadas se retransmiten individualmente en un
        # evento "pregunta" aparte según van llegando, para que el
        # frontend pueda empezar el test en cuanto tenga las primeras N
        # sin esperar a que termine todo el streaming.
        eventos_pregunta = [e for e in eventos if e["tipo"] == "pregunta"]
        assert len(eventos_pregunta) == 20
        assert all("pregunta" in e and "opciones" in e["pregunta"] for e in eventos_pregunta)

    def test_generar_tarjetas_desde_pdf_registra_coste(self, client, db, documento_sembrado):
        def fake_call(messages, on_usage=None, **kwargs):
            if on_usage:
                on_usage({"prompt_tokens": 15, "completion_tokens": 8})
            if "verificador independiente" in messages[0]["content"]:
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps({"tarjetas": [{"pregunta": "¿P?", "respuesta": "R"}]})

        parche = _con_sesion(client)
        try:
            with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call), \
                 patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}):
                resp = client.post("/generar-tarjetas-desde-pdf",
                                    data={"documento_id": documento_sembrado, "num_tarjetas": "1"},
                                    headers={"Authorization": "Bearer x"})
                # /generar-tarjetas-desde-pdf va en streaming SSE: hay que
                # drenar el cuerpo (dentro del "with patch") para asegurar
                # que el hilo de fondo ya terminó antes de leer los costes.
                resp.get_data()
        finally:
            parche.stop()

        assert resp.status_code == 200
        # Antes esta ruta no registraba coste EN ABSOLUTO (bypaseaba
        # deepseek_utils con un requests.post manual) -- ahora sí, vía
        # call_deepseek_api + AcumuladorTokens.
        coste = db.leer(("usuarios", "u1"))["coste_ia"][self._mes_actual()]
        assert coste["tokens_in"] == 30
        assert coste["tokens_out"] == 16
        assert coste["llamadas"] == 2


class TestMisDocumentos:
    # "Continuar" en la biblioteca: antes, un test desde PDF empezado y no
    # terminado no aparecía por ningún sitio (solo "Ver"/"Generar más" si ya
    # había uno finalizado) -- /mis-documentos debe exponer el test_id
    # en_progreso de cada documento para que el frontend pueda ofrecerlo.

    def test_documento_con_test_en_progreso(self, client, db, documento_sembrado):
        db.sembrar(("usuarios", "u1", "tests", "t1"), {
            "estado": "en_progreso", "tipo": "test_pdf", "documento_id": documento_sembrado, "fecha": "2026-01-01",
        })
        parche = _con_sesion(client)
        try:
            resp = client.get("/mis-documentos", headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        documentos = {d["id"]: d for d in resp.get_json()["documentos"]}
        assert documentos[documento_sembrado]["test_en_progreso"] == "t1"

    def test_documento_sin_test_en_progreso(self, client, documento_sembrado):
        parche = _con_sesion(client)
        try:
            resp = client.get("/mis-documentos", headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        documentos = {d["id"]: d for d in resp.get_json()["documentos"]}
        assert documentos[documento_sembrado]["test_en_progreso"] is None
