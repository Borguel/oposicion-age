"""Pruebas de exportación y borrado de cuenta (gestion_cuenta.py + rutas de
blueprints/pagos.py): que la exportación incluya todo lo del usuario, y que
borrar la cuenta cancele Stripe, borre subcolecciones y la cuenta de auth."""
import os
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


def test_eliminar_cuenta_borra_firebase_auth_antes_que_firestore(db):
    # Si el borrado de Firebase Auth falla por algo que no sea "ya no
    # existe", los datos de Firestore deben seguir intactos para poder
    # reintentar sin dejar una cuenta de Auth huérfana con datos perdidos.
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    db.sembrar(("usuarios", "u1", "tests", "t1"), {"tipo": "oficial"})

    with patch("gestion_cuenta.firebase_auth.delete_user", side_effect=RuntimeError("red caída")):
        try:
            eliminar_cuenta_usuario(db, "u1")
        except RuntimeError:
            pass

    assert db.leer(("usuarios", "u1")) is not None
    assert db.leer(("usuarios", "u1", "tests", "t1")) is not None


def test_exportar_datos_incluye_conversaciones_de_tu_tutor(db):
    # Las conversaciones de Tu Tutor cuelgan de conversaciones_IA/{uid}/conversaciones,
    # NO de usuarios/{uid}/conversaciones (ver chat_controller.py: crear_conversacion).
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    db.sembrar(("conversaciones_IA", "u1", "conversaciones", "c1"), {"titulo": "Duda sobre el TREBEP"})

    datos = exportar_datos_usuario(db, "u1")

    assert datos["conversaciones"] == [{"id": "c1", "titulo": "Duda sobre el TREBEP"}]


def test_eliminar_cuenta_borra_conversaciones_de_tu_tutor(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    db.sembrar(("conversaciones_IA", "u1", "conversaciones", "c1"), {"titulo": "Duda sobre el TREBEP"})

    with patch("gestion_cuenta.firebase_auth.delete_user"):
        eliminar_cuenta_usuario(db, "u1")

    assert db.leer(("conversaciones_IA", "u1", "conversaciones", "c1")) is None
    assert db.leer(("conversaciones_IA", "u1")) is None


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


def test_eliminar_cuenta_avisa_por_email_si_stripe_da_error(db):
    # Sin este aviso, una suscripción que Stripe no pudo cancelar podía
    # seguir cobrando indefinidamente a una cuenta ya borrada, sin que
    # nadie se enterase hasta un impago meses después.
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"stripe_subscription_id": "sub_123"}}
    })

    with patch("gestion_cuenta.stripe.Subscription.delete", side_effect=RuntimeError("stripe caído")), \
         patch("gestion_cuenta.firebase_auth.delete_user"), \
         patch("gestion_cuenta.enviar_email_alerta_cancelacion_stripe_fallida") as mock_alerta:
        eliminar_cuenta_usuario(db, "u1")

    mock_alerta.assert_called_once_with(os.environ.get("BREVO_FROM_EMAIL"), "u1", "sub_123")


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
