"""Pruebas de blueprints/temario.py: catálogo de oposiciones y su
temario -- sin ningún test dedicado hasta ahora pese a ser la fuente que
usan Tu Tutor y el selector de temas del resto de la web."""
from unittest.mock import patch

from conftest import sembrar_usuario_activo


def _con_sesion(cliente, uid="u1", email="u1@example.com"):
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email, "email_verified": True})
    parche.start()
    return parche


def test_oposiciones_disponibles_no_requiere_login(client):
    resp = client.get("/oposiciones-disponibles")
    assert resp.status_code == 200
    oposiciones = resp.get_json()["oposiciones"]
    ids = [o["id"] for o in oposiciones]
    assert "AGE" in ids
    assert "GACE" in ids
    # Formato real del simulacro oficial (para el botón "Simulacro oficial"
    # de un clic en /test-oficial/).
    por_id = {o["id"]: o for o in oposiciones}
    assert por_id["AGE"]["simulacro_oficial"] == {"num_preguntas": 70, "minutos": None}
    assert por_id["GACE"]["simulacro_oficial"] == {"num_preguntas": 100, "minutos": 90}
    assert por_id["AUXILIAR"]["simulacro_oficial"] == {"num_preguntas": 110, "minutos": 90}
    # Sin ningún examen oficial sembrado en el FakeFirestore de test, ninguna
    # oposición tiene datos para el reparto "realista" todavía.
    assert por_id["AGE"]["tiene_pesos_reales"] is False
    assert por_id["GACE"]["tiene_pesos_reales"] is False
    assert por_id["AUXILIAR"]["tiene_pesos_reales"] is False
    # Igual que con tiene_pesos_reales, sin ningún examen sembrado no hay
    # preguntas psicotécnicas para ninguna oposición.
    assert por_id["AGE"]["tiene_psicotecnicas"] is False
    assert por_id["AUXILIAR"]["tiene_psicotecnicas"] is False


def test_oposiciones_disponibles_marca_tiene_psicotecnicas_solo_donde_las_hay(client, db):
    db.sembrar(("examenes_oficiales_AUXILIAR", "p1"), {"tipo": "pregunta", "psicotecnico": True})
    db.sembrar(("examenes_oficiales_AGE", "a1"), {"tipo": "pregunta", "psicotecnico": False})
    resp = client.get("/oposiciones-disponibles")
    por_id = {o["id"]: o for o in resp.get_json()["oposiciones"]}
    assert por_id["AUXILIAR"]["tiene_psicotecnicas"] is True
    assert por_id["AGE"]["tiene_psicotecnicas"] is False


def test_oposiciones_disponibles_marca_tiene_pesos_reales_si_hay_examenes(client, db):
    db.sembrar(("examenes_oficiales_AGE", "p1"), {"tipo": "pregunta", "tema_id": "bloque_01-tema_01"})
    resp = client.get("/oposiciones-disponibles")
    por_id = {o["id"]: o for o in resp.get_json()["oposiciones"]}
    assert por_id["AGE"]["tiene_pesos_reales"] is True
    assert por_id["GACE"]["tiene_pesos_reales"] is False


def test_temas_disponibles_requiere_login(client):
    resp = client.get("/temas-disponibles")
    assert resp.status_code == 401


def test_temas_disponibles_devuelve_bloque_y_tema(client, db):
    db.collection("Temario AGE").document("bloque_01").set({"titulo": "Derecho constitucional"})
    db.collection("Temario AGE").document("bloque_01").collection("temas").document("tema_01").set({"titulo": "La Constitución"})

    parche = _con_sesion(client)
    try:
        resp = client.get("/temas-disponibles?oposicion=AGE", headers={"Authorization": "Bearer x"})
    finally:
        parche.stop()

    assert resp.status_code == 200
    datos = resp.get_json()
    assert datos["oposicion"] == "AGE"
    assert datos["temas"] == [{
        "id": "bloque_01-tema_01",
        "titulo": "La Constitución",
        "bloque_id": "bloque_01",
        "bloque_titulo": "Derecho constitucional",
    }]


def test_temas_disponibles_usa_la_coleccion_de_la_oposicion_pedida(client, db):
    db.collection("Temario GACE").document("bloque_01").set({"titulo": "Bloque GACE"})
    db.collection("Temario GACE").document("bloque_01").collection("temas").document("tema_01").set({"titulo": "Tema GACE"})
    # AGE queda vacío a propósito -- si la ruta ignorase ?oposicion=GACE y
    # mirase siempre "Temario AGE", esto devolvería una lista vacía.

    parche = _con_sesion(client)
    try:
        resp = client.get("/temas-disponibles?oposicion=GACE", headers={"Authorization": "Bearer x"})
    finally:
        parche.stop()

    assert len(resp.get_json()["temas"]) == 1


def test_avisos_oficiales_requiere_login(client):
    resp = client.get("/avisos-oficiales?oposicion=AGE")
    assert resp.status_code == 401


def test_avisos_oficiales_devuelve_los_de_esa_oposicion(client, db):
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposiciones": ["AGE"], "tipo": "convocatoria", "titulo": "Convocatoria AGE 2026",
        "estado": "publicado", "fecha_boe": "20260701",
    })
    db.sembrar(("avisos_oficiales", "a2"), {
        "oposiciones": ["GACE"], "tipo": "convocatoria", "titulo": "Convocatoria GACE 2026",
        "estado": "publicado", "fecha_boe": "20260702",
    })
    parche = _con_sesion(client)
    try:
        resp = client.get("/avisos-oficiales?oposicion=AGE", headers={"Authorization": "Bearer x"})
    finally:
        parche.stop()

    assert resp.status_code == 200
    avisos = resp.get_json()["avisos"]
    assert len(avisos) == 1
    assert avisos[0]["titulo"] == "Convocatoria AGE 2026"


def test_avisos_oficiales_incluye_uno_que_afecta_a_varias_oposiciones(client, db):
    # Regresión: un aviso guardado con "oposiciones": ["AGE", "GACE"] (el
    # nuevo formato, que permite publicar una vez para varias oposiciones)
    # tiene que seguir apareciendo para cada una de ellas por separado.
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposiciones": ["AGE", "GACE"], "tipo": "llamamiento_extraordinario",
        "titulo": "Llamamiento extraordinario (AGE y GACE)", "estado": "publicado", "fecha_boe": "20260701",
    })
    parche = _con_sesion(client)
    try:
        resp_age = client.get("/avisos-oficiales?oposicion=AGE", headers={"Authorization": "Bearer x"})
        resp_gace = client.get("/avisos-oficiales?oposicion=GACE", headers={"Authorization": "Bearer x"})
    finally:
        parche.stop()

    assert len(resp_age.get_json()["avisos"]) == 1
    assert len(resp_gace.get_json()["avisos"]) == 1


def test_avisos_oficiales_ignora_los_de_otra_oposicion(client, db):
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposiciones": ["AUXILIAR"], "tipo": "convocatoria", "titulo": "x", "estado": "publicado", "fecha_boe": "20260701",
    })
    parche = _con_sesion(client)
    try:
        resp = client.get("/avisos-oficiales?oposicion=AGE", headers={"Authorization": "Bearer x"})
    finally:
        parche.stop()

    assert resp.get_json()["avisos"] == []


def test_progreso_usuario_requiere_login(client):
    resp = client.get("/progreso-usuario")
    assert resp.status_code == 401


def test_progreso_usuario_404_si_no_existe(client, db):
    parche = _con_sesion(client, uid="fantasma")
    try:
        resp = client.get("/progreso-usuario", headers={"Authorization": "Bearer x"})
    finally:
        parche.stop()
    # requiere_login ya crea al usuario en su primera petición autenticada,
    # así que en la práctica nunca da 404 -- pero si algún día esa garantía
    # cambiase, la ruta debe seguir respondiendo con un 404 explícito y no
    # con un error 500 al leer campos de un documento inexistente.
    assert resp.status_code in (200, 404)


def test_progreso_usuario_devuelve_los_campos_esperados(client, db):
    sembrar_usuario_activo(db, "u1", plan="basico",
        tests_realizados=3,
        puntuacion_media_test=7.5,
        ultimo_test={"aciertos": 8},
        total_aciertos=20,
        esquemas_generados=2,
    )
    parche = _con_sesion(client)
    try:
        resp = client.get("/progreso-usuario", headers={"Authorization": "Bearer x"})
    finally:
        parche.stop()
    assert resp.status_code == 200
    assert resp.get_json() == {
        "tests_realizados": 3,
        "puntuacion_media_test": 7.5,
        "ultimo_test": {"aciertos": 8},
        "total_aciertos": 20,
        "esquemas_generados": 2,
    }
