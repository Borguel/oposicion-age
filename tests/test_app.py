"""Pruebas del middleware verificar_api_key (app.py): con API_SECRET_KEY
activada, /tareas/* debe seguir siendo alcanzable (los workflows de cron
solo mandan X-Cron-Key, nunca X-API-Key -- cada ruta ya se autentica por
su cuenta con hmac.compare_digest), mientras que el resto de rutas siguen
exigiendo la cabecera."""
from unittest.mock import patch

import app as app_module


def _con_api_key_activada(valor="clave-de-prueba"):
    return patch.object(app_module, "API_SECRET_KEY", valor)


def test_ruta_de_tareas_no_exigida_x_api_key_con_clave_activada(client, db):
    # vigilar_gasto_ia solo lee Firestore (sin red ni email si no hay pico) --
    # con la BD vacía del fixture no hay foto previa, así que responde 200
    # sin avisar. Lo relevante aquí es que el middleware NO la bloquee con
    # 401 antes de llegar a su propia comprobación de X-Cron-Key.
    with _con_api_key_activada(), patch("blueprints.tareas_programadas._clave_cron_valida", return_value=True):
        resp = client.post("/tareas/vigilar-gasto-ia")
    assert resp.status_code == 200
    assert resp.get_json() == {"gasto_hoy": None, "aviso_enviado": False}


def test_ruta_de_tareas_sigue_exigiendo_su_propia_clave_de_cron(client):
    # El middleware la deja pasar, pero _clave_cron_valida (sin mockear)
    # sigue bloqueando si no llega X-Cron-Key -- eximir /tareas/ del
    # candado de API_SECRET_KEY no las deja abiertas del todo.
    with _con_api_key_activada():
        resp = client.post("/tareas/vigilar-gasto-ia")
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "No autorizado"}


def test_ruta_normal_sigue_exigiendo_x_api_key_con_clave_activada(client):
    with _con_api_key_activada():
        resp = client.get("/conversaciones")
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "No autorizado"}


def test_ruta_normal_pasa_el_middleware_con_x_api_key_correcta(client):
    # Pasa el middleware (no 401 "No autorizado") y sigue hasta la propia
    # autenticación de Firebase de la ruta, que sí bloquea sin token real.
    with _con_api_key_activada():
        resp = client.get("/conversaciones", headers={"X-API-Key": "clave-de-prueba"})
    assert resp.status_code == 401
    assert resp.get_json() != {"error": "No autorizado"}
