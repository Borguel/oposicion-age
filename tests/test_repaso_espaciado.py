"""Pruebas del repaso espaciado aplicado a los tests generados desde el
banco de preguntas falladas y desde el banco de favoritas (ver
banco_fallos.ordenar_por_prioridad_repaso y
banco_favoritas.ordenar_por_prioridad_repaso): en vez de un muestreo
puramente aleatorio, deben priorizarse las preguntas que de verdad hace
falta repasar ya."""
from datetime import datetime, timedelta
from unittest.mock import patch

from banco_favoritas import _id_pregunta


def _con_sesion(cliente, uid="u1", email="u1@example.com"):
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email})
    parche.start()
    return parche


def _pregunta_base(texto, tema_id="b1-t1"):
    return {
        "oposicion": "AGE",
        "tema_id": tema_id,
        "pregunta": texto,
        "opciones": {"A": "x", "B": "y"},
        "respuesta_correcta": "A",
        "explicacion": "Explicación.",
    }


def test_generar_test_fallos_prioriza_la_mas_fallada(client, db):
    db.sembrar(("usuarios", "u1"), {})
    hace_poco = (datetime.utcnow() - timedelta(days=1)).isoformat()
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "poco_fallada"), dict(
        _pregunta_base("¿Poco fallada?"), veces_fallada=1, fecha_ultimo_fallo=hace_poco))
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "muy_fallada"), dict(
        _pregunta_base("¿Muy fallada?"), veces_fallada=5, fecha_ultimo_fallo=hace_poco))

    parche = _con_sesion(client)
    try:
        resp = client.post("/generar-test-fallos?oposicion=AGE", json={"num_preguntas": 1},
                            headers={"Authorization": "Bearer x"})
        datos = resp.get_json()
        assert datos["total_disponibles"] == 2
        assert datos["test"][0]["pregunta"] == "¿Muy fallada?"
    finally:
        parche.stop()


def test_generar_test_fallos_a_igualdad_prioriza_la_mas_antigua(client, db):
    db.sembrar(("usuarios", "u1"), {})
    hace_mucho = (datetime.utcnow() - timedelta(days=30)).isoformat()
    hace_poco = (datetime.utcnow() - timedelta(days=1)).isoformat()
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "reciente"), dict(
        _pregunta_base("¿Reciente?"), veces_fallada=2, fecha_ultimo_fallo=hace_poco))
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "antigua"), dict(
        _pregunta_base("¿Antigua?"), veces_fallada=2, fecha_ultimo_fallo=hace_mucho))

    parche = _con_sesion(client)
    try:
        resp = client.post("/generar-test-fallos?oposicion=AGE", json={"num_preguntas": 1},
                            headers={"Authorization": "Bearer x"})
        datos = resp.get_json()
        assert datos["test"][0]["pregunta"] == "¿Antigua?"
    finally:
        parche.stop()


def test_generar_test_favoritas_prioriza_la_nunca_repasada(client, db):
    db.sembrar(("usuarios", "u1"), {})
    hace_poco = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    db.sembrar(("usuarios", "u1", "preguntas_favoritas", _id_pregunta("AGE", "¿Ya repasada?")), dict(
        _pregunta_base("¿Ya repasada?"), fecha_marcada=hace_poco, fecha_ultimo_repaso=hace_poco))
    db.sembrar(("usuarios", "u1", "preguntas_favoritas", _id_pregunta("AGE", "¿Nunca repasada?")), dict(
        _pregunta_base("¿Nunca repasada?"), fecha_marcada=hace_poco))

    parche = _con_sesion(client)
    try:
        resp = client.post("/generar-test-favoritas?oposicion=AGE", json={"num_preguntas": 1},
                            headers={"Authorization": "Bearer x"})
        datos = resp.get_json()
        assert datos["total_disponibles"] == 2
        assert datos["test"][0]["pregunta"] == "¿Nunca repasada?"
    finally:
        parche.stop()


def test_preguntas_pendientes_repaso_cuenta_solo_la_oposicion_pedida(client, db):
    db.sembrar(("usuarios", "u1"), {})
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "age1"), _pregunta_base("¿AGE 1?", "b1-t1"))
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "age2"), _pregunta_base("¿AGE 2?", "b1-t1"))
    gace = dict(_pregunta_base("¿GACE 1?", "b1-t1"))
    gace["oposicion"] = "GACE"
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "gace1"), gace)

    parche = _con_sesion(client)
    try:
        resp = client.get("/preguntas-pendientes-repaso?oposicion=AGE", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        assert resp.get_json()["total_pendientes"] == 2

        resp_gace = client.get("/preguntas-pendientes-repaso?oposicion=GACE", headers={"Authorization": "Bearer x"})
        assert resp_gace.get_json()["total_pendientes"] == 1
    finally:
        parche.stop()


def test_preguntas_pendientes_repaso_requiere_login(client):
    resp = client.get("/preguntas-pendientes-repaso?oposicion=AGE")
    assert resp.status_code == 401


def test_generar_test_favoritas_marca_fecha_ultimo_repaso(client, db):
    db.sembrar(("usuarios", "u1"), {})
    doc_id = _id_pregunta("AGE", "¿Nunca repasada?")
    db.sembrar(("usuarios", "u1", "preguntas_favoritas", doc_id), _pregunta_base("¿Nunca repasada?"))

    parche = _con_sesion(client)
    try:
        resp = client.post("/generar-test-favoritas?oposicion=AGE", json={"num_preguntas": 1},
                            headers={"Authorization": "Bearer x"})
        assert resp.get_json()["total_disponibles"] == 1

        guardada = db.leer(("usuarios", "u1", "preguntas_favoritas", doc_id))
        assert guardada.get("fecha_ultimo_repaso")
    finally:
        parche.stop()
