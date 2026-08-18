"""Borrado de tests propios (finalizados y en progreso) desde Mis Tests."""

from conftest import sembrar_usuario_activo


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
