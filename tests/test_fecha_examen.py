"""Pruebas de /fecha-examen: guardar, leer y borrar la fecha de examen que
el usuario configura para la cuenta atrás de Zona Opositor, siempre por
oposición (no debe mezclarse entre AGE y GACE)."""

from conftest import sembrar_usuario_activo


def test_guardar_y_leer_fecha_examen(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    usuario_autenticado()
    resp = client.post("/fecha-examen?oposicion=AGE", json={"fecha_examen": "2026-11-15"},
                        headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    resp = client.get("/fecha-examen?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert resp.get_json()["fecha_examen"] == "2026-11-15"


def test_fecha_examen_no_se_mezcla_entre_oposiciones(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico", fechas_examen={"AGE": "2026-11-15"}, suscripciones={
        "AGE": {"plan": "basico", "subscription_status": "active"},
        "GACE": {"plan": "basico", "subscription_status": "active"},
    })
    usuario_autenticado()
    resp = client.get("/fecha-examen?oposicion=GACE", headers={"Authorization": "Bearer x"})
    assert resp.get_json()["fecha_examen"] is None


def test_fecha_examen_vacia_la_borra(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico", fechas_examen={"AGE": "2026-11-15"})
    usuario_autenticado()
    resp = client.post("/fecha-examen?oposicion=AGE", json={"fecha_examen": ""},
                        headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    resp = client.get("/fecha-examen?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.get_json()["fecha_examen"] is None


def test_fecha_examen_formato_invalido_devuelve_error(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    usuario_autenticado()
    resp = client.post("/fecha-examen?oposicion=AGE", json={"fecha_examen": "15/11/2026"},
                        headers={"Authorization": "Bearer x"})
    assert resp.status_code == 400
