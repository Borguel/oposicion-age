"""Prueba del endpoint /health: sin autenticación, y devuelve error si
Firestore falla en vez de dar un 200 falso."""
from unittest.mock import patch

from flask import Flask, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"estado": "ok"}


def test_health_sin_cabecera_de_autenticacion(client):
    # No manda Authorization -- a diferencia del resto de rutas, esto no
    # debe devolver 401.
    resp = client.get("/health")
    assert resp.status_code != 401


def test_health_devuelve_503_si_firestore_falla(client):
    with patch("app.db.collection", side_effect=RuntimeError("caído")):
        resp = client.get("/health")
        assert resp.status_code == 503
        datos = resp.get_json()
        assert datos["estado"] == "error"
        assert datos["firestore"] == "error"


def test_prueba_ip_directa_ok_si_google_responde(client):
    # Que Google responda 401 (sin credenciales, a propósito) cuenta como
    # "la IP no está bloqueada" -- lo único que importa es si la conexión
    # de red llega, no si la petición está autenticada.
    class RespuestaFalsa:
        status_code = 401
    with patch("app.requests.get", return_value=RespuestaFalsa()) as mock_get:
        resp = client.get("/health/prueba-ip")
        assert resp.status_code == 200
        assert resp.get_json()["ip_bloqueada"] is False
        # Confirma que se fuerza a ignorar el proxy de Fixie/QuotaGuard.
        assert mock_get.call_args.kwargs["proxies"] == {"http": None, "https": None}


def test_prueba_ip_directa_detecta_bloqueo(client):
    import requests as requests_module
    with patch("app.requests.get", side_effect=requests_module.exceptions.ConnectTimeout("bloqueada")):
        resp = client.get("/health/prueba-ip")
        assert resp.status_code == 503
        assert resp.get_json()["ip_bloqueada"] is True


def test_health_devuelve_503_si_falta_una_variable_critica(client, monkeypatch):
    # Firestore sigue respondiendo bien -- el fallo es solo de
    # configuración (p. ej. una variable que se quedó sin rellenar tras
    # un redeploy), sin llamar de verdad a Stripe/DeepSeek/Brevo.
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    resp = client.get("/health")
    assert resp.status_code == 503
    datos = resp.get_json()
    assert datos["firestore"] == "ok"
    assert "STRIPE_SECRET_KEY" in datos["variables_faltantes"]


def test_limiter_corta_pasado_el_limite_por_ip():
    # El limiter de la app real está desactivado durante toda la suite
    # (ver RATELIMIT_ENABLED en conftest.py) -- reactivarlo a mitad de una
    # sesión de pytest no sirve, porque flask-limiter decide si engancha
    # sus hooks una sola vez, en el momento de construir el objeto
    # (Limiter.init_app hace "if not self.enabled: return" y ya no vuelve
    # a comprobarlo). Así que en vez de tocar la app compartida, esta
    # prueba monta una app mínima con la MISMA configuración que /health
    # (mismo límite, mismo key_func) para confirmar que esa configuración
    # sí corta el flujo pasado el límite -- es la pieza real que hay que
    # verificar, no el objeto concreto de la app de producción.
    app = Flask(__name__)
    limiter = Limiter(key_func=get_remote_address, app=app, storage_uri="memory://")

    @app.route("/health")
    @limiter.limit("30 per minute")
    def salud():
        return jsonify({"estado": "ok"})

    cliente = app.test_client()
    for _ in range(30):
        assert cliente.get("/health").status_code == 200
    assert cliente.get("/health").status_code == 429
