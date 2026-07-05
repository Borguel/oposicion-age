"""Pruebas de marcar/desmarcar preguntas como favoritas y de generar un
test a partir de ellas, siguiendo el mismo patrón de deduplicación por
hash que ya usa el banco de preguntas falladas."""
from unittest.mock import patch


def _con_sesion(cliente, uid="u1", email="u1@example.com"):
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email})
    parche.start()
    return parche


PREGUNTA = {
    "pregunta": "¿Qué es la Constitución?",
    "opciones": {"A": "Una ley", "B": "Un tratado"},
    "respuesta_correcta": "A",
    "explicacion": "Es la norma suprema.",
    "tema_id": "b1-t1",
}


def test_marcar_y_listar_favorita(client, db):
    db.sembrar(("usuarios", "u1"), {})
    parche = _con_sesion(client)
    try:
        resp = client.post("/marcar-favorita?oposicion=AGE", json={"pregunta": PREGUNTA},
                            headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200

        resp = client.get("/preguntas-favoritas?oposicion=AGE", headers={"Authorization": "Bearer x"})
        favoritas = resp.get_json()["favoritas"]
        assert len(favoritas) == 1
        assert favoritas[0]["pregunta"] == PREGUNTA["pregunta"]
    finally:
        parche.stop()


def test_marcar_dos_veces_no_duplica(client, db):
    db.sembrar(("usuarios", "u1"), {})
    parche = _con_sesion(client)
    try:
        client.post("/marcar-favorita?oposicion=AGE", json={"pregunta": PREGUNTA}, headers={"Authorization": "Bearer x"})
        client.post("/marcar-favorita?oposicion=AGE", json={"pregunta": PREGUNTA}, headers={"Authorization": "Bearer x"})

        resp = client.get("/preguntas-favoritas?oposicion=AGE", headers={"Authorization": "Bearer x"})
        assert len(resp.get_json()["favoritas"]) == 1
    finally:
        parche.stop()


def test_desmarcar_favorita(client, db):
    db.sembrar(("usuarios", "u1"), {})
    parche = _con_sesion(client)
    try:
        client.post("/marcar-favorita?oposicion=AGE", json={"pregunta": PREGUNTA}, headers={"Authorization": "Bearer x"})
        resp = client.post("/desmarcar-favorita?oposicion=AGE", json={"pregunta": PREGUNTA["pregunta"]},
                            headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200

        resp = client.get("/preguntas-favoritas?oposicion=AGE", headers={"Authorization": "Bearer x"})
        assert resp.get_json()["favoritas"] == []
    finally:
        parche.stop()


def test_favoritas_no_se_mezclan_entre_oposiciones(client, db):
    db.sembrar(("usuarios", "u1"), {})
    parche = _con_sesion(client)
    try:
        client.post("/marcar-favorita?oposicion=AGE", json={"pregunta": PREGUNTA}, headers={"Authorization": "Bearer x"})
        resp = client.get("/preguntas-favoritas?oposicion=GACE", headers={"Authorization": "Bearer x"})
        assert resp.get_json()["favoritas"] == []
    finally:
        parche.stop()


def test_generar_test_favoritas_filtra_por_tema(client, db):
    db.sembrar(("usuarios", "u1"), {})
    parche = _con_sesion(client)
    try:
        client.post("/marcar-favorita?oposicion=AGE", json={"pregunta": PREGUNTA}, headers={"Authorization": "Bearer x"})
        otra = dict(PREGUNTA, pregunta="¿Otra pregunta?", tema_id="b1-t2")
        client.post("/marcar-favorita?oposicion=AGE", json={"pregunta": otra}, headers={"Authorization": "Bearer x"})

        resp = client.post("/generar-test-favoritas?oposicion=AGE",
                            json={"num_preguntas": 10, "temas": ["b1-t1"]},
                            headers={"Authorization": "Bearer x"})
        datos = resp.get_json()
        assert datos["total_disponibles"] == 1
        assert datos["test"][0]["tema_id"] == "b1-t1"
    finally:
        parche.stop()


def test_generar_test_favoritas_sin_favoritas_avisa(client, db):
    db.sembrar(("usuarios", "u1"), {})
    parche = _con_sesion(client)
    try:
        resp = client.post("/generar-test-favoritas?oposicion=AGE", json={"num_preguntas": 10},
                            headers={"Authorization": "Bearer x"})
        datos = resp.get_json()
        assert datos["total_disponibles"] == 0
        assert "favoritas" in datos["mensaje"]
    finally:
        parche.stop()
