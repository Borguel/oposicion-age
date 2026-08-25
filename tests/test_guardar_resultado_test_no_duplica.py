"""Guardar el mismo test_id dos veces no debe contabilizarlo dos veces en
estadisticas.{oposicion} -- bug real (24/08/2026, auditoría de condiciones
de carrera): guardar_resultado_en_firestore llamaba SIEMPRE a
actualizar_estadisticas_test, aunque el test_id ya estuviera "finalizado"
de antes (reintento del frontend tras un timeout que en realidad sí
llegó, dos disparadores de "Finalizar" solapados)."""
from guardar_resultado import guardar_resultado_en_firestore


def _contenido():
    return [
        {"pregunta": "p1", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
        {"pregunta": "p2", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
    ]


def _guardar(db, test_id):
    guardar_resultado_en_firestore(
        db, "test", _contenido(),
        usuario_id="u1",
        metadatos={"respuestas": ["A", "B"], "tipo": "personalizado", "tiempo": 30},
        oposicion="AGE",
        test_id=test_id,
    )


def test_guardar_el_mismo_test_id_finalizado_dos_veces_no_duplica_estadisticas(db):
    _guardar(db, "t1")
    stats = db.leer(("usuarios", "u1"))["estadisticas"]["AGE"]
    assert stats["tests_realizados"] == 1
    assert stats["total_aciertos"] == 1
    assert stats["total_fallos"] == 1

    # Mismo test_id, ya "finalizado" -- reintento de red / doble disparo.
    _guardar(db, "t1")
    stats = db.leer(("usuarios", "u1"))["estadisticas"]["AGE"]
    assert stats["tests_realizados"] == 1
    assert stats["total_aciertos"] == 1
    assert stats["total_fallos"] == 1


def test_guardar_dos_test_id_distintos_si_se_contabilizan_los_dos(db):
    _guardar(db, "t1")
    _guardar(db, "t2")
    stats = db.leer(("usuarios", "u1"))["estadisticas"]["AGE"]
    assert stats["tests_realizados"] == 2


def test_guardar_sin_test_id_siempre_se_contabiliza(db):
    # Sin test_id (test-oficial/otros flujos que no reutilizan un borrador
    # "en_progreso") no hay nada que comprobar -- cada llamada es un test
    # nuevo de verdad.
    _guardar(db, None)
    _guardar(db, None)
    stats = db.leer(("usuarios", "u1"))["estadisticas"]["AGE"]
    assert stats["tests_realizados"] == 2


def test_reanudar_un_test_en_progreso_y_finalizarlo_si_se_contabiliza(db):
    # El mismo test_id se usa primero para autoguardar el borrador
    # "en_progreso" (nunca pasa por guardar_resultado_en_firestore, ver
    # /autosave-test) y luego para finalizarlo -- como el documento previo
    # NO estaba "finalizado" (estaba "en_progreso"), sí debe contabilizarse.
    db.sembrar(("usuarios", "u1", "tests", "t1"), {
        "estado": "en_progreso", "oposicion": "AGE", "num_preguntas": 2,
    })
    _guardar(db, "t1")
    stats = db.leer(("usuarios", "u1"))["estadisticas"]["AGE"]
    assert stats["tests_realizados"] == 1
