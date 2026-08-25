"""Prueba de los manejadores de errores globales de app.py:
@app.errorhandler(Exception) (cualquier excepción no controlada debe
devolver JSON consistente con el resto de la API, sin filtrar el
traceback) y @app.errorhandler(429) (un 429 de flask-limiter debe seguir
siendo JSON, no la página HTML por defecto de la librería -- el frontend
ya sabe interpretar un 429 con {"error": "..."} porque es el mismo status
que usa limites_uso.py para la cuota agotada, y sin este manejador
intentaba hacer res.json() sobre HTML y fallaba con un error de sintaxis
visible tal cual al usuario).

Se monta una app mínima con el mismo manejador (en vez de forzar el error
en la app real, que ya tiene sus propias rutas con try/except propio y el
limiter desactivado en toda la suite -- ver RATELIMIT_ENABLED en
conftest.py) para verificar la pieza de código en sí, igual que
test_health.py::test_limiter_corta_pasado_el_limite_por_ip hace con el
limiter."""
from flask import Flask, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException


def _app_con_manejador():
    app = Flask(__name__)

    @app.errorhandler(Exception)
    def manejar_error_no_controlado(error):
        if isinstance(error, HTTPException):
            return error
        return jsonify({"error": "Error interno del servidor"}), 500

    @app.route("/explota")
    def explota():
        raise RuntimeError("fallo interno inesperado")

    return app.test_client()


def test_excepcion_no_controlada_devuelve_500_json_consistente():
    cliente = _app_con_manejador()
    resp = cliente.get("/explota")
    assert resp.status_code == 500
    assert resp.get_json() == {"error": "Error interno del servidor"}


def test_excepcion_no_controlada_no_filtra_el_traceback():
    cliente = _app_con_manejador()
    resp = cliente.get("/explota")
    cuerpo = resp.get_data(as_text=True)
    assert "RuntimeError" not in cuerpo
    assert "Traceback" not in cuerpo


def test_error_http_normal_sigue_devolviendo_su_propia_respuesta():
    cliente = _app_con_manejador()
    resp = cliente.get("/ruta-que-no-existe")
    assert resp.status_code == 404


def _app_con_limite_y_manejador_429(limite="2 per minute"):
    app = Flask(__name__)
    limiter = Limiter(key_func=get_remote_address, app=app, storage_uri="memory://")

    @app.errorhandler(429)
    def demasiadas_peticiones(_error):
        return jsonify({"error": "Estás yendo muy rápido. Espera un momento antes de volver a intentarlo."}), 429

    @app.route("/ia")
    @limiter.limit(limite)
    def ia():
        return jsonify({"ok": True})

    return app.test_client()


def test_429_de_rate_limit_devuelve_json_no_html():
    cliente = _app_con_limite_y_manejador_429()
    cliente.get("/ia")
    cliente.get("/ia")
    resp = cliente.get("/ia")  # tercera, ya por encima del límite de 2/min
    assert resp.status_code == 429
    assert resp.content_type.startswith("application/json")
    assert resp.get_json()["error"]


def test_429_de_rate_limit_no_es_la_pagina_html_por_defecto():
    cliente = _app_con_limite_y_manejador_429()
    cliente.get("/ia")
    cliente.get("/ia")
    resp = cliente.get("/ia")
    cuerpo = resp.get_data(as_text=True)
    assert "<html" not in cuerpo.lower()


def test_json_mal_formado_devuelve_400_json_no_html(client, usuario_autenticado):
    """Bug real (25/08/2026, auditoría): request.get_json() sin silent=True
    (usado en varias rutas, p. ej. /guardar-test) lanza BadRequest, que sin
    el manejador de app.py se deja pasar tal cual y devuelve la página HTML
    por defecto de Flask -- mismo bug que el 429 de arriba, con el mismo
    disparador real: un body vacío/truncado por una red inestable, no un
    fallo del propio frontend."""
    usuario_autenticado()
    resp = client.post(
        "/guardar-test?oposicion=AGE",
        data="{esto no es json valido",
        content_type="application/json",
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 400
    assert resp.content_type.startswith("application/json")
    assert resp.get_json()["error"]
    assert "<html" not in resp.get_data(as_text=True).lower()


def test_content_type_no_json_devuelve_415_json_no_html(client, usuario_autenticado):
    usuario_autenticado()
    resp = client.post(
        "/guardar-test?oposicion=AGE",
        data="lo que sea",
        content_type="text/plain",
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 415
    assert resp.content_type.startswith("application/json")
    assert resp.get_json()["error"]
