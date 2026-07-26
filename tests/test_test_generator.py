"""Pruebas de test_generator.py: generar_preguntas_ia_en_lotes con su
pipeline de verificación por pregunta (mismo principio que
generador_preguntas_verificado.py, aquí sobre un documento libre en vez de
un artículo anclado en Firestore). DeepSeek se mockea por CONTENIDO del
mensaje (no por orden de llamada), porque la generación y verificación de
un lote corren en paralelo."""
import itertools
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
            # (pedida con "No repitas esta pregunta").
            if "No repitas esta pregunta" in messages[0]["content"]:
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
        # El error de "ninguna superó la verificación" del lote original,
        # más el aviso de que el relleno tampoco pudo completar el único
        # hueco que faltaba (la verificación sigue fallando siempre).
        assert len(errores) == 2
        assert errores[0].startswith("Ninguna de las")
        # El hueco original agota MAX_INTENTOS_POR_PREGUNTA_PDF candidatas
        # (la del lote + los recambios); el relleno le da al mismo hueco
        # que sigue faltando una segunda tanda completa del mismo tamaño
        # -- el doble en total, nunca más.
        assert len(llamadas_generacion) == MAX_INTENTOS_POR_PREGUNTA_PDF * 2

    def test_on_progreso_se_llama_una_vez_por_pregunta_no_por_lote(self):
        # Con num_preguntas=2 y tamano_lote=1 hay 2 lotes, cada uno con su
        # propia candidata única -- se completan las 2 sin relleno, y
        # "total" en cada evento debe ser num_preguntas (2), no el número
        # de lotes -- la granularidad es por pregunta, no por lote.
        construir_prompt = _construir_prompt_fabrica(None)
        contador = itertools.count()

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps([{
                "pregunta": f"¿Pregunta {next(contador)}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "..."
            }])

        eventos = []
        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            generar_preguntas_ia_en_lotes(
                construir_prompt, 2, "Texto de prueba.", tamano_lote=1,
                on_progreso=lambda e: eventos.append(e),
            )

        assert len(eventos) == 2
        assert {e["total"] for e in eventos} == {2}
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
        # El error del lote sin respuesta, más el aviso de que el relleno
        # tampoco pudo completar el hueco (DeepSeek sigue sin responder).
        assert len(errores) == 2

    def test_relleno_completa_el_hueco_que_deja_una_verificacion_fallida(self):
        # Regresión real: un usuario pidió 10 preguntas desde un PDF y
        # recibió solo 7 -- 3 candidatas del lote inicial no superaron la
        # verificación y, al agotar sus MAX_INTENTOS_POR_PREGUNTA_PDF
        # recambios (que aquí siguen siendo "malos" a propósito, para que
        # el hueco se pierda de verdad dentro del lote), se perdían para
        # siempre sin ningún intento de compensarlas. Las otras 7
        # candidatas del lote son válidas a la primera. El relleno FINAL
        # (fuera del lote, se reconoce porque pide 1 pregunta sin "No
        # repitas") debe generar 3 preguntas nuevas y válidas para llegar
        # a las 10 pedidas.
        construir_prompt = _construir_prompt_fabrica(None)
        contador_mala = itertools.count()
        contador_relleno = itertools.count()

        def fake_call(messages, **kwargs):
            contenido = messages[0]["content"]
            if _es_llamada_verificacion(messages):
                candidata = json.loads(messages[1]["content"].split("PREGUNTA A VERIFICAR:\n")[1])
                valido = not candidata["pregunta"].startswith("¿Mala")
                return json.dumps({"valido": valido, "problemas": [] if valido else ["dato inventado"]})
            if "No repitas esta pregunta" in contenido:
                # Recambio INTERNO del lote (sustituye una "Mala" ya
                # descartada) -- sigue siendo inválido a propósito, para
                # que el lote agote de verdad sus intentos y pierda el
                # hueco (el relleno final es quien debe cerrarlo).
                return json.dumps([{
                    "pregunta": f"¿Mala recambio {next(contador_mala)}?",
                    "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                    "respuesta_correcta": "A", "explicacion": "..."
                }])
            if "Genera 1 preguntas" in contenido:
                # Relleno FINAL: pide 1 pregunta nueva sin evitar nada --
                # solo puede venir de fuera del lote, tras agotarlo.
                return json.dumps([{
                    "pregunta": f"¿Relleno {next(contador_relleno)}?",
                    "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                    "respuesta_correcta": "A", "explicacion": "..."
                }])
            # Generación inicial del lote completo (10 preguntas pedidas).
            return json.dumps([
                {"pregunta": f"¿Mala {i}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "..."}
                for i in range(3)
            ] + [
                {"pregunta": f"¿Buena {i}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "..."}
                for i in range(7)
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, 10, "Texto de prueba.", tamano_lote=10)

        assert len(preguntas) == 10
        assert errores == []
        preguntas_texto = {p["pregunta"] for p in preguntas}
        assert all("Mala" not in t for t in preguntas_texto)

    def test_max_tokens_del_lote_sigue_la_formula_1500_por_pregunta(self):
        # Regresión del bug real: con la fórmula antigua (min(4000, 300*n)),
        # un lote de 10 preguntas pedía max_tokens=3000 y DeepSeek lo
        # truncaba a mitad de JSON (finish_reason="length") -- ver el log
        # real citado en test_generator.py. Este test fija la fórmula nueva
        # para que un cambio futuro no la vuelva a bajar sin darse cuenta.
        construir_prompt = _construir_prompt_fabrica(None)
        max_tokens_recibidos = []

        def fake_call(messages, max_tokens=None, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            max_tokens_recibidos.append(max_tokens)
            return json.dumps([
                {"pregunta": f"¿Pregunta {i}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "..."}
                for i in range(4)
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            generar_preguntas_ia_en_lotes(construir_prompt, 4, "Texto de prueba.", tamano_lote=4)

        assert max_tokens_recibidos == [6000]  # min(8000, 1500*4)

    def test_max_tokens_del_lote_se_limita_a_8000(self):
        construir_prompt = _construir_prompt_fabrica(None)
        max_tokens_recibidos = []

        def fake_call(messages, max_tokens=None, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            max_tokens_recibidos.append(max_tokens)
            return json.dumps([
                {"pregunta": f"¿Pregunta {i}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "..."}
                for i in range(6)
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            generar_preguntas_ia_en_lotes(construir_prompt, 6, "Texto de prueba.", tamano_lote=6)

        assert max_tokens_recibidos == [8000]  # min(8000, 1500*6=9000) -> 8000
