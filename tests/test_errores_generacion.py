"""Pruebas del registro unificado de errores_generacion.py -- la escritura
de auto_verificacion (generador_preguntas_verificado.py) y de usuario_admin
(/reportar-pregunta) se prueban aparte, aquí solo el helper compartido."""
from unittest.mock import MagicMock

from errores_generacion import _clasificar_tipo_error, registrar_error_generacion


def test_registrar_error_generacion_escribe_los_7_campos_del_esquema(db):
    registrar_error_generacion(
        db, tema_id="bloque_01-tema_01", fuente="auto_verificacion",
        pregunta_texto="¿Pregunta?", detalle="el plazo no coincide", intento_numero=2,
    )
    documentos = [doc.to_dict() for doc in db.collection("errores_generacion").stream()]
    assert len(documentos) == 1
    doc = documentos[0]
    assert set(doc) == {
        "tema_id", "tipo_error", "fuente", "pregunta_texto", "detalle",
        "intento_numero", "resuelto", "timestamp",
    }
    assert doc["tema_id"] == "bloque_01-tema_01"
    assert doc["fuente"] == "auto_verificacion"
    assert doc["pregunta_texto"] == "¿Pregunta?"
    assert doc["detalle"] == "el plazo no coincide"
    assert doc["intento_numero"] == 2
    assert doc["resuelto"] is False


def test_registrar_error_generacion_conserva_campos_extra(db):
    # p.ej. uid del usuario que reporta -- ver /reportar-pregunta.
    registrar_error_generacion(
        db, tema_id="", fuente="usuario_admin", pregunta_texto="¿Pregunta?",
        detalle="la B también es correcta", uid="u1", oposicion="AGE", pregunta_id="p1",
    )
    doc = next(db.collection("errores_generacion").stream()).to_dict()
    assert doc["uid"] == "u1"
    assert doc["oposicion"] == "AGE"
    assert doc["pregunta_id"] == "p1"


def test_registrar_error_generacion_no_bloqueante_si_firestore_falla(db, caplog):
    db_roto = MagicMock()
    db_roto.collection.side_effect = RuntimeError("Firestore caído")
    with caplog.at_level("WARNING"):
        registrar_error_generacion(
            db_roto, tema_id="t1", fuente="auto_verificacion",
            pregunta_texto="x", detalle="y",
        )  # no debe lanzar
    assert any("no se pudo escribir" in r.message for r in caplog.records)
    assert not any(r.levelname == "ERROR" for r in caplog.records)


def test_clasificar_tipo_error_por_palabras_clave():
    assert _clasificar_tipo_error("el plazo citado en el artículo no coincide") == "desfase_legal"
    assert _clasificar_tipo_error("la respuesta marcada no es completamente correcta") == "respuesta_incorrecta"
    assert _clasificar_tipo_error("otra opción también sería defendible") == "distractor_implausible"
    assert _clasificar_tipo_error("hay una contradicción entre pregunta y explicación") == "ambiguedad"
    assert _clasificar_tipo_error("algo raro sin palabras clave reconocibles") == "otro"


def test_tipo_error_explicito_gana_a_la_heuristica(db):
    registrar_error_generacion(
        db, tema_id="t1", fuente="usuario_admin", pregunta_texto="x",
        detalle="el plazo no coincide", tipo_error="otro",
    )
    doc = next(db.collection("errores_generacion").stream()).to_dict()
    assert doc["tipo_error"] == "otro"
