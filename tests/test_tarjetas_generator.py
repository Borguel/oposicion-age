"""Pruebas de tarjetas_generator.py: reparto de cupos entre fragmentos,
parseo de la respuesta cruda de DeepSeek, y el pipeline completo
generar->verificar->reintentar (con DeepSeek mockeado por CONTENIDO del
prompt, no por orden de llamada -- el pipeline es paralelo)."""
import json
from unittest.mock import patch

from tarjetas_generator import (
    _repartir_cupos, _parsear_tarjetas, _contiene_frase_prohibida, generar_tarjetas_verificadas,
    _verificar_tarjeta,
)


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


class TestContieneFrasesProhibidas:
    def test_pregunta_que_remite_al_texto_se_detecta(self):
        tarjeta = {"pregunta": "¿Qué tipos de costumbre existen según el texto?", "respuesta": "R"}
        assert _contiene_frase_prohibida(tarjeta) is True

    def test_respuesta_que_remite_al_documento_tambien_se_detecta(self):
        tarjeta = {"pregunta": "¿Qué es la costumbre?", "respuesta": "Según el documento, es una fuente del derecho."}
        assert _contiene_frase_prohibida(tarjeta) is True

    def test_mayusculas_no_evitan_la_deteccion(self):
        tarjeta = {"pregunta": "¿Qué dice SEGÚN EL TEXTO sobre la costumbre?", "respuesta": "R"}
        assert _contiene_frase_prohibida(tarjeta) is True

    def test_tarjeta_autonoma_pasa(self):
        tarjeta = {"pregunta": "¿Qué es la costumbre jurídica?", "respuesta": "Una fuente del derecho no escrita."}
        assert _contiene_frase_prohibida(tarjeta) is False


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

    def test_tarjeta_con_frase_prohibida_se_descarta_sin_gastar_verificacion(self):
        # La primera candidata remite al texto de origen ("según el texto")
        # -- debe descartarse y regenerarse SIN llegar a pedir verificación
        # por IA (el filtro es local, más barato que una llamada a
        # DeepSeek). Si el prompt de verificación llegara a recibir la
        # candidata "A", el AssertionError de abajo lo delataría.
        def fake_call(messages, **kwargs):
            if _es_prompt_generacion(messages):
                if "No repitas esta pregunta" in messages[0]["content"]:
                    return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta B?", "respuesta": "Respuesta B"}]})
                return json.dumps({"tarjetas": [
                    {"pregunta": "¿Qué dice el texto sobre X?", "respuesta": "Según el texto, X es Y."}
                ]})
            if _es_prompt_verificacion(messages):
                candidata = json.loads(messages[1]["content"].split("TARJETA A VERIFICAR:\n")[1])
                assert candidata["pregunta"] == "¿Pregunta B?", "la tarjeta con frase prohibida no debería verificarse"
                return json.dumps({"valido": True, "problemas": []})
            raise AssertionError("prompt inesperado")

        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call):
            resultado = generar_tarjetas_verificadas("Texto corto del documento.", 1)

        assert len(resultado["tarjetas"]) == 1
        assert resultado["tarjetas"][0]["pregunta"] == "¿Pregunta B?"

    def test_tope_de_intentos_agotado_descarta_la_tarjeta(self):
        # La verificación SIEMPRE falla -- tras MAX_INTENTOS_POR_TARJETA
        # regeneraciones fallidas, la tarjeta se descarta y no aparece en
        # el resultado (nunca se entrega sin validar). Con un único
        # fragmento disponible, el paso de relleno también lo intenta ahí
        # y también agota sus intentos -- 2 descartes en total (el hueco
        # original + el intento de relleno), no 1.
        def fake_call(messages, **kwargs):
            if _es_prompt_generacion(messages):
                return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta única?", "respuesta": "Respuesta"}]})
            if _es_prompt_verificacion(messages):
                return json.dumps({"valido": False, "problemas": ["dato inventado"]})
            raise AssertionError("prompt inesperado")

        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call):
            resultado = generar_tarjetas_verificadas("Texto corto del documento.", 1)

        assert resultado["tarjetas"] == []
        assert resultado["descartadas"] == 2
        assert "advertencia" in resultado

    def test_relleno_completa_deficit_de_generacion_inicial(self):
        # El fragmento A nunca entrega ninguna candidata (el modelo ignoró
        # el "Genera EXACTAMENTE 1 tarjeta") mientras que el B sí -- sin
        # relleno el resultado sería 1/2. itertools.cycle(fragmentos)
        # arranca siempre por el primero, así que se pone B primero para
        # que el único hueco de relleno recaiga en el fragmento que sí
        # produce candidatas; un contador evita que la tarjeta de relleno
        # sea idéntica (y por tanto descartada como duplicada) a la ya
        # aceptada del mismo fragmento.
        contador_b = {"n": 0}

        def fake_call(messages, **kwargs):
            contenido = messages[0]["content"] + messages[1]["content"]
            if _es_prompt_generacion(messages):
                if "Fragmento A" in contenido:
                    return json.dumps({"tarjetas": []})
                contador_b["n"] += 1
                return json.dumps({"tarjetas": [{"pregunta": f"¿Pregunta B{contador_b['n']}?", "respuesta": "Respuesta"}]})
            if _es_prompt_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            raise AssertionError("prompt inesperado")

        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call), \
             patch("tarjetas_generator._trocear_en_parrafos", return_value=["Fragmento B", "Fragmento A"]):
            resultado = generar_tarjetas_verificadas("Documento con dos fragmentos.", 2)

        assert len(resultado["tarjetas"]) == 2
        assert "advertencia" not in resultado

    def test_relleno_completa_descarte_agotado_usando_otro_fragmento(self):
        # La tarjeta del fragmento A siempre falla verificación (se agota,
        # como hoy); la del B es válida a la primera. Sin relleno: 1/2 con
        # advertencia. Con relleno, como B sigue teniendo contenido
        # disponible, produce una segunda tarjeta válida y distinta (B
        # primero en la lista de fragmentos, igual que en el test anterior,
        # para que itertools.cycle recaiga en él; un contador evita que la
        # tarjeta de relleno sea idéntica a la ya aceptada).
        contador_b = {"n": 0}

        def fake_call(messages, **kwargs):
            contenido = messages[0]["content"] + messages[1]["content"]
            if _es_prompt_generacion(messages):
                if "Fragmento A" in contenido:
                    return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta A?", "respuesta": "Respuesta A"}]})
                contador_b["n"] += 1
                return json.dumps({"tarjetas": [{"pregunta": f"¿Pregunta B{contador_b['n']}?", "respuesta": "Respuesta B"}]})
            if _es_prompt_verificacion(messages):
                candidata = json.loads(messages[1]["content"].split("TARJETA A VERIFICAR:\n")[1])
                valido = candidata["pregunta"] != "¿Pregunta A?"
                return json.dumps({"valido": valido, "problemas": [] if valido else ["dato inventado"]})
            raise AssertionError("prompt inesperado")

        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call), \
             patch("tarjetas_generator._trocear_en_parrafos", return_value=["Fragmento B", "Fragmento A"]):
            resultado = generar_tarjetas_verificadas("Documento con dos fragmentos.", 2)

        assert len(resultado["tarjetas"]) == 2
        preguntas = {t["pregunta"] for t in resultado["tarjetas"]}
        assert "¿Pregunta A?" not in preguntas
        assert "advertencia" not in resultado

    def test_relleno_prueba_otro_fragmento_si_el_primero_agota_intentos_dentro_del_mismo_hueco(self):
        # Bug real reportado en un documento extenso: pedir 10 tarjetas y
        # recibir solo 7. Antes, un hueco de relleno tenía asignado un
        # ÚNICO fragmento fijo -- si ese fragmento concreto no daba una
        # tarjeta válida tras MAX_INTENTOS_POR_TARJETA intentos, el hueco se
        # perdía aunque el documento tuviera de sobra contenido sin usar en
        # OTROS fragmentos. Con num_tarjetas=1 y 2 fragmentos, el reparto de
        # cupos ([1, 0]) hace que solo el fragmento A reciba intento
        # inicial (y siempre falla verificación); el B queda sin usar en la
        # fase normal. El MISMO hueco de relleno debe, tras agotar A,
        # probar con B y conseguir la tarjeta -- antes se habría perdido
        # ahí, con 0/1 y advertencia.
        def fake_call(messages, **kwargs):
            contenido = messages[0]["content"] + messages[1]["content"]
            if _es_prompt_generacion(messages):
                if "Fragmento A" in contenido:
                    return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta A?", "respuesta": "Respuesta A"}]})
                return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta B?", "respuesta": "Respuesta B"}]})
            if _es_prompt_verificacion(messages):
                candidata = json.loads(messages[1]["content"].split("TARJETA A VERIFICAR:\n")[1])
                valido = candidata["pregunta"] == "¿Pregunta B?"
                return json.dumps({"valido": valido, "problemas": [] if valido else ["dato inventado"]})
            raise AssertionError("prompt inesperado")

        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call), \
             patch("tarjetas_generator._trocear_en_parrafos", return_value=["Fragmento A", "Fragmento B"]):
            resultado = generar_tarjetas_verificadas("Documento con dos fragmentos.", 1)

        assert len(resultado["tarjetas"]) == 1
        assert resultado["tarjetas"][0]["pregunta"] == "¿Pregunta B?"
        assert "advertencia" not in resultado

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

    def test_verificacion_pide_4000_tokens_no_400(self):
        # Mismo bug real que en test_generator.py: con max_tokens=400,
        # deepseek-v4-flash podía truncar la respuesta de verificación al
        # detallar varios problemas, y el JSON cortado se trataba como
        # tarjeta inválida aunque no lo fuera. Subido a 4000 (igual que en
        # test_generator.py) tras ver en producción que 2000 seguía
        # cortándose alguna vez para la verificación de test.
        max_tokens_verificacion = []

        def fake_call(messages, max_tokens=None, **kwargs):
            if _es_prompt_generacion(messages):
                return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta?", "respuesta": "Respuesta"}]})
            max_tokens_verificacion.append(max_tokens)
            return json.dumps({"valido": True, "problemas": []})

        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call):
            generar_tarjetas_verificadas("Texto corto.", 1)

        assert max_tokens_verificacion == [4000]

    def test_verificacion_mantiene_el_thinking_encendido(self):
        # call_deepseek_api desactiva el razonamiento de deepseek-v4-flash
        # por defecto (02/08/2026, ver deepseek_utils.py) porque en la
        # GENERACIÓN no aportaba nada -- pero esto es una verificación, la
        # tarea que se juega la precisión frente al fragmento de origen, así
        # que debe pedir thinking_enabled=True explícitamente.
        with patch("tarjetas_generator.call_deepseek_api",
                   return_value=json.dumps({"valido": True, "problemas": []})) as mock:
            _verificar_tarjeta({"pregunta": "¿?", "respuesta": "R"}, "Fragmento de prueba.", on_usage=None)
        assert mock.call_args.kwargs["thinking_enabled"] is True

    def test_relleno_de_varios_huecos_se_ejecuta_en_paralelo(self):
        # Regresión de lentitud: el relleno era un "for" secuencial, así que
        # con varios huecos pendientes (documento difícil que necesita
        # muchas tarjetas de recambio) el tiempo total crecía linealmente
        # con el número de huecos -- el mismo problema real ya detectado y
        # corregido en test_generator.py para Generar Test desde PDF (ver
        # ahí "bug real reportado: 16 preguntas tardando 5-6 minutos").
        # Aquí se comprueba que varios huecos tardan bastante menos que la
        # suma de sus tiempos individuales, es decir, que corren solapados
        # en vez de uno detrás de otro.
        import time
        import threading

        RETRASO = 0.05
        NUM_HUECOS = 5

        def fake_call(messages, **kwargs):
            time.sleep(RETRASO)
            if _es_prompt_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            contenido = messages[0]["content"] + messages[1]["content"]
            if "Genera EXACTAMENTE 1 tarjeta" in contenido:
                # Enunciado único por hilo para no colisionar con el dedup
                # (que descartaría el resto como duplicados de la primera).
                return json.dumps({"tarjetas": [
                    {"pregunta": f"¿Pregunta de relleno {threading.get_ident()}?", "respuesta": "R"}
                ]})
            # Generación inicial: entrega solo 1 de las NUM_HUECOS + 1
            # pedidas, dejando NUM_HUECOS huecos para el relleno.
            return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta inicial?", "respuesta": "R"}]})

        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call), \
             patch("tarjetas_generator._trocear_en_parrafos", return_value=["Fragmento único"]):
            inicio = time.perf_counter()
            resultado = generar_tarjetas_verificadas("Documento.", NUM_HUECOS + 1)
            duracion = time.perf_counter() - inicio

        assert len(resultado["tarjetas"]) == NUM_HUECOS + 1
        # Secuencial habría tardado NUM_HUECOS * 2 llamadas * RETRASO; en
        # paralelo debe quedar muy por debajo (cota floja pero suficiente
        # para distinguir "en paralelo" de "uno detrás de otro").
        assert duracion < RETRASO * NUM_HUECOS
