"""Pruebas de utils.barajar_opciones_pregunta: los LLM tienden a poner la
respuesta correcta en la opción A con mucha más frecuencia de la que
correspondería al azar, así que hay que barajar la posición de las 4
opciones tras generarlas (y remapear "respuesta_correcta" y la explicación
para que sigan señalando a la opción correcta)."""
from utils import barajar_opciones_pregunta


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
