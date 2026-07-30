"""Limiter compartido, creado SIN app (patrón de fábrica de flask-limiter:
Limiter(...) aquí, limiter.init_app(app) en app.py) para que los blueprints
puedan importar este mismo objeto y decorar sus propias rutas con
@limiter.limit(...) sin crear un import circular -- app.py importa los
blueprints, así que un blueprint no puede importar de vuelta app.py.

Misma configuración que ya usaba el limiter creado directamente en app.py:
por IP (Render sirve un único proceso, sin necesitar un backend compartido
como Redis para que el límite sea efectivo), desactivable en tests."""
import os

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per hour"],
    storage_uri="memory://",
    # Desactivado en tests (ver conftest.py): con cientos de peticiones de
    # test client en una misma sesión de pytest, todas "desde la misma IP",
    # se dispararía el límite real y los tests empezarían a fallar por un
    # 429 que no tiene nada que ver con lo que cada test comprueba.
    enabled=os.getenv("RATELIMIT_ENABLED", "true").lower() != "false",
)
