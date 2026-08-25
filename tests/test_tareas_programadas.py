"""Pruebas del cron de recordatorios de racha (blueprints/tareas_programadas.py):
que el endpoint exija la clave de cron, y que solo se avise a quien está en
riesgo de perder la racha hoy o cruza justo un umbral de inactividad."""
import os
from datetime import date, datetime, timedelta
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


def test_recordatorios_racha_ya_enviado_hoy_no_repite(client, db):
    # Bug real (25/08/2026, auditoría): sin esta guarda, un re-disparo
    # manual del workflow (workflow_dispatch habilitado) el mismo día en
    # que ya corrió el cron programado duplicaba el email.
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "racha": {"racha_actual": 5, "ultima_fecha": _fecha_hace(1)}
    })
    db.sembrar(("config", "cron_recordatorios_racha_ultimo_envio"), {"fecha": date.today().isoformat()})
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_racha_en_riesgo") as mock_riesgo:
        resp = client.post("/tareas/recordatorios-racha", headers={"X-Cron-Key": "secreta"})
        assert resp.status_code == 200
        assert "ya enviado" in resp.get_json()["mensaje"].lower()
        mock_riesgo.assert_not_called()


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


def test_recordatorios_prueba_ya_enviado_hoy_no_repite(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "gratis", "prueba_fin": _prueba_fin_en(2)}},
    })
    db.sembrar(("config", "cron_recordatorios_prueba_ultimo_envio"), {"fecha": date.today().isoformat()})
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminando") as mock_terminando:
        resp = client.post("/tareas/recordatorios-prueba", headers={"X-Cron-Key": "secreta"})
        assert resp.status_code == 200
        assert "ya enviado" in resp.get_json()["mensaje"].lower()
        mock_terminando.assert_not_called()


def test_avisa_a_quien_le_quedan_2_dias_de_prueba(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "gratis", "prueba_fin": _prueba_fin_en(2)}},
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminando") as mock_terminando, \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminada") as mock_terminada:
        resp = client.post("/tareas/recordatorios-prueba", headers={"X-Cron-Key": "secreta"})
        assert resp.status_code == 200
        assert resp.get_json() == {"terminando": 1, "terminada": 0}
        mock_terminando.assert_called_once_with("u1@example.com", 2, nombre="", oposicion_nombre="Cuerpo General Administrativo del Estado (AGE, C1)")
        mock_terminada.assert_not_called()


def test_avisa_a_quien_la_prueba_termino_ayer(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "gratis", "prueba_fin": _prueba_fin_en(-1)}},
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminando") as mock_terminando, \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminada") as mock_terminada:
        resp = client.post("/tareas/recordatorios-prueba", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"terminando": 0, "terminada": 1}
        mock_terminada.assert_called_once_with("u1@example.com", nombre="", oposicion_nombre="Cuerpo General Administrativo del Estado (AGE, C1)")
        mock_terminando.assert_not_called()


def test_no_avisa_si_ya_paga_por_otra_oposicion(client, db):
    # Bug real (25/08/2026, auditoría): quien ya paga Premium/Básico en OTRA
    # oposición seguía recibiendo el email de fin de prueba con el texto
    # fijo "tu cuenta ha quedado bloqueada", información falsa -- su cuenta
    # sigue con acceso completo por la oposición que sí paga. Mismo criterio
    # que ya usa el frontend (tiene_plan_de_pago_activo) para no mostrarle
    # ningún aviso de prueba.
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {
            "AGE": {"plan": "premium", "subscription_status": "active"},
            "GACE": {"plan": "gratis", "prueba_fin": _prueba_fin_en(-1)},
        },
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminando") as mock_terminando, \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminada") as mock_terminada:
        resp = client.post("/tareas/recordatorios-prueba", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"terminando": 0, "terminada": 0}
        mock_terminando.assert_not_called()
        mock_terminada.assert_not_called()


def test_avisa_por_cada_oposicion_cuya_prueba_cruce_el_umbral(client, db):
    # Cada oposición tiene su propia prueba independiente -- si dos cruzan
    # el mismo umbral el mismo día, se avisa una vez por cada una.
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {
            "AGE": {"plan": "gratis", "prueba_fin": _prueba_fin_en(2)},
            "GACE": {"plan": "gratis", "prueba_fin": _prueba_fin_en(2)},
        },
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminando") as mock_terminando, \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminada") as mock_terminada:
        resp = client.post("/tareas/recordatorios-prueba", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"terminando": 2, "terminada": 0}
        assert mock_terminando.call_count == 2
        mock_terminada.assert_not_called()


def test_no_avisa_a_quien_ya_tiene_plan_de_pago_en_esa_oposicion(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active", "prueba_fin": _prueba_fin_en(2)}},
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminando") as mock_terminando, \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminada") as mock_terminada:
        resp = client.post("/tareas/recordatorios-prueba", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"terminando": 0, "terminada": 0}
        mock_terminando.assert_not_called()
        mock_terminada.assert_not_called()


def test_no_avisa_fuera_de_los_dias_exactos(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "gratis", "prueba_fin": _prueba_fin_en(5)}},
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminando") as mock_terminando, \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminada") as mock_terminada:
        resp = client.post("/tareas/recordatorios-prueba", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"terminando": 0, "terminada": 0}
        mock_terminando.assert_not_called()
        mock_terminada.assert_not_called()


def test_ignora_usuarios_sin_email_o_sin_prueba_fin(client, db):
    db.sembrar(("usuarios", "sin_email"), {"suscripciones": {"AGE": {"plan": "gratis", "prueba_fin": _prueba_fin_en(2)}}})
    db.sembrar(("usuarios", "sin_prueba"), {"email": "x@example.com", "suscripciones": {"AGE": {"plan": "gratis"}}})
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminando") as mock_terminando, \
         patch("blueprints.tareas_programadas.enviar_email_prueba_terminada") as mock_terminada:
        resp = client.post("/tareas/recordatorios-prueba", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"terminando": 0, "terminada": 0}
        mock_terminando.assert_not_called()
        mock_terminada.assert_not_called()


# ============================================================
# /tareas/recordatorios-activacion
# ============================================================

def _registrado_hace(dias):
    return (datetime.utcnow() - timedelta(days=dias)).isoformat()


def test_recordatorios_activacion_sin_clave_devuelve_401(client):
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CRON_SECRET_KEY", None)
        resp = client.post("/tareas/recordatorios-activacion", headers={"X-Cron-Key": "lo-que-sea"})
        assert resp.status_code == 401


def test_recordatorios_activacion_ya_enviado_hoy_no_repite(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {},
        "fecha_creacion": _registrado_hace(2),
    })
    db.sembrar(("config", "cron_recordatorios_activacion_ultimo_envio"), {"fecha": date.today().isoformat()})
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_activar_oposicion") as mock_activar:
        resp = client.post("/tareas/recordatorios-activacion", headers={"X-Cron-Key": "secreta"})
        assert resp.status_code == 200
        assert "ya enviado" in resp.get_json()["mensaje"].lower()
        mock_activar.assert_not_called()


def test_avisa_a_quien_cruza_un_umbral_sin_ninguna_oposicion_activada(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "nombre": "Virginia",
        "suscripciones": {},
        "fecha_creacion": _registrado_hace(2),
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_activar_oposicion") as mock_activar:
        resp = client.post("/tareas/recordatorios-activacion", headers={"X-Cron-Key": "secreta"})
        assert resp.status_code == 200
        assert resp.get_json() == {"avisados": 1}
        mock_activar.assert_called_once_with("u1@example.com", nombre="Virginia")


def test_no_avisa_a_quien_ya_activo_alguna_oposicion(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "gratis", "prueba_fin": None}},
        "fecha_creacion": _registrado_hace(2),
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_activar_oposicion") as mock_activar:
        resp = client.post("/tareas/recordatorios-activacion", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"avisados": 0}
        mock_activar.assert_not_called()


def test_no_avisa_fuera_de_los_dias_exactos_de_activacion(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {},
        "fecha_creacion": _registrado_hace(4),
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_activar_oposicion") as mock_activar:
        resp = client.post("/tareas/recordatorios-activacion", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"avisados": 0}
        mock_activar.assert_not_called()


def test_avisa_dos_veces_en_la_primera_semana_si_sigue_sin_activar(client, db):
    # Las dos llamadas simulan dos ejecuciones del cron en DÍAS REALES
    # distintos (4 días de diferencia) -- hace falta mockear date.today()
    # para que la guarda de "ya enviado hoy" (25/08/2026, bug real
    # corregido) no bloquee la segunda como si fuera un redisparo del mismo
    # día.
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "suscripciones": {}, "fecha_creacion": datetime(2026, 1, 8).isoformat()})
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_activar_oposicion") as mock_activar, \
         patch("blueprints.tareas_programadas.date") as mock_date:
        mock_date.today.return_value = date(2026, 1, 10)  # 2 días desde el registro
        resp = client.post("/tareas/recordatorios-activacion", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"avisados": 1}

        mock_date.today.return_value = date(2026, 1, 14)  # 6 días desde el registro
        resp = client.post("/tareas/recordatorios-activacion", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"avisados": 1}

        assert mock_activar.call_count == 2


def test_ignora_usuarios_sin_email_o_sin_fecha_de_creacion(client, db):
    db.sembrar(("usuarios", "sin_email"), {"suscripciones": {}, "fecha_creacion": _registrado_hace(2)})
    db.sembrar(("usuarios", "sin_fecha"), {"email": "x@example.com", "suscripciones": {}})
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_activar_oposicion") as mock_activar:
        resp = client.post("/tareas/recordatorios-activacion", headers={"X-Cron-Key": "secreta"})
        assert resp.get_json() == {"avisados": 0}
        mock_activar.assert_not_called()


# ---------- Vigilancia de gasto en IA ----------
def _mes_actual():
    return date.today().strftime("%Y-%m")


def test_vigilar_gasto_ia_sin_clave_401(client, db):
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}):
        resp = client.post("/tareas/vigilar-gasto-ia", headers={"X-Cron-Key": "incorrecta"})
        assert resp.status_code == 401


def test_vigilar_gasto_ia_primer_run_no_avisa_solo_guarda_foto(client, db):
    # Sin ninguna foto previa no hay "gasto de hoy" que calcular todavía --
    # se guarda la referencia y se sale sin mandar ningún correo.
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "coste_ia": {_mes_actual(): {"coste": 5.0}}})
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_alerta_coste_ia") as mock_alerta:
        resp = client.post("/tareas/vigilar-gasto-ia", headers={"X-Cron-Key": "secreta"})
    assert resp.status_code == 200
    datos = resp.get_json()
    assert datos["gasto_hoy"] is None
    assert datos["aviso_enviado"] is False
    mock_alerta.assert_not_called()
    estado = db.leer(("config", "coste_ia_alerta"))
    assert estado["total_acumulado_mes"] == 5.0


# Fecha fija (día 15, lejos de cualquier borde de mes) para las dos pruebas
# de abajo: usaban date.today() - timedelta(days=1) como "foto de ayer", lo
# que las hacía fallar en falso cada día 1 de mes (ayer cae en el mes
# anterior, y el código -- correctamente -- descarta la comparación al ver
# que la foto previa es de otro mes). Fijar "hoy" evita depender del día real
# de ejecución.
_HOY_FIJO = date(2026, 1, 15)


def test_vigilar_gasto_ia_pico_respecto_a_la_media_avisa(client, db):
    mes_fijo = _HOY_FIJO.strftime("%Y-%m")
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "coste_ia": {mes_fijo: {"coste": 20.0}}})
    db.sembrar(("config", "coste_ia_alerta"), {
        "fecha": (_HOY_FIJO - timedelta(days=1)).isoformat(),
        "total_acumulado_mes": 10.0,
        "historial": [0.2, 0.3, 0.25],
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_alerta_coste_ia") as mock_alerta, \
         patch("blueprints.tareas_programadas.date") as mock_date, \
         patch("blueprints.tareas_programadas.datetime") as mock_datetime, \
         patch("coste_ia.datetime") as mock_datetime_coste:
        mock_date.today.return_value = _HOY_FIJO
        mock_datetime.utcnow.return_value = datetime(_HOY_FIJO.year, _HOY_FIJO.month, _HOY_FIJO.day)
        mock_datetime_coste.utcnow.return_value = datetime(_HOY_FIJO.year, _HOY_FIJO.month, _HOY_FIJO.day)
        resp = client.post("/tareas/vigilar-gasto-ia", headers={"X-Cron-Key": "secreta"})
    assert resp.status_code == 200
    datos = resp.get_json()
    assert datos["gasto_hoy"] == 10.0  # 20.0 - 10.0
    assert datos["aviso_enviado"] is True
    mock_alerta.assert_called_once()
    args = mock_alerta.call_args.args
    assert args[1] == 10.0


def test_vigilar_gasto_ia_por_debajo_del_minimo_no_avisa(client, db):
    mes_fijo = _HOY_FIJO.strftime("%Y-%m")
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "coste_ia": {mes_fijo: {"coste": 10.3}}})
    db.sembrar(("config", "coste_ia_alerta"), {
        "fecha": (_HOY_FIJO - timedelta(days=1)).isoformat(),
        "total_acumulado_mes": 10.0,
        "historial": [0.01, 0.02],
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_alerta_coste_ia") as mock_alerta, \
         patch("blueprints.tareas_programadas.date") as mock_date, \
         patch("blueprints.tareas_programadas.datetime") as mock_datetime, \
         patch("coste_ia.datetime") as mock_datetime_coste:
        mock_date.today.return_value = _HOY_FIJO
        mock_datetime.utcnow.return_value = datetime(_HOY_FIJO.year, _HOY_FIJO.month, _HOY_FIJO.day)
        mock_datetime_coste.utcnow.return_value = datetime(_HOY_FIJO.year, _HOY_FIJO.month, _HOY_FIJO.day)
        resp = client.post("/tareas/vigilar-gasto-ia", headers={"X-Cron-Key": "secreta"})
    assert resp.get_json()["aviso_enviado"] is False
    mock_alerta.assert_not_called()


def test_vigilar_gasto_ia_ya_comprobado_hoy_no_repite(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "coste_ia": {_mes_actual(): {"coste": 50.0}}})
    db.sembrar(("config", "coste_ia_alerta"), {
        "fecha": date.today().isoformat(),
        "total_acumulado_mes": 1.0,
        "historial": [0.1],
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_alerta_coste_ia") as mock_alerta:
        resp = client.post("/tareas/vigilar-gasto-ia", headers={"X-Cron-Key": "secreta"})
    assert resp.status_code == 200
    assert "ya comprobado" in resp.get_json()["mensaje"].lower()
    mock_alerta.assert_not_called()


def test_vigilar_gasto_ia_rollover_de_mes_no_avisa(client, db):
    # La foto de ayer era de un mes distinto (el total del mes se reinicia a
    # 0 cada mes) -- la diferencia no significa "gasto de hoy" en absoluto.
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "coste_ia": {_mes_actual(): {"coste": 0.5}}})
    db.sembrar(("config", "coste_ia_alerta"), {
        "fecha": "2020-01-31", "total_acumulado_mes": 40.0, "historial": [1.0],
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_alerta_coste_ia") as mock_alerta:
        resp = client.post("/tareas/vigilar-gasto-ia", headers={"X-Cron-Key": "secreta"})
    assert resp.get_json()["gasto_hoy"] is None
    mock_alerta.assert_not_called()


# ============================================================
# /tareas/vigilar-boe -- nunca publica nada solo, solo deja propuestas/avisos
# pendientes de revisión (ver vigilancia_boe.py + blueprints/admin.py)
# ============================================================
def test_vigilar_boe_sin_clave_devuelve_401(client):
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CRON_SECRET_KEY", None)
        resp = client.post("/tareas/vigilar-boe", headers={"X-Cron-Key": "lo-que-sea"})
        assert resp.status_code == 401


def test_vigilar_boe_con_clave_incorrecta_devuelve_401(client):
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}):
        resp = client.post("/tareas/vigilar-boe", headers={"X-Cron-Key": "incorrecta"})
        assert resp.status_code == 401


def test_vigilar_boe_llama_a_las_tres_comprobaciones_y_devuelve_los_totales(client, db):
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.detectar_avisos_oficiales", return_value=2) as mock_avisos, \
         patch("blueprints.tareas_programadas.detectar_cambios_leyes_vigiladas", return_value=1) as mock_cambios, \
         patch("blueprints.tareas_programadas.verificar_bloque_temas_referenciados", return_value=[{"oposicion": "AGE", "bloque_id": "bloque_01", "tema_id": "tema_01"}]) as mock_salud:
        resp = client.post("/tareas/vigilar-boe", headers={"X-Cron-Key": "secreta"})
    assert resp.status_code == 200
    assert resp.get_json() == {"avisos_creados": 2, "cambios_propuestos": 1, "temas_faltantes": 1}
    mock_avisos.assert_called_once_with(db)
    mock_cambios.assert_called_once_with(db)
    mock_salud.assert_called_once_with(db)


