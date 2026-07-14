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
os.environ.setdefault("SENDGRID_API_KEY", "dummy")
os.environ.setdefault("SENDGRID_FROM_EMAIL", "test@example.com")
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


@pytest.fixture
def flask_app():
    app_module.app.config.update(TESTING=True)
    return app_module.app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()
