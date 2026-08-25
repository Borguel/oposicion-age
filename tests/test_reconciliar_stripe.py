"""Reconciliación periódica con Stripe (blueprints/tareas_programadas.py::
reconciliar_stripe -> blueprints/pagos.py::reconciliar_suscripciones_con_
stripe): red de seguridad frente a un webhook perdido -- ver el comentario
largo junto a la función. Sigue el mismo patrón de auth (X-Cron-Key) que
el resto de tareas de tests/test_tareas_programadas.py."""
import os
from unittest.mock import patch

import stripe

from conftest import sembrar_usuario_activo

PRICE_PREMIUM = "price_premium_test"  # coincide con conftest.py
PRICE_BASICO = "price_basico_test"  # coincide con conftest.py


def _sub_stripe(status, price_id=PRICE_PREMIUM, cancel_at_period_end=False):
    return {
        "id": "sub_test_1",
        "status": status,
        "cancel_at_period_end": cancel_at_period_end,
        "items": {"data": [{"price": {"id": price_id}, "current_period_end": 1900000000}]},
    }


def test_sin_clave_configurada_devuelve_401(client):
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CRON_SECRET_KEY", None)
        resp = client.post("/tareas/reconciliar-stripe", headers={"X-Cron-Key": "lo-que-sea"})
    assert resp.status_code == 401


def test_sin_suscripciones_de_pago_no_hace_nada(client, db):
    sembrar_usuario_activo(db, "u1", plan="premium")  # sin stripe_subscription_id
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.pagos.stripe.Subscription.retrieve") as mock_retrieve:
        resp = client.post("/tareas/reconciliar-stripe", headers={"X-Cron-Key": "secreta"})
    assert resp.status_code == 200
    assert resp.get_json() == {"revisadas": 0, "corregidas": 0}
    mock_retrieve.assert_not_called()


def test_estado_sincronizado_no_se_toca(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {
            "plan": "premium", "subscription_status": "active",
            "stripe_subscription_id": "sub_test_1",
        }},
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.pagos.stripe.Subscription.retrieve", return_value=_sub_stripe("active")) as mock_retrieve, \
         patch("blueprints.pagos.actualizar_suscripcion") as mock_actualizar:
        resp = client.post("/tareas/reconciliar-stripe", headers={"X-Cron-Key": "secreta"})
    assert resp.status_code == 200
    assert resp.get_json() == {"revisadas": 1, "corregidas": 0}
    mock_retrieve.assert_called_once_with("sub_test_1")
    mock_actualizar.assert_not_called()


def test_suscripcion_cancelada_en_stripe_se_corrige_en_firestore(client, db):
    # Bug real: Stripe canceló la suscripción (impago, disputa, cancelada
    # a mano desde el Dashboard) pero el webhook correspondiente se
    # perdió -- sin esta reconciliación, el usuario se quedaba con acceso
    # de pago indefinidamente sin cobro real.
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {
            "plan": "premium", "subscription_status": "active",
            "stripe_subscription_id": "sub_test_1",
        }},
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.pagos.stripe.Subscription.retrieve", return_value=_sub_stripe("canceled")):
        resp = client.post("/tareas/reconciliar-stripe", headers={"X-Cron-Key": "secreta"})
    assert resp.status_code == 200
    assert resp.get_json() == {"revisadas": 1, "corregidas": 1}
    sub = db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]
    assert sub["subscription_status"] == "canceled"


def test_plan_cambia_sin_cambiar_status_se_corrige(client, db):
    # Bug real (ronda de auditoría #4): un cambio de plan que no cambia el
    # status (sigue "active" en Stripe antes y después) se saltaba por
    # completo -- la comparación solo miraba el status, nunca el plan.
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {
            "plan": "basico", "subscription_status": "active",
            "stripe_subscription_id": "sub_test_1",
        }},
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.pagos.stripe.Subscription.retrieve", return_value=_sub_stripe("active", price_id=PRICE_PREMIUM)):
        resp = client.post("/tareas/reconciliar-stripe", headers={"X-Cron-Key": "secreta"})
    assert resp.status_code == 200
    assert resp.get_json() == {"revisadas": 1, "corregidas": 1}
    sub = db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]
    assert sub["plan"] == "premium"
    assert sub["subscription_status"] == "active"


def test_suscripcion_borrada_por_completo_en_stripe_se_trata_como_cancelada(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {
            "plan": "premium", "subscription_status": "active",
            "stripe_subscription_id": "sub_test_1",
        }},
    })
    error_stripe = stripe.error.InvalidRequestError("No such subscription", "id")
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.pagos.stripe.Subscription.retrieve", side_effect=error_stripe):
        resp = client.post("/tareas/reconciliar-stripe", headers={"X-Cron-Key": "secreta"})
    assert resp.status_code == 200
    assert resp.get_json() == {"revisadas": 1, "corregidas": 1}
    sub = db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]
    assert sub["plan"] == "gratis"
    assert sub["subscription_status"] == "canceled"


def test_error_inesperado_de_stripe_no_corrige_ni_rompe_el_resto(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {
            "plan": "premium", "subscription_status": "active",
            "stripe_subscription_id": "sub_test_1",
        }},
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.pagos.stripe.Subscription.retrieve", side_effect=RuntimeError("Stripe caído")):
        resp = client.post("/tareas/reconciliar-stripe", headers={"X-Cron-Key": "secreta"})
    assert resp.status_code == 200
    assert resp.get_json() == {"revisadas": 1, "corregidas": 0}
    sub = db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]
    assert sub["subscription_status"] == "active"  # sin tocar


def test_suscripciones_ya_canceladas_no_se_vuelven_a_revisar(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {
            "plan": "gratis", "subscription_status": "canceled",
            "stripe_subscription_id": "sub_test_1",
        }},
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.pagos.stripe.Subscription.retrieve") as mock_retrieve:
        resp = client.post("/tareas/reconciliar-stripe", headers={"X-Cron-Key": "secreta"})
    assert resp.status_code == 200
    assert resp.get_json() == {"revisadas": 0, "corregidas": 0}
    mock_retrieve.assert_not_called()
