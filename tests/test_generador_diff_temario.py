"""Pruebas de generador_diff_temario.py: el mismo espíritu que
generador_preguntas_verificado.py -- generar + verificar de forma
independiente, y descartar la propuesta ENTERA (nunca "parchearla") si algo
no cuadra."""
import json
from unittest.mock import patch

from generador_diff_temario import generar_propuesta_cambio

SUBBLOQUES = [
    {"chunk_id": "c1", "titulo": "TREBEP", "texto": "El plazo para solicitarlo es de quince días hábiles desde la notificación."},
]


def _respuesta_generacion(chunk_id="c1", texto_eliminar="quince días hábiles", texto_anadir="veinte días hábiles"):
    return json.dumps({
        "chunk_id_afectado": chunk_id,
        "resumen": "El plazo pasa de quince a veinte días hábiles.",
        "texto_eliminar": texto_eliminar,
        "texto_anadir": texto_anadir,
    })


def _respuesta_verificacion(valido=True, problemas=None):
    return json.dumps({"valido": valido, "problemas": problemas or []})


def test_genera_propuesta_valida_cuando_todo_encaja():
    with patch("generador_diff_temario.call_deepseek_api", side_effect=[
        _respuesta_generacion(), _respuesta_verificacion(True),
    ]):
        propuesta = generar_propuesta_cambio("El plazo es de veinte días hábiles.", SUBBLOQUES)
    assert propuesta == {
        "chunk_id_afectado": "c1",
        "resumen": "El plazo pasa de quince a veinte días hábiles.",
        "texto_eliminar": "quince días hábiles",
        "texto_anadir": "veinte días hábiles",
    }


def test_descarta_sin_verificar_si_texto_eliminar_no_es_literal():
    # El LLM "resume" en vez de copiar textualmente -- no debe ni gastar la
    # segunda llamada de verificación.
    with patch("generador_diff_temario.call_deepseek_api", side_effect=[
        _respuesta_generacion(texto_eliminar="un plazo de dos semanas"),
    ]) as mock_llamada:
        propuesta = generar_propuesta_cambio("El plazo es de veinte días hábiles.", SUBBLOQUES)
    assert propuesta is None
    mock_llamada.assert_called_once()  # nunca llegó a la verificación


def test_descarta_si_la_verificacion_independiente_rechaza():
    with patch("generador_diff_temario.call_deepseek_api", side_effect=[
        _respuesta_generacion(), _respuesta_verificacion(False, ["texto_anadir no coincide con el texto vigente"]),
    ]):
        propuesta = generar_propuesta_cambio("El plazo es de veinte días hábiles.", SUBBLOQUES)
    assert propuesta is None


def test_descarta_si_el_chunk_afectado_no_existe_entre_los_candidatos():
    with patch("generador_diff_temario.call_deepseek_api", side_effect=[
        _respuesta_generacion(chunk_id="chunk_inventado"),
    ]):
        propuesta = generar_propuesta_cambio("El plazo es de veinte días hábiles.", SUBBLOQUES)
    assert propuesta is None


def test_sin_subbloques_candidatos_no_llama_a_deepseek():
    with patch("generador_diff_temario.call_deepseek_api") as mock_llamada:
        propuesta = generar_propuesta_cambio("texto nuevo", [])
    assert propuesta is None
    mock_llamada.assert_not_called()
