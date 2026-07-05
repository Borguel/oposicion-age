"""Prueba del endpoint /health: sin autenticación, y devuelve error si
Firestore falla en vez de dar un 200 falso."""
from unittest.mock import patch


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"estado": "ok"}


def test_health_sin_cabecera_de_autenticacion(client):
    # No manda Authorization -- a diferencia del resto de rutas, esto no
    # debe devolver 401.
    resp = client.get("/health")
    assert resp.status_code != 401


def test_health_devuelve_503_si_firestore_falla(client):
    with patch("app.db.collection", side_effect=RuntimeError("caído")):
        resp = client.get("/health")
        assert resp.status_code == 503
        assert resp.get_json() == {"estado": "error"}
