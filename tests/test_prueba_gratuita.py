"""La prueba gratuita de 7 días ya no se regala a ciegas: solo arranca si
el email está verificado (Google lo verifica de fábrica; email+contraseña
necesita que el usuario confirme el enlace) y su dominio no es de correo
desechable conocido -- para que crear cuentas en bucle no dé acceso
Premium gratis sin más coste que rellenar un formulario."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from flask import Flask, g, jsonify

from dominios_desechables import es_dominio_email_desechable
from registro_progreso_usuario import inicializar_estadisticas_usuario
from auth_utils import requiere_login, requiere_plan


def test_dominio_desechable_conocido_se_detecta():
    assert es_dominio_email_desechable("bot123@mailinator.com") is True
    assert es_dominio_email_desechable("BOT@YOPMAIL.COM") is True  # insensible a mayúsculas


def test_dominio_normal_no_es_desechable():
    assert es_dominio_email_desechable("persona@gmail.com") is False


def test_email_vacio_o_sin_arroba_no_es_desechable():
    assert es_dominio_email_desechable("") is False
    assert es_dominio_email_desechable(None) is False
    assert es_dominio_email_desechable("no-es-un-email") is False


def test_email_verificado_arranca_la_prueba_al_crear_la_cuenta(db):
    with patch("registro_progreso_usuario.enviar_email_bienvenida"):
        inicializar_estadisticas_usuario(db, "u1", email="persona@gmail.com", email_verificado=True)
    usuario = db.leer(("usuarios", "u1"))
    assert usuario["prueba_fin"] is not None
    dias_restantes = (datetime.fromisoformat(usuario["prueba_fin"]) - datetime.utcnow()).days
    assert 6 <= dias_restantes <= 7


def test_email_sin_verificar_no_arranca_la_prueba(db):
    with patch("registro_progreso_usuario.enviar_email_bienvenida"):
        inicializar_estadisticas_usuario(db, "u1", email="persona@gmail.com", email_verificado=False)
    usuario = db.leer(("usuarios", "u1"))
    assert usuario["prueba_fin"] is None


def test_dominio_desechable_no_arranca_la_prueba_aunque_diga_verificado(db):
    # Defensa en profundidad: aunque el claim email_verified viniera en
    # True, un dominio de correo desechable conocido tampoco se lleva la
    # prueba gratuita.
    with patch("registro_progreso_usuario.enviar_email_bienvenida"):
        inicializar_estadisticas_usuario(db, "u1", email="bot@mailinator.com", email_verificado=True)
    usuario = db.leer(("usuarios", "u1"))
    assert usuario["prueba_fin"] is None


def test_verificar_el_email_mas_tarde_arranca_la_prueba_pendiente(db):
    # Primera petición autenticada: email todavía sin verificar -> sin
    # prueba. Días después el usuario confirma su correo (el token ya trae
    # email_verified=True) -- la siguiente petición debe arrancarla, no
    # perderla para siempre por no haberse verificado a tiempo.
    with patch("registro_progreso_usuario.enviar_email_bienvenida"):
        inicializar_estadisticas_usuario(db, "u1", email="persona@gmail.com", email_verificado=False)
    assert db.leer(("usuarios", "u1"))["prueba_fin"] is None

    inicializar_estadisticas_usuario(db, "u1", email="persona@gmail.com", email_verificado=True)
    usuario = db.leer(("usuarios", "u1"))
    assert usuario["prueba_fin"] is not None


def test_no_se_reactiva_una_prueba_que_ya_estaba_en_marcha(db):
    # Si la prueba ya arrancó (con su propia fecha de fin), una petición
    # posterior no debe recalcularla ni alargarla.
    fin_original = (datetime.utcnow() + timedelta(days=3)).isoformat()
    db.sembrar(("usuarios", "u1"), {"email": "persona@gmail.com", "prueba_fin": fin_original})
    inicializar_estadisticas_usuario(db, "u1", email="persona@gmail.com", email_verificado=True)
    assert db.leer(("usuarios", "u1"))["prueba_fin"] == fin_original


@pytest.fixture
def mini_app(db):
    app = Flask(__name__)

    @app.route("/solo-basico")
    @requiere_plan(db, "basico")
    def solo_basico():
        return jsonify({"ok": True})

    return app


def test_requiere_plan_bloquea_a_quien_no_ha_verificado_el_email(mini_app, db):
    # Simula el registro por email+contraseña recién hecho: el token de
    # Firebase todavía trae email_verified=False -- no debe recibir la
    # prueba gratuita de Premium sin más.
    with patch("auth_utils.firebase_auth.verify_id_token",
               return_value={"uid": "nuevo", "email": "nuevo@gmail.com", "email_verified": False}):
        cliente = mini_app.test_client()
        resp = cliente.get("/solo-basico", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 403


def test_requiere_plan_deja_pasar_con_email_verificado(mini_app, db):
    with patch("auth_utils.firebase_auth.verify_id_token",
               return_value={"uid": "nuevo", "email": "nuevo@gmail.com", "email_verified": True}):
        cliente = mini_app.test_client()
        resp = cliente.get("/solo-basico", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200


def test_requiere_plan_deja_pasar_a_quien_entra_con_google_sin_el_claim_explicito(mini_app, db):
    # Un inicio de sesión con Google también manda email_verified=True en
    # el token (Google ya verifica la dirección) -- se prueba aparte del
    # caso general para dejar constancia de que Google no queda bloqueado.
    with patch("auth_utils.firebase_auth.verify_id_token",
               return_value={"uid": "goog1", "email": "persona@gmail.com", "email_verified": True,
                             "firebase": {"sign_in_provider": "google.com"}}):
        cliente = mini_app.test_client()
        resp = cliente.get("/solo-basico", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
