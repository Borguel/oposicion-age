"""Prueba del manejador de errores global (@app.errorhandler(Exception) en
app.py): cualquier excepción no controlada debe devolver JSON consistente
con el resto de la API, sin filtrar el traceback en la respuesta.

Se monta una app mínima con el mismo manejador (en vez de forzar una
excepción en la app real, que ya tiene sus propias rutas con try/except
propio) para verificar la pieza de código en sí, igual que
test_health.py::test_limiter_corta_pasado_el_limite_por_ip hace con el
limiter."""
from flask import Flask, jsonify
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
