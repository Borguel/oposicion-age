"""Pruebas del freno de ráfaga en los endpoints de IA (rate_limiter.py).

Igual que test_health.py::test_limiter_corta_pasado_el_limite_por_ip: el
limiter de la app real está desactivado durante toda la suite
(RATELIMIT_ENABLED en conftest.py), así que estas pruebas montan una app
mínima con la MISMA configuración que las rutas reales (mismo límite,
mismo key_func) para confirmar que esa configuración corta el flujo
pasado el número de peticiones -- es la pieza real que hay que verificar,
no el objeto concreto de la app de producción."""
from flask import Flask, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def _app_con_limite(limite):
    app = Flask(__name__)
    limiter = Limiter(key_func=get_remote_address, app=app, storage_uri="memory://")

    @app.route("/ia")
    @limiter.limit(limite)
    def ia():
        return jsonify({"ok": True})

    return app.test_client()


def test_limite_5_por_minuto_corta_pasado_el_limite():
    # Generación pesada de un solo uso: /generar-test-avanzado, /resumir-pdf,
    # /generar-esquema-desde-pdf, /generar-test-desde-pdf,
    # /generar-tarjetas-desde-pdf.
    cliente = _app_con_limite("5 per minute")
    for _ in range(5):
        assert cliente.get("/ia").status_code == 200
    assert cliente.get("/ia").status_code == 429


def test_limite_10_por_minuto_corta_pasado_el_limite():
    # /analisis-rendimiento.
    cliente = _app_con_limite("10 per minute")
    for _ in range(10):
        assert cliente.get("/ia").status_code == 200
    assert cliente.get("/ia").status_code == 429


def test_limite_20_por_minuto_corta_pasado_el_limite():
    # Chat conversacional: /tu-tutor, /tu-tutor/stream, /chat-pdf-mensaje.
    cliente = _app_con_limite("20 per minute")
    for _ in range(20):
        assert cliente.get("/ia").status_code == 200
    assert cliente.get("/ia").status_code == 429
