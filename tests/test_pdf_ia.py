"""Pruebas de blueprints/pdf_ia.py: _extraer_json_array (la reparación de
JSON de la respuesta de la IA, antes sin ningún test) y las rutas HTTP
más críticas -- las 4 de /guardar-*-pdf (persisten contenido y actualizan
estadísticas) y un test de humo de /resumir-pdf y /generar-test-desde-pdf
con DeepSeek mockeado. El resto de las ~20 rutas de este blueprint queda
fuera de esta tanda (desproporcionado para el alcance aprobado)."""
import json
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
        parche = _con_sesion(client)
        try:
            resp = client.post("/guardar-test-pdf", json={
                "preguntas": [{"pregunta": "?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"}, "respuesta_correcta": "A"}],
                "documento_id": documento_sembrado,
                "nombre_archivo": "doc.pdf",
            }, headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        assert db.leer(("usuarios", "u1"))["tests_pdf_realizados"] == 1

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


class TestResumirPdfYGenerarTestDesdePdf:
    """Test de humo: la ruta llega hasta el punto de generación con IA
    (mockeada) y devuelve el resultado esperado, sin ejercer aquí toda la
    lógica interna de deepseek_utils (ya cubierta en test_deepseek_utils.py)."""

    def test_resumir_pdf(self, client, documento_sembrado):
        parche = _con_sesion(client)
        try:
            with patch("blueprints.pdf_ia.generar_documento_largo_por_partes", return_value="# Resumen generado"), \
                 patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}):
                resp = client.post("/resumir-pdf", data={"documento_id": documento_sembrado},
                                    headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        assert resp.get_json()["resumen"] == "# Resumen generado"

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
        # El uso se cobra por adelantado (antes de abrir el stream) y, como la
        # generación no produjo ni una pregunta, el hilo de fondo lo devuelve:
        # el neto debe quedar en 0 (no se consume cuota por una generación
        # fallida, pero el contador ya existe por el cobro+devolución).
        assert db.leer(("usuarios", "u1"))["limites_uso"]["pdf_ia"]["contador"] == 0


class TestGenerarEsquemaDesdePdf:
    """Mismo patrón de test de humo que TestResumirPdfYGenerarTestDesdePdf --
    hasta ahora esta ruta no tenía ningún test."""

    def test_generar_esquema_desde_pdf(self, client, db, documento_sembrado):
        parche = _con_sesion(client)
        try:
            with patch("blueprints.pdf_ia.generar_documento_largo_por_partes", return_value="# Esquema generado"), \
                 patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}):
                resp = client.post("/generar-esquema-desde-pdf", data={"documento_id": documento_sembrado},
                                    headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 200
        assert resp.get_json()["esquema"] == "# Esquema generado"
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

    def test_generar_esquema_desde_pdf_error_deepseek_da_500_y_no_factura(self, client, db, documento_sembrado):
        parche = _con_sesion(client)
        try:
            with patch("blueprints.pdf_ia.generar_documento_largo_por_partes", return_value=None), \
                 patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}):
                resp = client.post("/generar-esquema-desde-pdf", data={"documento_id": documento_sembrado},
                                    headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 500
        # No se llegó a registrar_uso, así que ni siquiera existe el contador.
        assert "limites_uso" not in db.leer(("usuarios", "u1"))


class TestGenerarTarjetasDesdePdf:
    """Ruta rediseñada sobre tarjetas_generator.generar_tarjetas_verificadas
    (pipeline generar->verificar->reintentar) -- hasta ahora sin ningún
    test. El pipeline en sí (verificación, reparto, dedup) se prueba en
    tests/test_tarjetas_generator.py; aquí solo se comprueba que la ruta
    HTTP conecta bien con él (parseo de num_tarjetas, facturación de cupo,
    manejo de errores)."""

    def test_generar_tarjetas_desde_pdf(self, client, db, documento_sembrado):
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
        datos = resp.get_json()
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
        assert resp.get_json()["advertencia"] == resultado["advertencia"]

    def test_generar_tarjetas_desde_pdf_sin_tarjetas_da_error_500_y_no_factura(self, client, db, documento_sembrado):
        resultado = {"tarjetas": [], "descartadas": 1, "advertencia": "No se pudo verificar ninguna tarjeta."}
        parche = _con_sesion(client)
        try:
            with patch("blueprints.pdf_ia.generar_tarjetas_verificadas", return_value=resultado), \
                 patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}):
                resp = client.post("/generar-tarjetas-desde-pdf", data={"documento_id": documento_sembrado},
                                    headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()
        assert resp.status_code == 500
        assert "limites_uso" not in db.leer(("usuarios", "u1"))

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
                client.post("/generar-tarjetas-desde-pdf",
                            data={"documento_id": documento_sembrado, "num_tarjetas": "500"},
                            headers={"Authorization": "Bearer x"})
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
        def fake_call(messages, on_usage=None, **kwargs):
            if on_usage:
                on_usage({"prompt_tokens": 20, "completion_tokens": 10})
            if len(messages) == 2 and messages[0]["role"] == "system":
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps([{
                "pregunta": "¿P?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "..."
            }])

        parche = _con_sesion(client)
        try:
            with patch("test_generator.call_deepseek_api", side_effect=fake_call):
                resp = client.post("/generar-test-desde-pdf", data={
                    "documento_id": documento_sembrado, "num_preguntas": "20"
                }, headers={"Authorization": "Bearer x"})
        finally:
            parche.stop()

        assert resp.status_code == 200
        eventos = _eventos_sse(resp.get_data(as_text=True))
        assert eventos[-1]["tipo"] == "fin"
        # num_preguntas=20 con tamano_lote=15 -> 2 lotes; cada lote hace 1
        # llamada de generación + 1 de verificación = 4 llamadas en total.
        # Este hilo de fondo vuelca DIRECTO a Firestore (volcar_directo),
        # sin depender de flask.g -- el caso que antes perdía el coste por
        # completo.
        coste = db.leer(("usuarios", "u1"))["coste_ia"][self._mes_actual()]
        assert coste["tokens_in"] == 80
        assert coste["tokens_out"] == 40
        assert coste["llamadas"] == 4

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
