"""Pruebas del autoguardado y reanudación de tests (rutas_progreso.py):
que el primer autoguardado cree el borrador completo, que los siguientes
solo actualicen los campos que cambian (sin perder las preguntas ya
guardadas), y que un test "en_progreso" nunca se cuele como el último
test terminado."""
from unittest.mock import patch


def _con_sesion(cliente, uid="u1", email="u1@example.com"):
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email})
    parche.start()
    return parche


def test_primer_autosave_crea_el_borrador_completo(client, db):
    parche = _con_sesion(client)
    try:
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
    finally:
        parche.stop()


def test_autosave_posterior_no_borra_el_contenido_ya_guardado(client, db):
    parche = _con_sesion(client)
    try:
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
    finally:
        parche.stop()


def test_autosave_sin_test_id_devuelve_error(client):
    parche = _con_sesion(client)
    try:
        resp = client.post("/autosave-test", json={}, headers={"Authorization": "Bearer x"})
        assert resp.status_code == 400
    finally:
        parche.stop()


def test_ultimo_test_ignora_los_que_estan_en_progreso(client, db):
    db.sembrar(("usuarios", "u1", "tests", "borrador"), {
        "oposicion": "AGE", "estado": "en_progreso", "fecha": "2026-01-02T00:00:00",
        "preguntas": [{"pregunta": "sin terminar"}],
    })
    db.sembrar(("usuarios", "u1", "tests", "terminado"), {
        "oposicion": "AGE", "estado": "finalizado", "fecha": "2026-01-01T00:00:00",
        "preguntas": [{"pregunta": "ya terminado"}],
    })
    parche = _con_sesion(client)
    try:
        resp = client.get("/ultimo-test?oposicion=AGE", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        assert resp.get_json()["test"] == [{"pregunta": "ya terminado"}]
    finally:
        parche.stop()


def test_ultimo_test_devuelve_404_si_solo_hay_borradores(client, db):
    db.sembrar(("usuarios", "u1", "tests", "borrador"), {
        "oposicion": "AGE", "estado": "en_progreso", "fecha": "2026-01-02T00:00:00",
        "preguntas": [{"pregunta": "sin terminar"}],
    })
    parche = _con_sesion(client)
    try:
        resp = client.get("/ultimo-test?oposicion=AGE", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 404
    finally:
        parche.stop()
