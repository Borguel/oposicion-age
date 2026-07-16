"""Pruebas de tarjetas_generator.py: reparto de cupos entre fragmentos,
parseo de la respuesta cruda de DeepSeek, y el pipeline completo
generar->verificar->reintentar (con DeepSeek mockeado por CONTENIDO del
prompt, no por orden de llamada -- el pipeline es paralelo)."""
import json
from unittest.mock import patch

from tarjetas_generator import _repartir_cupos, _parsear_tarjetas, generar_tarjetas_verificadas


class TestRepartirCupos:
    def test_reparto_exacto(self):
        assert _repartir_cupos(2, 10) == [5, 5]

    def test_reparto_con_resto_a_los_primeros(self):
        assert _repartir_cupos(3, 10) == [4, 3, 3]

    def test_menos_tarjetas_que_fragmentos(self):
        assert _repartir_cupos(5, 2) == [1, 1, 0, 0, 0]


class TestParsearTarjetas:
    def test_objeto_envuelto(self):
        assert _parsear_tarjetas('{"tarjetas": [{"pregunta": "a", "respuesta": "b"}]}') == \
            [{"pregunta": "a", "respuesta": "b"}]

    def test_array_suelto_como_fallback(self):
        assert _parsear_tarjetas('[{"pregunta": "a", "respuesta": "b"}]') == \
            [{"pregunta": "a", "respuesta": "b"}]

    def test_json_invalido_devuelve_lista_vacia(self):
        assert _parsear_tarjetas("esto no es json") == []

    def test_vacio_o_none_devuelve_lista_vacia(self):
        assert _parsear_tarjetas("") == []
        assert _parsear_tarjetas(None) == []


def _es_prompt_generacion(messages):
    return "Genera EXACTAMENTE" in messages[0]["content"]


def _es_prompt_verificacion(messages):
    return "verificador independiente" in messages[0]["content"]


class TestGenerarTarjetasVerificadas:
    def test_happy_path_todas_validas(self):
        def fake_call(messages, **kwargs):
            if _es_prompt_generacion(messages):
                return json.dumps({"tarjetas": [
                    {"pregunta": "¿Pregunta 1?", "respuesta": "Respuesta 1"},
                    {"pregunta": "¿Pregunta 2?", "respuesta": "Respuesta 2"},
                ]})
            if _es_prompt_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            raise AssertionError("prompt inesperado")

        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call):
            resultado = generar_tarjetas_verificadas("Texto corto del documento.", 2)

        assert resultado["descartadas"] == 0
        assert "advertencia" not in resultado
        preguntas = {t["pregunta"] for t in resultado["tarjetas"]}
        assert preguntas == {"¿Pregunta 1?", "¿Pregunta 2?"}

    def test_tarjeta_invalida_se_descarta_y_se_regenera(self):
        # La tarjeta "A" nunca pasa la verificación; su recambio "B" sí --
        # debe aparecer en el resultado final, y "A" NO.
        def fake_call(messages, **kwargs):
            if _es_prompt_generacion(messages):
                if "No repitas esta pregunta" in messages[0]["content"]:
                    return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta B?", "respuesta": "Respuesta B"}]})
                return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta A?", "respuesta": "Respuesta A"}]})
            if _es_prompt_verificacion(messages):
                candidata = json.loads(messages[1]["content"].split("TARJETA A VERIFICAR:\n")[1])
                valido = candidata["pregunta"] != "¿Pregunta A?"
                return json.dumps({"valido": valido, "problemas": [] if valido else ["dato inventado"]})
            raise AssertionError("prompt inesperado")

        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call):
            resultado = generar_tarjetas_verificadas("Texto corto del documento.", 1)

        assert resultado["descartadas"] == 0
        assert len(resultado["tarjetas"]) == 1
        assert resultado["tarjetas"][0]["pregunta"] == "¿Pregunta B?"

    def test_tope_de_intentos_agotado_descarta_la_tarjeta(self):
        # La verificación SIEMPRE falla -- tras MAX_INTENTOS_POR_TARJETA
        # regeneraciones fallidas, la tarjeta se descarta y no aparece en
        # el resultado (nunca se entrega sin validar).
        def fake_call(messages, **kwargs):
            if _es_prompt_generacion(messages):
                return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta única?", "respuesta": "Respuesta"}]})
            if _es_prompt_verificacion(messages):
                return json.dumps({"valido": False, "problemas": ["dato inventado"]})
            raise AssertionError("prompt inesperado")

        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call):
            resultado = generar_tarjetas_verificadas("Texto corto del documento.", 1)

        assert resultado["tarjetas"] == []
        assert resultado["descartadas"] == 1
        assert "advertencia" in resultado

    def test_sin_candidatas_generadas_da_advertencia(self):
        with patch("tarjetas_generator.call_deepseek_api", return_value=None):
            resultado = generar_tarjetas_verificadas("Texto corto.", 3)

        assert resultado["tarjetas"] == []
        assert resultado["descartadas"] == 0
        assert "advertencia" in resultado

    def test_on_usage_se_llama_por_cada_llamada_a_deepseek(self):
        def fake_call(messages, on_usage=None, **kwargs):
            if on_usage:
                on_usage({"prompt_tokens": 10, "completion_tokens": 5})
            if _es_prompt_generacion(messages):
                return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta?", "respuesta": "Respuesta"}]})
            return json.dumps({"valido": True, "problemas": []})

        recibidos = []
        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call):
            generar_tarjetas_verificadas("Texto corto.", 1, on_usage=lambda u: recibidos.append(u))

        # 1 llamada de generación + 1 de verificación = 2 avisos de usage.
        assert len(recibidos) == 2
