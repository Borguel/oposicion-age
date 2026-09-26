"""Comprueba las funciones puras (sin Firestore/DeepSeek) de
regenerar_explicaciones_examenes_oficiales: detectar si una explicación ya
repasa las 4 opciones (para no tocarla ni gastar dinero regenerándola) y
que el prompt nuevo incluye todo lo necesario para generar una buena."""
from regenerar_explicaciones_examenes_oficiales import (
    _prompt_explicacion,
    _tiene_formato_bueno,
)

# Ejemplo real (anonimizado en la forma, no en el fondo) que motivó esta
# tarea: la explicación solo justifica la opción correcta.
EXPLICACION_POBRE_REAL = (
    "La Ley 47/2003 General Presupuestaria define el reconocimiento de la "
    "obligación como el acto mediante el cual se declara la existencia de "
    "un crédito exigible contra la Hacienda Pública estatal, derivado de "
    "un gasto aprobado y comprometido."
)

EXPLICACION_BUENA = (
    "A) es correcta porque el art. 73 LGP define así el reconocimiento de "
    "la obligación. B) es incorrecta porque describe el compromiso del "
    "gasto, no el reconocimiento. C) es incorrecta porque describe la "
    "autorización del gasto, una fase anterior. D) es incorrecta porque "
    "el reconocimiento de la obligación no es un ingreso ni un pago."
)


def test_explicacion_pobre_no_tiene_formato_bueno():
    assert _tiene_formato_bueno(EXPLICACION_POBRE_REAL) is False


def test_explicacion_vacia_no_tiene_formato_bueno():
    assert _tiene_formato_bueno("") is False
    assert _tiene_formato_bueno(None) is False


def test_explicacion_con_las_4_opciones_tiene_formato_bueno():
    assert _tiene_formato_bueno(EXPLICACION_BUENA) is True


def test_explicacion_con_solo_3_opciones_no_es_suficiente():
    # Le falta "D)" -- no debe colarse como "ya buena".
    sin_d = EXPLICACION_BUENA.rsplit("D)", 1)[0]
    assert _tiene_formato_bueno(sin_d) is False


def test_prompt_incluye_pregunta_las_4_opciones_y_la_correcta():
    opciones = {
        "A": "El acto mediante el que se declara la existencia de un crédito exigible.",
        "B": "El acto mediante el cual se acuerda la realización de gastos previamente aprobados.",
        "C": "El acto mediante el cual se autoriza la realización de un gasto determinado.",
        "D": "El ingreso del pago.",
    }
    prompt = _prompt_explicacion(
        "De acuerdo con la Ley 47/2003, el reconocimiento de la obligación es:",
        opciones,
        "A",
    )
    assert "reconocimiento de la obligación" in prompt
    for letra, texto in opciones.items():
        assert f"{letra}) {texto}" in prompt
    assert "Respuesta correcta: A)" in prompt
    # Pide el formato por opción y advierte de no inventar citas legales.
    assert "es correcta/incorrecta porque" in prompt
    assert "no inventes ninguna referencia legal" in prompt
