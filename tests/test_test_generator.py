"""Pruebas de test_generator.py: generar_preguntas_ia_en_lotes con su
pipeline de verificación EN BLOQUE por lote (una sola llamada juzga todas
las candidatas del lote a la vez, ver _verificar_lote) y su mecanismo de
recambio individual para las que no pasan (mismo principio que
generador_preguntas_verificado.py, aquí sobre un documento libre en vez de
un artículo anclado en Firestore). DeepSeek se mockea por CONTENIDO del
mensaje (no por orden de llamada), porque la generación y verificación de
un lote corren en paralelo."""
import itertools
import json
import re
from unittest.mock import patch

from test_generator import (
    generar_preguntas_ia_en_lotes, MAX_INTENTOS_POR_PREGUNTA_PDF, _verificar_pregunta, _verificar_lote,
    _claves_dedup,
)


def _construir_prompt_fabrica(preguntas_por_llamada):
    """Devuelve un construir_prompt(n) de prueba que siempre pide n=1 (los
    tests aquí usan lotes pequeños) y cuyo texto de prompt no contiene
    'system' -- la generación en este módulo va toda en un único mensaje
    'user', a diferencia de la verificación (individual o en bloque) que sí
    usa 'system'."""
    def construir_prompt(n):
        return f"Genera {n} preguntas.\n\nDocumento para crear preguntas test:\nTexto de prueba."
    return construir_prompt


def _es_llamada_verificacion_lote(messages):
    return (
        len(messages) == 2 and messages[0]["role"] == "system"
        and "PREGUNTAS A VERIFICAR:" in messages[1]["content"]
    )


def _es_llamada_verificacion(messages):
    """Verificación INDIVIDUAL de una candidata de recambio -- excluye la
    verificación en bloque de un lote entero (_es_llamada_verificacion_lote),
    que también es un mensaje system+user pero con un enunciado en plural
    ('PREGUNTAS A VERIFICAR', no 'PREGUNTA A VERIFICAR')."""
    return (
        len(messages) == 2 and messages[0]["role"] == "system"
        and "PREGUNTAS A VERIFICAR:" not in messages[1]["content"]
    )


def _preguntas_del_lote_desde_mensaje(messages):
    """Extrae, en el mismo orden en que se listaron, el texto 'pregunta' de
    cada candidata dentro de una llamada de verificación en bloque -- para
    poder responder con el veredicto correcto por índice sin acoplar el
    test al formato exacto del prompt."""
    return re.findall(r'"pregunta":\s*"([^"]*)"', messages[1]["content"])


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
            if _es_llamada_verificacion_lote(messages):
                textos = _preguntas_del_lote_desde_mensaje(messages)
                return json.dumps({"resultados": [
                    {"indice": i, "valido": t != "¿Pregunta mala?", "problemas": [] if t != "¿Pregunta mala?" else ["dato inventado"]}
                    for i, t in enumerate(textos)
                ]})
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
            if _es_llamada_verificacion_lote(messages):
                return json.dumps({"resultados": [{"indice": 0, "valido": False, "problemas": ["dato inventado"]}]})
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
            if _es_llamada_verificacion_lote(messages):
                textos = _preguntas_del_lote_desde_mensaje(messages)
                return json.dumps({"resultados": [
                    {"indice": i, "valido": t != "¿Mala?", "problemas": [] if t != "¿Mala?" else ["dato inventado"]}
                    for i, t in enumerate(textos)
                ]})
            if _es_llamada_verificacion(messages):
                candidata = json.loads(messages[1]["content"].split("PREGUNTA A VERIFICAR:\n")[1])
                valido = candidata["pregunta"] != "¿Mala?"
                return json.dumps({"valido": valido, "problemas": [] if valido else ["dato inventado"]})
            if "No repitas esta pregunta" in messages[0]["content"]:
                return json.dumps([{
                    "pregunta": "¿Mala?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                    "respuesta_correcta": "A", "explicacion": "..."
                }])
            return json.dumps([
                {"pregunta": "¿Buena?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "..."},
                {"pregunta": "¿Mala?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "..."},
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
            if _es_llamada_verificacion_lote(messages):
                return json.dumps({"resultados": [{"indice": 0, "valido": True, "problemas": []}]})
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

        # 1 llamada de generación + 1 de verificación EN BLOQUE (sin
        # candidatas inválidas, no hace falta ningún recambio individual)
        # = 2 avisos de usage.
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
            if _es_llamada_verificacion_lote(messages):
                textos = _preguntas_del_lote_desde_mensaje(messages)
                return json.dumps({"resultados": [
                    {"indice": i, "valido": not t.startswith("¿Mala"), "problemas": [] if not t.startswith("¿Mala") else ["dato inventado"]}
                    for i, t in enumerate(textos)
                ]})
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
        parrafo = "Frase de relleno para simular contenido real del documento. " * 10
        texto_largo = "\n\n".join(f"SECCION {i}. {parrafo}" for i in range(4))
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
                "respuesta_correcta": "A", "explicacion": "..."
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
        # entre sí, ninguno el documento completo, y ambos contenidos
        # dentro del documento original.
        assert len(fragmentos_recibidos) == 2
        assert all(f is not None for f in fragmentos_recibidos)
        assert fragmentos_recibidos[0] != fragmentos_recibidos[1]
        assert all(f != texto_largo for f in fragmentos_recibidos)
        assert all(f in texto_largo for f in fragmentos_recibidos)

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
                 "respuesta_correcta": "C", "explicacion": "..."},
                {"pregunta": "¿Es renovable el cargo del Presidente y por cuánto tiempo se ejerce?",
                 "opciones": {"A": "6 años, no renovable.", "B": "5 años", "C": "4 años", "D": "7 años"},
                 "respuesta_correcta": "A", "explicacion": "..."},
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
                    "respuesta_correcta": "A", "explicacion": "...",
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
                    "respuesta_correcta": "A", "explicacion": "...",
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
                    "respuesta_correcta": "A", "explicacion": "..."
                }])
            # Lote inicial: pide 2 preguntas pero solo devuelve 1 (deja un
            # hueco que el relleno debe rellenar).
            return json.dumps([{
                "pregunta": "¿Cuánto dura el mandato del Presidente?",
                "opciones": {"A": "1", "B": "2", "C": "6 años, no renovable.", "D": "4"},
                "respuesta_correcta": "C", "explicacion": "..."
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
                "respuesta_correcta": "A", "explicacion": "..."
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
                    "respuesta_correcta": "A", "explicacion": "..."
                }])
            # Lote inicial: pide 2 preguntas pero solo devuelve 1 (deja un
            # hueco que el relleno debe rellenar).
            return json.dumps([{
                "pregunta": "¿Pregunta del lote?",
                "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "..."
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
            if _es_llamada_verificacion_lote(messages):
                textos = _preguntas_del_lote_desde_mensaje(messages)
                return json.dumps({"resultados": [
                    {"indice": i, "valido": True, "problemas": []} for i in range(len(textos))
                ]})
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
            if _es_llamada_verificacion_lote(messages):
                textos = _preguntas_del_lote_desde_mensaje(messages)
                return json.dumps({"resultados": [
                    {"indice": i, "valido": True, "problemas": []} for i in range(len(textos))
                ]})
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

    def test_verificacion_en_bloque_escala_los_tokens_con_el_tamano_del_lote(self):
        # La verificación en bloque (_verificar_lote) sustituyó a una
        # llamada de verificación por pregunta -- su presupuesto de tokens
        # debe escalar con cuántas preguntas lleva el lote, no quedarse
        # fijo como si siempre verificara una sola (ver la fórmula en
        # test_generator.py).
        construir_prompt = _construir_prompt_fabrica(None)
        max_tokens_lote = []

        def fake_call(messages, max_tokens=None, **kwargs):
            if _es_llamada_verificacion_lote(messages):
                textos = _preguntas_del_lote_desde_mensaje(messages)
                max_tokens_lote.append(max_tokens)
                return json.dumps({"resultados": [
                    {"indice": i, "valido": True, "problemas": []} for i in range(len(textos))
                ]})
            return json.dumps([
                {"pregunta": f"¿Pregunta {i}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "..."}
                for i in range(4)
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            generar_preguntas_ia_en_lotes(construir_prompt, 4, "Texto de prueba.", tamano_lote=4)

        assert max_tokens_lote == [min(8000, 500 + 700 * 4)]

    def test_verificacion_individual_de_recambio_sigue_pidiendo_4000_tokens(self):
        # Bug real de producción: con max_tokens=400, deepseek-v4-flash
        # truncaba la respuesta de verificación (finish_reason="length")
        # cuando detallaba varios problemas, y el JSON cortado se trataba
        # como pregunta inválida aunque no lo fuera -- multiplicando las
        # llamadas totales y dejando el test por debajo de lo pedido. Ese
        # margen (ya corregido a 4000, ver _verificar_pregunta) se sigue
        # usando cuando la verificación en bloque marca una candidata como
        # inválida y hay que verificar su recambio de una en una
        # (_asegurar_pregunta_valida no cambió con la verificación en
        # bloque).
        construir_prompt = _construir_prompt_fabrica(None)
        max_tokens_individual = []

        def fake_call(messages, max_tokens=None, **kwargs):
            if _es_llamada_verificacion_lote(messages):
                return json.dumps({"resultados": [{"indice": 0, "valido": False, "problemas": ["dato inventado"]}]})
            if _es_llamada_verificacion(messages):
                max_tokens_individual.append(max_tokens)
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps([{
                "pregunta": "¿Pregunta?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "respuesta_correcta": "A", "explicacion": "..."
            }])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            generar_preguntas_ia_en_lotes(construir_prompt, 1, "Texto de prueba.", tamano_lote=1)

        assert max_tokens_individual == [4000]

    def test_verificacion_individual_mantiene_el_thinking_encendido(self):
        # call_deepseek_api desactiva el razonamiento de deepseek-v4-flash
        # por defecto (02/08/2026, ver deepseek_utils.py) porque en la
        # GENERACIÓN no aportaba nada -- pero esto es una verificación, la
        # tarea que se juega la precisión frente al documento de origen, así
        # que debe pedir thinking_enabled=True explícitamente.
        with patch("test_generator.call_deepseek_api", return_value=json.dumps({"valido": True, "problemas": []})) as mock:
            _verificar_pregunta({"pregunta": "¿?"}, "Documento de prueba.", on_usage=None)
        assert mock.call_args.kwargs["thinking_enabled"] is True

    def test_verificacion_en_bloque_mantiene_el_thinking_encendido(self):
        respuesta = json.dumps({"resultados": [{"indice": 0, "valido": True, "problemas": []}]})
        with patch("test_generator.call_deepseek_api", return_value=respuesta) as mock:
            _verificar_lote([{"pregunta": "¿?"}], "Documento de prueba.", on_usage=None)
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
                 "respuesta_correcta": "A", "explicacion": "..."}
                for _ in range(3)
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, 4, "Texto de prueba.", tamano_lote=2)

        assert len(preguntas) == 4
        assert errores == []

    def test_verificacion_en_bloque_reduce_las_llamadas_totales(self):
        # El objetivo real de la verificación en bloque: bug reportado en
        # producción, generar un test de 30 preguntas podía disparar más
        # de 50 llamadas a DeepSeek en total (1 generación + 1 verificación
        # POR PREGUNTA). Con un lote de 5 preguntas todas válidas a la
        # primera, el total debe ser 2 llamadas (1 generación + 1
        # verificación en bloque), no 6 (1 + 5).
        construir_prompt = _construir_prompt_fabrica(None)
        llamadas = {"total": 0}

        def fake_call(messages, **kwargs):
            llamadas["total"] += 1
            if _es_llamada_verificacion_lote(messages):
                textos = _preguntas_del_lote_desde_mensaje(messages)
                return json.dumps({"resultados": [
                    {"indice": i, "valido": True, "problemas": []} for i in range(len(textos))
                ]})
            return json.dumps([
                {"pregunta": f"¿Pregunta {i}?", "opciones": {"A": "1", "B": "2", "C": "3", "D": "4"},
                 "respuesta_correcta": "A", "explicacion": "..."}
                for i in range(5)
            ])

        with patch("test_generator.call_deepseek_api", side_effect=fake_call):
            preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, 5, "Texto de prueba.", tamano_lote=5)

        assert len(preguntas) == 5
        assert errores == []
        assert llamadas["total"] == 2
