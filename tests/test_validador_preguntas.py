"""Pruebas de validador_preguntas.py: filtra preguntas mal formadas o de
baja calidad antes de guardarlas -- central en el pipeline de generación
verificada de preguntas (generador_preguntas_verificado.py) pero sin
ningún test dedicado hasta ahora."""
from validador_preguntas import validar_pregunta, detectar_repeticiones, filtrar_preguntas_repetidas


def _pregunta_valida(**overrides):
    base = {
        "pregunta": "¿Quién nombra al Presidente del Gobierno?",
        "opciones": {"A": "El Rey", "B": "El Congreso", "C": "El Senado", "D": "El Tribunal Constitucional"},
        "respuesta_correcta": "A",
        "explicacion": "El artículo 62 de la Constitución Española establece esta competencia del Rey.",
    }
    base.update(overrides)
    return base


def test_pregunta_valida_pasa():
    assert validar_pregunta(_pregunta_valida()) is True


def test_no_es_un_diccionario():
    assert validar_pregunta(["no", "es", "un", "dict"]) is False


def test_falta_una_clave_obligatoria():
    pregunta = _pregunta_valida()
    del pregunta["explicacion"]
    assert validar_pregunta(pregunta) is False


def test_opciones_no_es_diccionario():
    assert validar_pregunta(_pregunta_valida(opciones=["El Rey", "El Congreso"])) is False


def test_falta_una_opcion_de_la_a_a_la_d():
    pregunta = _pregunta_valida()
    del pregunta["opciones"]["D"]
    assert validar_pregunta(pregunta) is False


def test_rechaza_frase_prohibida_segun_el_texto():
    assert validar_pregunta(_pregunta_valida(
        explicacion="Según el texto, el Rey nombra al Presidente del Gobierno."
    )) is False


def test_rechaza_frase_prohibida_en_mayusculas_o_minusculas_mezcladas():
    assert validar_pregunta(_pregunta_valida(
        explicacion="SEGÚN EL CONTENIDO proporcionado, el Rey nombra al Presidente."
    )) is False


def test_rechaza_pregunta_que_remite_al_contenido_invisible():
    # Regresión: "¿Qué tienen en común todas las escalas y auxiliares
    # mencionados en el contenido?" -- quien responde el test nunca ve el
    # material de origen, solo la pregunta, así que remitir a "el
    # contenido" la deja sin sentido.
    assert validar_pregunta(_pregunta_valida(
        pregunta="¿Qué tienen en común todas las escalas y auxiliares mencionados en el contenido?"
    )) is False


def test_rechaza_variantes_de_remision_a_contenido_documento_o_texto():
    variantes = [
        "los órganos mencionados en el documento tienen esto en común.",
        "las funciones mencionadas en el texto comparten este rasgo.",
        "como se explicó arriba mencionado, el plazo es de un mes.",
        "según lo anteriormente mencionado, el órgano competente decide.",
    ]
    for explicacion in variantes:
        assert validar_pregunta(_pregunta_valida(explicacion=explicacion)) is False, explicacion


def test_rechaza_pregunta_de_acuerdo_con_el_contenido():
    # Regresión real: "¿De acuerdo con el contenido, el Permalink ELI de
    # las versiones consolidadas se construye siguiendo el estándar
    # europeo?" se coló en un test personalizado porque "de acuerdo con"
    # no estaba en frases_prohibidas (solo "según"/"del"/"en el"/"mencionado
    # en el"), pese a ser la misma remisión al material de origen invisible
    # para quien responde el test.
    assert validar_pregunta(_pregunta_valida(
        pregunta="¿De acuerdo con el contenido, cómo se construye el Permalink?"
    )) is False
    for variante in [
        "de acuerdo con el contenido, el órgano competente decide.",
        "de acuerdo con el texto, el plazo es de un mes.",
        "de acuerdo con el documento, la competencia es del Rey.",
        "de acuerdo con el fragmento, la norma aplicable es esta.",
    ]:
        assert validar_pregunta(_pregunta_valida(explicacion=variante)) is False, variante


def test_rechaza_conforme_al_contenido_o_al_documento():
    # Bug real (03/08/2026), test generado desde PDF: la primera pregunta
    # empezaba con "Conforme al contenido del tema, ¿...?" -- FRASES_PROHIBIDAS
    # solo cubría "según"/"de acuerdo con", no "conforme a(l)", así que esta
    # variante se colaba tal cual.
    assert validar_pregunta(_pregunta_valida(
        pregunta="Conforme al contenido del tema, ¿cómo se construye el Permalink?"
    )) is False
    for variante in [
        "conforme al contenido, el órgano competente decide.",
        "conforme al documento, el plazo es de un mes.",
        "conforme al texto, la competencia es del Rey.",
        "conforme al tema, la norma aplicable es esta.",
    ]:
        assert validar_pregunta(_pregunta_valida(explicacion=variante)) is False, variante


def test_rechaza_el_documento_establece_indica_o_menciona():
    # Bug real (03/08/2026), mismo test: varias explicaciones decían "el
    # documento establece/indica/señala que..." y una decía "el tema cita
    # el artículo..." -- no son frases fijas (varía el verbo), así que
    # FRASES_PROHIBIDAS (que solo compara substrings exactos) nunca las
    # cazaba; hace falta un patrón sujeto+verbo.
    for variante in [
        "el documento establece que el plazo es de un mes.",
        "el documento indica que la competencia es del Rey.",
        "el documento señala que el órgano competente decide.",
        "el documento menciona que la norma aplicable es esta.",
        "el tema cita el artículo 62 de la Constitución.",
        "el contenido dispone que se aplique el procedimiento ordinario.",
        "el texto regula esta materia de forma expresa.",
        "el fragmento recoge la excepción prevista en la ley.",
    ]:
        assert validar_pregunta(_pregunta_valida(explicacion=variante)) is False, variante


def test_rechaza_el_documento_con_inciso_entre_comas_antes_del_verbo():
    # Bug real de producción (03/08/2026), documento real: "el documento, al
    # detallar la iniciativa de reforma, señala que..." se coló en un test
    # porque PATRON_REFERENCIA_META exigía que el verbo viniera INMEDIATAMENTE
    # después del sustantivo (solo espacios de por medio) -- cualquier
    # inciso entre comas antes del verbo (habitual en explicaciones más
    # largas) lo dejaba sin detectar aunque la referencia al documento fuera
    # exactamente la misma que en test_rechaza_el_documento_establece_indica_o_menciona.
    for variante in [
        "el documento, al detallar la iniciativa de reforma, señala que el requisito es este.",
        "el texto, más adelante, establece una excepción a esta regla.",
        "el tema, en el apartado dedicado a la reforma, cita el artículo 62 de la Constitución.",
    ]:
        assert validar_pregunta(_pregunta_valida(explicacion=variante)) is False, variante


def test_no_rechaza_conforme_a_seguido_de_una_norma_legitima():
    # "conforme a" es una construcción legítima cuando lo que sigue es una
    # norma real, no el material de origen -- PATRON_REFERENCIA_META solo
    # dispara con documento/contenido/texto/tema/fragmento justo detrás.
    assert validar_pregunta(_pregunta_valida(
        explicacion="Conforme a la Constitución Española, el Rey nombra al Presidente del Gobierno."
    )) is True


def test_no_rechaza_contenido_esencial_como_termino_juridico_legitimo():
    # "contenido esencial" es terminología constitucional real (artículo
    # 53.1 de la Constitución Española) -- no debe confundirse con una
    # remisión al material de origen.
    assert validar_pregunta(_pregunta_valida(
        explicacion="El artículo 53.1 de la Constitución Española protege el contenido esencial de los "
                    "derechos fundamentales."
    )) is True


def test_rechaza_sigla_ce_en_vez_del_nombre_completo():
    # Regresión: los exámenes oficiales de estas oposiciones nunca abrevian
    # -- una pregunta que diga "según la CE" en vez de "según la
    # Constitución Española" debe descartarse.
    assert validar_pregunta(_pregunta_valida(
        pregunta="¿Qué artículo de la CE regula el derecho a la tutela judicial efectiva?"
    )) is False


def test_rechaza_otras_siglas_habituales_de_normas():
    for sigla in ["TREBEP", "LPAC", "LRJSP", "LOTC"]:
        explicacion = f"El artículo 1 de la {sigla} establece esta obligación de forma clara y suficiente."
        assert validar_pregunta(_pregunta_valida(explicacion=explicacion)) is False, sigla


def test_no_rechaza_palabras_que_contienen_las_letras_de_una_sigla():
    # "CE" no debe dispararse sobre palabras normales que solo contienen esas
    # letras seguidas (p. ej. "acerca de"), gracias al \b de la regex.
    assert validar_pregunta(_pregunta_valida(
        explicacion="El artículo 62 de la Constitución Española trata acerca de esta competencia del Rey."
    )) is True


def test_rechaza_abreviatura_de_tipo_de_norma_con_numero():
    # Regresión: "Según la LO 3/2007, ¿cuál es la diferencia..." -- abrevia
    # "Ley Orgánica 3/2007" con el tipo de norma + número en vez del nombre
    # completo. No lo pilla la lista de siglas fijas (no es una palabra
    # suelta, va seguida de un número), hace falta un patrón aparte.
    for texto in ["LO 3/2007", "RD 203/2021", "RDL 5/2015", "RDLeg 5/2015"]:
        assert validar_pregunta(_pregunta_valida(pregunta=f"Según la {texto}, ¿qué establece?")) is False, texto


def test_no_rechaza_lo_o_rd_sueltos_sin_numero_de_norma_detras():
    # El patrón exige el número X/YYYY justo detrás para evitar falsos
    # positivos con letras sueltas que no estén citando ninguna norma.
    assert validar_pregunta(_pregunta_valida(
        explicacion="El artículo 62 de la Constitución Española lo regula de forma clara y directa."
    )) is True


def test_rechaza_explicacion_demasiado_corta():
    assert validar_pregunta(_pregunta_valida(explicacion="Porque sí.")) is False


def test_rechaza_pregunta_con_campos_no_string_en_vez_de_petar():
    # Si DeepSeek devuelve "pregunta" o "explicacion" con un tipo raro (None,
    # un número...) a pesar del modo JSON forzado, esto debe descartarse como
    # cualquier otra pregunta mal formada -- nunca lanzar un TypeError al
    # concatenarlo con " " más abajo, que tiraría todo el lote de
    # generar_test_verificado (ver test_generador_preguntas_verificado.py).
    assert validar_pregunta(_pregunta_valida(pregunta=None)) is False
    assert validar_pregunta(_pregunta_valida(explicacion=123)) is False


def test_acepta_explicacion_justo_en_el_limite():
    # 15 caracteres exactos: el filtro rechaza < 15, así que esto debe pasar.
    assert validar_pregunta(_pregunta_valida(explicacion="123456789012345")) is True


def test_detectar_repeticiones_cuenta_frases_normativas_repetidas():
    # NOTA: la regex de detectar_repeticiones (validador_preguntas.py) usa
    # "\\s*\\d+" dentro de una raw string -- eso son literalmente un
    # backslash + "s"/"d" en el patrón, no las clases \s/\d de regex. En la
    # práctica "artículo 14" y "Ley Orgánica 3/2007" NUNCA hacen match hoy
    # (haría falta un backslash literal en el texto real); solo las frases
    # sin backslash en el patrón ("Constitución Española", "Poder
    # Judicial", "Defensor del Pueblo") se detectan de verdad. Este test
    # documenta el comportamiento real, no el que probablemente se
    # pretendía -- corregir la regex queda fuera de esta tanda.
    preguntas = [
        {"pregunta": "P1 sobre la Constitución Española", "explicacion": ""},
        {"pregunta": "P2 sobre la Constitución Española", "explicacion": ""},
        {"pregunta": "P3 sobre la Constitución Española", "explicacion": ""},
        {"pregunta": "P4 sobre el Poder Judicial", "explicacion": ""},
        {"pregunta": "P5 sobre el artículo 14 (no se detecta, ver nota arriba)", "explicacion": ""},
    ]
    repetidas = detectar_repeticiones(preguntas, max_repeticiones=2)
    assert repetidas == {"constitución española": 3}


def test_filtrar_preguntas_repetidas_quita_las_que_mencionan_el_concepto():
    preguntas = [
        {"pregunta": "P1 sobre la Constitución Española", "explicacion": ""},
        {"pregunta": "P2 sin relación", "explicacion": ""},
    ]
    filtradas = filtrar_preguntas_repetidas(preguntas, {"constitución española"})
    assert filtradas == [{"pregunta": "P2 sin relación", "explicacion": ""}]
