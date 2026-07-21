"""Pruebas de utils.barajar_opciones_pregunta: los LLM tienden a poner la
respuesta correcta en la opción A con mucha más frecuencia de la que
correspondería al azar, así que hay que barajar la posición de las 4
opciones tras generarlas (y remapear "respuesta_correcta" y la explicación
para que sigan señalando a la opción correcta)."""
from utils import (
    barajar_opciones_pregunta,
    limpiar_cache_preguntas_banco_ia,
    obtener_catalogo_temas,
    obtener_preguntas_banco_ia,
    obtener_titulos_temas_reales,
    parsear_explicacion_por_opcion,
    _limpiar_cache_temario,
)


def _pregunta_base():
    return {
        "pregunta": "¿Quién nombra al Presidente del Gobierno?",
        "opciones": {"A": "El Rey", "B": "El Congreso", "C": "El Senado", "D": "El Tribunal Constitucional"},
        "respuesta_correcta": "A",
        "explicacion": (
            "A) es correcta porque el artículo 62 CE lo establece. "
            "B) es incorrecta porque el Congreso solo lo propone. "
            "C) es incorrecta porque el Senado no interviene. "
            "D) es incorrecta porque no tiene esa función."
        ),
    }


def test_respuesta_correcta_sigue_señalando_al_mismo_contenido():
    original = _pregunta_base()
    texto_correcto = original["opciones"][original["respuesta_correcta"]]

    resultado = barajar_opciones_pregunta(dict(original, opciones=dict(original["opciones"])))

    assert resultado["opciones"][resultado["respuesta_correcta"]] == texto_correcto


def test_conserva_las_4_opciones_sin_perder_ni_duplicar_contenido():
    original = _pregunta_base()
    resultado = barajar_opciones_pregunta(dict(original, opciones=dict(original["opciones"])))

    assert set(resultado["opciones"].keys()) == {"A", "B", "C", "D"}
    assert set(resultado["opciones"].values()) == set(original["opciones"].values())


def test_explicacion_remapeada_a_la_nueva_letra_correcta():
    original = _pregunta_base()
    resultado = barajar_opciones_pregunta(dict(original, opciones=dict(original["opciones"])))

    nueva_letra_correcta = resultado["respuesta_correcta"]
    assert f"{nueva_letra_correcta}) es correcta" in resultado["explicacion"]
    # Las otras tres letras deben decir "es incorrecta" en la explicación reordenada.
    for letra in "ABCD":
        if letra != nueva_letra_correcta:
            assert f"{letra}) es incorrecta" in resultado["explicacion"]


def test_no_siempre_deja_la_correcta_en_a():
    # Con 200 repeticiones sobre una pregunta cuya respuesta original es "A",
    # la correcta debería acabar en cada una de las 4 posiciones con
    # frecuencia similar -- si el bug reapareciera (sin barajar), siempre
    # sería "A" las 200 veces.
    letras_resultantes = set()
    for _ in range(200):
        resultado = barajar_opciones_pregunta(dict(_pregunta_base(), opciones=dict(_pregunta_base()["opciones"])))
        letras_resultantes.add(resultado["respuesta_correcta"])
    assert letras_resultantes == {"A", "B", "C", "D"}


def test_no_toca_la_pregunta_si_las_opciones_no_tienen_forma_esperada():
    pregunta = {"pregunta": "...", "opciones": {"A": "x", "B": "y"}, "respuesta_correcta": "A", "explicacion": "..."}
    resultado = barajar_opciones_pregunta(pregunta)
    assert resultado["opciones"] == {"A": "x", "B": "y"}
    assert resultado["respuesta_correcta"] == "A"


def test_no_toca_explicacion_que_no_sigue_el_formato_por_letra():
    original = _pregunta_base()
    original["explicacion"] = "La respuesta correcta es la A porque así lo dice la ley."
    resultado = barajar_opciones_pregunta(dict(original, opciones=dict(original["opciones"])))
    assert resultado["explicacion"] == "La respuesta correcta es la A porque así lo dice la ley."


def test_parsear_explicacion_por_opcion_bien_formada():
    explicacion = (
        "A) es correcta porque el artículo 62 CE lo establece. "
        "B) es incorrecta porque el Congreso solo lo propone. "
        "C) es incorrecta porque el Senado no interviene. "
        "D) es incorrecta porque no tiene esa función."
    )
    segmentos = parsear_explicacion_por_opcion(explicacion)
    assert segmentos == {
        "A": "es correcta porque el artículo 62 CE lo establece.",
        "B": "es incorrecta porque el Congreso solo lo propone.",
        "C": "es incorrecta porque el Senado no interviene.",
        "D": "es incorrecta porque no tiene esa función.",
    }


def test_parsear_explicacion_por_opcion_devuelve_none_si_falta_una_letra():
    explicacion = "A) es correcta. B) es incorrecta. C) es incorrecta."
    assert parsear_explicacion_por_opcion(explicacion) is None


def test_parsear_explicacion_por_opcion_devuelve_none_sin_prefijo_de_letra():
    assert parsear_explicacion_por_opcion("La respuesta correcta es la A porque sí.") is None
    assert parsear_explicacion_por_opcion("") is None
    assert parsear_explicacion_por_opcion(None) is None


def test_obtener_catalogo_temas_usa_cache_hasta_que_se_limpia(db):
    db.collection("Test").document("bloque_01").set({"titulo": "Bloque uno"})
    db.collection("Test").document("bloque_01").collection("temas").document("tema_01").set({"titulo": "Tema uno"})

    primera_llamada = obtener_catalogo_temas(db, "Test")
    assert len(primera_llamada) == 1

    # Se añade un tema nuevo directamente en Firestore, SIN pasar por la
    # caché -- la siguiente llamada debe seguir viendo el resultado
    # cacheado (1 tema), no el dato fresco (2 temas), porque el TTL
    # todavía no ha vencido.
    db.collection("Test").document("bloque_01").collection("temas").document("tema_02").set({"titulo": "Tema dos"})
    segunda_llamada = obtener_catalogo_temas(db, "Test")
    assert len(segunda_llamada) == 1

    # Al limpiar la caché (lo que hace el fixture autouse entre tests),
    # la siguiente llamada sí debe recalcular y ver el dato fresco.
    _limpiar_cache_temario()
    tercera_llamada = obtener_catalogo_temas(db, "Test")
    assert len(tercera_llamada) == 2


def test_obtener_preguntas_banco_ia_usa_cache_hasta_que_se_invalida(db):
    # Bug real visto en producción: una pregunta de Test Personalizado
    # recién generada no aparecía para Tu Tutor (buscar_pregunta_banco_ia)
    # hasta que venciera el TTL de 30 min de esta caché, porque
    # generador_preguntas_verificado.py no invalidaba nada tras guardarla.
    db.collection("banco_preguntas_ia_AGE").document("p1").set({"pregunta": "Pregunta uno", "respuesta_correcta": "A"})

    primera_llamada = obtener_preguntas_banco_ia(db, "AGE")
    assert len(primera_llamada) == 1

    # Se añade una segunda pregunta directamente en Firestore, sin pasar por
    # guardar_pregunta_generada (simula una caché ya caliente de antes) --
    # la siguiente llamada debe seguir viendo el resultado cacheado (1), no
    # el dato fresco (2), porque el TTL todavía no ha vencido.
    db.collection("banco_preguntas_ia_AGE").document("p2").set({"pregunta": "Pregunta dos", "respuesta_correcta": "B"})
    segunda_llamada = obtener_preguntas_banco_ia(db, "AGE")
    assert len(segunda_llamada) == 1

    # Al invalidar solo esta clave (lo que hace guardar_pregunta_generada tras
    # cada pregunta nueva vía generador_preguntas_verificado.py), la próxima
    # llamada sí debe recalcular y ver el dato fresco.
    limpiar_cache_preguntas_banco_ia("AGE")
    tercera_llamada = obtener_preguntas_banco_ia(db, "AGE")
    assert len(tercera_llamada) == 2


def test_obtener_titulos_temas_reales_traduce_codigos_via_get_all(db):
    db.collection("Test").document("bloque_01").collection("temas").document("tema_01").set({"titulo": "Constitución"})
    db.collection("Test").document("bloque_02").collection("temas").document("tema_01").set({"titulo": "Poder Judicial"})

    resultado = obtener_titulos_temas_reales(db, "Test", [
        "bloque_01-tema_01",
        "bloque_02-tema_01",
        "bloque_09-tema_09",  # no existe en Firestore -> se conserva el código
        "sin_guion_medio",     # formato inesperado -> se conserva tal cual
    ])

    assert resultado == ["Constitución", "Poder Judicial", "bloque_09-tema_09", "sin_guion_medio"]
