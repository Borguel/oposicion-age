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
