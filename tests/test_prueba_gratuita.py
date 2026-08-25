"""La prueba gratuita de 7 días ya no se regala a ciegas ni es una única
prueba compartida por toda la cuenta: solo arranca cuando el usuario
ACTIVA una oposición concreta (activar_oposicion_usuario), y solo si su
email está verificado (Google lo verifica de fábrica; email+contraseña
necesita que el usuario confirme el enlace) y su dominio no es de correo
desechable conocido -- para que activar oposiciones en bucle con cuentas
desechables no dé acceso Premium gratis sin más coste que rellenar un
formulario. Cada oposición activada tiene su propia prueba independiente
(ver planes.py), así que tener varias no multiplica el uso efectivo contra
los límites por herramienta durante los 7 días de ninguna en concreto."""
import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from flask import Flask, jsonify

from dominios_desechables import es_dominio_email_desechable
from registro_progreso_usuario import (
    inicializar_estadisticas_usuario,
    activar_oposicion_usuario,
    obtener_perfil_usuario,
)
from auth_utils import requiere_plan
from planes import resolver_plan_efectivo, tiene_plan_de_pago_activo


def test_dominio_desechable_conocido_se_detecta():
    assert es_dominio_email_desechable("bot123@mailinator.com") is True
    assert es_dominio_email_desechable("BOT@YOPMAIL.COM") is True  # insensible a mayúsculas


def test_dominio_normal_no_es_desechable():
    assert es_dominio_email_desechable("persona@gmail.com") is False


def test_email_vacio_o_sin_arroba_no_es_desechable():
    assert es_dominio_email_desechable("") is False
    assert es_dominio_email_desechable(None) is False
    assert es_dominio_email_desechable("no-es-un-email") is False


def test_crear_cuenta_no_activa_ninguna_oposicion(db):
    # A diferencia del modelo anterior (una única prueba de cuenta,
    # arrancada al crearla), una cuenta recién creada no tiene ninguna
    # oposición activada todavía -- ni aunque el email ya esté verificado.
    # Activar la primera es una acción explícita del usuario (ver
    # activar_oposicion_usuario), normalmente desde Zona opositor.
    with patch("registro_progreso_usuario.enviar_email_bienvenida"), \
         patch("registro_progreso_usuario.enviar_email_alerta_nuevo_usuario"):
        inicializar_estadisticas_usuario(db, "u1", email="persona@gmail.com", email_verificado=True)
    usuario = db.leer(("usuarios", "u1"))
    assert usuario["suscripciones"] == {}


def test_inicializar_estadisticas_usuario_manda_la_bienvenida_una_sola_vez(db):
    # Bug real (11/08/2026, reportado por un usuario: "le han llegado tres
    # mensajes de bienvenida"): al registrarse, el frontend dispara varias
    # peticiones autenticadas casi a la vez (GET /mi-perfil desde el
    # listener global de auth.js, POST /registrar-usuario del propio
    # formulario...), todas pasando por requiere_login ->
    # inicializar_estadisticas_usuario. Antes era un simple "lee, si no
    # existe escribe" sin ninguna atomicidad -- varias peticiones podían ver
    # "no existe" antes de que ninguna hubiera escrito, y cada una mandaba
    # su propio correo. Ahora la creación va dentro de una transacción de
    # Firestore (ver utils.ejecutar_en_transaccion): el fake no simula la
    # concurrencia real entre hilos/peticiones (esa garantía la da el
    # servidor de Firestore, no el fake), pero este test sí deja fijado que
    # llamar repetidamente sobre el mismo usuario -- el caso normal de
    # "cada petición autenticada pasa por aquí" -- nunca vuelve a mandar el
    # correo una segunda vez.
    with patch("registro_progreso_usuario.enviar_email_bienvenida") as mock_email, \
         patch("registro_progreso_usuario.enviar_email_alerta_nuevo_usuario") as mock_alerta:
        inicializar_estadisticas_usuario(db, "u1", email="persona@gmail.com", email_verificado=True)
        assert mock_email.call_count == 1
        mock_alerta.assert_called_once_with(os.environ.get("BREVO_FROM_EMAIL"), "persona@gmail.com")
        inicializar_estadisticas_usuario(db, "u1", email="persona@gmail.com", email_verificado=True)
        inicializar_estadisticas_usuario(db, "u1", email="persona@gmail.com", email_verificado=True)
        assert mock_email.call_count == 1
        assert mock_alerta.call_count == 1


def test_activar_oposicion_con_email_verificado_arranca_la_prueba(db):
    with patch("registro_progreso_usuario.enviar_email_bienvenida"), \
         patch("registro_progreso_usuario.enviar_email_alerta_nuevo_usuario"):
        inicializar_estadisticas_usuario(db, "u1", email="persona@gmail.com", email_verificado=True)
    activar_oposicion_usuario(db, "u1", "AGE", email="persona@gmail.com", email_verificado=True)
    sub = db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]
    assert sub["plan"] == "gratis"
    assert sub["prueba_fin"] is not None
    dias_restantes = (datetime.fromisoformat(sub["prueba_fin"]) - datetime.utcnow()).days
    assert 6 <= dias_restantes <= 7


def test_activar_oposicion_sin_verificar_deja_la_prueba_pendiente(db):
    activar_oposicion_usuario(db, "u1", "AGE", email="persona@gmail.com", email_verificado=False)
    sub = db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]
    assert sub["plan"] == "gratis"
    assert sub["prueba_fin"] is None


def test_activar_oposicion_con_dominio_desechable_deja_la_prueba_pendiente(db):
    # Defensa en profundidad: aunque el claim email_verified viniera en
    # True, un dominio de correo desechable conocido tampoco se lleva la
    # prueba gratuita.
    activar_oposicion_usuario(db, "u1", "AGE", email="bot@mailinator.com", email_verificado=True)
    sub = db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]
    assert sub["prueba_fin"] is None


def test_verificar_el_email_mas_tarde_arranca_las_pruebas_pendientes(db):
    # Activa dos oposiciones sin haber verificado el correo todavía -> las
    # dos quedan pendientes. Verificarlo (en la siguiente petición
    # autenticada, ver auth_utils.requiere_login) arranca las dos de golpe,
    # no se pierden por no haberse verificado a tiempo.
    activar_oposicion_usuario(db, "u1", "AGE", email="persona@gmail.com", email_verificado=False)
    activar_oposicion_usuario(db, "u1", "GACE", email="persona@gmail.com", email_verificado=False)
    suscripciones = db.leer(("usuarios", "u1"))["suscripciones"]
    assert suscripciones["AGE"]["prueba_fin"] is None
    assert suscripciones["GACE"]["prueba_fin"] is None

    with patch("registro_progreso_usuario.enviar_email_bienvenida"), \
         patch("registro_progreso_usuario.enviar_email_alerta_nuevo_usuario"):
        inicializar_estadisticas_usuario(db, "u1", email="persona@gmail.com", email_verificado=True)
    suscripciones = db.leer(("usuarios", "u1"))["suscripciones"]
    assert suscripciones["AGE"]["prueba_fin"] is not None
    assert suscripciones["GACE"]["prueba_fin"] is not None


def test_activar_oposicion_es_idempotente_no_reinicia_una_prueba_en_marcha(db):
    activar_oposicion_usuario(db, "u1", "AGE", email="persona@gmail.com", email_verificado=True)
    fin_original = db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]["prueba_fin"]

    activar_oposicion_usuario(db, "u1", "AGE", email="persona@gmail.com", email_verificado=True)
    assert db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]["prueba_fin"] == fin_original


def test_activar_oposicion_no_reactiva_una_prueba_ya_terminada(db):
    fin_pasado = (datetime.utcnow() - timedelta(days=1)).isoformat()
    db.sembrar(("usuarios", "u1"), {"suscripciones": {"AGE": {"plan": "gratis", "prueba_fin": fin_pasado}}})
    activar_oposicion_usuario(db, "u1", "AGE", email="persona@gmail.com", email_verificado=True)
    assert db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]["prueba_fin"] == fin_pasado


def test_borrar_cuenta_y_volver_a_registrarse_no_da_otra_prueba_gratuita(db):
    # Bug real de abuso (24/08/2026): eliminar_cuenta_usuario borra por
    # completo usuarios/{uid} -- antes de este arreglo, nada impedía
    # volver a registrarse con el MISMO email real y conseguir otros 7
    # días de prueba gratuita, indefinidamente. La marca de "ya concedida"
    # vive en una colección aparte (pruebas_gratuitas_concedidas) que no
    # cuelga del uid, así que sobrevive al borrado de la cuenta.
    activar_oposicion_usuario(db, "u1-viejo", "AGE", email="persona@gmail.com", email_verificado=True)
    assert db.leer(("usuarios", "u1-viejo"))["suscripciones"]["AGE"]["prueba_fin"] is not None

    # Simula el borrado de la cuenta (gestion_cuenta.eliminar_cuenta_usuario
    # borra usuarios/{uid} entero, pero NUNCA la colección de pruebas
    # concedidas -- eso es justo lo que la hace sobrevivir).
    db.collection("usuarios").document("u1-viejo").delete()

    # Cuenta nueva, mismo email real -> la oposición se activa (plan
    # "gratis") pero SIN otra prueba gratuita.
    activar_oposicion_usuario(db, "u2-nuevo", "AGE", email="persona@gmail.com", email_verificado=True)
    sub = db.leer(("usuarios", "u2-nuevo"))["suscripciones"]["AGE"]
    assert sub["plan"] == "gratis"
    assert sub["prueba_fin"] is None


def test_prueba_gratuita_ya_gastada_no_bloquea_otra_oposicion_distinta(db):
    # La marca es por email + oposición, no solo por email -- una prueba ya
    # gastada en AGE no debe impedir la prueba de GACE con el mismo email.
    activar_oposicion_usuario(db, "u1", "AGE", email="persona@gmail.com", email_verificado=True)
    activar_oposicion_usuario(db, "u1", "GACE", email="persona@gmail.com", email_verificado=True)
    assert db.leer(("usuarios", "u1"))["suscripciones"]["GACE"]["prueba_fin"] is not None


def test_prueba_gratuita_ya_gastada_no_bloquea_a_otro_email_distinto(db):
    activar_oposicion_usuario(db, "u1", "AGE", email="persona@gmail.com", email_verificado=True)
    activar_oposicion_usuario(db, "u2", "AGE", email="otra-persona@gmail.com", email_verificado=True)
    assert db.leer(("usuarios", "u2"))["suscripciones"]["AGE"]["prueba_fin"] is not None


def test_verificar_el_email_mas_tarde_no_concede_una_prueba_ya_gastada(db):
    # Mismo caso que "borrar cuenta y volver a registrarse", pero pasando
    # por la activación DIFERIDA (inicializar_estadisticas_usuario, cuando
    # la oposición se activó sin el email verificado todavía) -- también
    # debe respetar la marca de prueba ya concedida.
    activar_oposicion_usuario(db, "u1-viejo", "AGE", email="persona@gmail.com", email_verificado=True)
    db.collection("usuarios").document("u1-viejo").delete()

    activar_oposicion_usuario(db, "u2-nuevo", "AGE", email="persona@gmail.com", email_verificado=False)
    assert db.leer(("usuarios", "u2-nuevo"))["suscripciones"]["AGE"]["prueba_fin"] is None

    with patch("registro_progreso_usuario.enviar_email_bienvenida"), \
         patch("registro_progreso_usuario.enviar_email_alerta_nuevo_usuario"):
        inicializar_estadisticas_usuario(db, "u2-nuevo", email="persona@gmail.com", email_verificado=True)
    assert db.leer(("usuarios", "u2-nuevo"))["suscripciones"]["AGE"]["prueba_fin"] is None


@pytest.fixture
def mini_app(db):
    app = Flask(__name__)

    @app.route("/solo-basico")
    @requiere_plan(db, "basico")
    def solo_basico():
        return jsonify({"ok": True})

    return app


def test_requiere_plan_bloquea_sin_haber_activado_la_oposicion(mini_app, db, usuario_autenticado):
    # Aunque el email esté verificado, una cuenta que nunca ha activado AGE
    # (oposición por defecto, ver obtener_oposicion_solicitada) no tiene
    # acceso -- verificar el email ya no basta por sí solo, hay que activar
    # la oposición primero (ver activar_oposicion_usuario).
    usuario_autenticado(uid="nuevo", email="nuevo@gmail.com", email_verified=True)
    cliente = mini_app.test_client()
    resp = cliente.get("/solo-basico", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 403


def test_requiere_plan_bloquea_a_quien_no_ha_verificado_el_email(mini_app, db, usuario_autenticado):
    usuario_autenticado(uid="nuevo", email="nuevo@gmail.com", email_verified=False)
    cliente = mini_app.test_client()
    resp = cliente.get("/solo-basico", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 403


def test_requiere_plan_deja_pasar_tras_activar_la_oposicion(mini_app, db, usuario_autenticado):
    activar_oposicion_usuario(db, "nuevo", "AGE", email="nuevo@gmail.com", email_verificado=True)
    usuario_autenticado(uid="nuevo", email="nuevo@gmail.com", email_verified=True)
    cliente = mini_app.test_client()
    resp = cliente.get("/solo-basico", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200


def test_requiere_plan_deja_pasar_a_quien_entra_con_google_tras_activar(mini_app, db, usuario_autenticado):
    # Un inicio de sesión con Google también manda email_verified=True en
    # el token (Google ya verifica la dirección) -- se prueba aparte del
    # caso general para dejar constancia de que Google no queda bloqueado
    # una vez ha activado su oposición.
    activar_oposicion_usuario(db, "goog1", "AGE", email="persona@gmail.com", email_verificado=True)
    usuario_autenticado(uid="goog1", email="persona@gmail.com", email_verified=True,
                         firebase={"sign_in_provider": "google.com"})
    cliente = mini_app.test_client()
    resp = cliente.get("/solo-basico", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200


# Quien ya paga por una oposición no debe seguir recibiendo el "empujón" de
# la prueba gratuita de 7 días al mirar otra que todavía no ha activado --
# sencillamente porque una oposición sin activar no tiene su propio
# prueba_fin, así que no hay nada que "empujar" (tiene_plan_de_pago_activo
# sigue existiendo solo para los mensajes del frontend, ver
# assets/plan.js).

def test_tiene_plan_de_pago_activo_detecta_cualquier_suscripcion_de_pago():
    assert tiene_plan_de_pago_activo({
        "suscripciones": {"AGE": {"plan": "premium", "subscription_status": "active"}}
    }) is True


def test_tiene_plan_de_pago_activo_ignora_planes_gratis_o_inactivos():
    assert tiene_plan_de_pago_activo({"suscripciones": {"AGE": {"plan": "gratis"}}}) is False
    assert tiene_plan_de_pago_activo({
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "past_due"}}
    }) is False
    assert tiene_plan_de_pago_activo({}) is False


def test_resolver_plan_efectivo_no_da_prueba_a_una_oposicion_sin_activar():
    datos = {
        "suscripciones": {
            "AGE": {"plan": "premium", "subscription_status": "active"},
            # AUXILIAR ni siquiera tiene entrada: nunca se ha activado.
        },
    }
    plan, sub = resolver_plan_efectivo(datos, oposicion="AUXILIAR")
    assert plan == "gratis"
    assert sub.get("subscription_status") != "trialing"


def test_resolver_plan_efectivo_da_prueba_a_la_oposicion_activada():
    fin_prueba = (datetime.utcnow() + timedelta(days=5)).isoformat()
    datos = {
        "suscripciones": {
            "AGE": {"plan": "premium", "subscription_status": "active"},
            "AUXILIAR": {"plan": "gratis", "prueba_fin": fin_prueba},
        },
    }
    plan, sub = resolver_plan_efectivo(datos, oposicion="AUXILIAR")
    assert plan == "premium"
    assert sub.get("subscription_status") == "trialing"


def test_perfil_usuario_expone_tiene_plan_de_pago_y_oposicion_activada(db):
    db.sembrar(("usuarios", "u1"), {
        "suscripciones": {"AGE": {"plan": "premium", "subscription_status": "active"}},
    })
    perfil = obtener_perfil_usuario(db, "u1", oposicion="AUXILIAR")
    assert perfil["tiene_plan_de_pago"] is True
    assert perfil["plan"] == "gratis"
    assert perfil["oposicion_activada"] is False

    perfil_age = obtener_perfil_usuario(db, "u1", oposicion="AGE")
    assert perfil_age["oposicion_activada"] is True
