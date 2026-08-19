"""Pruebas de "marcar pregunta como duda": el usuario puede marcar una
pregunta durante el test para ver, al terminar, la nota que habría
sacado sin contarla. El array en curso (`marcadas_duda`, autoguardado) y
el flag final por pregunta (`marcada_duda`, en el test finalizado) deben
sobrevivir el mismo recorrido que ya prueba `marcadas_revision`."""

from conftest import sembrar_usuario_activo


def test_autosave_guarda_marcadas_duda(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    resp = client.post("/autosave-test", json={
        "test_id": "t1",
        "oposicion": "AGE",
        "contenido": [
            {"pregunta": "¿Qué es X?", "opciones": {"A": "1", "B": "2"}, "respuesta_correcta": "A"},
            {"pregunta": "¿Qué es Y?", "opciones": {"A": "1", "B": "2"}, "respuesta_correcta": "B"},
        ],
        "respuestas_usuario": ["A", None],
        "marcadas_duda": [False, True],
        "indice_actual": 1,
    }, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    guardado = db.leer(("usuarios", "u1", "tests", "t1"))
    assert guardado["marcadas_duda"] == [False, True]


def test_autosave_sin_marcadas_duda_por_defecto_vacio(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    resp = client.post("/autosave-test", json={
        "test_id": "t1",
        "contenido": [{"pregunta": "¿Qué es X?", "opciones": {"A": "1"}, "respuesta_correcta": "A"}],
        "respuestas_usuario": [None],
        "indice_actual": 0,
    }, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    guardado = db.leer(("usuarios", "u1", "tests", "t1"))
    assert guardado["marcadas_duda"] == []


def test_guardar_test_persiste_marcada_duda_por_pregunta(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    contenido = [
        {"pregunta": "¿Uno?", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
        {"pregunta": "¿Dos?", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
        {"pregunta": "¿Tres?", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
    ]
    respuestas = ["A", "B", None]
    usuario_autenticado(email_verified=True)
    resp = client.post("/guardar-test?oposicion=AGE", json={
        "test_id": "t1",
        "contenido": contenido,
        "respuestas": respuestas,
        "metadatos": {"tipo": "personalizado", "tiempo": 0},
        "marcadas_duda": [False, True, False],
    }, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    guardado = db.leer(("usuarios", "u1", "tests", "t1"))
    assert [p["marcada_duda"] for p in guardado["preguntas"]] == [False, True, False]


def test_guardar_test_sin_marcadas_duda_por_defecto_false(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    contenido = [
        {"pregunta": "¿Uno?", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
        {"pregunta": "¿Dos?", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
    ]
    usuario_autenticado(email_verified=True)
    resp = client.post("/guardar-test?oposicion=AGE", json={
        "test_id": "t2",
        "contenido": contenido,
        "respuestas": ["A", "A"],
        "metadatos": {"tipo": "personalizado", "tiempo": 0},
    }, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    guardado = db.leer(("usuarios", "u1", "tests", "t2"))
    assert [p["marcada_duda"] for p in guardado["preguntas"]] == [False, False]


def test_mi_test_devuelve_marcada_duda_de_preguntas_ya_guardadas(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    db.sembrar(("usuarios", "u1", "tests", "t3"), {
        "oposicion": "AGE", "estado": "finalizado",
        "preguntas": [
            {"pregunta": "x", "marcada_duda": True},
            {"pregunta": "y", "marcada_duda": False},
        ],
    })
    usuario_autenticado(email_verified=True)
    resp = client.get("/mi-test/t3", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    preguntas = resp.get_json()["test"]["preguntas"]
    assert [p["marcada_duda"] for p in preguntas] == [True, False]


def test_guardar_test_excluye_dudas_de_la_nota_final(client, db, usuario_autenticado):
    # Sin marcar duda: 1 acierto, 1 fallo, 1 blanco -> nota 2.23/10,
    # suspendido. Marcando como duda la pregunta fallada (la 2ª), esa
    # pregunta no debe contar ni como fallo ni en el total: queda 1 acierto
    # y 1 blanco sobre 2 preguntas -> nota 5.0/10, aprobado.
    sembrar_usuario_activo(db, "u1", plan="basico")
    contenido = [
        {"pregunta": "¿Uno?", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
        {"pregunta": "¿Dos?", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
        {"pregunta": "¿Tres?", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
    ]
    respuestas = ["A", "B", None]
    usuario_autenticado(email_verified=True)
    resp = client.post("/guardar-test?oposicion=AGE", json={
        "test_id": "t1",
        "contenido": contenido,
        "respuestas": respuestas,
        "metadatos": {"tipo": "personalizado", "tiempo": 0},
        "marcadas_duda": [False, True, False],
    }, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    guardado = db.leer(("usuarios", "u1", "tests", "t1"))
    assert guardado["aciertos"] == 1
    assert guardado["fallos"] == 0
    assert guardado["blancos"] == 1
    assert guardado["resultado"] == "aprobado"


def test_guardar_test_si_se_marcan_todas_como_duda_se_cuentan_igual(client, db, usuario_autenticado):
    # Si se marcan TODAS las preguntas como duda no queda ninguna con la que
    # calcular una nota -- se cuentan todas igualmente en vez de guardar un
    # resultado vacío/sin sentido.
    sembrar_usuario_activo(db, "u1", plan="basico")
    contenido = [
        {"pregunta": "¿Uno?", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
        {"pregunta": "¿Dos?", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}},
    ]
    usuario_autenticado(email_verified=True)
    resp = client.post("/guardar-test?oposicion=AGE", json={
        "test_id": "t1",
        "contenido": contenido,
        "respuestas": ["A", "A"],
        "metadatos": {"tipo": "personalizado", "tiempo": 0},
        "marcadas_duda": [True, True],
    }, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    guardado = db.leer(("usuarios", "u1", "tests", "t1"))
    assert guardado["aciertos"] == 2
    assert guardado["fallos"] == 0
    assert guardado["resultado"] == "aprobado"


def test_mi_test_con_preguntas_antiguas_sin_marcada_duda_no_rompe(client, db, usuario_autenticado):
    # Tests guardados antes de esta función no tienen "marcada_duda" en sus
    # preguntas -- la ruta debe devolver el documento tal cual, sin fallar.
    sembrar_usuario_activo(db, "u1", plan="basico")
    db.sembrar(("usuarios", "u1", "tests", "t4"), {
        "oposicion": "AGE", "estado": "finalizado",
        "preguntas": [{"pregunta": "x"}, {"pregunta": "y"}],
    })
    usuario_autenticado(email_verified=True)
    resp = client.get("/mi-test/t4", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    preguntas = resp.get_json()["test"]["preguntas"]
    assert all("marcada_duda" not in p for p in preguntas)
