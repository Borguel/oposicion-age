"""Pruebas de propagar_proxy_saliente() (firebase_setup.py): sin
FIXIE_URL ni QUOTAGUARDSTATIC_URL no debe tocar nada, y con cualquiera de
las dos debe rellenar las 4 variables de proxy que leen requests y gRPC
sin pisar las que ya estuvieran puestas a mano. FIXIE_URL tiene prioridad
si ambas están fijadas (migración de una a otra sin borrar la vieja)."""
from firebase_setup import propagar_proxy_saliente


def test_sin_ninguna_variable_de_proxy_no_hace_nada():
    entorno = {}
    propagar_proxy_saliente(entorno)
    assert entorno == {}


def test_con_quotaguardstatic_url_rellena_las_variables_de_proxy():
    entorno = {"QUOTAGUARDSTATIC_URL": "http://user:pass@static.quotaguard.com:9293"}
    propagar_proxy_saliente(entorno)
    for variable in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        assert entorno[variable] == "http://user:pass@static.quotaguard.com:9293"


def test_con_fixie_url_rellena_las_variables_de_proxy():
    entorno = {"FIXIE_URL": "http://fixie:token@tu-subdominio.usefixie.com:80"}
    propagar_proxy_saliente(entorno)
    for variable in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        assert entorno[variable] == "http://fixie:token@tu-subdominio.usefixie.com:80"


def test_fixie_url_tiene_prioridad_sobre_quotaguardstatic_url():
    entorno = {
        "FIXIE_URL": "http://fixie:token@tu-subdominio.usefixie.com:80",
        "QUOTAGUARDSTATIC_URL": "http://user:pass@static.quotaguard.com:9293",
    }
    propagar_proxy_saliente(entorno)
    assert entorno["HTTPS_PROXY"] == "http://fixie:token@tu-subdominio.usefixie.com:80"


def test_no_pisa_una_variable_de_proxy_ya_puesta_a_mano():
    entorno = {
        "QUOTAGUARDSTATIC_URL": "http://user:pass@static.quotaguard.com:9293",
        "HTTPS_PROXY": "http://otro-proxy-distinto:8080",
    }
    propagar_proxy_saliente(entorno)
    assert entorno["HTTPS_PROXY"] == "http://otro-proxy-distinto:8080"
    assert entorno["HTTP_PROXY"] == "http://user:pass@static.quotaguard.com:9293"
