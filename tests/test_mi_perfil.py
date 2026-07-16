"""Pruebas de /mi-perfil: en particular, que un administrador (custom
claim de Firebase) nunca vea el banner ni la pantalla de bloqueo de
prueba/plan en el frontend, aunque su cuenta no tenga ninguna
suscripción de pago -- mismo bypass que ya tiene requiere_plan() para
las rutas protegidas (ver auth_utils.py)."""
from unittest.mock import patch

from conftest import sembrar_usuario_activo


def _con_sesion(cliente, uid="u1", email="u1@example.com", admin=False):
    datos_token = {"uid": uid, "email": email}
    if admin:
        datos_token["admin"] = True
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value=datos_token)
    parche.start()
    return parche


def test_mi_perfil_usuario_normal_sin_plan_ni_prueba_da_gratis(client, db):
    db.sembrar(("usuarios", "u1"), {"suscripciones": {}})
    parche = _con_sesion(client)
    try:
        resp = client.get("/mi-perfil?oposicion=AGE", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        assert resp.get_json()["plan"] == "gratis"
    finally:
        parche.stop()


def test_mi_perfil_admin_sin_plan_ni_prueba_da_premium(client, db):
    db.sembrar(("usuarios", "adm"), {"suscripciones": {}})
    parche = _con_sesion(client, uid="adm", email="adm@example.com", admin=True)
    try:
        resp = client.get("/mi-perfil?oposicion=AGE", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        datos = resp.get_json()
        assert datos["plan"] == "premium"
        assert datos["subscription_status"] == "active"
    finally:
        parche.stop()


def test_mi_perfil_admin_sin_documento_de_usuario_da_premium(client, db):
    parche = _con_sesion(client, uid="fantasma_admin", email="fantasma@example.com", admin=True)
    try:
        resp = client.get("/mi-perfil?oposicion=AGE", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        assert resp.get_json()["plan"] == "premium"
    finally:
        parche.stop()


def test_mi_perfil_admin_con_plan_de_pago_sigue_dando_premium(client, db):
    sembrar_usuario_activo(db, "adm2", plan="premium", email="adm2@example.com")
    parche = _con_sesion(client, uid="adm2", email="adm2@example.com", admin=True)
    try:
        resp = client.get("/mi-perfil?oposicion=AGE", headers={"Authorization": "Bearer x"})
        assert resp.get_json()["plan"] == "premium"
    finally:
        parche.stop()
