"""Pruebas de las rutas de suscripción a notificaciones push (guardar,
deduplicar por endpoint y borrar), y de que el cron de racha en riesgo
avise por push además de por email a quien tenga una suscripción
guardada."""
import os
from datetime import date, timedelta
from unittest.mock import patch


def _con_sesion(cliente, uid="u1", email="u1@example.com"):
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email})
    parche.start()
    return parche


SUSCRIPCION = {"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "x", "auth": "y"}}


def test_suscribir_guarda_la_suscripcion(client, db):
    db.sembrar(("usuarios", "u1"), {})
    parche = _con_sesion(client)
    try:
        resp = client.post("/notificaciones-push/suscribir", json=SUSCRIPCION,
                            headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        guardado = db.leer(("usuarios", "u1"))
        assert guardado["push_subscriptions"] == [SUSCRIPCION]
    finally:
        parche.stop()


def test_suscribir_dos_veces_no_duplica(client, db):
    db.sembrar(("usuarios", "u1"), {})
    parche = _con_sesion(client)
    try:
        client.post("/notificaciones-push/suscribir", json=SUSCRIPCION, headers={"Authorization": "Bearer x"})
        client.post("/notificaciones-push/suscribir", json=SUSCRIPCION, headers={"Authorization": "Bearer x"})
        guardado = db.leer(("usuarios", "u1"))
        assert len(guardado["push_subscriptions"]) == 1
    finally:
        parche.stop()


def test_desuscribir_quita_la_suscripcion(client, db):
    db.sembrar(("usuarios", "u1"), {"push_subscriptions": [SUSCRIPCION]})
    parche = _con_sesion(client)
    try:
        resp = client.post("/notificaciones-push/desuscribir", json={"endpoint": SUSCRIPCION["endpoint"]},
                            headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        guardado = db.leer(("usuarios", "u1"))
        assert guardado["push_subscriptions"] == []
    finally:
        parche.stop()


def test_suscribir_sin_endpoint_devuelve_error(client, db):
    db.sembrar(("usuarios", "u1"), {})
    parche = _con_sesion(client)
    try:
        resp = client.post("/notificaciones-push/suscribir", json={"keys": {}},
                            headers={"Authorization": "Bearer x"})
        assert resp.status_code == 400
    finally:
        parche.stop()


def test_clave_publica_no_requiere_login(client):
    resp = client.get("/notificaciones-push/clave-publica")
    assert resp.status_code == 200
    assert "clave_publica" in resp.get_json()


def _fecha_hace(dias):
    return (date.today() - timedelta(days=dias)).isoformat()


def test_cron_racha_en_riesgo_envia_push_a_suscripciones_guardadas(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "racha": {"racha_actual": 5, "ultima_fecha": _fecha_hace(1)},
        "push_subscriptions": [SUSCRIPCION],
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_racha_en_riesgo"), \
         patch("blueprints.tareas_programadas.enviar_email_reengagement"), \
         patch("blueprints.tareas_programadas.enviar_push") as mock_push:
        resp = client.post("/tareas/recordatorios-racha", headers={"X-Cron-Key": "secreta"})
        assert resp.status_code == 200
        mock_push.assert_called_once()
        args, _ = mock_push.call_args
        assert args[0] == SUSCRIPCION
