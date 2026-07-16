"""Pruebas de /fecha-examen: guardar, leer y borrar la fecha de examen que
el usuario configura para la cuenta atrás de Zona Opositor, siempre por
oposición (no debe mezclarse entre AGE y GACE)."""
from unittest.mock import patch

from conftest import sembrar_usuario_activo


def _con_sesion(cliente, uid="u1", email="u1@example.com"):
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email})
    parche.start()
    return parche


def test_guardar_y_leer_fecha_examen(client, db):
    sembrar_usuario_activo(db, "u1", plan="basico")
    parche = _con_sesion(client)
    try:
        resp = client.post("/fecha-examen?oposicion=AGE", json={"fecha_examen": "2026-11-15"},
                            headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200

        resp = client.get("/fecha-examen?oposicion=AGE", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        assert resp.get_json()["fecha_examen"] == "2026-11-15"
    finally:
        parche.stop()


def test_fecha_examen_no_se_mezcla_entre_oposiciones(client, db):
    sembrar_usuario_activo(db, "u1", plan="basico", fechas_examen={"AGE": "2026-11-15"}, suscripciones={
        "AGE": {"plan": "basico", "subscription_status": "active"},
        "GACE": {"plan": "basico", "subscription_status": "active"},
    })
    parche = _con_sesion(client)
    try:
        resp = client.get("/fecha-examen?oposicion=GACE", headers={"Authorization": "Bearer x"})
        assert resp.get_json()["fecha_examen"] is None
    finally:
        parche.stop()


def test_fecha_examen_vacia_la_borra(client, db):
    sembrar_usuario_activo(db, "u1", plan="basico", fechas_examen={"AGE": "2026-11-15"})
    parche = _con_sesion(client)
    try:
        resp = client.post("/fecha-examen?oposicion=AGE", json={"fecha_examen": ""},
                            headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200

        resp = client.get("/fecha-examen?oposicion=AGE", headers={"Authorization": "Bearer x"})
        assert resp.get_json()["fecha_examen"] is None
    finally:
        parche.stop()


def test_fecha_examen_formato_invalido_devuelve_error(client, db):
    sembrar_usuario_activo(db, "u1", plan="basico")
    parche = _con_sesion(client)
    try:
        resp = client.post("/fecha-examen?oposicion=AGE", json={"fecha_examen": "15/11/2026"},
                            headers={"Authorization": "Bearer x"})
        assert resp.status_code == 400
    finally:
        parche.stop()
