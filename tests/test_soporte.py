"""Pruebas del mensaje de soporte/contacto desde Mi Cuenta:
POST /mi-cuenta/contactar (blueprints/pagos.py) y su revisión en el panel
admin, reusando el permiso "reportes" (blueprints/admin.py)."""
from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def _como(admin=True, uid="admin1", email="admin@example.com", permisos=None):
    decoded = {"uid": uid, "email": email}
    if admin:
        decoded["admin"] = True
    if permisos:
        decoded["permisos"] = permisos
    with patch("auth_utils.firebase_auth.verify_id_token", return_value=decoded):
        yield


_AUTH = {"Authorization": "Bearer x"}


def test_contactar_sin_login_401(client, db):
    r = client.post("/mi-cuenta/contactar", json={"mensaje": "Hola"})
    assert r.status_code == 401


def test_contactar_mensaje_vacio_400(client, db):
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "u1@x.com"}):
        r = client.post("/mi-cuenta/contactar", json={"mensaje": "   "}, headers=_AUTH)
    assert r.status_code == 400


def test_contactar_guarda_mensaje_pendiente(client, db):
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "u1@x.com"}):
        r = client.post("/mi-cuenta/contactar", json={"mensaje": "Tengo un problema con mi factura"}, headers=_AUTH)
    assert r.status_code == 201
    with _como():
        mensajes = client.get("/admin/api/soporte?estado=pendiente", headers=_AUTH).get_json()["mensajes"]
    assert len(mensajes) == 1
    assert mensajes[0]["mensaje"] == "Tengo un problema con mi factura"
    assert mensajes[0]["email"] == "u1@x.com"
    assert mensajes[0]["estado"] == "pendiente"


def test_usuario_contacta_y_admin_lo_revisa(client, db):
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u2", "email": "u2@x.com"}):
        client.post("/mi-cuenta/contactar", json={"mensaje": "¿Cómo cambio de oposición?"}, headers=_AUTH)
    with _como():
        mensajes = client.get("/admin/api/soporte?estado=pendiente", headers=_AUTH).get_json()["mensajes"]
        assert len(mensajes) == 1
        mid = mensajes[0]["id"]
        client.patch(f"/admin/api/soporte/{mid}", json={"estado": "revisado"}, headers=_AUTH)
        pendientes = client.get("/admin/api/soporte?estado=pendiente", headers=_AUTH).get_json()["mensajes"]
        assert pendientes == []
        revisados = client.get("/admin/api/soporte?estado=revisado", headers=_AUTH).get_json()["mensajes"]
        assert len(revisados) == 1


def test_soporte_sin_permiso_reportes_403(client, db):
    with _como(admin=False, uid="mod1", permisos=["temario"]):
        assert client.get("/admin/api/soporte", headers=_AUTH).status_code == 403
        assert client.patch("/admin/api/soporte/x", json={"estado": "revisado"}, headers=_AUTH).status_code == 403


def test_soporte_con_permiso_reportes_accede(client, db):
    with _como(admin=False, uid="mod1", permisos=["reportes"]):
        assert client.get("/admin/api/soporte?estado=pendiente", headers=_AUTH).status_code == 200


def test_reportes_pendientes_suma_soporte_y_preguntas(client, db):
    db.sembrar(("reportes_preguntas", "r1"), {"estado": "pendiente"})
    db.sembrar(("mensajes_soporte", "s1"), {"estado": "pendiente"})
    db.sembrar(("mensajes_soporte", "s2"), {"estado": "revisado"})
    with _como():
        d = client.get("/admin/api/sistema", headers=_AUTH).get_json()
    assert d["diagnostico"]["reportes_pendientes"] == 2
