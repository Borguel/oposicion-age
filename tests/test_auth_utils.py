"""Pruebas de auth_utils.py: el guardián de acceso de toda la API. Un
fallo aquí significa que rutas protegidas podrían quedar abiertas (o al
revés, usuarios de pago bloqueados), así que se cubre tanto el camino
feliz como los rechazos."""
from unittest.mock import patch

import pytest
from flask import Flask, g, jsonify

from firebase_admin import auth as firebase_auth

from auth_utils import (
    obtener_uid_desde_token,
    obtener_identidad_desde_token,
    requiere_login,
    requiere_plan,
    _mejor_plan,
)


class FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


def test_obtener_uid_sin_cabecera_authorization():
    assert obtener_uid_desde_token(FakeRequest()) is None


def test_obtener_uid_con_cabecera_mal_formada():
    assert obtener_uid_desde_token(FakeRequest({"Authorization": "Token abc"})) is None


def test_obtener_uid_con_bearer_vacio():
    assert obtener_uid_desde_token(FakeRequest({"Authorization": "Bearer "})) is None


def test_obtener_uid_con_token_invalido():
    with patch("auth_utils.firebase_auth.verify_id_token", side_effect=ValueError("token malo")):
        assert obtener_uid_desde_token(FakeRequest({"Authorization": "Bearer x"})) is None


def test_obtener_uid_con_token_valido():
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "a@b.com"}):
        assert obtener_uid_desde_token(FakeRequest({"Authorization": "Bearer x"})) == ("u1", "a@b.com")


def test_obtener_uid_verifica_pasando_check_revoked():
    # Una cuenta desactivada/borrada en Firebase debe dejar de poder usar
    # la API de inmediato, no solo cuando el token expire por sí solo
    # (hasta 1h después) -- eso exige pedirle al SDK que compruebe la
    # revocación en cada verificación.
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "a@b.com"}) as mock_verify:
        obtener_uid_desde_token(FakeRequest({"Authorization": "Bearer x"}))
    mock_verify.assert_called_once_with("x", check_revoked=True)


def test_obtener_uid_con_token_revocado():
    with patch("auth_utils.firebase_auth.verify_id_token", side_effect=firebase_auth.RevokedIdTokenError("revocado")):
        assert obtener_uid_desde_token(FakeRequest({"Authorization": "Bearer x"})) is None


def test_obtener_uid_reintenta_tras_fallo_de_red_al_verificar():
    # Visto en producción: un corte de conexión saliente de un par de
    # segundos entre Render y googleapis.com hacía fallar la verificación
    # de CUALQUIER token válido (CertificateFetchError, al no poder
    # descargar los certificados públicos de Google) -- un usuario
    # perfectamente logueado veía "No autenticado" sin motivo real. Un
    # reintento absorbe ese corte puntual.
    error_red = firebase_auth.CertificateFetchError("sin red", cause=None)
    with patch(
        "auth_utils.firebase_auth.verify_id_token",
        side_effect=[error_red, {"uid": "u1", "email": "a@b.com"}],
    ), patch("auth_utils.time.sleep"):
        assert obtener_uid_desde_token(FakeRequest({"Authorization": "Bearer x"})) == ("u1", "a@b.com")


def test_obtener_uid_no_reintenta_indefinidamente_si_la_red_sigue_caida():
    error_red = firebase_auth.CertificateFetchError("sin red", cause=None)
    with patch("auth_utils.firebase_auth.verify_id_token", side_effect=error_red), \
            patch("auth_utils.time.sleep"):
        assert obtener_uid_desde_token(FakeRequest({"Authorization": "Bearer x"})) is None


@pytest.fixture
def mini_app(db):
    app = Flask(__name__)

    @app.route("/protegida")
    @requiere_login(db)
    def protegida():
        return jsonify({"uid": g.uid})

    @app.route("/solo-basico")
    @requiere_plan(db, "basico")
    def solo_basico():
        return jsonify({"ok": True, "oposicion": g.oposicion})

    @app.route("/solo-premium-global")
    @requiere_plan(db, "premium", global_check=True)
    def solo_premium_global():
        return jsonify({"ok": True})

    return app


def test_requiere_login_sin_token_devuelve_401(mini_app):
    cliente = mini_app.test_client()
    resp = cliente.get("/protegida")
    assert resp.status_code == 401


def test_requiere_login_con_token_valido_deja_pasar(mini_app):
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "a@b.com"}):
        cliente = mini_app.test_client()
        resp = cliente.get("/protegida", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert resp.get_json()["uid"] == "u1"


def test_requiere_plan_bloquea_si_el_plan_es_insuficiente(mini_app, db):
    db.sembrar(("usuarios", "u1"), {"suscripciones": {"AGE": {"plan": "gratis"}}})
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "a@b.com"}):
        cliente = mini_app.test_client()
        resp = cliente.get("/solo-basico?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 403
    assert resp.get_json()["plan_actual"] == "gratis"


def test_requiere_plan_deja_pasar_con_plan_suficiente_y_activo(mini_app, db):
    db.sembrar(("usuarios", "u1"), {"suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active"}}})
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "a@b.com"}):
        cliente = mini_app.test_client()
        resp = cliente.get("/solo-basico?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert resp.get_json()["oposicion"] == "AGE"


def test_requiere_plan_bloquea_si_suscripcion_no_esta_activa(mini_app, db):
    # Plan suficiente pero, p. ej., pago fallido -- no debe dar acceso.
    db.sembrar(("usuarios", "u1"), {"suscripciones": {"AGE": {"plan": "basico", "subscription_status": "past_due"}}})
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "a@b.com"}):
        cliente = mini_app.test_client()
        resp = cliente.get("/solo-basico?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 403


def test_requiere_plan_global_check_usa_la_mejor_oposicion(mini_app, db):
    # global_check=True: basta con tener el plan requerido en CUALQUIER
    # oposición, no en la que se esté pidiendo en ese momento.
    db.sembrar(("usuarios", "u1"), {"suscripciones": {
        "AGE": {"plan": "gratis"},
        "GACE": {"plan": "premium", "subscription_status": "active"},
    }})
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "a@b.com"}):
        cliente = mini_app.test_client()
        resp = cliente.get("/solo-premium-global", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200


def test_identidad_marca_es_admin_con_claim():
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "a@b.com", "admin": True}):
        assert obtener_identidad_desde_token(FakeRequest({"Authorization": "Bearer x"})) == ("u1", "a@b.com", True)


def test_identidad_no_admin_sin_claim():
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "a@b.com"}):
        assert obtener_identidad_desde_token(FakeRequest({"Authorization": "Bearer x"})) == ("u1", "a@b.com", False)


def test_requiere_plan_deja_pasar_al_admin_sin_suscripcion(mini_app, db):
    # Un administrador (claim admin:true) debe poder usar cualquier
    # herramienta premium sin tener suscripción de pago, para probar y dar
    # soporte. Sin este bypass el admin recibía 403 y, p. ej., el tutor no
    # guardaba conversación.
    db.sembrar(("usuarios", "adm"), {"suscripciones": {"AGE": {"plan": "gratis"}}})
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "adm", "email": "a@b.com", "admin": True}):
        cliente = mini_app.test_client()
        resp = cliente.get("/solo-basico?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert resp.get_json()["oposicion"] == "AGE"


def test_mejor_plan_elige_el_mas_alto_entre_oposiciones():
    plan, sub = _mejor_plan({"AGE": {"plan": "gratis"}, "GACE": {"plan": "premium"}})
    assert plan == "premium"
    assert sub == {"plan": "premium"}


def test_mejor_plan_sin_suscripciones_es_gratis():
    plan, sub = _mejor_plan({})
    assert plan == "gratis"
    assert sub == {}
