"""Pruebas de test_generator.py: generar_preguntas_ia_en_lotes con su
pipeline de verificación por pregunta (mismo principio que
generador_preguntas_verificado.py, aquí sobre un documento libre en vez de
un artículo anclado en Firestore). DeepSeek se mockea por CONTENIDO del
mensaje (no por orden de llamada), porque la generación y verificación de
un lote corren en paralelo."""
import json
from unittest.mock import patch

from test_generator import generar_preguntas_ia_en_lotes, MAX_INTENTOS_POR_PREGUNTA_PDF


def _construir_prompt_fabrica(preguntas_por_llamada):
    """Devuelve un construir_prompt(n) de prueba que siempre pide n=1 (los
    tests aquí usan lotes pequeños) y cuyo texto de prompt no contiene
    'system' -- la generación en este módulo va toda en un único mensaje
    'user', a diferencia de la verificación que sí usa 'system'."""
    def construir_prompt(n):
        return f"Genera {n} preguntas.\n\nDocumento para crear preguntas test:\nTexto de prueba."
    return construir_prompt


def _es_llamada_verificacion(messages):
    return len(messages) == 2 and messages[0]["role"] == "system"


class TestGenerarPreguntasIaEnLotes:
    def test_happy_path_todas_validas(self):
        construir_prompt = _construir_prompt_fabrica(None)

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps([
                {"pregunta": "¿Pregunta 1?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "..."},
                {"pregunta": "¿Pregunta 2?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "B", "explicacion": "..."},
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, 2, "Texto de prueba.", tamano_lote=15)

        assert errores == []
        assert {p["pregunta"] for p in preguntas} == {"¿Pregunta 1?", "¿Pregunta 2?"}

    def test_pregunta_invalida_se_descarta_y_se_sustituye(self):
        construir_prompt = _construir_prompt_fabrica(None)

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                candidata = json.loads(messages[1]["content"].split("PREGUNTA A VERIFICAR:\n")[1])
                valido = candidata["pregunta"] != "¿Pregunta mala?"
                return json.dumps({"valido": valido, "problemas": [] if valido else ["dato inventado"]})
            # Generación del lote inicial (1 candidata mala) vs. de recambio
            # (pedida con la exclusión de la pregunta ya descartada).
            if "Estas preguntas ya existen" in messages[0]["content"]:
                return json.dumps([{
                    "pregunta": "¿Pregunta buena?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                    "respuesta_correcta": "A", "explicacion": "..."
                }])
            return json.dumps([{
                "pregunta": "¿Pregunta mala?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "..."
            }])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, 1, "Texto de prueba.", tamano_lote=15)

        assert errores == []
        assert len(preguntas) == 1
        assert preguntas[0]["pregunta"] == "¿Pregunta buena?"

    def test_tope_de_intentos_agotado_descarta_la_pregunta(self):
        construir_prompt = _construir_prompt_fabrica(None)
        llamadas_generacion = []

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": False, "problemas": ["dato inventado"]})
            llamadas_generacion.append(1)
            return json.dumps([{
                "pregunta": f"¿Pregunta intento {len(llamadas_generacion)}?",
                "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "..."
            }])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, 1, "Texto de prueba.", tamano_lote=15)

        assert preguntas == []
        # 0 supervivientes tras verificar SÍ se reporta en errores (aunque no
        # sea un fallo técnico de generación) para que el llamante pueda
        # distinguir "documento sin contenido suficiente" de un fallo real de
        # DeepSeek -- ver blueprints/pdf_ia.py.
        assert len(errores) == 1
        assert errores[0].startswith("Ninguna de las")
        # Como mucho MAX_INTENTOS_POR_PREGUNTA_PDF candidatas distintas probadas
        # en total (la del lote + las de recambio), nunca más.
        assert len(llamadas_generacion) == MAX_INTENTOS_POR_PREGUNTA_PDF

    def test_on_progreso_se_llama_una_vez_por_pregunta_no_por_lote(self):
        # Con este mock cada lote (independientemente de las n preguntas que
        # pida) solo genera 1 candidata -- así, con 20 preguntas y lotes de
        # 15 (2 lotes: 15 + 5), hay exactamente 2 candidatas verificadas en
        # total, y "total" en cada evento debe ser num_preguntas (20), no el
        # número de lotes (2) -- la granularidad ahora es por pregunta.
        construir_prompt = _construir_prompt_fabrica(None)

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps([{
                "pregunta": "¿Pregunta?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "..."
            }])

        eventos = []
        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            generar_preguntas_ia_en_lotes(
                construir_prompt, 20, "Texto de prueba.", tamano_lote=15,
                on_progreso=lambda e: eventos.append(e),
            )

        assert len(eventos) == 2
        assert {e["total"] for e in eventos} == {20}
        assert {e["completadas"] for e in eventos} == {1, 2}

    def test_on_progreso_se_llama_por_cada_candidata_dentro_de_un_mismo_lote(self):
        # El caso real que antes se perdía: un ÚNICO lote (num_preguntas <=
        # tamano_lote) que genera VARIAS candidatas -- antes solo llegaba un
        # evento de progreso al final del lote entero; ahora debe llegar uno
        # por cada candidata verificada dentro de ese mismo lote.
        construir_prompt = _construir_prompt_fabrica(None)

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps([
                {"pregunta": "¿Pregunta 1?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "..."},
                {"pregunta": "¿Pregunta 2?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "B", "explicacion": "..."},
                {"pregunta": "¿Pregunta 3?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "C", "explicacion": "..."},
            ])

        eventos = []
        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            generar_preguntas_ia_en_lotes(
                construir_prompt, 3, "Texto de prueba.", tamano_lote=15,
                on_progreso=lambda e: eventos.append(e),
            )

        assert len(eventos) == 3
        assert {e["total"] for e in eventos} == {3}
        assert {e["completadas"] for e in eventos} == {1, 2, 3}

    def test_on_usage_recibe_generacion_y_verificacion(self):
        construir_prompt = _construir_prompt_fabrica(None)

        def fake_call(messages, on_usage=None, **kwargs):
            if on_usage:
                on_usage({"prompt_tokens": 10, "completion_tokens": 5})
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps([{
                "pregunta": "¿Pregunta?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "..."
            }])

        recibidos = []
        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            generar_preguntas_ia_en_lotes(
                construir_prompt, 1, "Texto de prueba.", tamano_lote=15,
                on_usage=lambda u: recibidos.append(u),
            )

        # 1 llamada de generación + 1 de verificación = 2 avisos de usage.
        assert len(recibidos) == 2

    def test_sin_respuesta_de_deepseek_da_error_de_lote(self):
        construir_prompt = _construir_prompt_fabrica(None)
        with patch("test_generator.call_deepseek_api", return_value=None):
            preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, 1, "Texto de prueba.", tamano_lote=15)
        assert preguntas == []
        assert len(errores) == 1

    def test_duplicado_semantico_se_sustituye_por_una_pregunta_distinta(self):
        # Caso real reportado: dos preguntas con enunciados distintos que en
        # realidad preguntan por el mismo dato del documento (aquí, "misma
        # pregunta reformulada") -- la deduplicación por texto exacto no las
        # detecta, así que debe entrar en juego la deduplicación semántica
        # (_detectar_indices_duplicados) y pedir una de recambio.
        construir_prompt = _construir_prompt_fabrica(None)

        def fake_call(messages, **kwargs):
            if len(messages) == 2 and messages[1]["content"].startswith("PREGUNTAS:"):
                # Llamada de detección de duplicados semánticos: la pregunta
                # 1 (índice 1) se marca como duplicada de la 0.
                return json.dumps({"duplicados": [1]})
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            if "Estas preguntas ya existen" in messages[0]["content"]:
                return json.dumps([{
                    "pregunta": "¿Pregunta distinta?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                    "respuesta_correcta": "A", "explicacion": "..."
                }])
            return json.dumps([
                {"pregunta": "¿Cuánto dura el mandato?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "..."},
                {"pregunta": "¿Cuál es la duración del cargo?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "..."},
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, 2, "Texto de prueba.", tamano_lote=15)

        assert errores == []
        assert len(preguntas) == 2
        textos = {p["pregunta"] for p in preguntas}
        assert "¿Cuánto dura el mandato?" in textos
        assert "¿Cuál es la duración del cargo?" not in textos
        assert "¿Pregunta distinta?" in textos

    def test_preguntas_a_evitar_se_incluyen_en_el_prompt_de_cada_lote(self):
        # "Generar más" desde un documento ya subido antes debe avisar a la
        # IA de las preguntas de tests anteriores para no repetirlas (ver
        # blueprints/pdf_ia.py, obtener_preguntas_previas).
        construir_prompt = _construir_prompt_fabrica(None)
        prompts_recibidos = []

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            prompts_recibidos.append(messages[0]["content"])
            return json.dumps([{
                "pregunta": "¿Pregunta nueva?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "..."
            }])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            generar_preguntas_ia_en_lotes(
                construir_prompt, 1, "Texto de prueba.", tamano_lote=15,
                preguntas_a_evitar=["¿Pregunta ya usada en un test anterior?"],
            )

        assert any("¿Pregunta ya usada en un test anterior?" in p for p in prompts_recibidos)
