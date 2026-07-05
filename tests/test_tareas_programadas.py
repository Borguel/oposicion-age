"""Pruebas del cron de recordatorios de racha (blueprints/tareas_programadas.py):
que el endpoint exija la clave de cron, y que solo se avise a quien está en
riesgo de perder la racha hoy o cruza justo un umbral de inactividad."""
import os
from datetime import date, timedelta
from unittest.mock import patch


def _fecha_hace(dias):
    return (date.today() - timedelta(days=dias)).isoformat()


def test_sin_clave_configurada_devuelve_401(client):
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CRON_SECRET_KEY", None)
        resp = client.post("/tareas/recordatorios-racha", headers={"X-Cron-Key": "lo-que-sea"})
        assert resp.status_code == 401


def test_con_clave_incorrecta_devuelve_401(client):
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}):
        resp = client.post("/tareas/recordatorios-racha", headers={"X-Cron-Key": "incorrecta"})
        assert resp.status_code == 401


def test_avisa_a_quien_esta_en_riesgo_de_perder_la_racha(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "racha": {"racha_actual": 5, "ultima_fecha": _fecha_hace(1)}
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_racha_en_riesgo") as mock_riesgo, \
         patch("blueprints.tareas_programadas.enviar_email_reengagement") as mock_reengagement:
        resp = client.post("/tareas/recordatorios-racha", headers={"X-Cron-Key": "secreta"})
        assert resp.status_code == 200
        assert resp.get_json() == {"en_riesgo": 1, "reengagement": 0}
        mock_riesgo.assert_called_once_with("u1@example.com", 5, nombre="")
        mock_reengagement.assert_not_called()


def test_avisa_a_quien_cruza_un_umbral_de_inactividad(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "racha": {"racha_actual": 0, "ultima_fecha": _fecha_hace(7)}
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_racha_en_riesgo") as mock_riesgo, \
         patch("blueprints.tareas_programadas.enviar_email_reengagement") as mock_reengagement:
        resp = client.post("/tareas/recordatorios-racha", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"en_riesgo": 0, "reengagement": 1}
        mock_reengagement.assert_called_once_with("u1@example.com", 7, nombre="")
        mock_riesgo.assert_not_called()


def test_no_avisa_a_quien_no_esta_en_riesgo_ni_en_un_umbral(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "racha": {"racha_actual": 2, "ultima_fecha": _fecha_hace(4)}
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_racha_en_riesgo") as mock_riesgo, \
         patch("blueprints.tareas_programadas.enviar_email_reengagement") as mock_reengagement:
        resp = client.post("/tareas/recordatorios-racha", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"en_riesgo": 0, "reengagement": 0}
        mock_riesgo.assert_not_called()
        mock_reengagement.assert_not_called()


def test_ignora_usuarios_sin_email_o_sin_racha(client, db):
    db.sembrar(("usuarios", "sin_email"), {"racha": {"racha_actual": 5, "ultima_fecha": _fecha_hace(1)}})
    db.sembrar(("usuarios", "sin_racha"), {"email": "x@example.com"})
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_racha_en_riesgo") as mock_riesgo, \
         patch("blueprints.tareas_programadas.enviar_email_reengagement") as mock_reengagement:
        resp = client.post("/tareas/recordatorios-racha", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"en_riesgo": 0, "reengagement": 0}
        mock_riesgo.assert_not_called()
        mock_reengagement.assert_not_called()
