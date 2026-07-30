"""Pruebas del catálogo de carpetas de Mis Documentos (documentos_pdf.py +
rutas de blueprints/pdf_ia.py): crear una carpeta debe hacerla aparecer
aunque no tenga documentos dentro todavía, y borrarla debe dejar "sin
carpeta" a los documentos que tuviera en vez de borrarlos."""
from unittest.mock import patch

from documentos_pdf import listar_carpetas, crear_carpeta, eliminar_carpeta


def _con_sesion(cliente, uid="u1", email="u1@example.com"):
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email, "email_verified": True})
    parche.start()
    return parche


def test_carpeta_recien_creada_aparece_vacia(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    crear_carpeta(db, "u1", "Tema 1")
    assert listar_carpetas(db, "u1") == ["Tema 1"]


def test_crear_carpeta_con_nombre_vacio_no_hace_nada(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    resultado = crear_carpeta(db, "u1", "   ")
    assert resultado is None
    assert listar_carpetas(db, "u1") == []


def test_listar_carpetas_incluye_las_ya_usadas_por_documentos_antiguos(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"carpeta": "Carpeta antigua"})
    assert listar_carpetas(db, "u1") == ["Carpeta antigua"]


def test_eliminar_carpeta_deja_sin_carpeta_los_documentos_dentro(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "carpetas_documentos": ["Tema 1"]})
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"carpeta": "Tema 1"})
    eliminar_carpeta(db, "u1", "Tema 1")
    assert listar_carpetas(db, "u1") == []
    assert db.leer(("usuarios", "u1", "documentos", "d1"))["carpeta"] == ""


def test_ruta_crear_carpeta_devuelve_error_si_esta_vacio(client):
    parche = _con_sesion(client)
    try:
        resp = client.post("/carpetas-documentos", json={"nombre": ""}, headers={"Authorization": "Bearer x"})
        assert resp.status_code == 400
    finally:
        parche.stop()


def test_ruta_crear_y_ver_carpeta_en_mis_documentos(client, db):
    parche = _con_sesion(client)
    try:
        resp = client.post("/carpetas-documentos", json={"nombre": "Constitución"}, headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        assert resp.get_json()["nombre"] == "Constitución"

        resp = client.get("/mis-documentos", headers={"Authorization": "Bearer x"})
        assert resp.get_json()["carpetas"] == ["Constitución"]
    finally:
        parche.stop()


def test_ruta_eliminar_carpeta(client, db):
    parche = _con_sesion(client)
    try:
        client.post("/carpetas-documentos", json={"nombre": "Temporal"}, headers={"Authorization": "Bearer x"})
        resp = client.delete("/carpetas-documentos", json={"nombre": "Temporal"}, headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200

        resp = client.get("/mis-documentos", headers={"Authorization": "Bearer x"})
        assert resp.get_json()["carpetas"] == []
    finally:
        parche.stop()
