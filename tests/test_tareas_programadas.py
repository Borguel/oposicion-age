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


# ============================================================
# /tareas/recordatorios-prueba
# ============================================================

def _prueba_fin_en(dias):
    return (date.today() + timedelta(days=dias)).isoformat() + "T00:00:00"


def test_recordatorios_prueba_sin_clave_devuelve_401(client):
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CRON_SECRET_KEY", None)
        resp = client.post("/tareas/recordatorios-prueba", headers={"X-Cron-Key": "lo-que-sea"})
        assert resp.status_code == 401


def test_avisa_a_quien_le_quedan_2_dias_de_prueba(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "prueba_fin": _prueba_fin_en(2)})
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminando") as mock_terminando, \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminada") as mock_terminada:
        resp = client.post("/tareas/recordatorios-prueba", headers={"X-Cron-Key": "secreta"})
        assert resp.status_code == 200
        assert resp.get_json() == {"terminando": 1, "terminada": 0}
        mock_terminando.assert_called_once_with("u1@example.com", 2, nombre="")
        mock_terminada.assert_not_called()


def test_avisa_a_quien_la_prueba_termino_ayer(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "prueba_fin": _prueba_fin_en(-1)})
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminando") as mock_terminando, \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminada") as mock_terminada:
        resp = client.post("/tareas/recordatorios-prueba", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"terminando": 0, "terminada": 1}
        mock_terminada.assert_called_once_with("u1@example.com", nombre="")
        mock_terminando.assert_not_called()


def test_no_avisa_a_quien_ya_tiene_plan_de_pago(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "prueba_fin": _prueba_fin_en(2),
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active"}},
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminando") as mock_terminando, \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminada") as mock_terminada:
        resp = client.post("/tareas/recordatorios-prueba", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"terminando": 0, "terminada": 0}
        mock_terminando.assert_not_called()
        mock_terminada.assert_not_called()


def test_no_avisa_fuera_de_los_dias_exactos(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "prueba_fin": _prueba_fin_en(5)})
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminando") as mock_terminando, \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminada") as mock_terminada:
        resp = client.post("/tareas/recordatorios-prueba", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"terminando": 0, "terminada": 0}
        mock_terminando.assert_not_called()
        mock_terminada.assert_not_called()


def test_ignora_usuarios_sin_email_o_sin_prueba_fin(client, db):
    db.sembrar(("usuarios", "sin_email"), {"prueba_fin": _prueba_fin_en(2)})
    db.sembrar(("usuarios", "sin_prueba"), {"email": "x@example.com"})
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminando") as mock_terminando, \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminada") as mock_terminada:
        resp = client.post("/tareas/recordatorios-prueba", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"terminando": 0, "terminada": 0}
        mock_terminando.assert_not_called()
        mock_terminada.assert_not_called()
