"""Pruebas de la clasificación anónima y opcional (blueprints/ranking.py):
que nadie aparezca sin haberse apuntado, que el alias se valide, y que
salir del ranking oculte al usuario sin borrarle la racha."""
from unittest.mock import patch

from conftest import sembrar_usuario_activo


def _con_sesion(cliente, uid="u1", email="u1@example.com"):
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email})
    parche.start()
    return parche


def test_ranking_vacio_si_nadie_se_ha_apuntado(client, db):
    sembrar_usuario_activo(db, "u1", plan="basico", racha={"racha_actual": 5})
    parche = _con_sesion(client)
    try:
        resp = client.get("/ranking", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        datos = resp.get_json()
        assert datos["ranking"] == []
        assert datos["total_participantes"] == 0
    finally:
        parche.stop()


def test_unirse_con_alias_invalido_devuelve_error(client):
    parche = _con_sesion(client)
    try:
        resp = client.post("/ranking/unirse", json={"alias": "ab"}, headers={"Authorization": "Bearer x"})
        assert resp.status_code == 400
    finally:
        parche.stop()


def test_unirse_aparece_en_el_ranking_con_alias_no_con_email(client, db):
    parche = _con_sesion(client)
    try:
        resp = client.post("/ranking/unirse", json={"alias": "Opositor Anónimo"}, headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200

        resp = client.get("/ranking/mi-estado", headers={"Authorization": "Bearer x"})
        assert resp.get_json() == {"participa": True, "alias": "Opositor Anónimo"}

        resp = client.get("/ranking", headers={"Authorization": "Bearer x"})
        datos = resp.get_json()
        assert datos["ranking"] == [{"alias": "Opositor Anónimo", "racha_actual": 0, "tu": True}]
        assert "u1@example.com" not in str(datos)
    finally:
        parche.stop()


def test_ranking_ordenado_por_racha_actual_descendente(client, db):
    db.sembrar(("usuarios", "u2"), {"racha": {"racha_actual": 10}, "ranking_optin": True, "ranking_alias": "Rápido"})
    db.sembrar(("usuarios", "u3"), {"racha": {"racha_actual": 3}, "ranking_optin": True, "ranking_alias": "Lento"})
    parche = _con_sesion(client)
    try:
        resp = client.get("/ranking", headers={"Authorization": "Bearer x"})
        alias_en_orden = [p["alias"] for p in resp.get_json()["ranking"]]
        assert alias_en_orden == ["Rápido", "Lento"]
    finally:
        parche.stop()


def test_salir_del_ranking_lo_oculta_sin_borrar_la_racha(client, db):
    parche = _con_sesion(client)
    try:
        client.post("/ranking/unirse", json={"alias": "Temporal"}, headers={"Authorization": "Bearer x"})
        resp = client.post("/ranking/salir", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200

        resp = client.get("/ranking/mi-estado", headers={"Authorization": "Bearer x"})
        assert resp.get_json()["participa"] is False

        resp = client.get("/ranking", headers={"Authorization": "Bearer x"})
        assert resp.get_json()["ranking"] == []

        guardado = db.leer(("usuarios", "u1"))
        assert guardado["ranking_optin"] is False
    finally:
        parche.stop()
