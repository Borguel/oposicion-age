"""Pruebas del webhook de Stripe: la ruta que decide si alguien pasa a
tener una suscripción de pago. Se cubre el rechazo de firmas inválidas
(cualquiera podría intentar simular un pago sin esto) y que un mismo
evento no se procese dos veces si Stripe lo reintenta."""
import hashlib
import hmac
import json
import time

STRIPE_WEBHOOK_SECRET = "whsec_test_dummy"  # coincide con conftest.py


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
