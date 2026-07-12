"""Pruebas de las rutas que crean sesiones de pago en Stripe
(/crear-sesion-checkout, /crear-sesion-portal): la parte de la web que
mueve dinero real, y hasta ahora la única sin ninguna prueba automática
(el webhook que sí las tiene está en test_webhook_stripe.py). Se mockean
las llamadas reales a la API de Stripe -- lo que se prueba es la lógica
propia (validación, creación/reuso de customer, propagación de errores),
no el SDK de Stripe en sí."""
from unittest.mock import MagicMock, patch


def _con_sesion(cliente, uid="u1", email="u1@example.com"):
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email})
    parche.start()
    return parche


def test_crear_sesion_checkout_exige_login(client):
    resp = client.post("/crear-sesion-checkout", json={"plan": "basico"})
    assert resp.status_code == 401


def test_crear_sesion_checkout_rechaza_oposicion_no_valida(client, db):
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/crear-sesion-checkout",
            json={"plan": "basico", "oposicion": "NO_EXISTE"},
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 400
        assert "no válida" in resp.get_json()["error"].lower()
    finally:
        parche.stop()


def test_crear_sesion_checkout_rechaza_plan_no_valido(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/crear-sesion-checkout",
            json={"plan": "no_existe", "oposicion": "AGE"},
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 400
        assert "plan" in resp.get_json()["error"].lower()
    finally:
        parche.stop()


def test_crear_sesion_checkout_crea_customer_nuevo_y_guarda_su_id(client, db):
    # Usuario sin stripe_customer_id todavía -- debe crear un Customer nuevo
    # en Stripe y guardar su id antes de crear la sesión de checkout.
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    parche = _con_sesion(client)
    mock_customer = MagicMock(id="cus_nuevo_1")
    mock_session = MagicMock(url="https://checkout.stripe.com/nueva")
    try:
        with patch("blueprints.pagos.stripe.Customer.create", return_value=mock_customer) as mock_crear_customer, \
             patch("blueprints.pagos.stripe.checkout.Session.create", return_value=mock_session) as mock_crear_sesion:
            resp = client.post(
                "/crear-sesion-checkout",
                json={"plan": "basico", "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"},
            )
        assert resp.status_code == 200
        assert resp.get_json()["url"] == "https://checkout.stripe.com/nueva"
        mock_crear_customer.assert_called_once_with(email="u1@example.com", metadata={"uid": "u1"})
        # stripe_customer_id es un campo de nivel superior del usuario (se
        # comparte entre todas sus oposiciones, aunque cada una tenga su
        # propia suscripción -- ver registro_progreso_usuario.actualizar_suscripcion).
        assert db.leer(("usuarios", "u1"))["stripe_customer_id"] == "cus_nuevo_1"

        # La sesión de checkout se crea con ese customer, en modo suscripción,
        # con el price_id correcto y la metadata (uid/plan/oposicion) tanto en
        # la propia sesión como en subscription_data -- lo que el webhook
        # necesita luego para reconciliar el evento.
        _, kwargs = mock_crear_sesion.call_args
        assert kwargs["mode"] == "subscription"
        assert kwargs["customer"] == "cus_nuevo_1"
        assert kwargs["line_items"] == [{"price": "price_basico_test", "quantity": 1}]
        assert kwargs["client_reference_id"] == "u1"
        assert kwargs["metadata"] == {"uid": "u1", "plan": "basico", "oposicion": "AGE"}
        assert kwargs["subscription_data"] == {"metadata": {"uid": "u1", "plan": "basico", "oposicion": "AGE"}}
    finally:
        parche.stop()


def test_crear_sesion_checkout_reusa_customer_existente(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "stripe_customer_id": "cus_existente_1"})
    parche = _con_sesion(client)
    mock_session = MagicMock(url="https://checkout.stripe.com/existente")
    try:
        with patch("blueprints.pagos.stripe.Customer.create") as mock_crear_customer, \
             patch("blueprints.pagos.stripe.checkout.Session.create", return_value=mock_session) as mock_crear_sesion:
            resp = client.post(
                "/crear-sesion-checkout",
                json={"plan": "premium", "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"},
            )
        assert resp.status_code == 200
        mock_crear_customer.assert_not_called()
        _, kwargs = mock_crear_sesion.call_args
        assert kwargs["customer"] == "cus_existente_1"
        assert kwargs["line_items"] == [{"price": "price_premium_test", "quantity": 1}]
    finally:
        parche.stop()


def test_crear_sesion_checkout_usa_oposicion_por_defecto_si_no_se_manda(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "stripe_customer_id": "cus_existente_1"})
    parche = _con_sesion(client)
    mock_session = MagicMock(url="https://checkout.stripe.com/x")
    try:
        with patch("blueprints.pagos.stripe.checkout.Session.create", return_value=mock_session) as mock_crear_sesion:
            resp = client.post(
                "/crear-sesion-checkout",
                json={"plan": "basico"},
                headers={"Authorization": "Bearer x"},
            )
        assert resp.status_code == 200
        _, kwargs = mock_crear_sesion.call_args
        assert kwargs["metadata"]["oposicion"] == "AGE"
    finally:
        parche.stop()


def test_crear_sesion_checkout_propaga_error_de_stripe_como_500(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "stripe_customer_id": "cus_existente_1"})
    parche = _con_sesion(client)
    try:
        with patch("blueprints.pagos.stripe.checkout.Session.create", side_effect=RuntimeError("stripe caído")):
            resp = client.post(
                "/crear-sesion-checkout",
                json={"plan": "basico", "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"},
            )
        assert resp.status_code == 500
        assert "stripe caído" in resp.get_json()["error"]
    finally:
        parche.stop()


def test_crear_sesion_portal_exige_login(client):
    resp = client.post("/crear-sesion-portal")
    assert resp.status_code == 401


def test_crear_sesion_portal_sin_suscripcion_da_error(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    parche = _con_sesion(client)
    try:
        resp = client.post("/crear-sesion-portal", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 400
        assert "suscripción" in resp.get_json()["error"].lower()
    finally:
        parche.stop()


def test_crear_sesion_portal_devuelve_url_de_stripe(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "stripe_customer_id": "cus_existente_1"})
    parche = _con_sesion(client)
    mock_session = MagicMock(url="https://billing.stripe.com/portal-x")
    try:
        with patch("blueprints.pagos.stripe.billing_portal.Session.create", return_value=mock_session) as mock_crear:
            resp = client.post("/crear-sesion-portal", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        assert resp.get_json()["url"] == "https://billing.stripe.com/portal-x"
        mock_crear.assert_called_once_with(customer="cus_existente_1", return_url="http://localhost:8080/mi-cuenta/")
    finally:
        parche.stop()


def test_crear_sesion_portal_propaga_error_de_stripe_como_500(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "stripe_customer_id": "cus_existente_1"})
    parche = _con_sesion(client)
    try:
        with patch("blueprints.pagos.stripe.billing_portal.Session.create", side_effect=RuntimeError("stripe caído")):
            resp = client.post("/crear-sesion-portal", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 500
        assert "stripe caído" in resp.get_json()["error"]
    finally:
        parche.stop()
