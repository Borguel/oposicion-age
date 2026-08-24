"""Borrado de tests propios (finalizados y en progreso) desde Mis Tests."""

from conftest import sembrar_usuario_activo
from registro_progreso_usuario import actualizar_estadisticas_test


def test_borrar_test_finalizado(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    db.sembrar(("usuarios", "u1", "tests", "t1"), {
        "oposicion": "AGE", "estado": "finalizado", "aciertos": 5, "fallos": 0, "blancos": 0,
    })
    usuario_autenticado()
    resp = client.delete("/mi-test/t1", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    listado = client.get("/mis-tests?oposicion=AGE", headers={"Authorization": "Bearer x"}).get_json()
    assert listado["tests"] == []


def test_borrar_test_finalizado_revierte_las_estadisticas_agregadas(client, db, usuario_autenticado):
    # Bug real (24/08/2026): el test desaparecía de "Mis tests" pero
    # seguía contando en el resumen de progreso/análisis de rendimiento.
    sembrar_usuario_activo(db, "u1", plan="basico")
    actualizar_estadisticas_test(
        db, "u1", "AGE", aciertos=4, fallos=1, temas=["tema_01"], tiempo_en_segundos=50, blancos=0,
        rendimiento_temas={"tema_01": {"aciertos": 4, "fallos": 1, "blancos": 0}},
    )
    db.sembrar(("usuarios", "u1", "tests", "t1"), {
        "oposicion": "AGE", "estado": "finalizado", "aciertos": 4, "fallos": 1, "blancos": 0,
        "tiempo": 50, "resultado": "aprobado",
        "preguntas": [
            {"tema_id": "tema_01", "respuesta_usuario": "A", "acierto": True},
            {"tema_id": "tema_01", "respuesta_usuario": "A", "acierto": True},
            {"tema_id": "tema_01", "respuesta_usuario": "A", "acierto": True},
            {"tema_id": "tema_01", "respuesta_usuario": "A", "acierto": True},
            {"tema_id": "tema_01", "respuesta_usuario": "B", "acierto": False},
        ],
    })
    usuario_autenticado()
    resp = client.delete("/mi-test/t1", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    stats = db.leer(("usuarios", "u1"))["estadisticas"]["AGE"]
    assert stats["tests_realizados"] == 0
    assert stats["total_aciertos"] == 0
    assert stats["total_fallos"] == 0
    assert stats["rendimiento_por_tema"]["tema_01"] == {"aciertos": 0, "fallos": 0, "blancos": 0}


def test_borrar_test_en_progreso_no_toca_las_estadisticas(client, db, usuario_autenticado):
    # Un borrador "en_progreso" nunca llegó a sumarse a las estadísticas
    # (eso solo pasa al finalizar, ver actualizar_estadisticas_test) -- no
    # debe restarse nada al borrarlo.
    sembrar_usuario_activo(db, "u1", plan="basico")
    actualizar_estadisticas_test(db, "u1", "AGE", aciertos=3, fallos=0, temas=[], tiempo_en_segundos=20, blancos=0)
    db.sembrar(("usuarios", "u1", "tests", "t2"), {
        "oposicion": "AGE", "estado": "en_progreso", "num_preguntas": 10, "indice_actual": 3,
    })
    usuario_autenticado()
    resp = client.delete("/mi-test/t2", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    stats = db.leer(("usuarios", "u1"))["estadisticas"]["AGE"]
    assert stats["tests_realizados"] == 1
    assert stats["total_aciertos"] == 3


def test_borrar_test_en_progreso(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    db.sembrar(("usuarios", "u1", "tests", "t2"), {
        "oposicion": "AGE", "estado": "en_progreso", "num_preguntas": 10, "indice_actual": 3,
    })
    usuario_autenticado()
    resp = client.delete("/mi-test/t2", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    listado = client.get("/mis-tests?oposicion=AGE&estado=en_progreso", headers={"Authorization": "Bearer x"}).get_json()
    assert listado["tests"] == []


def test_borrar_test_de_otro_usuario_no_lo_afecta(client, db, usuario_autenticado):
    # El borrado vive bajo la subcolección del propio uid autenticado -- un
    # usuario no puede tocar el test de otro aunque conozca su id, porque la
    # ruta solo mira dentro de usuarios/{g.uid}/tests.
    sembrar_usuario_activo(db, "victima", plan="basico")
    db.sembrar(("usuarios", "victima", "tests", "t3"), {"oposicion": "AGE", "estado": "finalizado"})
    usuario_autenticado(uid="atacante", email="atacante@example.com")
    sembrar_usuario_activo(db, "atacante", plan="basico", email="atacante@example.com")
    resp = client.delete("/mi-test/t3", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200  # borra (si existe) bajo SU propia subcolección, no la ajena

    listado = client.get("/mis-tests?oposicion=AGE", headers={"Authorization": "Bearer x"}).get_json()
    assert listado["tests"] == []  # nunca tuvo ese test bajo su propio uid
