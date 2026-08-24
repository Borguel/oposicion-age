"""Pruebas del webhook de Stripe: la ruta que decide si alguien pasa a
tener una suscripción de pago. Se cubre el rechazo de firmas inválidas
(cualquiera podría intentar simular un pago sin esto), que un mismo
evento no se procese dos veces si Stripe lo reintenta, y los 3 eventos
que de verdad conceden/cambian/degradan el acceso de pago:
checkout.session.completed, customer.subscription.updated (subida y
bajada de plan) e invoice.payment_failed."""
import hashlib
import hmac
import json
import time
from unittest.mock import patch

STRIPE_WEBHOOK_SECRET = "whsec_test_dummy"  # coincide con conftest.py
# Coinciden con STRIPE_PRICE_ID_BASICO / STRIPE_PRICE_ID_PREMIUM en conftest.py
PRICE_BASICO = "price_basico_test"
PRICE_PREMIUM = "price_premium_test"


def _firmar(payload_bytes, secreto=STRIPE_WEBHOOK_SECRET, timestamp=None):
    timestamp = timestamp or int(time.time())
    payload_firmado = f"{timestamp}.{payload_bytes.decode()}"
    firma = hmac.new(secreto.encode(), payload_firmado.encode(), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={firma}"


def _evento(tipo="customer.subscription.deleted", **objeto_extra):
    # "object": "event" es el campo que el SDK de Stripe espera en todo
    # evento real (lo pone Stripe, no hace falta pensarlo al llamar a la
    # API) -- sin él, stripe.Webhook.construct_event no reconoce el payload
    # como un evento válido.
    return {
        "id": "evt_test_1",
        "object": "event",
        "type": tipo,
        "data": {"object": {"id": "sub_test_1", "object": "subscription", **objeto_extra}},
    }


def test_webhook_rechaza_firma_invalida(client):
    payload = json.dumps(_evento()).encode()
    resp = client.post(
        "/webhook-stripe",
        data=payload,
        headers={"Stripe-Signature": "t=123,v1=firma_falsa", "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert "inválida" in resp.get_json()["error"]


def test_webhook_rechaza_sin_cabecera_de_firma(client):
    payload = json.dumps(_evento()).encode()
    resp = client.post("/webhook-stripe", data=payload, headers={"Content-Type": "application/json"})
    assert resp.status_code == 400


def test_webhook_acepta_firma_valida_y_no_reprocesa_el_mismo_evento(client, db):
    evento = _evento()
    payload = json.dumps(evento).encode()
    firma = _firmar(payload)

    # Se marca el evento como ya procesado (lo que hace la propia ruta tras
    # tramitarlo la primera vez), para probar el candado de idempotencia sin
    # tener que simular todo un ciclo de suscripción de Stripe.
    db.sembrar(("stripe_events", "evt_test_1"), {"tipo": "customer.subscription.deleted"})

    resp = client.post(
        "/webhook-stripe",
        data=payload,
        headers={"Stripe-Signature": firma, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["mensaje"] == "Evento ya procesado"


def test_webhook_con_firma_de_otro_timestamp_muy_antiguo_se_rechaza(client):
    # stripe.Webhook.construct_event tiene una tolerancia de tiempo por
    # defecto (evita "replay" de una petición capturada hace mucho).
    payload = json.dumps(_evento()).encode()
    firma_antigua = _firmar(payload, timestamp=int(time.time()) - 10000)
    resp = client.post(
        "/webhook-stripe",
        data=payload,
        headers={"Stripe-Signature": firma_antigua, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def _post_evento(client, evento):
    payload = json.dumps(evento).encode()
    return client.post(
        "/webhook-stripe",
        data=payload,
        headers={"Stripe-Signature": _firmar(payload), "Content-Type": "application/json"},
    )


def test_webhook_checkout_completado_activa_suscripcion(client, db):
    # checkout.session.completed no trae el plan/estado definitivos en el
    # propio evento -- el handler vuelve a consultar la Subscription real a
    # la API de Stripe para no fiarse de nada que venga solo del evento.
    evento = {
        "id": "evt_checkout_1",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {"object": {
            "object": "checkout.session",
            "client_reference_id": "u1",
            "customer": "cus_test_1",
            "subscription": "sub_test_1",
            "metadata": {"uid": "u1", "plan": "basico", "oposicion": "AGE"},
        }},
    }
    mock_subscription = {
        "status": "active",
        "items": {"data": [{"price": {"id": PRICE_BASICO}}]},
        "current_period_end": 1893456000,
    }
    with patch("blueprints.pagos.stripe.Subscription.retrieve", return_value=mock_subscription):
        resp = _post_evento(client, evento)

    assert resp.status_code == 200
    suscripcion = db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]
    assert suscripcion["plan"] == "basico"
    assert suscripcion["subscription_status"] == "active"


def test_webhook_checkout_completado_cancela_la_suscripcion_anterior_al_cambiar_de_plan(client, db):
    # Bug real (23/08/2026): /crear-sesion-checkout siempre crea una
    # sesión de Checkout NUEVA -- así que cambiar de plan (Básico -> Premium)
    # para la MISMA oposición dejaba la suscripción anterior huérfana en
    # Stripe, cobrando en paralelo con la nueva. u1 ya tiene "sub_viejo"
    # activa en AGE (plan básico) cuando llega el checkout.session.completed
    # de una suscripción NUEVA ("sub_nuevo", premium) para esa misma
    # oposición -- la anterior debe cancelarse en Stripe.
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@x.com",
        "suscripciones": {"AGE": {"plan": "basico", "stripe_subscription_id": "sub_viejo", "subscription_status": "active"}},
    })
    evento = {
        "id": "evt_checkout_cambio",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {"object": {
            "object": "checkout.session",
            "client_reference_id": "u1",
            "customer": "cus_test_1",
            "subscription": "sub_nuevo",
            "metadata": {"uid": "u1", "plan": "premium", "oposicion": "AGE"},
        }},
    }
    mock_subscription = {
        "status": "active",
        "items": {"data": [{"price": {"id": PRICE_PREMIUM}}]},
        "current_period_end": 1893456000,
    }
    with patch("blueprints.pagos.stripe.Subscription.retrieve", return_value=mock_subscription), \
         patch("blueprints.pagos.stripe.Subscription.delete") as mock_delete:
        resp = _post_evento(client, evento)

    assert resp.status_code == 200
    mock_delete.assert_called_once_with("sub_viejo")
    suscripcion = db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]
    assert suscripcion["plan"] == "premium"
    assert suscripcion["stripe_subscription_id"] == "sub_nuevo"


def test_webhook_checkout_completado_primera_alta_no_cancela_nada(client, db):
    # Sin ninguna suscripción previa para esa oposición (alta nueva, no
    # cambio de plan), no debe intentarse cancelar nada en Stripe.
    evento = {
        "id": "evt_checkout_primera_vez",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {"object": {
            "object": "checkout.session",
            "client_reference_id": "u1",
            "customer": "cus_test_1",
            "subscription": "sub_nuevo",
            "metadata": {"uid": "u1", "plan": "basico", "oposicion": "AGE"},
        }},
    }
    mock_subscription = {
        "status": "active",
        "items": {"data": [{"price": {"id": PRICE_BASICO}}]},
        "current_period_end": 1893456000,
    }
    with patch("blueprints.pagos.stripe.Subscription.retrieve", return_value=mock_subscription), \
         patch("blueprints.pagos.stripe.Subscription.delete") as mock_delete:
        resp = _post_evento(client, evento)

    assert resp.status_code == 200
    mock_delete.assert_not_called()


def test_webhook_subscription_updated_sube_y_luego_baja_de_plan(client, db):
    # customer.subscription.updated SÍ trae directamente el price_id en el
    # propio evento -- no hace falta volver a consultar Stripe. Se busca al
    # usuario por stripe_customer_id (no por uid, que aquí no viaja).
    db.sembrar(("usuarios", "u2"), {
        "stripe_customer_id": "cus_test_2",
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active"}},
    })

    def _evento_updated(evt_id, price_id):
        return {
            "id": evt_id,
            "object": "event",
            "type": "customer.subscription.updated",
            "data": {"object": {
                "object": "subscription",
                "id": "sub_test_2",
                "customer": "cus_test_2",
                "status": "active",
                "items": {"data": [{"price": {"id": price_id}}]},
                "metadata": {"oposicion": "AGE"},
            }},
        }

    resp_subida = _post_evento(client, _evento_updated("evt_sub_upd_1", PRICE_PREMIUM))
    assert resp_subida.status_code == 200
    assert db.leer(("usuarios", "u2"))["suscripciones"]["AGE"]["plan"] == "premium"

    resp_bajada = _post_evento(client, _evento_updated("evt_sub_upd_2", PRICE_BASICO))
    assert resp_bajada.status_code == 200
    assert db.leer(("usuarios", "u2"))["suscripciones"]["AGE"]["plan"] == "basico"


def test_webhook_payment_failed_marca_past_due_y_avisa_por_email(client, db):
    db.sembrar(("usuarios", "u3"), {
        "email": "u3@example.com",
        "stripe_customer_id": "cus_test_3",
        "suscripciones": {"AGE": {"plan": "premium", "subscription_status": "active"}},
    })
    evento = {
        "id": "evt_payment_failed_1",
        "object": "event",
        "type": "invoice.payment_failed",
        "data": {"object": {
            "object": "invoice",
            "customer": "cus_test_3",
            "subscription": "sub_test_3",
        }},
    }
    mock_subscription = {"metadata": {"oposicion": "AGE"}}
    with patch("blueprints.pagos.stripe.Subscription.retrieve", return_value=mock_subscription), \
         patch("blueprints.pagos.enviar_email_pago_fallido") as mock_email:
        resp = _post_evento(client, evento)

    assert resp.status_code == 200
    suscripcion = db.leer(("usuarios", "u3"))["suscripciones"]["AGE"]
    assert suscripcion["subscription_status"] == "past_due"
    assert suscripcion["plan"] == "premium"
    # Hasta ahora este webhook solo actualizaba Firestore en silencio: el
    # usuario no se enteraba de que Stripe no había podido cobrarle hasta
    # perder el acceso. Ahora se le avisa de inmediato para que actualice
    # su método de pago antes de que se agoten los reintentos de Stripe.
    mock_email.assert_called_once()
    assert mock_email.call_args.args[0] == "u3@example.com"


def test_webhook_reclama_el_evento_por_transaccion(client, db):
    # Lo que cierra la ventana de carrera entre dos entregas casi
    # simultáneas del mismo evento (Stripe reintenta) es que la
    # comprobación de "ya existe" y el marcado como reclamado vayan en la
    # MISMA transacción -- no un get().exists() seguido de un set() suelto.
    evento = _evento()
    llamadas = []
    transaction_original = db.transaction

    def transaction_espia():
        llamadas.append(1)
        return transaction_original()

    db.transaction = transaction_espia
    try:
        resp = _post_evento(client, evento)
    finally:
        db.transaction = transaction_original

    assert resp.status_code == 200
    assert len(llamadas) == 1
    assert db.leer(("stripe_events", "evt_test_1")) is not None


def test_webhook_libera_el_evento_si_falla_el_procesamiento(client, db):
    # Si el procesamiento revienta a mitad, el reclamo debe liberarse -- si
    # no, un reintento posterior de Stripe (con el mismo evento, esta vez
    # sin el fallo) se encontraría el evento ya marcado y lo daría por
    # procesado sin haberlo completado nunca.
    db.sembrar(("usuarios", "u4"), {
        "email": "u4@example.com",
        "stripe_customer_id": "cus_test_4",
        "suscripciones": {"AGE": {"plan": "premium", "subscription_status": "active"}},
    })
    evento = _evento(tipo="customer.subscription.deleted", customer="cus_test_4")

    with patch("blueprints.pagos.actualizar_suscripcion", side_effect=RuntimeError("Firestore caído")):
        resp = _post_evento(client, evento)
    assert resp.status_code == 500
    assert db.leer(("stripe_events", "evt_test_1")) is None

    # Reintento de Stripe con el mismo evento, ahora sin el fallo: debe
    # procesarse de verdad, no salir como "ya procesado".
    resp2 = _post_evento(client, evento)
    assert resp2.status_code == 200
    assert resp2.get_json()["mensaje"] == "Evento procesado"
    assert db.leer(("usuarios", "u4"))["suscripciones"]["AGE"]["subscription_status"] == "canceled"
