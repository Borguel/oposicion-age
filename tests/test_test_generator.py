"""Pruebas de test_generator.py: generar_preguntas_ia_en_lotes con su
pipeline de verificación INDIVIDUAL en paralelo (una llamada por candidata,
mismo principio que generador_preguntas_verificado.py) y su mecanismo de
recambio individual para las que no pasan. DeepSeek se mockea por CONTENIDO
del mensaje (no por orden de llamada), porque la generación y verificación
de un lote corren en paralelo.

La verificación en bloque (una sola llamada juzgando varias candidatas a la
vez) se probó y se retiró (03/08/2026, bug real de producción): con
thinking_enabled=True el razonamiento del modelo escala con cuántas
candidatas hay que juzgar A LA VEZ, no con el número de llamadas, así que
un lote de 5 podía agotar el presupuesto de tokens SOLO PENSANDO sin
llegar a escribir el veredicto -- más lento y menos fiable que verificar
cada candidata por separado. Ver el comentario largo junto a
_pedir_lote_verificado en test_generator.py."""
import itertools
import json
from unittest.mock import patch

from test_generator import (
    generar_preguntas_ia_en_lotes, MAX_INTENTOS_POR_PREGUNTA_PDF, _verificar_pregunta,
    _claves_dedup, _fragmentos_por_lote, _es_duplicado_por_contencion,
    _bloques_estructurales, _repartir_bloques_en_lotes, _bloques_por_esquema_ia,
    _detectar_duplicados_finales, generar_banco_preguntas_adaptativo,
)


def _construir_prompt_fabrica(preguntas_por_llamada):
    """Devuelve un construir_prompt(n) de prueba que siempre pide n=1 (los
    tests aquí usan lotes pequeños) y cuyo texto de prompt no contiene
    'system' -- la generación en este módulo va toda en un único mensaje
    'user', a diferencia de la verificación (siempre individual) que sí
    usa 'system'."""
    def construir_prompt(n):
        return f"Genera {n} preguntas.\n\nDocumento para crear preguntas test:\nTexto de prueba."
    return construir_prompt


def _es_llamada_verificacion(messages):
    # "PREGUNTA A VERIFICAR:" solo aparece en _prompt_verificacion (la
    # verificación INDIVIDUAL de una candidata contra el documento) -- la
    # pasada final de deduplicación semántica (_prompt_deduplicacion_final,
    # ver _detectar_duplicados_finales en test_generator.py) también manda
    # un mensaje [system, user], pero con un listado de preguntas ya
    # aceptadas, no "PREGUNTA A VERIFICAR:". Sin este marcador, ambas
    # llamadas eran indistinguibles para los tests que mockean
    # call_deepseek_api por FORMA de mensaje en vez de por contenido.
    return (
        len(messages) == 2
        and messages[0]["role"] == "system"
        and "PREGUNTA A VERIFICAR:" in messages[1]["content"]
    )


def _es_llamada_deduplicacion_final(messages):
    return (
        len(messages) == 2
        and messages[0]["role"] == "system"
        and "grupos_duplicados" in messages[0]["content"]
    )


class TestGenerarPreguntasIaEnLotes:
    def test_happy_path_todas_validas(self):
        construir_prompt = _construir_prompt_fabrica(None)

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps([
                {"pregunta": "¿Pregunta 1?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."},
                {"pregunta": "¿Pregunta 2?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "B", "explicacion": "Explicación de prueba para el test."},
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
                    "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
                }])
            return json.dumps([{
                "pregunta": "¿Pregunta mala?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
            }])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, 1, "Texto de prueba.", tamano_lote=15)

        assert errores == []
        assert len(preguntas) == 1
        assert preguntas[0]["pregunta"] == "¿Pregunta buena?"

    def test_frase_prohibida_se_descarta_sin_gastar_verificacion(self):
        # Bug real de producción (02/08/2026): este archivo nunca usaba el
        # filtro local determinista (validador_preguntas.validar_pregunta)
        # que sí usan generador_preguntas_verificado.py y
        # tarjetas_generator.py -- dependía solo de que la IA verificadora
        # cazara frases como "según el contenido"/"el documento indica
        # que..." (prohibidas en el propio prompt de generación), y en un
        # test real de 20 preguntas varias se colaron sin que la
        # verificación las descartara. Aquí, una candidata con una frase
        # prohibida debe descartarse SIN llegar a pedir SU verificación (si
        # llegara, el AssertionError de abajo lo delataría) -- se manda
        # directa al recambio, cuya propia verificación sí debe ocurrir
        # con normalidad.
        construir_prompt = _construir_prompt_fabrica(None)

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                if "Según el contenido" in messages[1]["content"]:
                    raise AssertionError("la candidata con frase prohibida no debería llegar a verificarse")
                return json.dumps({"valido": True, "problemas": []})
            if "No repitas esta pregunta" in messages[0]["content"]:
                return json.dumps([{
                    "pregunta": "¿Pregunta buena?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                    "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
                }])
            return json.dumps([{
                "pregunta": "Según el contenido, ¿qué establece la norma?",
                "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
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
                "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
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
        # (la del lote + los recambios); el relleno (_MAX_RONDAS_RELLENO=3,
        # ver test_generator.py) le da al mismo hueco que sigue faltando
        # TRES tandas completas más del mismo tamaño -- el cuádruple en
        # total, nunca más.
        assert len(llamadas_generacion) == MAX_INTENTOS_POR_PREGUNTA_PDF * 4

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
                "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
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
                 "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."},
                {"pregunta": "¿Pregunta 2?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "B", "explicacion": "Explicación de prueba para el test."},
                {"pregunta": "¿Pregunta 3?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "C", "explicacion": "Explicación de prueba para el test."},
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

    def test_evento_progreso_incluye_la_pregunta_aceptada(self):
        # blueprints/pdf_ia.py separa este campo en un evento SSE "pregunta"
        # aparte (mismo patrón que blueprints/test_ia.py para Test
        # Personalizado) para que el frontend pueda empezar el test en
        # cuanto lleguen las primeras N, sin esperar a que termine todo el
        # test. Una pregunta descartada (falla verificación y agota sus
        # recambios) NO debe llevar "pregunta" en su evento -- nunca se
        # anuncia algo que no va a estar en el test final.
        construir_prompt = _construir_prompt_fabrica(None)

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                candidata = json.loads(messages[1]["content"].split("PREGUNTA A VERIFICAR:\n")[1])
                valido = candidata["pregunta"] != "¿Mala?"
                return json.dumps({"valido": valido, "problemas": [] if valido else ["dato inventado"]})
            if "No repitas esta pregunta" in messages[0]["content"]:
                return json.dumps([{
                    "pregunta": "¿Mala?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                    "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
                }])
            return json.dumps([
                {"pregunta": "¿Buena?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."},
                {"pregunta": "¿Mala?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."},
            ])

        eventos = []
        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            generar_preguntas_ia_en_lotes(
                construir_prompt, 2, "Texto de prueba.", tamano_lote=15,
                on_progreso=lambda e: eventos.append(e),
            )

        con_pregunta = [e for e in eventos if "pregunta" in e]
        sin_pregunta = [e for e in eventos if "pregunta" not in e]
        assert len(con_pregunta) == 1
        assert con_pregunta[0]["pregunta"]["pregunta"] == "¿Buena?"
        assert len(sin_pregunta) >= 1

    def test_on_usage_recibe_generacion_y_verificacion(self):
        construir_prompt = _construir_prompt_fabrica(None)

        def fake_call(messages, on_usage=None, **kwargs):
            if on_usage:
                on_usage({"prompt_tokens": 10, "completion_tokens": 5})
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps([{
                "pregunta": "¿Pregunta?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
            }])

        recibidos = []
        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            generar_preguntas_ia_en_lotes(
                construir_prompt, 1, "Texto de prueba.", tamano_lote=15,
                on_usage=lambda u: recibidos.append(u),
            )

        # 1 llamada de generación + 1 de verificación individual (sin
        # candidatas inválidas, no hace falta ningún recambio) = 2 avisos
        # de usage.
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
                    "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
                }])
            if "Genera 1 preguntas" in contenido:
                # Relleno FINAL: pide 1 pregunta nueva sin evitar nada --
                # solo puede venir de fuera del lote, tras agotarlo.
                return json.dumps([{
                    "pregunta": f"¿Relleno {next(contador_relleno)}?",
                    "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                    "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
                }])
            # Generación inicial del lote completo (10 preguntas pedidas).
            return json.dumps([
                {"pregunta": f"¿Mala {i}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."}
                for i in range(3)
            ] + [
                {"pregunta": f"¿Buena {i}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."}
                for i in range(7)
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, 10, "Texto de prueba.", tamano_lote=10)

        assert len(preguntas) == 10
        assert errores == []
        preguntas_texto = {p["pregunta"] for p in preguntas}
        assert all("Mala" not in t for t in preguntas_texto)

    def test_segunda_ronda_de_relleno_completa_el_hueco_si_la_primera_falla(self):
        # Con el dedup ampliado (mayoría/fracción/artículo-en-explicación,
        # ver test_generator.py) el relleno se invoca más a menudo que
        # antes -- antes, un hueco de relleno que agotaba su presupuesto
        # completo de MAX_INTENTOS_POR_PREGUNTA_PDF candidatas se perdía
        # para siempre sin una segunda oportunidad. Aquí, la primera ronda
        # de relleno agota sus 3 intentos (todas "malas" a propósito) y
        # solo la SEGUNDA ronda (_MAX_RONDAS_RELLENO=2) consigue una
        # candidata válida (con _MAX_RONDAS_RELLENO=3, sin necesidad de
        # llegar a la tercera).
        construir_prompt = _construir_prompt_fabrica(None)
        contador_generacion = itertools.count()

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                candidata = json.loads(messages[1]["content"].split("PREGUNTA A VERIFICAR:\n")[1])
                valido = candidata["pregunta"] != "¿Mala primera ronda de relleno?"
                return json.dumps({"valido": valido, "problemas": [] if valido else ["dato inventado"]})
            indice = next(contador_generacion)
            if indice == 0:
                # Generación inicial del lote: no aporta ninguna candidata,
                # deja el único hueco pedido completamente a cargo del
                # relleno.
                return json.dumps([])
            if indice <= MAX_INTENTOS_POR_PREGUNTA_PDF:
                # Primera ronda de relleno: mala a propósito las
                # MAX_INTENTOS_POR_PREGUNTA_PDF veces, agota su
                # presupuesto sin llenar el hueco.
                return json.dumps([{
                    "pregunta": "¿Mala primera ronda de relleno?",
                    "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                    "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
                }])
            # Segunda ronda de relleno: válida a la primera.
            return json.dumps([{
                "pregunta": "¿Buena segunda ronda de relleno?",
                "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
            }])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, 1, "Texto de prueba.", tamano_lote=1)

        assert len(preguntas) == 1
        assert preguntas[0]["pregunta"] == "¿Buena segunda ronda de relleno?"
        assert errores == []

    def test_fragmenta_el_documento_entre_lotes_en_paralelo(self):
        # Bug real: con num_preguntas=20 sobre un PDF de 11 páginas, 8 de
        # las 20 preguntas recibidas acabaron siendo la misma pregunta
        # reformulada ("¿cuál es la duración del mandato del Presidente de
        # la Autoridad...?") porque los 4 lotes en paralelo recibían el
        # documento COMPLETO y convergían todos en el mismo hecho más
        # citable del texto -- el dedup por texto normalizado no detecta
        # reformulaciones de la misma información. Con un documento largo
        # y más de un lote, cada lote debe recibir un FRAGMENTO distinto
        # (ver _fragmentos_por_lote en test_generator.py) para repartir la
        # generación entre partes distintas del documento.
        # "PARRAFO N" (no "SECCION N"/"ARTÍCULO N") a propósito: este texto
        # no representa un documento legal real, solo prueba el reparto
        # intercalado por párrafo -- con un marcador que _bloques_
        # estructurales reconociera como Sección/Artículo, el reparto por
        # BLOQUE (ver TestFragmentosPorLote más abajo) se activaría en su
        # lugar y este test dejaría de probar lo que dice probar.
        parrafo = "Frase de relleno para simular contenido real del documento. " * 10
        texto_largo = "\n\n".join(f"PARRAFO {i}. {parrafo}" for i in range(4))
        assert len(texto_largo) >= 2 * 400  # por encima del umbral de fragmentación

        fragmentos_recibidos = []
        contador = itertools.count()

        def construir_prompt(n, fragmento=None):
            fragmentos_recibidos.append(fragmento)
            documento = fragmento if fragmento is not None else texto_largo
            return f"Genera {n} preguntas.\n\nDocumento para crear preguntas test:\n{documento}"

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps([{
                "pregunta": f"¿Pregunta {next(contador)}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
            } for _ in range(2)])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(
                construir_prompt, 4, texto_largo, tamano_lote=2,
            )

        assert len(preguntas) == 4
        assert errores == []
        # 2 lotes, cada uno pide su generación una sola vez (todo se acepta
        # a la primera, sin recambios ni relleno): 2 llamadas a
        # construir_prompt, cada una con un fragmento no vacío, DISTINTO
        # entre sí y distinto del documento completo. El reparto es
        # INTERCALADO por párrafo (ver _fragmentos_por_lote), no contiguo,
        # así que cada fragmento ya no es necesariamente una subcadena
        # literal del original -- se comprueba en su lugar que cada
        # PÁRRAFO de cada fragmento SÍ viene del documento original, y que
        # entre los dos fragmentos se reparten los 4 párrafos sin perder
        # ninguno.
        assert len(fragmentos_recibidos) == 2
        assert all(f is not None for f in fragmentos_recibidos)
        assert fragmentos_recibidos[0] != fragmentos_recibidos[1]
        assert all(f != texto_largo for f in fragmentos_recibidos)
        parrafos_originales = [p for p in texto_largo.split("\n\n") if p.strip()]
        parrafos_repartidos = [p for f in fragmentos_recibidos for p in f.split("\n\n")]
        assert sorted(parrafos_repartidos) == sorted(parrafos_originales)

    def test_dedupe_tambien_por_respuesta_correcta_larga(self):
        # Bug real: 4 preguntas sobre "la duración del mandato del
        # Presidente..." con el enunciado reformulado de 4 formas
        # distintas pero la MISMA respuesta correcta larga ("6 años, no
        # renovable.") pasaban el dedup anterior (que solo comparaba el
        # texto de la pregunta) como si fueran 4 preguntas distintas.
        # Aquí, dos candidatas con textos de pregunta completamente
        # distintos pero la misma respuesta correcta larga deben
        # deduplicarse a 1 sola.
        construir_prompt = _construir_prompt_fabrica(None)

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps([
                {"pregunta": "¿Cuánto dura el mandato del Presidente?",
                 "opciones": {"A": "4 años", "B": "5 años", "C": "6 años, no renovable.", "D": "7 años"},
                 "respuesta_correcta": "C", "explicacion": "Explicación de prueba para el test."},
                {"pregunta": "¿Es renovable el cargo del Presidente y por cuánto tiempo se ejerce?",
                 "opciones": {"A": "6 años, no renovable.", "B": "5 años", "C": "4 años", "D": "7 años"},
                 "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."},
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(
                construir_prompt, 2, "Texto de prueba.", tamano_lote=15,
            )

        assert len(preguntas) == 1

    def test_dedupe_por_articulo_y_cifras_pese_a_redaccion_muy_distinta(self):
        # Bug real de producción (02/08/2026), documento real: el art. 26.6
        # de una ley (plazo de audiencia pública, "15 días hábiles,
        # reducible a 7 días hábiles") generado 4 veces con redacciones
        # tan distintas que ni el texto de la pregunta ni el de la
        # respuesta completa coincidían -- se coló como 4 preguntas
        # "distintas" en un test de 20. Aquí, dos candidatas que citan el
        # mismo artículo base con la misma respuesta en cifras, pero con
        # el enunciado Y la respuesta completa redactados de forma
        # distinta, deben deduplicarse a 1 sola.
        construir_prompt = _construir_prompt_fabrica(None)

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps([
                {
                    "pregunta": "De acuerdo con el artículo 26.6 de la Ley 50/1997, ¿cuál es el plazo mínimo de "
                                "la audiencia e información públicas y en qué casos puede reducirse?",
                    "opciones": {
                        "A": "15 días hábiles, reducible a 7 días hábiles cuando razones debidamente "
                             "motivadas lo justifiquen o se aplique la tramitación urgente",
                        "B": "10 días hábiles", "C": "1 mes", "D": "15 días naturales",
                    },
                    "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test.",
                },
                {
                    "pregunta": "Conforme a lo establecido en el artículo 26 de la Ley 50/1997, ¿cuál es el "
                                "plazo mínimo de la audiencia e información públicas en el procedimiento de "
                                "elaboración de normas, y en qué supuestos puede reducirse?",
                    "opciones": {
                        "A": "El plazo mínimo es de 15 días hábiles, y puede reducirse hasta un mínimo de 7 "
                             "días hábiles cuando existan razones debidamente motivadas o se aplique la "
                             "tramitación urgente de iniciativas normativas.",
                        "B": "10 días hábiles", "C": "1 mes", "D": "15 días naturales",
                    },
                    "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test.",
                },
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(
                construir_prompt, 2, "Texto de prueba.", tamano_lote=15,
            )

        assert len(preguntas) == 1

    def test_no_dedupe_preguntas_legitimamente_distintas_del_mismo_articulo(self):
        # Mismo artículo base (26) pero cifras distintas (15/7 días frente
        # a 1 mes): son sub-puntos legítimamente distintos del mismo
        # artículo (audiencia pública frente a informes preceptivos) y NO
        # deben deduplicarse entre sí -- la clave nueva exige coincidir en
        # artículo Y cifras, no solo en el artículo.
        q_audiencia = {
            "pregunta": "Según el artículo 26.6 de la Ley 50/1997, ¿cuál es el plazo mínimo de la audiencia "
                        "e información públicas?",
            "opciones": {"A": "15 días hábiles"},
            "respuesta_correcta": "A",
        }
        q_informes = {
            "pregunta": "Según el artículo 26 de la Ley 50/1997, ¿en qué plazo se emiten los informes "
                        "preceptivos cuando se solicitan a otra Administración?",
            "opciones": {"A": "1 mes"},
            "respuesta_correcta": "A",
        }
        assert _claves_dedup(q_audiencia).isdisjoint(_claves_dedup(q_informes))

    def test_dedupe_de_fracciones_en_palabras_cifras_y_barra(self):
        # Bug real de producción (03/08/2026), documento real: 4 preguntas
        # sobre la mayoría exigida por el art. 168 de la Constitución
        # Española ("dos tercios de cada Cámara") se colaron como 4
        # preguntas "distintas" en un test de 20 porque la respuesta
        # correcta expresaba la misma fracción de formas distintas --
        # "dos tercios", "2/3" -- y _PATRON_CIFRA solo cazaba cifras con un
        # DÍGITO pegado a la unidad ("15 días", "1 mes"), nunca un número
        # en palabras ni una fracción con barra. Las mayorías cualificadas
        # (tercios, cuartos, quintos...) son uno de los datos más citados
        # en cualquier temario de oposición, así que esto no es específico
        # de un documento. Aquí, tres formas distintas de escribir "2/3"
        # deben producir la MISMA clave de dedup.
        q_palabras = {
            "pregunta": "Según el artículo 168 de la Constitución Española, ¿qué mayoría se exige para "
                        "la aprobación del principio de una reforma que afecte al Título II?",
            "opciones": {"A": "Mayoría de dos tercios de cada Cámara."}, "respuesta_correcta": "A",
        }
        q_barra = {
            "pregunta": "Conforme al artículo 168 de la Constitución Española, ¿qué mayoría se requiere "
                        "en cada Cámara para el principio de reforma del Título II?",
            "opciones": {"A": "Mayoría de 2/3 de cada Cámara."}, "respuesta_correcta": "A",
        }
        q_cifra_pegada = {
            "pregunta": "De acuerdo con el artículo 168 de la Constitución Española, ¿cuántos de los "
                        "miembros de cada Cámara deben votar a favor del principio de reforma del Título II?",
            "opciones": {"A": "Se exigen 2 tercios de cada Cámara."}, "respuesta_correcta": "A",
        }
        claves_palabras = _claves_dedup(q_palabras)
        claves_barra = _claves_dedup(q_barra)
        claves_cifra_pegada = _claves_dedup(q_cifra_pegada)
        assert any(c.startswith("d:168:2/3") for c in claves_palabras)
        assert (claves_palabras & claves_barra) and (claves_palabras & claves_cifra_pegada)

    def test_no_dedupe_fracciones_distintas_del_mismo_articulo(self):
        # "un tercio" y "dos tercios" del MISMO artículo son datos
        # distintos (no la misma fracción escrita de otra forma) y no
        # deben confundirse entre sí.
        q_un_tercio = {
            "pregunta": "Según el artículo 168, ¿qué fracción de la Cámara debe estar presente?",
            "opciones": {"A": "Un tercio de sus miembros."}, "respuesta_correcta": "A",
        }
        q_dos_tercios = {
            "pregunta": "Según el artículo 168, ¿qué mayoría se exige para aprobar la reforma?",
            "opciones": {"A": "Dos tercios de sus miembros."}, "respuesta_correcta": "A",
        }
        assert _claves_dedup(q_un_tercio).isdisjoint(_claves_dedup(q_dos_tercios))

    def test_dedupe_por_mayoria_cualificada_sin_cifra_numerica(self):
        # Bug real de producción (03/08/2026), documento real: "¿qué mayoría
        # se requiere en el Senado para que el Congreso apruebe por dos
        # tercios?" se preguntó 3 VECES en un test de 20 con enunciados
        # distintos, las 3 con la misma respuesta correcta ("Mayoría
        # absoluta") -- pero "absoluta" no lleva ningún dígito ni fracción
        # pegados, así que _PATRON_CIFRA no la reconocía como cifra y la
        # clave artículo+cifras nunca se generaba. Una de las 3 ni siquiera
        # citaba "artículo 167" en el enunciado (solo en la explicación) --
        # ver también test_dedupe_articulo_citado_solo_en_la_explicacion.
        q2 = {
            "pregunta": "Según el artículo 167 de la Constitución Española, en el procedimiento ordinario de "
                        "reforma constitucional, si el texto presentado por la Comisión Paritaria no obtiene "
                        "las mayorías exigidas, ¿qué mayoría se requiere en el Senado para que el Congreso de "
                        "los Diputados pueda aprobar la reforma por mayoría de dos tercios?",
            "opciones": {"A": "Mayoría simple.", "B": "Mayoría de tres quintos.", "C": "Mayoría absoluta.",
                         "D": "Mayoría de dos tercios."},
            "respuesta_correcta": "C",
            "explicacion": "C) es correcta porque el artículo 167 de la Constitución Española establece que, "
                           "si el Senado aprueba el texto por mayoría absoluta, el Congreso podrá aprobar la "
                           "reforma por mayoría de dos tercios.",
        }
        q11 = {
            "pregunta": "Según el artículo 167 de la Constitución Española, en el procedimiento ordinario de "
                        "reforma constitucional, si no se logra la aprobación mediante el procedimiento de la "
                        "Comisión de composición paritaria de Diputados y Senadores, ¿qué condición debe "
                        "cumplirse para que el Congreso pueda aprobar la reforma por mayoría de dos tercios?",
            "opciones": {"A": "Que el texto hubiere obtenido el voto favorable de la mayoría absoluta del Senado",
                         "B": "x", "C": "y", "D": "z"},
            "respuesta_correcta": "A",
            "explicacion": "A) es correcta porque el artículo 167.2 de la Constitución Española establece que, "
                           "de no lograrse la aprobación mediante el procedimiento del apartado anterior, y "
                           "siempre que el texto hubiere obtenido el voto favorable de la mayoría absoluta del "
                           "Senado, el Congreso, por mayoría de dos tercios, podrá aprobar la reforma.",
        }
        q18 = {
            "pregunta": "Según la Constitución Española de 1978, ¿qué mayoría se exige en el Senado para que, "
                        "en el procedimiento de reforma ordinaria, el Congreso pueda aprobar la reforma por "
                        "mayoría de dos tercios si no se logra el acuerdo inicial entre ambas Cámaras?",
            "opciones": {"A": "Mayoría simple", "B": "Mayoría absoluta", "C": "Mayoría de tres quintos",
                         "D": "Mayoría de dos tercios"},
            "respuesta_correcta": "B",
            "explicacion": "B) es correcta porque el artículo 167.2 de la Constitución Española de 1978 "
                           "establece que, de no lograrse la aprobación mediante la Comisión de composición "
                           "paritaria, y siempre que el texto hubiere obtenido el voto favorable de la mayoría "
                           "absoluta del Senado, el Congreso, por mayoría de dos tercios, podrá aprobar la "
                           "reforma.",
        }
        claves_q2, claves_q11, claves_q18 = _claves_dedup(q2), _claves_dedup(q11), _claves_dedup(q18)
        assert any(c.startswith("d:167:mayor") for c in claves_q2)
        assert (claves_q2 & claves_q11) and (claves_q2 & claves_q18)

    def test_dedupe_articulo_citado_solo_en_la_explicacion(self):
        # Bug real (mismo caso que arriba, pregunta 18): el enunciado dice
        # "Según la Constitución Española de 1978..." sin repetir el número
        # de artículo -- solo la explicación lo cita ("el artículo 167.2 de
        # la Constitución Española establece..."). _articulos_citados debe
        # encontrarlo igual, buscando en explicación además de en el
        # enunciado.
        q_sin_articulo_en_enunciado = {
            "pregunta": "Según la Constitución Española de 1978, ¿qué mayoría se exige en el Senado para que "
                        "el Congreso pueda aprobar la reforma por mayoría de dos tercios?",
            "opciones": {"A": "Mayoría absoluta"}, "respuesta_correcta": "A",
            "explicacion": "El artículo 167.2 de la Constitución Española establece que el Congreso, por "
                           "mayoría de dos tercios, podrá aprobar la reforma.",
        }
        q_con_articulo_en_enunciado = {
            "pregunta": "Según el artículo 167 de la Constitución Española, ¿qué mayoría se requiere en el "
                        "Senado para que el Congreso pueda aprobar la reforma por dos tercios?",
            "opciones": {"A": "Mayoría absoluta."}, "respuesta_correcta": "A",
            "explicacion": "Explicación de prueba para el test.",
        }
        claves_1 = _claves_dedup(q_sin_articulo_en_enunciado)
        claves_2 = _claves_dedup(q_con_articulo_en_enunciado)
        assert claves_1 & claves_2

    def test_dedupe_de_fracciones_expresadas_como_una_quinta_parte(self):
        # Bug real de producción (03/08/2026), documento real: "la firma de
        # 2 Grupos Parlamentarios o de una quinta parte de los miembros de
        # la Cámara" (art. 146 del Reglamento del Congreso) se preguntó 2
        # veces con enunciados distintos -- "una quinta parte" es la forma
        # HABITUAL de expresar una fracción en español jurídico (adjetivo
        # ordinal femenino + "parte"), gramaticalmente distinta de "un
        # quinto"/"dos quintos" que ya cubría el patrón anterior.
        q16 = {
            "pregunta": "Según el artículo 146 del Reglamento del Congreso de los Diputados, ¿qué se requiere "
                        "para presentar una proposición de reforma constitucional en el Congreso de los "
                        "Diputados?",
            "opciones": {"A": "x", "B": "La firma de 2 Grupos Parlamentarios o de una quinta parte de los "
                                        "miembros de la Cámara.", "C": "y", "D": "z"},
            "respuesta_correcta": "B",
        }
        q17 = {
            "pregunta": "Según el artículo 146 del Reglamento del Congreso de los Diputados, ¿qué se exige "
                        "para que los Grupos parlamentarios puedan presentar una proposición de reforma "
                        "constitucional?",
            "opciones": {"A": "x", "B": "Que esté suscrita por 2 Grupos parlamentarios o por una quinta parte "
                                        "de los miembros de la Cámara.", "C": "y", "D": "z"},
            "respuesta_correcta": "B",
        }
        claves_q16, claves_q17 = _claves_dedup(q16), _claves_dedup(q17)
        assert any(c.startswith("d:146:1/5") for c in claves_q16)
        assert claves_q16 & claves_q17

    def test_dedupe_por_principio_juridico_con_nombre_propio(self):
        # Bug real de producción (03/08/2026), documento real: "¿qué
        # principio implica que la ley no podrá aplicarse a casos
        # anteriores...?" (respuesta: "El principio de irretroactividad de
        # ciertas normas.") es un hecho de nombre propio (no una cifra) del
        # artículo 9.3 de la Constitución Española -- uno de los artículos
        # más citados en cualquier temario de oposición sobre Administración
        # Pública.
        q_a = {
            "pregunta": "Según el artículo 9.3 de la Constitución Española, ¿qué principio del ordenamiento "
                        "jurídico implica que la ley no podrá aplicarse a casos anteriores cuando se trate de "
                        "disposiciones sancionadoras no favorables?",
            "opciones": {"A": "El principio de legalidad.", "B": "El principio de jerarquía normativa.",
                         "C": "El principio de irretroactividad de ciertas normas.",
                         "D": "El principio de seguridad jurídica."},
            "respuesta_correcta": "C",
        }
        q_b = {
            "pregunta": "De acuerdo con el artículo 9.3 de la Constitución Española, ¿qué garantiza la "
                        "irretroactividad de las disposiciones sancionadoras no favorables?",
            "opciones": {"A": "El principio de irretroactividad.", "B": "x", "C": "y", "D": "z"},
            "respuesta_correcta": "A",
        }
        assert _claves_dedup(q_a) & _claves_dedup(q_b)

    def test_no_dedupe_principios_distintos_pese_a_explicacion_cruzada(self):
        # Bug potencial descartado durante el desarrollo de la clave de
        # arriba: la "explicacion" de este tipo de pregunta repasa las 4
        # opciones (formato exigido por el prompt de generación), así que
        # una pregunta sobre "publicidad de las normas" menciona en su
        # propia explicación "el principio de legalidad", "jerarquía
        # normativa" e "irretroactividad" -- los distractores descartados.
        # Dos preguntas legítimamente distintas que solo comparten un
        # distractor mencionado en la explicación (nada raro con 7
        # principios posibles del art. 9.3 y varias preguntas sobre el
        # mismo artículo) NO deben confundirse -- por eso la clave busca
        # solo en la pregunta y la respuesta CORRECTA, nunca en la
        # explicación completa.
        q_publicidad = {
            "pregunta": "Según el artículo 9.3 de la Constitución Española, ¿qué principio implica que los "
                        "ciudadanos solo podrán acatar las normas si tienen la oportunidad de conocerlas?",
            "opciones": {"A": "El principio de legalidad", "B": "El principio de jerarquía normativa",
                         "C": "El principio de publicidad de las normas",
                         "D": "El principio de irretroactividad de las disposiciones sancionadoras"},
            "respuesta_correcta": "C",
            "explicacion": "C) es correcta porque garantiza la publicidad de las normas. A) es incorrecta "
                           "porque el principio de legalidad no se refiere a esto. B) es incorrecta porque el "
                           "principio de jerarquía normativa ordena las normas. D) es incorrecta porque el "
                           "principio de irretroactividad de las disposiciones sancionadoras no favorables se "
                           "refiere a otra cosa.",
        }
        q_interdiccion = {
            "pregunta": "De acuerdo con el artículo 9.3 de la Constitución Española, ¿qué principio se "
                        "relaciona con la desviación de poder del artículo 106?",
            "opciones": {"A": "El principio de responsabilidad de los poderes públicos",
                         "B": "El principio de interdicción de la arbitrariedad de los poderes públicos",
                         "C": "El principio de seguridad jurídica", "D": "El principio de jerarquía normativa"},
            "respuesta_correcta": "B",
            "explicacion": "B) es correcta porque se relaciona con la desviación de poder. A) es incorrecta "
                           "porque el principio de responsabilidad de los poderes públicos es otra cosa. C) es "
                           "incorrecta porque el principio de seguridad jurídica implica claridad normativa. "
                           "D) es incorrecta porque el principio de jerarquía normativa ordena las normas.",
        }
        assert _claves_dedup(q_publicidad).isdisjoint(_claves_dedup(q_interdiccion))

    def test_dedupe_ignora_referencia_cruzada_a_otro_articulo_en_la_explicacion(self):
        # Bug real de producción (03/08/2026), documento real: dos preguntas
        # casi idénticas sobre el artículo 167 ("mayoría de tres quintos"
        # para la reforma ordinaria) se colaron juntas en un test de 18/20
        # pese a que _claves_dedup debería haberlas fusionado. Antes,
        # _articulos_citados buscaba en el enunciado Y en TODA la
        # explicación: una de las dos preguntas, al descartar la opción
        # "mayoría de dos tercios", mencionaba de pasada que esa mayoría
        # "se exige... en el procedimiento agravado del artículo 168" --
        # una simple referencia cruzada en un distractor, no el artículo de
        # la pregunta -- así que esa candidata quedaba con
        # articulos={'167','168'} mientras la otra (sin esa referencia
        # cruzada) quedaba con articulos={'167'}, produciendo claves
        # distintas (d:167|168:3/5 frente a d:167:3/5) que nunca coincidían.
        q_con_referencia_cruzada = {
            "pregunta": "Conforme al artículo 167 de la Constitución Española, ¿qué mayoría se exige "
                        "inicialmente para la aprobación de un proyecto de reforma constitucional por el "
                        "procedimiento ordinario en cada una de las Cámaras?",
            "opciones": {"A": "Mayoría absoluta.", "B": "Mayoría de tres quintos.",
                         "C": "Mayoría de dos tercios.", "D": "Mayoría simple."},
            "respuesta_correcta": "B",
            "explicacion": "A) es incorrecta porque el artículo 167 de la Constitución Española no establece "
                           "la mayoría absoluta como requisito inicial para la aprobación de la reforma "
                           "ordinaria. B) es correcta porque el artículo 167 de la Constitución Española "
                           "establece que los proyectos de reforma constitucional deberán ser aprobados por "
                           "una mayoría de tres quintos de cada una de las Cámaras. C) es incorrecta porque la "
                           "mayoría de dos tercios se exige en el artículo 167 de la Constitución Española "
                           "solo en una fase posterior, como alternativa si no se logra el acuerdo inicial y el "
                           "Senado ha aprobado el texto por mayoría absoluta, o en el procedimiento agravado "
                           "del artículo 168 de la Constitución Española. D) es incorrecta porque la mayoría "
                           "simple no se contempla en el artículo 167 de la Constitución Española para la "
                           "aprobación inicial de la reforma ordinaria.",
        }
        q_sin_referencia_cruzada = {
            "pregunta": "Según el artículo 167 de la Constitución Española de 1978, ¿qué mayoría se exige "
                        "inicialmente para la aprobación de un proyecto de reforma constitucional en cada una "
                        "de las Cámaras?",
            "opciones": {"A": "Mayoría absoluta", "B": "Mayoría de tres quintos", "C": "Mayoría de dos tercios",
                         "D": "Mayoría simple"},
            "respuesta_correcta": "B",
            "explicacion": "A) es incorrecta porque el artículo 167 de la Constitución Española de 1978 exige "
                           "una mayoría de tres quintos, no mayoría absoluta, para la aprobación inicial de los "
                           "proyectos de reforma constitucional en cada Cámara. B) es correcta porque el "
                           "apartado 1 del artículo 167 de la Constitución Española de 1978 establece que los "
                           "proyectos de reforma constitucional deberán ser aprobados por una mayoría de tres "
                           "quintos de cada una de las Cámaras. C) es incorrecta porque la mayoría de dos "
                           "tercios solo se requiere en el procedimiento ordinario como alternativa final, "
                           "cuando el Senado ha aprobado el texto por mayoría absoluta y el Congreso debe "
                           "aprobarlo por dos tercios, según el apartado 2 del artículo 167 de la Constitución "
                           "Española de 1978, no como mayoría inicial. D) es incorrecta porque la mayoría "
                           "simple no es la exigida en el artículo 167 de la Constitución Española de 1978 "
                           "para la aprobación inicial de una reforma constitucional ordinaria.",
        }
        assert _claves_dedup(q_con_referencia_cruzada) & _claves_dedup(q_sin_referencia_cruzada)

    def test_dedupe_por_contencion_pregunta_amplia_y_pregunta_concreta(self):
        # Bug real de producción (03/08/2026), documento real: "¿qué
        # establece el artículo 8 sobre las Fuerzas Armadas?" (respuesta:
        # composición Y misión) y "¿cuál es la misión de las Fuerzas
        # Armadas según el artículo 8?" (respuesta: solo la misión, un
        # fragmento LITERAL de la respuesta anterior) se colaron como 2
        # preguntas "distintas" en un test de 20 -- ni el texto de la
        # pregunta ni el de la respuesta completa coinciden entre sí, y sin
        # cifras concretas (es un dato de composición/misión, no un
        # número) tampoco se genera la clave artículo+cifras. Aquí, con los
        # textos reales de esas dos preguntas, _es_duplicado_por_contencion
        # debe detectar que la respuesta de la segunda es un fragmento de
        # la primera.
        pregunta_amplia = {
            "pregunta": "Según la Constitución Española de 1978, ¿qué se establece en su artículo 8 en "
                        "relación con las Fuerzas Armadas?",
            "opciones": {"A": "Que están constituidas por el Ejército de Tierra, la Armada y el Ejército "
                              "del Aire, y tienen como misión garantizar la soberanía e independencia de "
                              "España, defender su integridad territorial y el ordenamiento constitucional."},
            "respuesta_correcta": "A",
        }
        pregunta_concreta = {
            "pregunta": "Según el artículo 8 de la Constitución Española de 1978, ¿cuál es la misión de "
                        "las Fuerzas Armadas?",
            "opciones": {"A": "Garantizar la soberanía e independencia de España, defender su integridad "
                              "territorial y el ordenamiento constitucional."},
            "respuesta_correcta": "A",
        }
        assert _claves_dedup(pregunta_amplia).isdisjoint(_claves_dedup(pregunta_concreta))
        assert _es_duplicado_por_contencion(pregunta_concreta, [pregunta_amplia])

    def test_no_dedupe_por_contencion_respuestas_cortas_coincidentes_por_azar(self):
        # Dos preguntas LEGÍTIMAMENTE distintas del mismo artículo con una
        # respuesta corta y genérica que coincide por casualidad (aquí,
        # ambas responden "Mayoría absoluta.") no deben confundirse --
        # el umbral de longitud de la contención es más alto que el de la
        # clave "r:" a propósito para esto.
        pregunta_1 = {
            "pregunta": "Según el artículo 9, ¿qué mayoría se exige al Senado en la primera votación?",
            "opciones": {"A": "Mayoría absoluta."}, "respuesta_correcta": "A",
        }
        pregunta_2 = {
            "pregunta": "Según el artículo 9, ¿qué mayoría se exige al Congreso en la ratificación final?",
            "opciones": {"A": "Mayoría absoluta."}, "respuesta_correcta": "A",
        }
        assert not _es_duplicado_por_contencion(pregunta_2, [pregunta_1])

    def test_dedupe_por_solapamiento_de_palabras_con_orden_distinto(self):
        # Bug real de producción (03/08/2026), documento real: 3 preguntas
        # sobre el mismo requisito del artículo 1.3 del Código Civil (que la
        # costumbre "regirá en defecto de ley aplicable, siempre que resulte
        # probada y no sea contraria a la moral o al orden público") se
        # colaron juntas en un test de 20. Ninguna de las tres coincidía en
        # texto exacto con otra (falla "r:"), ni ninguna era un fragmento
        # LITERAL CONTIGUO de otra (falla la contención de arriba): una
        # reordenaba "resulte probada" y "no sea contraria..." al revés, y
        # otra cambiaba "o" por "ni". El solapamiento de palabras (sin
        # importar el orden) sí detecta que es el mismo hecho.
        pregunta_completa = {
            "pregunta": "Según el artículo 1 del Real Decreto de 24 de julio de 1889 por el que se publica "
                        "el Código Civil, ¿cuál de las siguientes afirmaciones sobre la costumbre es "
                        "correcta?",
            "opciones": {"A": "La costumbre solo regirá en defecto de ley aplicable, siempre que resulte "
                              "probada y no sea contraria a la moral o al orden público."},
            "respuesta_correcta": "A",
        }
        pregunta_orden_invertido = {
            "pregunta": "Según el artículo 1.3 del Real Decreto de 24 de julio de 1889 por el que se "
                        "publica el Código Civil, ¿en qué condiciones la costumbre regirá en defecto de "
                        "ley aplicable?",
            "opciones": {"A": "Siempre que no sea contraria a la moral o al orden público y resulte "
                              "probada."},
            "respuesta_correcta": "A",
        }
        pregunta_una_palabra_distinta = {
            "pregunta": "Según artículo 1 del Código Civil, publicado por el Real Decreto de 24 de julio "
                        "de 1889, ¿cuál de las siguientes afirmaciones sobre las fuentes del ordenamiento "
                        "jurídico español es correcta?",
            "opciones": {"A": "La costumbre solo regirá en defecto de ley aplicable, siempre que resulte "
                              "probada y no sea contraria a la moral ni al orden público."},
            "respuesta_correcta": "A",
        }
        assert _claves_dedup(pregunta_completa).isdisjoint(_claves_dedup(pregunta_orden_invertido))
        assert _claves_dedup(pregunta_completa).isdisjoint(_claves_dedup(pregunta_una_palabra_distinta))
        assert _es_duplicado_por_contencion(pregunta_orden_invertido, [pregunta_completa])
        assert _es_duplicado_por_contencion(pregunta_una_palabra_distinta, [pregunta_completa])

    def test_no_dedupe_por_solapamiento_hechos_distintos_del_mismo_articulo(self):
        # Bug potencial descartado durante el desarrollo del solapamiento de
        # palabras de arriba: el mismo documento real tiene VARIAS preguntas
        # legítimamente distintas sobre el artículo 1 del Código Civil (el
        # deber de los jueces de resolver, la nulidad de disposiciones que
        # contradicen una norma superior, las fuentes del ordenamiento...) --
        # ninguna de ellas debe fusionarse con la pregunta sobre los
        # requisitos de la costumbre solo por compartir el mismo artículo
        # base. Probado con el umbral 0.5: estos pares reales dan como mucho
        # 0.18 de solapamiento.
        pregunta_costumbre = {
            "pregunta": "Según el artículo 1 del Código Civil, ¿cuál de las siguientes afirmaciones sobre "
                        "la costumbre es correcta?",
            "opciones": {"A": "La costumbre solo regirá en defecto de ley aplicable, siempre que resulte "
                              "probada y no sea contraria a la moral o al orden público."},
            "respuesta_correcta": "A",
        }
        pregunta_deber_jueces = {
            "pregunta": "Según el artículo 1 del Código Civil, ¿cuál es el deber de los Jueces y "
                        "Tribunales respecto al sistema de fuentes?",
            "opciones": {"A": "Tienen el deber inexcusable de resolver en todo caso los asuntos de que "
                              "conozcan, ateniéndose al sistema de fuentes establecido."},
            "respuesta_correcta": "A",
        }
        pregunta_nulidad = {
            "pregunta": "Según el artículo 1.2 del Código Civil, ¿qué consecuencia se deriva para las "
                        "disposiciones que contradigan otra de rango superior?",
            "opciones": {"A": "Carecerán de validez."},
            "respuesta_correcta": "A",
        }
        assert not _es_duplicado_por_contencion(pregunta_deber_jueces, [pregunta_costumbre])
        assert not _es_duplicado_por_contencion(pregunta_nulidad, [pregunta_costumbre])

    def test_dedupe_por_contencion_de_cifras_con_formatos_distintos(self):
        # Bug real de producción (03/08/2026), documento real: una pregunta
        # concreta sobre el límite de deuda pública de las Comunidades
        # Autónomas ("El 13 por ciento del Producto Interior Bruto
        # nacional") y otra más amplia sobre el mismo artículo con el
        # desglose completo por subsector ("El 60% del PIB..., un 13% para
        # las Comunidades Autónomas...") citan el MISMO dato, pero ninguna
        # comprobación existente lo detectaba: el texto no coincide ni por
        # contención ni por solapamiento de palabras (la pregunta amplia
        # tiene muchas más palabras propias -- 44%, 3%, Corporaciones
        # Locales... -- que diluyen el solapamiento muy por debajo del
        # umbral), y la clave "d:" exige que el conjunto de cifras sea
        # IDÉNTICO, no que uno esté contenido en el otro -- y ni siquiera
        # llegaba a comparar bien: "13 por ciento" y "13%" son cadenas
        # distintas para _PATRON_CIFRA (ver _normalizar_cifra, que ahora
        # normaliza ambos formatos a "13%").
        pregunta_concreta = {
            "pregunta": "De acuerdo con el artículo 13 de la Ley Orgánica 2/2012, de 27 de abril, de "
                        "Estabilidad Presupuestaria y Sostenibilidad Financiera, ¿cuál es el límite "
                        "máximo de deuda pública para el conjunto de Comunidades Autónomas en relación "
                        "con el Producto Interior Bruto nacional?",
            "opciones": {"A": "El 13 por ciento del Producto Interior Bruto nacional."},
            "respuesta_correcta": "A",
        }
        pregunta_amplia = {
            "pregunta": "Conforme a la Ley Orgánica 2/2012, de 27 de abril, de Estabilidad "
                        "Presupuestaria y Sostenibilidad Financiera, ¿cuál es el porcentaje del "
                        "Producto Interior Bruto nacional que, como máximo, puede alcanzar el volumen "
                        "de deuda pública del conjunto de las Administraciones Públicas, y cómo se "
                        "distribuye entre los diferentes subsectores?",
            "opciones": {"A": "El 60% del PIB nacional, distribuido en un 44% para la Administración "
                              "central, un 13% para el conjunto de las Comunidades Autónomas y un 3% "
                              "para el conjunto de las Corporaciones Locales."},
            "respuesta_correcta": "A",
            "explicacion": "el artículo 13 de la Ley Orgánica 2/2012 establece el límite de deuda.",
        }
        assert _claves_dedup(pregunta_concreta).isdisjoint(_claves_dedup(pregunta_amplia))
        assert _es_duplicado_por_contencion(pregunta_concreta, [pregunta_amplia])

    def test_lotes_en_paralelo_no_reportan_duplicados_por_sse(self):
        # Bug real de producción (03/08/2026), con un documento real: 3
        # preguntas casi idénticas sobre el art. 26.6 (plazo de audiencia
        # pública) generadas por LOTES DISTINTOS en paralelo se mostraban
        # las 3 en el test, aunque _claves_dedup ya las identificaba
        # correctamente como la misma pregunta. La causa no era la clave de
        # dedup (correcta) sino que _reportar_avance_pregunta (el evento SSE
        # que el frontend muestra de inmediato) se disparaba dentro de cada
        # lote en cuanto pasaba SU PROPIA verificación, antes de que el
        # dedup -- que antes solo corría en una pasada final tras acabar
        # TODOS los lotes -- tuviera ocasión de detectarla. Aquí, con 2
        # lotes de 1 pregunta cada uno generando SIEMPRE una candidata
        # equivalente (mismo artículo, mismas cifras, redacción distinta),
        # el resultado final debe tener como mucho 1 pregunta de ese hecho Y
        # el evento SSE con "pregunta" (el que el frontend muestra) solo
        # debe haberse disparado una vez con ese contenido -- nunca dos
        # veces con la misma pregunta duplicada.
        construir_prompt = _construir_prompt_fabrica(None)
        candidatas_equivalentes = [
            {
                "pregunta": "¿Cuál es el plazo mínimo de audiencia pública del artículo 26?",
                "opciones": {"A": "15 días hábiles", "B": "10 días", "C": "1 mes", "D": "2 meses"},
                "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test.",
            },
            {
                "pregunta": "Según el artículo 26.6, ¿en cuántos días hábiles debe darse audiencia pública?",
                "opciones": {"A": "15 días hábiles", "B": "10 días", "C": "1 mes", "D": "2 meses"},
                "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test.",
            },
        ]
        contador_generacion = itertools.count()

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            indice = next(contador_generacion) % 2
            return json.dumps([candidatas_equivalentes[indice]])

        eventos = []
        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(
                construir_prompt, 2, "Texto de prueba.", tamano_lote=1, on_progreso=eventos.append,
            )

        assert len(preguntas) == 1
        eventos_con_pregunta = [e for e in eventos if "pregunta" in e]
        assert len(eventos_con_pregunta) == 1

    def test_relleno_evita_repetir_preguntas_ya_aceptadas(self):
        # El relleno debe conocer lo que YA está aceptado en el resto del
        # test para no volver a generar el mismo hecho sobreexplotado del
        # documento -- antes, un hueco de relleno solo sabía evitar LA
        # candidata que él mismo acababa de descartar en su propio
        # intento, sin ninguna noción de las preguntas ya aceptadas de
        # los lotes o de otros huecos.
        construir_prompt = _construir_prompt_fabrica(None)
        prompts_relleno = []

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            contenido = messages[0]["content"]
            if "Genera 1 preguntas" in contenido:
                prompts_relleno.append(contenido)
                return json.dumps([{
                    "pregunta": "¿Pregunta de relleno?",
                    "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                    "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
                }])
            # Lote inicial: pide 2 preguntas pero solo devuelve 1 (deja un
            # hueco que el relleno debe rellenar).
            return json.dumps([{
                "pregunta": "¿Cuánto dura el mandato del Presidente?",
                "opciones": {"A": "1", "B": "2", "C": "6 años, no renovable.", "D": "4"},
                "respuesta_correcta": "C", "explicacion": "Explicación de prueba para el test."
            }])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(
                construir_prompt, 2, "Texto de prueba.", tamano_lote=2,
            )

        assert len(preguntas) == 2
        assert len(prompts_relleno) >= 1
        assert any("6 años, no renovable." in p for p in prompts_relleno)
        assert any("No repitas ninguno de estos temas" in p for p in prompts_relleno)

    def test_preguntas_a_evitar_se_incluyen_en_el_lote_inicial(self):
        # "generar test" otra vez sobre un documento ya subido antes debe
        # avisar a la IA de las preguntas de tests ANTERIORES para no
        # repetirlas (ver blueprints/pdf_ia.py, obtener_preguntas_previas
        # en documentos_pdf.py) -- sin esto, cada llamada a
        # generar_preguntas_ia_en_lotes parte de cero, sin memoria de lo ya
        # preguntado en una generación previa del mismo documento.
        construir_prompt = _construir_prompt_fabrica(None)
        prompts_recibidos = []

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            prompts_recibidos.append(messages[0]["content"])
            return json.dumps([{
                "pregunta": "¿Pregunta nueva?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
            }])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            generar_preguntas_ia_en_lotes(
                construir_prompt, 1, "Texto de prueba.", tamano_lote=1,
                preguntas_a_evitar=["¿Pregunta ya usada en un test anterior? (respuesta: 6 años)"],
            )

        assert any(
            "¿Pregunta ya usada en un test anterior? (respuesta: 6 años)" in p and "tests ANTERIORES" in p
            for p in prompts_recibidos
        )

    def test_preguntas_a_evitar_tambien_llegan_al_relleno(self):
        construir_prompt = _construir_prompt_fabrica(None)
        prompts_relleno = []

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            contenido = messages[0]["content"]
            if "Genera 1 preguntas" in contenido:
                prompts_relleno.append(contenido)
                return json.dumps([{
                    "pregunta": "¿Pregunta de relleno?",
                    "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                    "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
                }])
            # Lote inicial: pide 2 preguntas pero solo devuelve 1 (deja un
            # hueco que el relleno debe rellenar).
            return json.dumps([{
                "pregunta": "¿Pregunta del lote?",
                "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
            }])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(
                construir_prompt, 2, "Texto de prueba.", tamano_lote=2,
                preguntas_a_evitar=["¿Pregunta de un test anterior?"],
            )

        assert len(preguntas) == 2
        assert any("¿Pregunta de un test anterior?" in p for p in prompts_relleno)

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
            if _es_llamada_deduplicacion_final(messages):
                return json.dumps({"grupos_duplicados": []})
            max_tokens_recibidos.append(max_tokens)
            return json.dumps([
                {"pregunta": f"¿Pregunta {i}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."}
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
            if _es_llamada_deduplicacion_final(messages):
                return json.dumps({"grupos_duplicados": []})
            max_tokens_recibidos.append(max_tokens)
            return json.dumps([
                {"pregunta": f"¿Pregunta {i}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."}
                for i in range(6)
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            generar_preguntas_ia_en_lotes(construir_prompt, 6, "Texto de prueba.", tamano_lote=6)

        assert max_tokens_recibidos == [8000]  # min(8000, 1500*6=9000) -> 8000

    def test_verificacion_individual_escala_max_workers_con_el_tamano_del_lote(self):
        # Cada candidata de un lote se verifica en paralelo con su propia
        # llamada (ver el comentario largo junto a _pedir_lote_verificado en
        # test_generator.py sobre por qué se retiró la verificación en
        # bloque) -- aquí se comprueba que las 4 candidatas de un lote
        # generan 4 llamadas de verificación independientes, cada una con su
        # propio max_tokens=8000 (ver _verificar_pregunta), no una sola
        # llamada conjunta.
        construir_prompt = _construir_prompt_fabrica(None)
        max_tokens_individuales = []

        def fake_call(messages, max_tokens=None, **kwargs):
            if _es_llamada_verificacion(messages):
                max_tokens_individuales.append(max_tokens)
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps([
                {"pregunta": f"¿Pregunta {i}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."}
                for i in range(4)
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            generar_preguntas_ia_en_lotes(construir_prompt, 4, "Texto de prueba.", tamano_lote=4)

        assert max_tokens_individuales == [8000, 8000, 8000, 8000]

    def test_verificacion_individual_de_recambio_sigue_pidiendo_8000_tokens(self):
        # Bug real de producción: con max_tokens=400, deepseek-v4-flash
        # truncaba la respuesta de verificación (finish_reason="length")
        # cuando detallaba varios problemas, y el JSON cortado se trataba
        # como pregunta inválida aunque no lo fuera -- multiplicando las
        # llamadas totales y dejando el test por debajo de lo pedido. Ese
        # margen (subido de 400 a 2000, a 4000 y finalmente a 8000 -- ver
        # _verificar_pregunta) se sigue usando tanto en la primera
        # verificación individual de una candidata como en la de su
        # recambio, si la primera falla (_asegurar_pregunta_valida no
        # cambia).
        construir_prompt = _construir_prompt_fabrica(None)
        max_tokens_individual = []

        def fake_call(messages, max_tokens=None, **kwargs):
            if _es_llamada_verificacion(messages):
                max_tokens_individual.append(max_tokens)
                candidata = json.loads(messages[1]["content"].split("PREGUNTA A VERIFICAR:\n")[1])
                valido = candidata["pregunta"] != "¿Pregunta mala?"
                return json.dumps({"valido": valido, "problemas": [] if valido else ["dato inventado"]})
            if "No repitas esta pregunta" in messages[0]["content"]:
                return json.dumps([{
                    "pregunta": "¿Pregunta buena?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                    "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
                }])
            return json.dumps([{
                "pregunta": "¿Pregunta mala?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
            }])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            generar_preguntas_ia_en_lotes(construir_prompt, 1, "Texto de prueba.", tamano_lote=1)

        # La primera verificación (de la candidata original, que falla) y la
        # de su recambio (que pasa) piden ambas el mismo margen de 8000.
        assert max_tokens_individual == [8000, 8000]

    def test_verificacion_individual_mantiene_el_thinking_encendido(self):
        # call_deepseek_api desactiva el razonamiento de deepseek-v4-flash
        # por defecto (02/08/2026, ver deepseek_utils.py) porque en la
        # GENERACIÓN no aportaba nada -- pero esto es una verificación, la
        # tarea que se juega la precisión frente al documento de origen, así
        # que debe pedir thinking_enabled=True explícitamente.
        with patch("test_generator.call_deepseek_api", return_value=json.dumps({"valido": True, "problemas": []})) as mock:
            _verificar_pregunta({"pregunta": "¿?"}, "Documento de prueba.", on_usage=None)
        assert mock.call_args.kwargs["thinking_enabled"] is True

    def test_nunca_devuelve_mas_preguntas_de_las_pedidas(self):
        # Bug real reportado: pedir 20 preguntas y recibir 22 -- un lote
        # puede ignorar el "EXACTAMENTE n" del prompt y devolver más
        # candidatas de las solicitadas (aquí, 2 lotes de 2 devuelven 3
        # candidatas cada uno, las 6 válidas y distintas). Antes nada
        # recortaba el exceso.
        construir_prompt = _construir_prompt_fabrica(None)
        contador = itertools.count()

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps([
                {"pregunta": f"¿Pregunta {next(contador)}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."}
                for _ in range(3)
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, 4, "Texto de prueba.", tamano_lote=2)

        assert len(preguntas) == 4
        assert errores == []

    def test_verificacion_individual_dispara_una_llamada_por_candidata(self):
        # Con un lote de 5 preguntas todas válidas a la primera, el total
        # debe ser 7 llamadas (1 generación + 1 verificación POR PREGUNTA
        # + 1 pasada final de deduplicación semántica sobre las 5 ya
        # aceptadas, ver _detectar_duplicados_finales) -- ver el
        # comentario largo junto a _pedir_lote_verificado en
        # test_generator.py sobre por qué se retiró la verificación en
        # bloque (una sola llamada para las 5) que antes reducía esto a 2:
        # con thinking_enabled=True el razonamiento del modelo escala con
        # cuántas candidatas juzga A LA VEZ, así que un lote lleno podía
        # agotar el presupuesto de tokens solo pensando -- verificar cada
        # una por separado es más lento en número de llamadas pero mucho
        # más fiable.
        construir_prompt = _construir_prompt_fabrica(None)
        llamadas = {"total": 0}

        def fake_call(messages, **kwargs):
            llamadas["total"] += 1
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            if _es_llamada_deduplicacion_final(messages):
                return json.dumps({"grupos_duplicados": []})
            return json.dumps([
                {"pregunta": f"¿Pregunta {i}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."}
                for i in range(5)
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, 5, "Texto de prueba.", tamano_lote=5)

        assert len(preguntas) == 5
        assert errores == []
        assert llamadas["total"] == 7

    def test_verificacion_individual_usa_el_fragmento_del_lote_no_el_documento_completo(self):
        # Optimización de tiempo (03/08/2026, bug real, documento real):
        # cada llamada de verificación pasaba SIEMPRE texto_fuente (el
        # documento COMPLETO, hasta 300000+ caracteres en documentos
        # grandes) aunque la candidata se hubiera generado ÚNICAMENTE a
        # partir de 'fragmento' -- el propio prompt de generación se lo
        # exige explícitamente (ver blueprints/pdf_ia.py: "Basa tus
        # preguntas ÚNICAMENTE en lo que aparece en este fragmento").
        # Verificar contra el documento entero cuando basta con el
        # fragmento multiplicaba sin necesidad el contexto que el
        # verificador (con thinking_enabled=True) tiene que leer y
        # razonar -- causa más probable de varias llamadas de más de 60s
        # (una de más de 130s) y un finish_reason truncado vistos en
        # producción con un documento de más de 300000 caracteres. Aquí,
        # con un documento real de 10 artículos repartido en 4 lotes
        # (mismo texto que test_un_articulo_largo_no_se_reparte_entre_dos_lotes),
        # cada llamada de verificación debe recibir solo el FRAGMENTO de
        # su lote (más corto que el documento completo), no el documento
        # entero.
        relleno = "Frase de relleno para simular contenido real de un artículo constitucional. " * 8
        texto = "\n\n".join(f"Artículo {n}.\n1. {relleno}" for n in range(160, 170))
        assert len(texto) >= 4 * 400

        def construir_prompt(n, fragmento=None):
            documento = fragmento if fragmento is not None else texto
            return f"Genera {n} preguntas.\n\nDocumento para crear preguntas test:\n{documento}"

        mensajes_de_verificacion = []
        contador = itertools.count()

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                mensajes_de_verificacion.append(messages[1]["content"])
                return json.dumps({"valido": True, "problemas": []})
            # Cada lote debe generar una candidata DISTINTA (si todas fueran
            # idénticas, el dedup rechazaría las de los lotes 2-4 y forzaría
            # un recambio -- que sí verifica contra texto_fuente completo a
            # propósito, contaminando esta comprobación).
            return json.dumps([
                {"pregunta": f"¿Pregunta {next(contador)}?",
                 "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."}
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            generar_preguntas_ia_en_lotes(construir_prompt, 4, texto, tamano_lote=1)

        assert mensajes_de_verificacion
        for mensaje in mensajes_de_verificacion:
            documento_verificado = mensaje.split("DOCUMENTO:\n", 1)[1].split("\n\nPREGUNTA A VERIFICAR:", 1)[0]
            assert len(documento_verificado) < len(texto), (
                "la verificación recibió el documento completo, no el fragmento"
            )

    def test_la_pasada_final_quita_un_duplicado_semantico_y_rellena_el_hueco(self):
        # Integración de extremo a extremo (03/08/2026): si la pasada final
        # de deduplicación semántica marca dos de las preguntas ya
        # aceptadas como el mismo dato (algo que las heurísticas
        # deterministas, aquí simuladas como si no lo hubieran cazado, se
        # supone que dejaron pasar), el resultado final debe tener 2
        # preguntas -- nunca 3 (una de las "duplicadas" descartada) ni 1
        # (sin rellenar el hueco que deja).
        construir_prompt = _construir_prompt_fabrica(None)
        contador_generacion = itertools.count()

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            if _es_llamada_deduplicacion_final(messages):
                # Las preguntas 0 y 1 se marcan como el mismo dato -- se
                # debe conservar la 0 y rellenar el hueco que deja la 1.
                return json.dumps({"grupos_duplicados": [[0, 1]]})
            return json.dumps([{
                "pregunta": f"¿Pregunta {next(contador_generacion)}?",
                "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
            }])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, 2, "Texto de prueba.", tamano_lote=1)

        assert len(preguntas) == 2
        assert errores == []

    def test_la_pasada_final_no_se_ejecuta_sin_texto_fuente(self):
        # Sin documento de origen no hay nada real que verificar -- la
        # pasada final tampoco debería dispararse (igual que la
        # verificación individual normal, ver el "if texto_fuente is None"
        # en _pedir_lote_verificado).
        construir_prompt = _construir_prompt_fabrica(None)
        contador_generacion = itertools.count()
        llamadas_deduplicacion = []

        def fake_call(messages, **kwargs):
            if _es_llamada_deduplicacion_final(messages):
                llamadas_deduplicacion.append(1)
                return json.dumps({"grupos_duplicados": []})
            return json.dumps([{
                "pregunta": f"¿Pregunta {next(contador_generacion)}?",
                "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
            }])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, _ = generar_preguntas_ia_en_lotes(construir_prompt, 2, texto_fuente=None, tamano_lote=1)

        assert len(preguntas) == 2
        assert llamadas_deduplicacion == []


class TestDetectarDuplicadosFinales:
    # _detectar_duplicados_finales es la red de seguridad SEMÁNTICA
    # añadida al final del pipeline (03/08/2026, decisión explícita del
    # usuario): una única llamada extra, sin el documento de origen, que
    # compara los enunciados y respuestas de la lista YA ACEPTADA entre sí
    # -- pensada para cazar reformulaciones que las heurísticas
    # deterministas (_claves_dedup, _es_duplicado_por_contencion) todavía
    # no cubran, sin repetir el patrón de "verificación en bloque" que
    # causó el bug de thinking-tokens agotados (aquí no hay
    # thinking_enabled=True ni se compara contra un documento grande, así
    # que no aplica el mismo riesgo).
    def _preguntas(self, n):
        return [
            {"pregunta": f"¿Pregunta {i}?", "opciones": {"A": f"Respuesta {i}"}, "respuesta_correcta": "A"}
            for i in range(n)
        ]

    def test_menos_de_dos_preguntas_no_hace_ninguna_llamada(self):
        with patch("test_generator.call_deepseek_api") as mock:
            resultado = _detectar_duplicados_finales(self._preguntas(1))
        mock.assert_not_called()
        assert resultado == set()

    def test_parsea_un_grupo_de_duplicados_y_conserva_el_primero(self):
        with patch("test_generator.call_deepseek_api",
                   return_value=json.dumps({"grupos_duplicados": [[0, 3]]})):
            resultado = _detectar_duplicados_finales(self._preguntas(5))
        assert resultado == {3}

    def test_parsea_varios_grupos_a_la_vez(self):
        with patch("test_generator.call_deepseek_api",
                   return_value=json.dumps({"grupos_duplicados": [[0, 2], [4, 6, 7]]})):
            resultado = _detectar_duplicados_finales(self._preguntas(8))
        assert resultado == {2, 6, 7}

    def test_sin_respuesta_no_elimina_nada(self):
        with patch("test_generator.call_deepseek_api", return_value=None):
            resultado = _detectar_duplicados_finales(self._preguntas(3))
        assert resultado == set()

    def test_json_invalido_no_elimina_nada(self):
        with patch("test_generator.call_deepseek_api", return_value="no es json"):
            resultado = _detectar_duplicados_finales(self._preguntas(3))
        assert resultado == set()

    def test_json_no_es_un_diccionario_no_elimina_nada(self):
        # Bug real durante el desarrollo de esta función: varios tests que
        # mockean call_deepseek_api por FORMA de mensaje (no por contenido)
        # devuelven el array de generación por defecto ante cualquier
        # llamada no reconocida como verificación -- un JSON válido, pero
        # una lista, no un diccionario con "grupos_duplicados". Debe
        # fallar abierto (sin eliminar nada) en vez de reventar con
        # AttributeError al llamar .get() sobre una lista.
        with patch("test_generator.call_deepseek_api", return_value=json.dumps([1, 2, 3])):
            resultado = _detectar_duplicados_finales(self._preguntas(3))
        assert resultado == set()

    def test_indices_fuera_de_rango_se_ignoran(self):
        with patch("test_generator.call_deepseek_api",
                   return_value=json.dumps({"grupos_duplicados": [[0, 99]]})):
            resultado = _detectar_duplicados_finales(self._preguntas(3))
        assert resultado == set()

    def test_grupo_de_un_solo_indice_no_cuenta_como_duplicado(self):
        with patch("test_generator.call_deepseek_api",
                   return_value=json.dumps({"grupos_duplicados": [[1]]})):
            resultado = _detectar_duplicados_finales(self._preguntas(3))
        assert resultado == set()


class TestFragmentosPorLote:
    def test_reparto_intercalado_cada_fragmento_abarca_todo_el_documento(self):
        # Bug real de producción (02/08/2026): con el reparto CONTIGUO
        # anterior, el primer lote se llevaba literalmente el primer tramo
        # del documento -- si esa zona trataba un único tema (un caso real:
        # varios artículos seguidos, todos sobre la invalidez de los actos
        # administrativos), las primeras preguntas que veía el usuario con
        # el arranque temprano salían TODAS de ese mismo tema. Aquí, con 8
        # párrafos (uno por "TEMA") y 4 lotes, cada fragmento debe contener
        # párrafos de TODO el documento -- del principio, la mitad y el
        # final -- no solo un tramo contiguo.
        # "TEMA N" no tiene marcadores reconocibles por _bloques_estructurales
        # (ni por artículo ni por título) y aquí se mockea la IA del nivel 2
        # (_bloques_por_esquema_ia) para que falle -- este test es
        # específicamente del reparto por párrafo, el fallback final.
        relleno = "Frase de relleno para simular contenido real del documento. " * 5
        parrafos_originales = [f"TEMA {i}. {relleno}" for i in range(8)]
        texto = "\n\n".join(parrafos_originales)
        assert len(texto) >= 4 * 400  # por encima del umbral de fragmentación

        with patch("test_generator.call_deepseek_api", return_value=None):
            fragmentos = _fragmentos_por_lote(texto, 4)

        assert len(fragmentos) == 4
        # Ningún fragmento debe limitarse a un tramo contiguo (p.ej. "TEMA 0"
        # y "TEMA 1" solamente) -- cada uno se lleva every-4º párrafo, así
        # que el primer fragmento contiene el primer Y el último tema.
        assert "TEMA 0" in fragmentos[0] and "TEMA 4" in fragmentos[0]
        assert "TEMA 1" in fragmentos[1] and "TEMA 5" in fragmentos[1]
        # Entre los 4 fragmentos se reparten los 8 párrafos sin perder ni
        # duplicar ninguno.
        parrafos_repartidos = [p for f in fragmentos for p in f.split("\n\n")]
        assert sorted(parrafos_repartidos) == sorted(parrafos_originales)

    def test_documento_con_pocos_parrafos_cae_al_reparto_contiguo(self):
        # Con menos del doble de párrafos que lotes, el reparto intercalado
        # dejaría lotes vacíos o casi vacíos -- se cae al reparto contiguo
        # de siempre en vez de eso. Se mockea la IA del nivel 2 para que
        # falle (mismo motivo que el test anterior).
        texto = "Una sola línea muy larga sin dobles saltos de párrafo. " * 20
        assert len(texto) >= 2 * 400

        with patch("test_generator.call_deepseek_api", return_value=None):
            fragmentos = _fragmentos_por_lote(texto, 2)

        assert len(fragmentos) == 2
        assert all(f is not None for f in fragmentos)
        assert all(f in texto for f in fragmentos)  # reparto contiguo: subcadena literal

    def test_documento_corto_o_un_solo_lote_no_fragmenta(self):
        assert _fragmentos_por_lote("Texto corto.", 3) == [None, None, None]
        assert _fragmentos_por_lote("Texto." * 200, 1) == [None]
        assert _fragmentos_por_lote(None, 3) == [None, None, None]


class TestBloquesEstructurales:
    def test_agrupa_un_articulo_con_apartados_numerados_como_un_solo_bloque(self):
        # Los apartados numerados ("1.", "2.") dentro de un artículo NO
        # deben tratarse como marcadores de bloque nuevo -- deben quedar
        # dentro del bloque de su artículo padre.
        texto = (
            "Artículo 167.\n"
            "1. Los proyectos de reforma constitucional deberán ser aprobados por una "
            "mayoría de tres quintos de cada una de las Cámaras.\n"
            "2. De no lograrse el acuerdo, y siempre que el texto hubiere obtenido el "
            "voto favorable de la mayoría absoluta del Senado, el Congreso podrá aprobar "
            "la reforma por mayoría de dos tercios.\n"
            "Artículo 168.\n"
            "1. Cuando se propusiere la revisión total de la Constitución se procederá a "
            "la aprobación del principio por mayoría de dos tercios de cada Cámara."
        )
        bloques, prosa_inicial = _bloques_estructurales(texto)
        assert prosa_inicial == ""
        assert [b["etiqueta"] for b in bloques] == ["Artículo 167", "Artículo 168"]
        assert [b["tipo"] for b in bloques] == ["primario", "primario"]
        assert "mayoría absoluta" in bloques[0]["texto"]
        assert "Artículo 168" not in bloques[0]["texto"]

    def test_no_confunde_una_referencia_cruzada_con_un_encabezado_nuevo(self):
        # Una mención a OTRO artículo a mitad de frase ("...a diferencia
        # del artículo 168...") no debe cortar el bloque del artículo que
        # la contiene -- solo un marcador al PRINCIPIO de su propia línea
        # cuenta como encabezado real.
        texto = (
            "Artículo 167.\n"
            "1. La mayoría de dos tercios, a diferencia de la exigida por el artículo 168 "
            "para el procedimiento agravado, solo se aplica en la vía alternativa de este "
            "artículo."
        )
        bloques, _ = _bloques_estructurales(texto)
        assert len(bloques) == 1
        assert bloques[0]["etiqueta"] == "Artículo 167"
        assert "artículo 168" in bloques[0]["texto"]

    def test_disposicion_transitoria_es_su_propio_bloque(self):
        texto = (
            "Artículo 169.\n"
            "No podrá iniciarse la reforma constitucional en tiempo de guerra.\n"
            "Disposición transitoria segunda.\n"
            "Las referencias que las leyes hagan a las Cortes se entenderán hechas al "
            "Congreso o al Senado, en su caso."
        )
        bloques, _ = _bloques_estructurales(texto)
        assert [b["etiqueta"] for b in bloques] == ["Artículo 169", "Disposición transitoria segunda"]
        assert bloques[1]["tipo"] == "primario"

    def test_titulo_seguido_de_articulo_no_deja_un_bloque_vacio(self):
        texto = (
            "TÍTULO PRELIMINAR\n"
            "Introducción general sin ningún artículo numerado en este bloque.\n"
            "TÍTULO I\n"
            "Artículo 10.\n"
            "1. La dignidad de la persona es fundamento del orden político."
        )
        bloques, _ = _bloques_estructurales(texto)
        etiquetas = [b["etiqueta"] for b in bloques]
        assert "TÍTULO PRELIMINAR completo (sin artículos numerados)" in etiquetas
        # TÍTULO I va seguido inmediatamente de un artículo -- el hueco
        # entre su propio marcador y el de "Artículo 10" está vacío y se
        # descarta, no aparece como bloque de texto por separado.
        assert "TÍTULO I completo (sin artículos numerados)" not in etiquetas
        assert "Artículo 10" in etiquetas

    def test_prosa_antes_del_primer_marcador_se_devuelve_aparte(self):
        texto = (
            "Portada del documento y resumen introductorio antes de cualquier título.\n\n"
            "Artículo 1.\n"
            "España se constituye en un Estado social y democrático de Derecho."
        )
        bloques, prosa_inicial = _bloques_estructurales(texto)
        assert "Portada del documento" in prosa_inicial
        assert len(bloques) == 1

    def test_sin_marcadores_devuelve_todo_como_prosa(self):
        texto = "Un documento puramente narrativo, sin ningún artículo ni título numerado."
        bloques, prosa_inicial = _bloques_estructurales(texto)
        assert bloques == []
        assert prosa_inicial == texto


class TestRepartirBloquesEnLotes:
    def test_equilibra_por_caracteres_no_por_numero_de_bloques(self):
        # Un reparto por CANTIDAD de bloques (2 y 2) dejaría un lote con
        # 1100 caracteres y otro con 200 -- muy desequilibrado. El bin
        # packing por caracteres debe agrupar los 3 bloques cortos juntos
        # frente al único largo.
        bloques = [
            {"etiqueta": "Artículo largo", "tipo": "primario", "inicio": 0, "texto": "X" * 1000},
            {"etiqueta": "Artículo corto 1", "tipo": "primario", "inicio": 1000, "texto": "X" * 100},
            {"etiqueta": "Artículo corto 2", "tipo": "primario", "inicio": 1100, "texto": "X" * 100},
            {"etiqueta": "Artículo corto 3", "tipo": "primario", "inicio": 1200, "texto": "X" * 100},
        ]
        lotes = _repartir_bloques_en_lotes(bloques, 2)
        tamanos = sorted(sum(len(b["texto"]) for b in lote) for lote in lotes)
        assert tamanos == [300, 1000]

    def test_nunca_deja_un_lote_vacio_si_hay_al_menos_un_bloque_por_lote(self):
        bloques = [
            {"etiqueta": f"Artículo {i}", "tipo": "primario", "inicio": i, "texto": "X" * 50}
            for i in range(4)
        ]
        lotes = _repartir_bloques_en_lotes(bloques, 4)
        assert all(len(lote) >= 1 for lote in lotes)

    def test_conserva_el_orden_original_del_documento_dentro_de_cada_lote(self):
        bloques = [
            {"etiqueta": "Artículo 5", "tipo": "primario", "inicio": 100, "texto": "X" * 10},
            {"etiqueta": "Artículo 2", "tipo": "primario", "inicio": 10, "texto": "X" * 10},
        ]
        lotes = _repartir_bloques_en_lotes(bloques, 1)
        assert [b["etiqueta"] for b in lotes[0]] == ["Artículo 2", "Artículo 5"]


class TestBloquesPorEsquemaIa:
    def test_localiza_bloques_a_partir_del_esquema_devuelto_por_la_ia(self):
        # Nivel 2 de detección de estructura (03/08/2026, bug real): un
        # documento subido por un usuario real -- un temario narrativo tipo
        # apunte de academia, no la ley en bruto -- no tiene ningún
        # "Artículo N" como encabezado propio (los artículos se citan
        # DENTRO de la prosa: "el art. 9 CE señala que..."), así que
        # _bloques_estructurales (regex) no encuentra nada útil. Aquí se
        # comprueba que, dada una respuesta de la IA con el esquema del
        # documento, las secciones se localizan correctamente por su texto
        # literal de inicio.
        texto = (
            "1. INTRODUCCIÓN\n"
            "La Constitución de 1978 fue fruto de un largo proceso.\n"
            "2. ESTRUCTURA\n"
            "La CE consta de 169 artículos repartidos en un Título Preliminar y diez Títulos.\n"
            "3. CARACTERÍSTICAS\n"
            "Como características de la CE cabe destacar que es una Constitución de consenso."
        )
        respuesta_ia = json.dumps([
            {"titulo": "Introducción", "inicio_literal": "1. INTRODUCCIÓN"},
            {"titulo": "Estructura", "inicio_literal": "2. ESTRUCTURA"},
            {"titulo": "Características", "inicio_literal": "3. CARACTERÍSTICAS"},
        ])
        with patch("test_generator.call_deepseek_api", return_value=respuesta_ia):
            bloques = _bloques_por_esquema_ia(texto, 3)

        assert [b["etiqueta"] for b in bloques] == ["Introducción", "Estructura", "Características"]
        assert "largo proceso" in bloques[0]["texto"]
        assert "2. ESTRUCTURA" not in bloques[0]["texto"]
        assert "169 artículos" in bloques[1]["texto"]
        assert "Constitución de consenso" in bloques[2]["texto"]

    def test_devuelve_vacio_si_deepseek_no_responde(self):
        with patch("test_generator.call_deepseek_api", return_value=None):
            assert _bloques_por_esquema_ia("Documento de prueba. " * 50, 3) == []

    def test_devuelve_vacio_si_el_json_no_es_valido(self):
        with patch("test_generator.call_deepseek_api", return_value="esto no es JSON en absoluto"):
            assert _bloques_por_esquema_ia("Documento de prueba. " * 50, 3) == []

    def test_devuelve_vacio_si_menos_de_la_mitad_de_los_fragmentos_se_localizan(self):
        # Si la IA "inventa" o reescribe la mayoría de los inicios
        # literales (pese a la instrucción de copiarlos tal cual) en vez
        # de devolver texto real del documento, no es de fiar -- mejor
        # caer al reparto por párrafo que repartir con cortes a medias.
        texto = "1. INTRODUCCIÓN\nTexto real del documento.\n2. ESTRUCTURA\nMás texto real."
        respuesta_ia = json.dumps([
            {"titulo": "Introducción", "inicio_literal": "1. INTRODUCCIÓN"},
            {"titulo": "Inventado 1", "inicio_literal": "Esto no aparece en el documento"},
            {"titulo": "Inventado 2", "inicio_literal": "Esto tampoco aparece"},
        ])
        with patch("test_generator.call_deepseek_api", return_value=respuesta_ia):
            assert _bloques_por_esquema_ia(texto, 3) == []

    def test_fragmentos_por_lote_usa_la_ia_para_un_documento_narrativo_sin_marcadores_regex(self):
        # Caso real completo: un documento SIN "Artículo N" como encabezado
        # (los artículos se citan dentro de la prosa) no activa el nivel 1
        # (regex), así que _fragmentos_por_lote debe recurrir al nivel 2
        # (IA) y repartir por el esquema que devuelva.
        relleno_seccion = "Frase de relleno para simular contenido real de un apunte de academia. " * 6
        texto = "\n\n".join(
            f"{i}. SECCIÓN NÚMERO {i}\nEl art. {i} CE señala varias cuestiones. {relleno_seccion}"
            for i in range(1, 5)
        )
        assert len(texto) >= 4 * 400

        # Regex (nivel 1) no encuentra nada -- "el art. N CE" es una
        # referencia dentro de la prosa, no un encabezado ("Artículo N").
        assert _bloques_estructurales(texto)[0] == []

        respuesta_ia = json.dumps([
            {"titulo": f"Sección {i}", "inicio_literal": f"{i}. SECCIÓN NÚMERO {i}"}
            for i in range(1, 5)
        ])
        with patch("test_generator.call_deepseek_api", return_value=respuesta_ia):
            fragmentos = _fragmentos_por_lote(texto, 4)

        assert len(fragmentos) == 4
        assert all(f is not None for f in fragmentos)
        for i in range(1, 5):
            marcador = f"SECCIÓN NÚMERO {i}"
            assert sum(1 for f in fragmentos if marcador in f) == 1


class TestFragmentosPorLoteConBloquesEstructurales:
    @staticmethod
    def _articulo(n, relleno):
        return f"Artículo {n}.\n1. {relleno}"

    def test_un_articulo_largo_no_se_reparte_entre_dos_lotes(self):
        # Bug real de producción (03/08/2026): con el reparto anterior
        # (intercalado por párrafo), un artículo con varios párrafos largos
        # se repartía ENTRE VARIOS LOTES -- cada uno veía solo un trozo,
        # pero lo bastante para generar, sin saber unos de otros, una
        # pregunta sobre el mismo dato citable del mismo artículo.
        # Confirmado con datos reales: 3 preguntas sobre "qué mayoría exige
        # el Senado" del art. 167 en un mismo test de 20, repartidas entre
        # lotes distintos. Aquí, cada "Artículo N." debe caer entero en
        # UN ÚNICO fragmento, nunca partido entre dos ni duplicado.
        relleno = "Frase de relleno para simular contenido real de un artículo constitucional. " * 8
        texto = "\n\n".join(self._articulo(n, relleno) for n in range(160, 170))
        assert len(texto) >= 4 * 400

        fragmentos = _fragmentos_por_lote(texto, 4)

        assert len(fragmentos) == 4
        assert all(f is not None for f in fragmentos)
        for n in range(160, 170):
            marcador = f"Artículo {n}."
            en_cuantos_fragmentos = sum(1 for f in fragmentos if marcador in f)
            assert en_cuantos_fragmentos == 1, f"{marcador} apareció en {en_cuantos_fragmentos} fragmentos"

    def test_la_prosa_inicial_se_reparte_por_parrafo_entre_los_lotes(self):
        relleno = "Frase de relleno para simular contenido real de un artículo constitucional. " * 8
        prosa = "\n\n".join(f"Párrafo introductorio {i} de la portada." for i in range(4))
        articulos = "\n\n".join(self._articulo(n, relleno) for n in range(1, 9))
        texto = f"{prosa}\n\n{articulos}"

        fragmentos = _fragmentos_por_lote(texto, 4)

        assert len(fragmentos) == 4
        for i in range(4):
            marcador = f"Párrafo introductorio {i} de la portada."
            assert sum(1 for f in fragmentos if marcador in f) == 1

    def test_documento_con_menos_bloques_que_lotes_intenta_la_ia_y_luego_cae_al_parrafo(self):
        # Con menos bloques estructurales (nivel 1, regex) que lotes no hay
        # suficientes para repartir sin dejar alguno vacío -- se intenta el
        # nivel 2 (IA), y si tampoco da suficientes bloques (aquí, mockeada
        # para fallar) se cae al reparto por párrafo/contiguo de siempre
        # para todo el documento, sin fallar.
        relleno = "Frase de relleno para simular contenido real de un artículo constitucional. " * 16
        texto = "\n\n".join(self._articulo(n, relleno) for n in range(1, 3))  # solo 2 artículos
        assert len(texto) >= 4 * 400  # por encima del umbral de fragmentación

        with patch("test_generator.call_deepseek_api", return_value=None):
            fragmentos = _fragmentos_por_lote(texto, 4)  # pero 4 lotes

        assert len(fragmentos) == 4


class TestGenerarBancoPreguntasAdaptativo:
    # generar_banco_preguntas_adaptativo (03/08/2026, decisión explícita del
    # usuario): genera en rondas sucesivas hasta agotar el contenido
    # distinto del documento, con un tope de seguridad -- no un número fijo
    # a forzar. Ver el comentario largo en test_generator.py.
    def test_para_al_llegar_al_tope_si_el_documento_da_de_sobra(self):
        contador = itertools.count(1)
        construir_prompt = _construir_prompt_fabrica(None)

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            if _es_llamada_deduplicacion_final(messages):
                return json.dumps({"grupos_duplicados": []})
            # Contenido "infinito": cada llamada de generación devuelve
            # preguntas nuevas y distintas, nunca se agota.
            return json.dumps([
                {"pregunta": f"¿Pregunta {next(contador)}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."}
                for _ in range(8)
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            resultado = generar_banco_preguntas_adaptativo(
                construir_prompt, "Texto de prueba.", tope=20, tamano_ronda=8,
            )

        assert len(resultado) == 20

    def test_para_por_bajo_rendimiento_aunque_no_haya_llegado_al_tope(self):
        # Ronda 1: el documento da 8 preguntas nuevas de sobra. Ronda 2: el
        # prompt ya lleva el aviso de exclusión (ver _prompt_con_exclusion)
        # -- se simula que el documento ya no da más devolviendo SIEMPRE la
        # misma pregunta de la ronda 1, que el dedup entre rondas de esta
        # función descarta por completo. El bajo rendimiento de la ronda 2
        # (0 nuevas) debe parar la generación mucho antes del tope de 100.
        construir_prompt = _construir_prompt_fabrica(None)

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            if _es_llamada_deduplicacion_final(messages):
                return json.dumps({"grupos_duplicados": []})
            if "ya se hicieron en tests ANTERIORES" in messages[0]["content"]:
                return json.dumps([{
                    "pregunta": "¿Pregunta 1?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                    "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
                }])
            return json.dumps([
                {"pregunta": f"¿Pregunta {i}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."}
                for i in range(1, 9)
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            resultado = generar_banco_preguntas_adaptativo(
                construir_prompt, "Texto de prueba.", tope=100, tamano_ronda=8,
            )

        assert len(resultado) == 8

    def test_on_progreso_solo_reporta_preguntas_nuevas_no_las_de_rondas_repetidas(self):
        construir_prompt = _construir_prompt_fabrica(None)

        def fake_call(messages, **kwargs):
            if _es_llamada_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            if _es_llamada_deduplicacion_final(messages):
                return json.dumps({"grupos_duplicados": []})
            return json.dumps([{
                "pregunta": "¿Pregunta 1?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "Explicación de prueba para el test."
            }])

        eventos = []
        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            resultado = generar_banco_preguntas_adaptativo(
                construir_prompt, "Texto de prueba.", tope=20, tamano_ronda=1, on_progreso=eventos.append,
            )

        assert len(resultado) == 1
        assert len(eventos) == 1
        assert eventos[0]["pregunta"]["pregunta"] == "¿Pregunta 1?"
        assert eventos[0]["completadas"] == 1
        assert eventos[0]["objetivo"] == 20
