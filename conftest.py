"""Configuración compartida de pytest: prepara variables de entorno
dummy y sustituye Firebase Admin (credenciales, inicialización y el
cliente de Firestore) por un doble en memoria ANTES de importar app.py,
para poder ejecutar los tests sin credenciales reales ni red."""
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("FIREBASE_CREDENTIALS_JSON", "{}")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_dummy")
os.environ.setdefault("STRIPE_PRICE_ID_BASICO", "price_basico_test")
os.environ.setdefault("STRIPE_PRICE_ID_PREMIUM", "price_premium_test")
os.environ.setdefault("DEEPSEEK_API_KEY", "dummy")
os.environ.setdefault("OPENAI_API_KEY", "dummy")
os.environ.setdefault("BREVO_API_KEY", "dummy")
os.environ.setdefault("BREVO_FROM_EMAIL", "test@example.com")
os.environ.setdefault("FRONTEND_URL", "http://localhost:8080")
os.environ.setdefault("API_SECRET_KEY", "")
os.environ.setdefault("RATELIMIT_ENABLED", "false")

import pytest

from tests.fakes import FakeFirestore
from utils import _limpiar_cache_temario

fake_db = FakeFirestore()

with patch("firebase_admin.credentials.Certificate", return_value=MagicMock()), \
     patch("firebase_admin.initialize_app", return_value=MagicMock()), \
     patch("firebase_admin.firestore.client", return_value=fake_db):
    import app as app_module


@pytest.fixture(autouse=True)
def _limpiar_fake_db():
    fake_db.reset()
    _limpiar_cache_temario()
    import limites_uso
    limites_uso.invalidar_cache_limites()  # evita que overrides de un test se filtren a otro
    yield


@pytest.fixture
def db():
    return fake_db


def sembrar_usuario_activo(db, uid, plan="premium", email=None, oposicion="AGE", **campos_extra):
    """Siembra usuarios/{uid} con una suscripción de pago ya activa (evita
    tener que pasar por inicializar_estadisticas_usuario para tener acceso
    en tests que no están probando específicamente el bloqueo por plan --
    desde que existe la prueba gratuita de 7 días, un usuario sembrado a
    mano sin esto no tiene `prueba_fin` y resuelve a plan "gratis")."""
    datos = {
        "email": email or f"{uid}@example.com",
        "suscripciones": {oposicion: {"plan": plan, "subscription_status": "active"}},
        **campos_extra,
    }
    db.sembrar(("usuarios", uid), datos)
    return datos


@pytest.fixture
def flask_app():
    app_module.app.config.update(TESTING=True)
    return app_module.app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def usuario_autenticado():
    """Mockea auth_utils.firebase_auth.verify_id_token para simular una
    sesión autenticada (17/08/2026, consolidación de la función local
    `_con_sesion` que ~19 archivos de tests reimplementaban a mano, cada
    uno con su propio try/finally para parar el parche).

    Se usa como FÁBRICA, no como valor fijo: `usuario_autenticado()` (con
    los mismos valores por defecto que ya usaban todas esas copias, uid
    "u1"/email "u1@example.com"), o `usuario_autenticado(uid=..., email=...,
    admin=True, email_verified=True)` para los casos que necesitan otra
    identidad. email_verified NO se incluye en el token salvo que se pida
    explícitamente -- algunos archivos lo hacían, otros no, y no es
    cosmético: auth_utils.requiere_login lee este campo para decidir si la
    prueba gratuita de 7 días arranca ya o queda pendiente de confirmar el
    correo (ver inicializar_estadisticas_usuario), así que unificarlo a
    ciegas habría cambiado comportamiento real en la mitad de los tests que
    lo usan. Puede llamarse varias veces en un mismo test (p. ej. para
    cambiar de identidad a mitad) -- cada parche se para solo al terminar
    el test, sin try/finally manual."""
    parches = []

    def _iniciar(uid="u1", email="u1@example.com", admin=False, email_verified=None, **extra):
        datos_token = {"uid": uid, "email": email, **extra}
        if admin:
            datos_token["admin"] = True
        if email_verified is not None:
            datos_token["email_verified"] = email_verified
        parche = patch("auth_utils.firebase_auth.verify_id_token", return_value=datos_token)
        parche.start()
        parches.append(parche)
        return parche

    yield _iniciar
    for parche in parches:
        parche.stop()
