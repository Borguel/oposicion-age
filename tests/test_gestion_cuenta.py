"""Pruebas de exportación y borrado de cuenta (gestion_cuenta.py + rutas de
blueprints/pagos.py): que la exportación incluya todo lo del usuario, y que
borrar la cuenta cancele Stripe, borre subcolecciones y la cuenta de auth."""
from unittest.mock import patch, MagicMock

from gestion_cuenta import exportar_datos_usuario, eliminar_cuenta_usuario


def _con_sesion(cliente, uid="u1", email="u1@example.com"):
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email})
    parche.start()
    return parche


def test_exportar_datos_incluye_perfil_y_subcolecciones(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "nombre": "Ana"})
    db.sembrar(("usuarios", "u1", "tests", "t1"), {"tipo": "oficial"})
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Tema 1"})

    datos = exportar_datos_usuario(db, "u1")

    assert datos["perfil"]["nombre"] == "Ana"
    assert datos["tests"] == [{"id": "t1", "tipo": "oficial"}]
    assert datos["documentos"] == [{"id": "d1", "titulo": "Tema 1"}]
    assert datos["esquemas_pdf"] == []


def test_eliminar_cuenta_borra_subcolecciones_y_documento(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    db.sembrar(("usuarios", "u1", "tests", "t1"), {"tipo": "oficial"})
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Tema 1"})

    with patch("gestion_cuenta.firebase_auth.delete_user") as mock_delete_user:
        eliminar_cuenta_usuario(db, "u1")
        mock_delete_user.assert_called_once_with("u1")

    assert db.leer(("usuarios", "u1")) is None
    assert db.leer(("usuarios", "u1", "tests", "t1")) is None
    assert db.leer(("usuarios", "u1", "documentos", "d1")) is None


def test_eliminar_cuenta_cancela_suscripciones_de_stripe(db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"stripe_subscription_id": "sub_123"}}
    })

    with patch("gestion_cuenta.stripe.Subscription.delete") as mock_cancelar, \
         patch("gestion_cuenta.firebase_auth.delete_user"):
        eliminar_cuenta_usuario(db, "u1")
        mock_cancelar.assert_called_once_with("sub_123")


def test_eliminar_cuenta_no_falla_si_stripe_da_error(db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"stripe_subscription_id": "sub_123"}}
    })

    with patch("gestion_cuenta.stripe.Subscription.delete", side_effect=RuntimeError("stripe caído")), \
         patch("gestion_cuenta.firebase_auth.delete_user"):
        eliminar_cuenta_usuario(db, "u1")  # no debe lanzar

    assert db.leer(("usuarios", "u1")) is None


def test_ruta_exportar_datos(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "nombre": "Ana"})
    parche = _con_sesion(client)
    try:
        resp = client.get("/mi-cuenta/exportar-datos", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        assert resp.get_json()["perfil"]["nombre"] == "Ana"
    finally:
        parche.stop()


def test_ruta_eliminar_cuenta(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    parche = _con_sesion(client)
    try:
        with patch("gestion_cuenta.firebase_auth.delete_user"):
            resp = client.delete("/mi-cuenta", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        assert db.leer(("usuarios", "u1")) is None
    finally:
        parche.stop()
