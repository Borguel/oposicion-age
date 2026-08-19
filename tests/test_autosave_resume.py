"""Pruebas del autoguardado y reanudación de tests (rutas_progreso.py):
que el primer autoguardado cree el borrador completo, que los siguientes
solo actualicen los campos que cambian (sin perder las preguntas ya
guardadas), y que un test "en_progreso" nunca se cuele como el último
test terminado."""

from conftest import sembrar_usuario_activo


def test_primer_autosave_crea_el_borrador_completo(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    resp = client.post("/autosave-test", json={
        "test_id": "t1",
        "oposicion": "AGE",
        "tipo": "personalizado",
        "temas": ["bloque_01-tema_01"],
        "contenido": [{"pregunta": "¿Qué es X?", "opciones": {"A": "1", "B": "2"}, "respuesta_correcta": "A"}],
        "respuestas_usuario": [None],
        "indice_actual": 0,
    }, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    guardado = db.leer(("usuarios", "u1", "tests", "t1"))
    assert guardado["estado"] == "en_progreso"
    assert guardado["num_preguntas"] == 1
    assert len(guardado["contenido"]) == 1


def test_autosave_posterior_no_borra_el_contenido_ya_guardado(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    preguntas = [{"pregunta": "¿Qué es X?", "opciones": {"A": "1", "B": "2"}, "respuesta_correcta": "A"}]
    client.post("/autosave-test", json={
        "test_id": "t1", "oposicion": "AGE", "contenido": preguntas,
        "respuestas_usuario": [None], "indice_actual": 0,
    }, headers={"Authorization": "Bearer x"})

    # Segundo autoguardado: ya sin "contenido" (como hace el frontend en
    # cada respuesta/tick), solo cambian índice y respuestas.
    resp = client.post("/autosave-test", json={
        "test_id": "t1", "respuestas_usuario": ["A"], "indice_actual": 1,
    }, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    guardado = db.leer(("usuarios", "u1", "tests", "t1"))
    assert guardado["contenido"] == preguntas
    assert guardado["indice_actual"] == 1
    assert guardado["respuestas_usuario"] == ["A"]
    assert guardado["estado"] == "en_progreso"


def test_autosave_corrige_documento_id_en_un_guardado_posterior(client, db, usuario_autenticado):
    # Bug real: con el arranque temprano de un test grande desde PDF, el
    # borrador se crea con documento_id=None (todavía no se conoce el
    # real, que solo llega en el evento SSE "fin") y se quedaba así para
    # siempre -- "Mis documentos" nunca podía ofrecer "Continuar" para ese
    # documento. Un autoguardado posterior que SÍ incluya documento_id
    # debe poder corregirlo.
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    preguntas = [{"pregunta": "¿Qué es X?", "opciones": {"A": "1", "B": "2"}, "respuesta_correcta": "A"}]
    client.post("/autosave-test", json={
        "test_id": "t1", "oposicion": "AGE", "tipo": "test_pdf", "contenido": preguntas,
        "respuestas_usuario": [None], "indice_actual": 0, "documento_id": None,
    }, headers={"Authorization": "Bearer x"})
    assert db.leer(("usuarios", "u1", "tests", "t1")).get("documento_id") is None

    resp = client.post("/autosave-test", json={
        "test_id": "t1", "respuestas_usuario": ["A"], "indice_actual": 1, "documento_id": "doc123",
    }, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    guardado = db.leer(("usuarios", "u1", "tests", "t1"))
    assert guardado["documento_id"] == "doc123"
    assert guardado["contenido"] == preguntas  # no se pierde por la corrección


def test_autosave_sin_documento_id_no_borra_el_ya_guardado(client, db, usuario_autenticado):
    # Los autoguardados de cada respuesta/tick nunca mandan documento_id
    # (ver frontend/subida-pdf-generar-test/script.js, autoguardarProgreso)
    # -- no debe interpretarse como "ponlo a nulo".
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    preguntas = [{"pregunta": "¿Qué es X?", "opciones": {"A": "1", "B": "2"}, "respuesta_correcta": "A"}]
    client.post("/autosave-test", json={
        "test_id": "t1", "oposicion": "AGE", "tipo": "test_pdf", "contenido": preguntas,
        "respuestas_usuario": [None], "indice_actual": 0, "documento_id": "doc123",
    }, headers={"Authorization": "Bearer x"})

    client.post("/autosave-test", json={
        "test_id": "t1", "respuestas_usuario": ["A"], "indice_actual": 1,
    }, headers={"Authorization": "Bearer x"})

    guardado = db.leer(("usuarios", "u1", "tests", "t1"))
    assert guardado["documento_id"] == "doc123"


def test_autosave_sin_test_id_devuelve_error(client, usuario_autenticado):
    usuario_autenticado(email_verified=True)
    resp = client.post("/autosave-test", json={}, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 400


def test_ultimo_test_ignora_los_que_estan_en_progreso(client, db, usuario_autenticado):
    db.sembrar(("usuarios", "u1", "tests", "borrador"), {
        "oposicion": "AGE", "estado": "en_progreso", "fecha": "2026-01-02T00:00:00",
        "preguntas": [{"pregunta": "sin terminar"}],
    })
    db.sembrar(("usuarios", "u1", "tests", "terminado"), {
        "oposicion": "AGE", "estado": "finalizado", "fecha": "2026-01-01T00:00:00",
        "preguntas": [{"pregunta": "ya terminado"}],
    })
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    resp = client.get("/ultimo-test?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert resp.get_json()["test"] == [{"pregunta": "ya terminado"}]


def test_ultimo_test_devuelve_404_si_solo_hay_borradores(client, db, usuario_autenticado):
    db.sembrar(("usuarios", "u1", "tests", "borrador"), {
        "oposicion": "AGE", "estado": "en_progreso", "fecha": "2026-01-02T00:00:00",
        "preguntas": [{"pregunta": "sin terminar"}],
    })
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    resp = client.get("/ultimo-test?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 404
