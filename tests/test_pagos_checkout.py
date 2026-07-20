"""Pruebas de las rutas que crean sesiones de pago en Stripe
(/crear-sesion-checkout, /crear-sesion-portal): la parte de la web que
mueve dinero real, y hasta ahora la única sin ninguna prueba automática
(el webhook que sí las tiene está en test_webhook_stripe.py). Se mockean
las llamadas reales a la API de Stripe -- lo que se prueba es la lógica
propia (validación, creación/reuso de customer, propagación de errores),
no el SDK de Stripe en sí."""
from unittest.mock import MagicMock, patch

import stripe


def _con_sesion(cliente, uid="u1", email="u1@example.com"):
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email})
    parche.start()
    return parche


def _mock_precio(currency="eur", unit_amount=999, interval="month"):
    # El checkout ya no manda un price_id fijo como line_item: genera un
    # Price "al vuelo" (price_data) reutilizando importe/moneda/periodicidad
    # del Price configurado (STRIPE_PRICE_ID_BASICO/PREMIUM), para que el
    # nombre del producto pueda incluir la oposición sin tener que crear
    # Products/Prices nuevos en Stripe (ver blueprints/pagos.py).
    return {"currency": currency, "unit_amount": unit_amount, "recurring": {"interval": interval}}


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
             patch("blueprints.pagos.stripe.Price.retrieve", return_value=_mock_precio()), \
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
        # con un price_data que reproduce el importe/moneda/periodicidad del
        # Price configurado pero con un nombre de producto que sí distingue
        # la oposición, y la metadata (uid/plan/oposicion) tanto en la propia
        # sesión como en subscription_data -- lo que el webhook necesita
        # luego para reconciliar el evento.
        _, kwargs = mock_crear_sesion.call_args
        assert kwargs["mode"] == "subscription"
        assert kwargs["customer"] == "cus_nuevo_1"
        assert kwargs["line_items"] == [{
            "price_data": {
                "currency": "eur",
                "unit_amount": 999,
                "recurring": {"interval": "month"},
                "product_data": {"name": "Domina tu Opo — Plan Básico (AGE)"},
            },
            "quantity": 1,
        }]
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
             patch("blueprints.pagos.stripe.Customer.retrieve", return_value=MagicMock()), \
             patch("blueprints.pagos.stripe.Price.retrieve", return_value=_mock_precio(unit_amount=1999)), \
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
        assert kwargs["line_items"] == [{
            "price_data": {
                "currency": "eur",
                "unit_amount": 1999,
                "recurring": {"interval": "month"},
                "product_data": {"name": "Domina tu Opo — Plan Premium (AGE)"},
            },
            "quantity": 1,
        }]
    finally:
        parche.stop()


def test_crear_sesion_checkout_crea_customer_nuevo_si_el_guardado_esta_huerfano(client, db):
    # El stripe_customer_id guardado puede quedar huérfano si la web cambió
    # de clave de Stripe (de test a live, por ejemplo) -- Stripe responde
    # "No such customer" al intentar reutilizarlo, y hay que crear uno nuevo
    # en vez de dejar que el error suba tal cual al usuario.
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "stripe_customer_id": "cus_huerfano"})
    parche = _con_sesion(client)
    mock_customer = MagicMock(id="cus_nuevo_2")
    mock_session = MagicMock(url="https://checkout.stripe.com/nueva-2")
    try:
        with patch("blueprints.pagos.stripe.Customer.retrieve", side_effect=stripe.InvalidRequestError("No such customer: 'cus_huerfano'", param="id")), \
             patch("blueprints.pagos.stripe.Customer.create", return_value=mock_customer) as mock_crear_customer, \
             patch("blueprints.pagos.stripe.Price.retrieve", return_value=_mock_precio()), \
             patch("blueprints.pagos.stripe.checkout.Session.create", return_value=mock_session) as mock_crear_sesion:
            resp = client.post(
                "/crear-sesion-checkout",
                json={"plan": "basico", "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"},
            )
        assert resp.status_code == 200
        mock_crear_customer.assert_called_once_with(email="u1@example.com", metadata={"uid": "u1"})
        assert db.leer(("usuarios", "u1"))["stripe_customer_id"] == "cus_nuevo_2"
        _, kwargs = mock_crear_sesion.call_args
        assert kwargs["customer"] == "cus_nuevo_2"
    finally:
        parche.stop()


def test_crear_sesion_checkout_usa_oposicion_por_defecto_si_no_se_manda(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "stripe_customer_id": "cus_existente_1"})
    parche = _con_sesion(client)
    mock_session = MagicMock(url="https://checkout.stripe.com/x")
    try:
        with patch("blueprints.pagos.stripe.Customer.retrieve", return_value=MagicMock()), \
             patch("blueprints.pagos.stripe.Price.retrieve", return_value=_mock_precio()), \
             patch("blueprints.pagos.stripe.checkout.Session.create", return_value=mock_session) as mock_crear_sesion:
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


def test_crear_sesion_checkout_aplica_descuento_de_promocion_activa_del_mismo_plan(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "stripe_customer_id": "cus_existente_1"})
    db.sembrar(("config", "promocion"), {
        "activo": True, "plan": "premium", "descuento_pct": 20,
        "fecha_fin": "2099-01-01T00:00:00", "stripe_promotion_code": "promo_xyz",
    })
    parche = _con_sesion(client)
    mock_session = MagicMock(url="https://checkout.stripe.com/promo")
    try:
        with patch("blueprints.pagos.stripe.Customer.retrieve", return_value=MagicMock()), \
             patch("blueprints.pagos.stripe.Price.retrieve", return_value=_mock_precio()), \
             patch("blueprints.pagos.stripe.checkout.Session.create", return_value=mock_session) as mock_crear_sesion:
            resp = client.post(
                "/crear-sesion-checkout",
                json={"plan": "premium", "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"},
            )
        assert resp.status_code == 200
        _, kwargs = mock_crear_sesion.call_args
        assert kwargs["discounts"] == [{"promotion_code": "promo_xyz"}]
    finally:
        parche.stop()


def test_crear_sesion_checkout_no_aplica_descuento_de_otro_plan(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "stripe_customer_id": "cus_existente_1"})
    db.sembrar(("config", "promocion"), {
        "activo": True, "plan": "premium", "descuento_pct": 20,
        "fecha_fin": "2099-01-01T00:00:00", "stripe_promotion_code": "promo_xyz",
    })
    parche = _con_sesion(client)
    mock_session = MagicMock(url="https://checkout.stripe.com/sin-promo")
    try:
        with patch("blueprints.pagos.stripe.Customer.retrieve", return_value=MagicMock()), \
             patch("blueprints.pagos.stripe.Price.retrieve", return_value=_mock_precio()), \
             patch("blueprints.pagos.stripe.checkout.Session.create", return_value=mock_session) as mock_crear_sesion:
            resp = client.post(
                "/crear-sesion-checkout",
                json={"plan": "basico", "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"},
            )
        assert resp.status_code == 200
        _, kwargs = mock_crear_sesion.call_args
        assert "discounts" not in kwargs
    finally:
        parche.stop()


def test_crear_sesion_checkout_no_aplica_descuento_de_promocion_caducada(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "stripe_customer_id": "cus_existente_1"})
    db.sembrar(("config", "promocion"), {
        "activo": True, "plan": "premium", "descuento_pct": 20,
        "fecha_fin": "2000-01-01T00:00:00", "stripe_promotion_code": "promo_xyz",
    })
    parche = _con_sesion(client)
    mock_session = MagicMock(url="https://checkout.stripe.com/caducada")
    try:
        with patch("blueprints.pagos.stripe.Customer.retrieve", return_value=MagicMock()), \
             patch("blueprints.pagos.stripe.Price.retrieve", return_value=_mock_precio()), \
             patch("blueprints.pagos.stripe.checkout.Session.create", return_value=mock_session) as mock_crear_sesion:
            resp = client.post(
                "/crear-sesion-checkout",
                json={"plan": "premium", "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"},
            )
        assert resp.status_code == 200
        _, kwargs = mock_crear_sesion.call_args
        assert "discounts" not in kwargs
    finally:
        parche.stop()


def test_crear_sesion_checkout_propaga_error_de_stripe_como_500(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "stripe_customer_id": "cus_existente_1"})
    parche = _con_sesion(client)
    try:
        with patch("blueprints.pagos.stripe.Customer.retrieve", return_value=MagicMock()), \
             patch("blueprints.pagos.stripe.Price.retrieve", return_value=_mock_precio()), \
             patch("blueprints.pagos.stripe.checkout.Session.create", side_effect=RuntimeError("stripe caído")):
            resp = client.post(
                "/crear-sesion-checkout",
                json={"plan": "basico", "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"},
            )
        assert resp.status_code == 500
        assert "stripe caído" in resp.get_json()["error"]
    finally:
        parche.stop()


def test_crear_sesion_checkout_propaga_error_al_obtener_precio_base_como_500(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "stripe_customer_id": "cus_existente_1"})
    parche = _con_sesion(client)
    try:
        with patch("blueprints.pagos.stripe.Customer.retrieve", return_value=MagicMock()), \
             patch("blueprints.pagos.stripe.Price.retrieve", side_effect=RuntimeError("price no encontrado")):
            resp = client.post(
                "/crear-sesion-checkout",
                json={"plan": "basico", "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"},
            )
        assert resp.status_code == 500
        assert "price no encontrado" in resp.get_json()["error"]
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


def test_crear_sesion_portal_con_customer_huerfano_limpia_el_estado_local(client, db):
    # El customer guardado puede quedar huérfano igual que en checkout/cancelar
    # (tras pasar de la clave de test a la de producción): Stripe responde
    # "No such customer", y como no hay ninguna suscripción real detrás, se
    # limpia el estado local (customer_id + planes de pago) en vez de dejar
    # al usuario con un botón que siempre va a fallar.
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "stripe_customer_id": "cus_huerfano",
        "suscripciones": {"AGE": {"plan": "premium", "stripe_subscription_id": "sub_huerfana"}},
    })
    parche = _con_sesion(client)
    try:
        with patch("blueprints.pagos.stripe.billing_portal.Session.create", side_effect=stripe.InvalidRequestError("No such customer: 'cus_huerfano'", param="customer")):
            resp = client.post("/crear-sesion-portal", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 400
        assert "no hemos encontrado" in resp.get_json()["error"].lower()
        usuario = db.leer(("usuarios", "u1"))
        assert "stripe_customer_id" not in usuario
        assert usuario["suscripciones"]["AGE"]["plan"] == "gratis"
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


def test_cancelar_suscripcion_exige_login(client):
    resp = client.post("/cancelar-suscripcion", json={"oposicion": "AGE", "motivo": "precio"})
    assert resp.status_code == 401


def test_cancelar_suscripcion_rechaza_motivo_no_valido(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "basico", "stripe_subscription_id": "sub_1"}},
    })
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/cancelar-suscripcion",
            json={"oposicion": "AGE", "motivo": "no_existe"},
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 400
        assert "motivo" in resp.get_json()["error"].lower()
    finally:
        parche.stop()


def test_cancelar_suscripcion_sin_suscripcion_activa_da_error(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/cancelar-suscripcion",
            json={"oposicion": "AGE", "motivo": "precio"},
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 400
        assert "ninguna suscripción activa" in resp.get_json()["error"].lower()
    finally:
        parche.stop()


def test_cancelar_suscripcion_programa_la_baja_y_guarda_el_motivo(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "premium", "stripe_subscription_id": "sub_1"}},
    })
    parche = _con_sesion(client)
    mock_subscription = {
        "id": "sub_1",
        "items": {"data": [{"current_period_end": 1893456000}]},
    }
    try:
        with patch("blueprints.pagos.stripe.Subscription.modify", return_value=mock_subscription) as mock_modify, \
             patch("blueprints.pagos.enviar_email_cancelacion_suscripcion") as mock_email:
            resp = client.post(
                "/cancelar-suscripcion",
                json={"oposicion": "AGE", "motivo": "precio", "comentario": "Demasiado caro para mí"},
                headers={"Authorization": "Bearer x"},
            )
        assert resp.status_code == 200
        mock_modify.assert_called_once_with("sub_1", cancel_at_period_end=True)
        assert resp.get_json()["current_period_end"] == "2030-01-01T00:00:00"

        # La confirmación de baja se manda al momento (no se espera al
        # webhook de Stripe, que llega días después al final del periodo).
        mock_email.assert_called_once()
        args_email = mock_email.call_args
        assert args_email.args[0] == "u1@example.com"
        assert "AGE" in args_email.args[1] or "Administrativo" in args_email.args[1]
        assert args_email.kwargs["fecha_fin"] == "01/01/2030"
        assert args_email.kwargs["motivo"] == "precio"

        # La suscripción sigue "activa" para Stripe hasta que el periodo
        # termine, pero el flag propio debe reflejar ya la baja programada.
        suscripcion = db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]
        assert suscripcion["cancelar_al_final_periodo"] is True

        motivos = [d.to_dict() for d in db.collection("usuarios").document("u1").collection("bajas_motivos").stream()]
        assert len(motivos) == 1
        assert motivos[0]["motivo"] == "precio"
        assert motivos[0]["comentario"] == "Demasiado caro para mí"
        assert motivos[0]["oposicion"] == "AGE"
    finally:
        parche.stop()


def test_cancelar_suscripcion_propaga_error_de_stripe_como_500(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "premium", "stripe_subscription_id": "sub_1"}},
    })
    parche = _con_sesion(client)
    try:
        with patch("blueprints.pagos.stripe.Subscription.modify", side_effect=RuntimeError("stripe caído")):
            resp = client.post(
                "/cancelar-suscripcion",
                json={"oposicion": "AGE", "motivo": "precio"},
                headers={"Authorization": "Bearer x"},
            )
        assert resp.status_code == 500
        assert "stripe caído" in resp.get_json()["error"]
        # Si Stripe falla no debe quedar registrado el motivo ni el flag de baja.
        motivos = list(db.collection("usuarios").document("u1").collection("bajas_motivos").stream())
        assert motivos == []
        assert "cancelar_al_final_periodo" not in db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]
    finally:
        parche.stop()


def test_cancelar_suscripcion_con_subscription_id_huerfano_se_marca_gratis_localmente(client, db):
    # La suscripción guardada puede quedar huérfana igual que el customer
    # (p. ej. tras pasar de la clave de test a la de producción de Stripe):
    # Stripe responde "No such subscription", y en ese caso no hay nada que
    # cancelar ahí -- se refleja localmente que el plan ya no está activo en
    # vez de devolver un error 500 sobre algo que el usuario no puede arreglar.
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "premium", "stripe_subscription_id": "sub_huerfana"}},
    })
    parche = _con_sesion(client)
    try:
        with patch("blueprints.pagos.stripe.Subscription.modify", side_effect=stripe.InvalidRequestError("No such subscription: 'sub_huerfana'", param="id")), \
             patch("blueprints.pagos.enviar_email_cancelacion_suscripcion") as mock_email:
            resp = client.post(
                "/cancelar-suscripcion",
                json={"oposicion": "AGE", "motivo": "precio"},
                headers={"Authorization": "Bearer x"},
            )
        assert resp.status_code == 200
        assert "ya no estaba activa" in resp.get_json()["mensaje"].lower()
        mock_email.assert_not_called()
        suscripcion = db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]
        assert suscripcion["plan"] == "gratis"
        assert suscripcion["subscription_status"] == "canceled"
    finally:
        parche.stop()


def test_reactivar_suscripcion_exige_login(client):
    resp = client.post("/reactivar-suscripcion", json={"oposicion": "AGE"})
    assert resp.status_code == 401


def test_reactivar_suscripcion_sin_suscripcion_activa_da_error(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/reactivar-suscripcion",
            json={"oposicion": "AGE"},
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 400
    finally:
        parche.stop()


def test_reactivar_suscripcion_deshace_la_baja_programada(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {
            "plan": "premium",
            "stripe_subscription_id": "sub_1",
            "cancelar_al_final_periodo": True,
        }},
    })
    parche = _con_sesion(client)
    try:
        with patch("blueprints.pagos.stripe.Subscription.modify", return_value={}) as mock_modify, \
             patch("blueprints.pagos.enviar_email_reactivacion_suscripcion") as mock_email:
            resp = client.post(
                "/reactivar-suscripcion",
                json={"oposicion": "AGE"},
                headers={"Authorization": "Bearer x"},
            )
        assert resp.status_code == 200
        mock_modify.assert_called_once_with("sub_1", cancel_at_period_end=False)
        assert db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]["cancelar_al_final_periodo"] is False
        # Contrapartida del email de cancelación: quien deshace la baja
        # también merece una confirmación explícita, no silencio.
        mock_email.assert_called_once()
        assert mock_email.call_args.args[0] == "u1@example.com"
    finally:
        parche.stop()
