"""Pruebas de tarjetas_generator.py: reparto de cupos entre fragmentos,
parseo de la respuesta cruda de DeepSeek, y el pipeline completo
generar->verificar->reintentar (con DeepSeek mockeado por CONTENIDO del
prompt, no por orden de llamada -- el pipeline es paralelo)."""
import itertools
import json
import threading
from unittest.mock import patch

from tarjetas_generator import (
    _repartir_cupos, _parsear_tarjetas, _contiene_frase_prohibida, generar_tarjetas_verificadas,
    _verificar_tarjeta, generar_banco_tarjetas_adaptativo, _es_semanticamente_duplicada,
    _generar_candidatas_fragmento, _claves_dedup, _articulos_citados,
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


class TestEsSemanticamenteDuplicada:
    # _es_semanticamente_duplicada (05/08/2026, bug real reportado por el
    # usuario: un banco de 100 tarjetas con ~40-50 reformulaciones del
    # mismo puñado de hechos, invisibles al dedup por texto exacto porque
    # cada una tenía el enunciado redactado de forma distinta).
    def test_misma_respuesta_reformulada_se_detecta_por_solapamiento(self):
        # Mismo hecho, mismas palabras, reordenadas -- el caso real
        # reportado por el usuario (10 tarjetas preguntando por los
        # mecanismos de ayuda financiera de la UE, cada una con la
        # respuesta redactada en otro orden).
        existentes = [{
            "pregunta": "¿Qué mecanismos de ayuda financiera creó la UE?",
            "respuesta": "La UE creó el MEEF, el FEEF y el MEDE como mecanismos de ayuda financiera para los Estados miembros.",
        }]
        nueva = {
            "pregunta": "¿Qué instrumentos de asistencia financiera puso en marcha la Unión Europea?",
            "respuesta": "La UE creó como mecanismos de ayuda financiera para los Estados miembros el MEEF, el FEEF y el MEDE.",
        }
        assert _es_semanticamente_duplicada(nueva, existentes) is True

    def test_respuesta_contenida_en_otra_mas_amplia_se_detecta(self):
        existentes = [{
            "pregunta": "¿Qué establece el artículo 8 sobre las Fuerzas Armadas?",
            "respuesta": "Tienen como misión garantizar la soberanía e independencia de España y defender su integridad territorial.",
        }]
        nueva = {
            "pregunta": "¿Cuál es la misión de las Fuerzas Armadas según el artículo 8?",
            "respuesta": "Garantizar la soberanía e independencia de España y defender su integridad territorial.",
        }
        assert _es_semanticamente_duplicada(nueva, existentes) is True

    def test_hechos_distintos_del_mismo_tema_no_se_marcan_como_duplicados(self):
        existentes = [{
            "pregunta": "¿Qué mayoría exige el Congreso para aprobar la ley?",
            "respuesta": "Mayoría absoluta en primera votación.",
        }]
        nueva = {
            "pregunta": "¿Cuándo entra en vigor la ley?",
            "respuesta": "A los veinte días de su publicación completa en el Boletín Oficial del Estado.",
        }
        assert _es_semanticamente_duplicada(nueva, existentes) is False

    def test_respuestas_demasiado_cortas_no_se_comparan(self):
        # Por debajo de _LONGITUD_MINIMA_CONTENCION_TARJETA una coincidencia
        # de texto es demasiado corta para ser una señal fiable (daría
        # falsos positivos con respuestas tipo "Sí." o "El Consejo.").
        existentes = [{"pregunta": "¿Es obligatorio?", "respuesta": "Sí."}]
        nueva = {"pregunta": "¿Hace falta hacerlo?", "respuesta": "Sí."}
        assert _es_semanticamente_duplicada(nueva, existentes) is False

    def test_lista_vacia_nunca_es_duplicada(self):
        nueva = {"pregunta": "¿Qué es el TFUE?", "respuesta": "El Tratado de Funcionamiento de la Unión Europea."}
        assert _es_semanticamente_duplicada(nueva, []) is False


class TestClavesDedup:
    # 12/08/2026, porte de test_generator.py._claves_dedup: detecta como
    # duplicadas dos tarjetas que citan el MISMO artículo y el MISMO dato
    # concreto (cifra o principio jurídico), aunque estén redactadas de
    # formas completamente distintas -- un caso que _es_semanticamente_
    # duplicada (contención/solapamiento de la respuesta) no siempre caza.

    def test_dedupe_por_articulo_y_cifra_pese_a_redaccion_muy_distinta(self):
        a = {
            "pregunta": "¿Cuál es el plazo de alegaciones?",
            "respuesta": "El artículo 14 establece un plazo de 15 días hábiles.",
        }
        b = {
            "pregunta": "Según el artículo 14, ¿en cuántos días hábiles se pueden presentar alegaciones?",
            "respuesta": "En 15 días hábiles.",
        }
        assert _claves_dedup(a) & _claves_dedup(b)

    def test_mismo_articulo_cifra_distinta_no_se_confunde(self):
        a = {"pregunta": "¿Plazo del artículo 14?", "respuesta": "El artículo 14 fija un plazo de 15 días hábiles."}
        b = {"pregunta": "¿Plazo del artículo 14?", "respuesta": "El artículo 14 fija un plazo de 1 mes."}
        claves_a = {c for c in _claves_dedup(a) if c.startswith("d:")}
        claves_b = {c for c in _claves_dedup(b) if c.startswith("d:")}
        assert claves_a.isdisjoint(claves_b)

    def test_articulo_solo_en_respuesta_se_usa_como_respaldo(self):
        tarjeta = {"pregunta": "¿Cuál es el plazo de alegaciones?", "respuesta": "El artículo 14 fija 15 días hábiles."}
        assert _articulos_citados(tarjeta) == {"14"}

    def test_articulo_en_pregunta_tiene_prioridad_sobre_respuesta(self):
        tarjeta = {"pregunta": "¿Qué dice el artículo 14?", "respuesta": "El artículo 20 regula algo distinto."}
        assert _articulos_citados(tarjeta) == {"14"}

    def test_dedupe_de_fracciones_en_distintas_formas(self):
        base = {"pregunta": "¿Mayoría del artículo 9?", "respuesta": "El artículo 9 exige dos tercios."}
        barra = {"pregunta": "¿Qué mayoría exige el artículo 9?", "respuesta": "El artículo 9 exige 2/3."}
        palabras = {"pregunta": "¿Fracción requerida por el artículo 9?", "respuesta": "El artículo 9 exige 2 tercios."}
        claves_base = {c for c in _claves_dedup(base) if c.startswith("d:")}
        claves_barra = {c for c in _claves_dedup(barra) if c.startswith("d:")}
        claves_palabras = {c for c in _claves_dedup(palabras) if c.startswith("d:")}
        assert claves_base == claves_barra == claves_palabras

    def test_dedupe_por_principio_juridico_con_nombre_propio(self):
        a = {
            "pregunta": "¿Qué principio recoge el artículo 9.3?",
            "respuesta": "El artículo 9.3 recoge el principio de seguridad jurídica.",
        }
        b = {
            "pregunta": "El artículo 9.3, ¿a qué principio hace referencia?",
            "respuesta": "Al principio de seguridad jurídica, entre otros.",
        }
        claves_a = {c for c in _claves_dedup(a) if c.startswith("c:")}
        claves_b = {c for c in _claves_dedup(b) if c.startswith("c:")}
        assert claves_a and claves_a == claves_b

    def test_texto_pregunta_identico_sigue_detectando_duplicado_exacto(self):
        a = {"pregunta": "¿Qué es el TFUE?", "respuesta": "El Tratado de Funcionamiento de la UE."}
        b = {"pregunta": "¿Qué es el TFUE?", "respuesta": "Otra respuesta completamente distinta."}
        assert _claves_dedup(a) & _claves_dedup(b)

    def test_respuesta_larga_identica_distinta_pregunta_es_duplicado(self):
        respuesta = "Es un texto de respuesta bastante largo y específico sobre un hecho concreto."
        a = {"pregunta": "¿Pregunta A?", "respuesta": respuesta}
        b = {"pregunta": "¿Pregunta B totalmente distinta?", "respuesta": respuesta}
        assert _claves_dedup(a) & _claves_dedup(b)

    def test_sin_articulo_ni_cifra_no_genera_clave_d_ni_c(self):
        tarjeta = {"pregunta": "¿Qué es el TFUE?", "respuesta": "El Tratado de Funcionamiento de la Unión Europea."}
        claves = _claves_dedup(tarjeta)
        assert not any(c.startswith("d:") or c.startswith("c:") for c in claves)
        assert any(c.startswith("p:") for c in claves)


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

    def test_on_progreso_incluye_la_tarjeta_aceptada(self):
        # Mismo patrón que generador_preguntas_verificado.py/test_generator.py:
        # el evento de progreso lleva el contenido de la tarjeta ACEPTADA
        # (no solo el contador), para que el llamante (ver
        # /generar-tarjetas-desde-pdf en blueprints/pdf_ia.py) pueda mandar
        # un evento SSE aparte y dejar repasar tarjetas ya listas sin
        # esperar a que termine todo el documento.
        def fake_call(messages, **kwargs):
            if _es_prompt_generacion(messages):
                return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta?", "respuesta": "Respuesta"}]})
            if _es_prompt_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            raise AssertionError("prompt inesperado")

        eventos = []
        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call):
            generar_tarjetas_verificadas("Texto corto del documento.", 1, on_progreso=eventos.append)

        assert len(eventos) == 1
        assert eventos[0]["tarjeta"]["pregunta"] == "¿Pregunta?"

    def test_on_progreso_no_incluye_tarjeta_si_se_descarta(self):
        def fake_call(messages, **kwargs):
            if _es_prompt_generacion(messages):
                return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta única?", "respuesta": "Respuesta"}]})
            if _es_prompt_verificacion(messages):
                return json.dumps({"valido": False, "problemas": ["dato inventado"]})
            raise AssertionError("prompt inesperado")

        eventos = []
        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call):
            generar_tarjetas_verificadas("Texto corto del documento.", 1, on_progreso=eventos.append)

        assert len(eventos) > 0
        assert all("tarjeta" not in evento for evento in eventos)

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

    def test_generar_candidatas_fragmento_recorta_al_cupo_pedido(self):
        # 12/08/2026, bug real: el modelo a veces devuelve más tarjetas de
        # las pedidas en "cupo" -- sin recortar, todas pasaban a
        # verificación, gastando llamadas de más sin ningún beneficio.
        respuesta = json.dumps({"tarjetas": [
            {"pregunta": f"¿Pregunta {i}?", "respuesta": f"Respuesta {i}"} for i in range(5)
        ]})
        with patch("tarjetas_generator.call_deepseek_api", return_value=respuesta):
            candidatas = _generar_candidatas_fragmento("Fragmento", cupo=2, on_usage=None)
        assert len(candidatas) == 2

    def test_dedup_por_articulo_y_cifra_caza_lo_que_el_solapamiento_semantico_no_llega(self):
        # 12/08/2026: dos fragmentos distintos generan tarjetas sobre el
        # MISMO artículo y el MISMO dato (15 días hábiles), pero redactadas
        # de forma tan distinta que el solapamiento de palabras de la
        # respuesta (_es_semanticamente_duplicada, umbral 0.5) NO las
        # detectaría como duplicadas -- solo _claves_dedup, por compartir
        # artículo+cifra, las caza.
        def fake_call(messages, **kwargs):
            contenido = messages[0]["content"] + messages[1]["content"]
            if _es_prompt_generacion(messages):
                if "Fragmento A" in contenido:
                    return json.dumps({"tarjetas": [{
                        "pregunta": "¿Cuál es el plazo de alegaciones del expediente?",
                        "respuesta": "El artículo 14 establece un plazo de 15 días hábiles para presentar alegaciones.",
                    }]})
                return json.dumps({"tarjetas": [{
                    "pregunta": "Conforme al artículo 14, ¿de cuánto tiempo dispone el interesado?",
                    "respuesta": "Dispone de 15 días hábiles conforme a la norma aplicable.",
                }]})
            if _es_prompt_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            raise AssertionError("prompt inesperado")

        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call), \
             patch("tarjetas_generator._trocear_en_parrafos", return_value=["Fragmento A", "Fragmento B"]):
            resultado = generar_tarjetas_verificadas("Documento con dos fragmentos.", 2)

        assert len(resultado["tarjetas"]) == 1

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

    def test_verificacion_pide_8000_tokens_no_400(self):
        # Mismo bug real que en test_generator.py: con max_tokens=400,
        # deepseek-v4-flash podía truncar la respuesta de verificación al
        # detallar varios problemas, y el JSON cortado se trataba como
        # tarjeta inválida aunque no lo fuera. Subido a 8000 (12/08/2026,
        # igual que test_generator.py._verificar_pregunta): con
        # thinking_enabled=True el razonamiento cuenta contra el mismo tope
        # que el JSON de salida, así que 4000 dejaba menos margen real que
        # en test_generator.py para una tarea equivalente.
        max_tokens_verificacion = []

        def fake_call(messages, max_tokens=None, **kwargs):
            if _es_prompt_generacion(messages):
                return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta?", "respuesta": "Respuesta"}]})
            max_tokens_verificacion.append(max_tokens)
            return json.dumps({"valido": True, "problemas": []})

        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call):
            generar_tarjetas_verificadas("Texto corto.", 1)

        assert max_tokens_verificacion == [8000]

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


class TestGenerarBancoTarjetasAdaptativo:
    # generar_banco_tarjetas_adaptativo (03/08/2026, decisión explícita del
    # usuario): genera en rondas sucesivas hasta agotar el contenido
    # distinto del documento, con un tope de seguridad -- no un número fijo
    # a forzar. Ver el comentario largo en tarjetas_generator.py.
    def test_para_al_llegar_al_tope_si_el_documento_da_de_sobra(self):
        contador = itertools.count(1)

        def fake_call(messages, **kwargs):
            if _es_prompt_generacion(messages):
                # Contenido "infinito": cada llamada devuelve tarjetas
                # nuevas y distintas, nunca se agota.
                return json.dumps({"tarjetas": [
                    {"pregunta": f"¿Pregunta {next(contador)}?", "respuesta": "R"} for _ in range(8)
                ]})
            if _es_prompt_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            raise AssertionError("prompt inesperado")

        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call), \
             patch("tarjetas_generator._trocear_en_parrafos", return_value=["Fragmento único"]):
            resultado = generar_banco_tarjetas_adaptativo("Documento.", tope=20, tamano_ronda=8)

        assert len(resultado) == 20

    def test_para_por_bajo_rendimiento_aunque_no_haya_llegado_al_tope(self):
        # Ronda 1: el documento da 8 tarjetas nuevas de sobra. Ronda 2: el
        # prompt ya lleva el aviso "no repitas" (ver tarjetas_generator.
        # _prompt_con_exclusion) -- se simula que el documento ya no da más
        # devolviendo SIEMPRE la misma tarjeta de la ronda 1, que el dedup
        # (interno vía tarjetas_previas, y el de esta función) descarta por
        # completo. El bajo rendimiento de la ronda 2 (0 nuevas) debe parar
        # la generación mucho antes de llegar al tope de 100.
        def fake_call(messages, **kwargs):
            if _es_prompt_generacion(messages):
                if "No repitas ninguna de estas tarjetas" in messages[0]["content"]:
                    return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta 1?", "respuesta": "Respuesta 1"}]})
                return json.dumps({"tarjetas": [
                    {"pregunta": f"¿Pregunta {i}?", "respuesta": f"Respuesta {i}"} for i in range(1, 9)
                ]})
            if _es_prompt_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            raise AssertionError("prompt inesperado")

        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call), \
             patch("tarjetas_generator._trocear_en_parrafos", return_value=["Fragmento único"]):
            resultado = generar_banco_tarjetas_adaptativo("Documento.", tope=100, tamano_ronda=8)

        assert len(resultado) == 8

    def test_on_progreso_solo_reporta_tarjetas_nuevas_no_las_de_rondas_repetidas(self):
        def fake_call(messages, **kwargs):
            if _es_prompt_generacion(messages):
                if "No repitas ninguna de estas tarjetas" in messages[0]["content"]:
                    return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta 1?", "respuesta": "Respuesta 1"}]})
                return json.dumps({"tarjetas": [{"pregunta": "¿Pregunta 1?", "respuesta": "Respuesta 1"}]})
            if _es_prompt_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            raise AssertionError("prompt inesperado")

        eventos = []
        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call), \
             patch("tarjetas_generator._trocear_en_parrafos", return_value=["Fragmento único"]):
            resultado = generar_banco_tarjetas_adaptativo(
                "Documento.", tope=20, tamano_ronda=1, on_progreso=eventos.append,
            )

        assert len(resultado) == 1
        assert len(eventos) == 1
        assert eventos[0] == {"completadas": 1, "objetivo": 20, "tarjeta": resultado[0]}

    def test_evento_parada_marcado_no_lanza_una_ronda_nueva(self):
        # 10/08/2026, a petición del usuario ("quiero un botón para parar
        # una generación mía en marcha para no gastar tokens de más"): con
        # el evento ya marcado ANTES de la primera ronda, no debe lanzarse
        # ninguna llamada.
        def fake_call(messages, **kwargs):
            raise AssertionError("no debería llamarse a la IA con evento_parada ya marcado")

        evento_parada = threading.Event()
        evento_parada.set()
        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call), \
             patch("tarjetas_generator._trocear_en_parrafos", return_value=["Fragmento único"]):
            resultado = generar_banco_tarjetas_adaptativo(
                "Documento.", tope=20, tamano_ronda=8, evento_parada=evento_parada,
            )
        assert resultado == []

    def test_para_por_bajo_rendimiento_con_duplicados_reformulados_entre_rondas(self):
        # Caso real reportado por el usuario: la ronda 2 no repite el
        # enunciado LITERAL de la ronda 1 (así que el dedup antiguo, solo
        # por texto exacto, la aceptaba igual), pero pregunta por el MISMO
        # hecho con la respuesta reordenada -- debe detectarse como
        # duplicada vía _es_semanticamente_duplicada y contar como
        # rendimiento 0 en la ronda 2, parando el banco antes del tope.
        def fake_call(messages, **kwargs):
            if _es_prompt_generacion(messages):
                if "No repitas ninguna de estas tarjetas" in messages[0]["content"]:
                    return json.dumps({"tarjetas": [{
                        "pregunta": "¿Qué instrumentos de asistencia financiera puso en marcha la Unión Europea?",
                        "respuesta": "La UE creó como mecanismos de ayuda financiera para los Estados miembros el MEEF, el FEEF y el MEDE.",
                    }]})
                return json.dumps({"tarjetas": [{
                    "pregunta": "¿Qué mecanismos de ayuda financiera creó la UE?",
                    "respuesta": "La UE creó el MEEF, el FEEF y el MEDE como mecanismos de ayuda financiera para los Estados miembros.",
                }]})
            if _es_prompt_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            raise AssertionError("prompt inesperado")

        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call), \
             patch("tarjetas_generator._trocear_en_parrafos", return_value=["Fragmento único"]):
            resultado = generar_banco_tarjetas_adaptativo("Documento.", tope=100, tamano_ronda=1)

        assert len(resultado) == 1

    def test_para_por_duplicado_de_articulo_y_cifra_entre_rondas(self):
        # 12/08/2026: la ronda 2 reformula la tarjeta de la ronda 1 con
        # palabras tan distintas que _es_semanticamente_duplicada no la
        # cazaría (solapamiento de palabras por debajo del umbral), pero
        # ambas citan el MISMO artículo y el MISMO dato -- debe detectarse
        # vía _claves_dedup y parar el banco antes del tope.
        def fake_call(messages, **kwargs):
            if _es_prompt_generacion(messages):
                if "No repitas ninguna de estas tarjetas" in messages[0]["content"]:
                    return json.dumps({"tarjetas": [{
                        "pregunta": "Conforme al artículo 14, ¿de cuánto tiempo dispone el interesado?",
                        "respuesta": "Dispone de 15 días hábiles conforme a la norma aplicable.",
                    }]})
                return json.dumps({"tarjetas": [{
                    "pregunta": "¿Cuál es el plazo de alegaciones del expediente?",
                    "respuesta": "El artículo 14 establece un plazo de 15 días hábiles para presentar alegaciones.",
                }]})
            if _es_prompt_verificacion(messages):
                return json.dumps({"valido": True, "problemas": []})
            raise AssertionError("prompt inesperado")

        with patch("tarjetas_generator.call_deepseek_api", side_effect=fake_call), \
             patch("tarjetas_generator._trocear_en_parrafos", return_value=["Fragmento único"]):
            resultado = generar_banco_tarjetas_adaptativo("Documento.", tope=100, tamano_ronda=1)

        assert len(resultado) == 1
