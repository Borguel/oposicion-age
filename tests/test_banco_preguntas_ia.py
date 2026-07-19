"""Pruebas del repositorio interno de preguntas ya generadas y verificadas
(banco_preguntas_ia.py) -- de momento solo almacenamiento, sin ninguna
ruta pública que lo lea."""
from unittest.mock import MagicMock

from banco_preguntas_ia import coleccion_banco_preguntas, guardar_pregunta_generada


def test_coleccion_banco_preguntas_separa_por_oposicion():
    assert coleccion_banco_preguntas("AGE") == "banco_preguntas_ia_AGE"
    assert coleccion_banco_preguntas("GACE") == "banco_preguntas_ia_GACE"


def test_coleccion_banco_preguntas_oposicion_no_valida_cae_a_la_de_defecto():
    assert coleccion_banco_preguntas("NO_EXISTE") == coleccion_banco_preguntas("AGE")


def test_guardar_pregunta_generada_escribe_los_campos_esperados(db):
    pregunta = {
        "pregunta": "¿Cuál es el plazo?",
        "opciones": {"A": "10 días", "B": "20 días", "C": "1 mes", "D": "3 meses"},
        "respuesta_correcta": "A",
        "explicacion": "El artículo fija un plazo de 10 días para este trámite.",
        "tema_id": "bloque_01-tema_01",
        "tipo_pregunta": "memoria_literal",
    }
    guardar_pregunta_generada(db, "AGE", pregunta)

    guardadas = [doc.to_dict() for doc in db.collection("banco_preguntas_ia_AGE").stream()]
    assert len(guardadas) == 1
    guardada = guardadas[0]
    assert guardada["pregunta"] == pregunta["pregunta"]
    assert guardada["opciones"] == pregunta["opciones"]
    assert guardada["respuesta_correcta"] == "A"
    assert guardada["tema_id"] == "bloque_01-tema_01"
    assert guardada["clave_normalizada"] == "¿cuál es el plazo?"
    assert guardada["fecha_generacion"]


def test_guardar_pregunta_generada_no_propaga_errores_de_firestore():
    db_roto = MagicMock()
    db_roto.collection.side_effect = RuntimeError("Firestore caído")
    # No debe lanzar -- es almacenamiento auxiliar, no debe romper la
    # generación del test del usuario si Firestore falla.
    guardar_pregunta_generada(db_roto, "AGE", {"pregunta": "x"})
