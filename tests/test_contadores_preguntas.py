"""Fase 1 del loop de dificultad calibrada: contadores atómicos por pregunta
(preguntas/{id}.total_respuestas / total_aciertos), actualizados al corregir
un test. Solo telemetría -- no clasifica ni cambia nada de cara al usuario,
ver guardar_resultado._actualizar_contadores_preguntas."""
from unittest.mock import patch

from conftest import sembrar_usuario_activo
from banco_fallos import _id_pregunta
from guardar_resultado import guardar_resultado_en_firestore


def test_guardar_test_incrementa_contadores_de_cada_pregunta(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    contenido = [
        {"pregunta": "acierto", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
        {"pregunta": "fallo", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
        {"pregunta": "blanco", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
    ]
    respuestas = ["A", "B", None]
    usuario_autenticado()
    resp = client.post("/guardar-test?oposicion=AGE", json={
        "contenido": contenido,
        "respuestas": respuestas,
        "metadatos": {"tipo": "personalizado", "tiempo": 0}
    }, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    id_acierto = _id_pregunta("AGE", "acierto")
    id_fallo = _id_pregunta("AGE", "fallo")
    id_blanco = _id_pregunta("AGE", "blanco")

    doc_acierto = db.leer(("preguntas", id_acierto))
    doc_fallo = db.leer(("preguntas", id_fallo))
    doc_blanco = db.leer(("preguntas", id_blanco))

    assert doc_acierto == {"total_respuestas": 1, "total_aciertos": 1}
    assert doc_fallo == {"total_respuestas": 1}
    assert doc_blanco == {"total_respuestas": 1}


def test_guardar_test_acumula_entre_tests_sucesivos_de_distintos_usuarios(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    sembrar_usuario_activo(db, "u2", plan="basico")
    contenido = [{"pregunta": "misma pregunta", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}}]

    usuario_autenticado(uid="u1", email="u1@example.com")
    client.post("/guardar-test?oposicion=AGE", json={
        "contenido": contenido, "respuestas": ["A"], "metadatos": {"tipo": "personalizado", "tiempo": 0}
    }, headers={"Authorization": "Bearer x"})

    usuario_autenticado(uid="u2", email="u2@example.com")
    client.post("/guardar-test?oposicion=AGE", json={
        "contenido": contenido, "respuestas": ["B"], "metadatos": {"tipo": "personalizado", "tiempo": 0}
    }, headers={"Authorization": "Bearer x"})

    doc = db.leer(("preguntas", _id_pregunta("AGE", "misma pregunta")))
    assert doc == {"total_respuestas": 2, "total_aciertos": 1}


def test_pregunta_marcada_duda_no_alimenta_los_contadores(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    contenido = [
        {"pregunta": "con duda", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
        {"pregunta": "sin duda", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
    ]
    usuario_autenticado()
    resp = client.post("/guardar-test?oposicion=AGE", json={
        "contenido": contenido,
        "respuestas": ["A", "A"],
        "metadatos": {"tipo": "personalizado", "tiempo": 0},
        "marcadas_duda": [True, False],
    }, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    assert db.leer(("preguntas", _id_pregunta("AGE", "con duda"))) is None
    assert db.leer(("preguntas", _id_pregunta("AGE", "sin duda"))) == {"total_respuestas": 1, "total_aciertos": 1}


def test_fallo_en_el_batch_no_rompe_la_correccion_del_test(client, db, caplog, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    contenido = [{"pregunta": "acierto", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}}]
    usuario_autenticado()
    with patch.object(db, "batch", side_effect=Exception("fallo simulado de escritura")):
        resp = client.post("/guardar-test?oposicion=AGE", json={
            "contenido": contenido,
            "respuestas": ["A"],
            "metadatos": {"tipo": "personalizado", "tiempo": 0},
        }, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert resp.get_json()["mensaje"] == "Test guardado correctamente"

    listado = client.get("/mis-tests?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert listado.status_code == 200

    assert any("[calibracion]" in registro.message for registro in caplog.records)


def test_total_aciertos_nunca_supera_total_respuestas(db):
    guardar_resultado_en_firestore(
        db, "test",
        [
            {"pregunta": "p1", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
            {"pregunta": "p1", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
        ],
        usuario_id="u1",
        metadatos={"respuestas": ["A", "B"], "tipo": "personalizado", "tiempo": 0},
        oposicion="AGE",
    )
    doc = db.leer(("preguntas", _id_pregunta("AGE", "p1")))
    assert doc["total_aciertos"] <= doc["total_respuestas"]
