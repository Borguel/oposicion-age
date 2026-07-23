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


def test_no_rechaza_contenido_esencial_como_termino_juridico_legitimo():
    # "contenido esencial" es terminología constitucional real (art. 53.1
    # CE) -- no debe confundirse con una remisión al material de origen.
    assert validar_pregunta(_pregunta_valida(
        explicacion="El artículo 53.1 CE protege el contenido esencial de los derechos fundamentales."
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
