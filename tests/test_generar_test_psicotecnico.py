"""Pruebas de /generar-test-psicotecnico: la prueba psicotécnica propia y
separada del temario (hoy, solo Metro -- ver
oposiciones.coleccion_psicotecnico). A diferencia de /generar-test-oficial,
no hay selección de temas ni checkbox de exclusión: cada prueba (verbal o
espacial) se sirve completa."""
from unittest.mock import patch


def _con_sesion(cliente, uid="u1", email="u1@example.com"):
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email})
    parche.start()
    return parche


def _pregunta_psico(numero, prueba, imagen=None):
    datos = {
        "tipo": "pregunta",
        "examen": "METRO 2023 - Prueba tipo examen, parte aptitudinal (Empleo Maquinistas)",
        "prueba": prueba,
        "numero": numero,
        "pregunta": f"Pregunta {numero}",
        "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"},
        "respuesta_correcta": "A",
        "explicacion": "porque sí",
    }
    if imagen:
        datos["imagen"] = imagen
    return datos


def _sembrar_usuario_metro(db, uid="u1"):
    db.sembrar(("usuarios", uid), {
        "email": f"{uid}@example.com",
        "suscripciones": {"METRO": {"plan": "basico", "subscription_status": "active"}}
    })


def test_ruta_generar_test_psicotecnico_devuelve_solo_la_prueba_pedida(client, db):
    for i in range(1, 26):
        db.sembrar(("psicotecnico_METRO", f"v{i:02d}"), _pregunta_psico(i, "verbal"))
    for i in range(26, 51):
        db.sembrar(("psicotecnico_METRO", f"e{i:02d}"), _pregunta_psico(i, "espacial", imagen=f"/assets/psicotecnico-metro/pregunta_{i}.png"))
    _sembrar_usuario_metro(db)
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/generar-test-psicotecnico",
            json={"oposicion": "METRO", "prueba": "verbal"},
            headers={"Authorization": "Bearer x"}
        )
        assert resp.status_code == 200
        test = resp.get_json()["test"]
        assert len(test) == 25
        assert all(p["numero"] <= 25 for p in test)
        # viene ordenado por número (1..25), como el examen real
        assert [p["numero"] for p in test] == list(range(1, 26))
        assert set(test[0]["opciones"].keys()) == {"A", "B", "C", "D"}
    finally:
        parche.stop()


def test_ruta_generar_test_psicotecnico_espacial_incluye_imagen(client, db):
    for i in range(26, 51):
        db.sembrar(("psicotecnico_METRO", f"e{i:02d}"), _pregunta_psico(i, "espacial", imagen=f"/assets/psicotecnico-metro/pregunta_{i}.png"))
    _sembrar_usuario_metro(db)
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/generar-test-psicotecnico",
            json={"oposicion": "METRO", "prueba": "espacial"},
            headers={"Authorization": "Bearer x"}
        )
        assert resp.status_code == 200
        test = resp.get_json()["test"]
        assert len(test) == 25
        assert test[0]["imagen"] == "/assets/psicotecnico-metro/pregunta_26.png"
    finally:
        parche.stop()


def test_ruta_generar_test_psicotecnico_prueba_invalida_400(client, db):
    _sembrar_usuario_metro(db)
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/generar-test-psicotecnico",
            json={"oposicion": "METRO", "prueba": "no-existe"},
            headers={"Authorization": "Bearer x"}
        )
        assert resp.status_code == 400
    finally:
        parche.stop()


def test_ruta_generar_test_psicotecnico_404_si_no_hay_preguntas_cargadas(client, db):
    _sembrar_usuario_metro(db)
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/generar-test-psicotecnico",
            json={"oposicion": "METRO", "prueba": "verbal"},
            headers={"Authorization": "Bearer x"}
        )
        assert resp.status_code == 404
        assert resp.get_json()["test"] == []
    finally:
        parche.stop()


def test_ruta_generar_test_psicotecnico_bloqueada_para_plan_gratis(client, db):
    db.sembrar(("psicotecnico_METRO", "v01"), _pregunta_psico(1, "verbal"))
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"METRO": {"plan": "gratis"}}
    })
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/generar-test-psicotecnico",
            json={"oposicion": "METRO", "prueba": "verbal"},
            headers={"Authorization": "Bearer x"}
        )
        assert resp.status_code == 403
    finally:
        parche.stop()


def test_ruta_generar_test_psicotecnico_registra_uso_en_preguntas(client, db):
    for i in range(1, 26):
        db.sembrar(("psicotecnico_METRO", f"v{i:02d}"), _pregunta_psico(i, "verbal"))
    _sembrar_usuario_metro(db)
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/generar-test-psicotecnico",
            json={"oposicion": "METRO", "prueba": "verbal"},
            headers={"Authorization": "Bearer x"}
        )
        assert resp.status_code == 200
        datos_usuario = db.leer(("usuarios", "u1"))
        assert datos_usuario["limites_uso"]["test_oficial"]["contador"] == 25
    finally:
        parche.stop()
