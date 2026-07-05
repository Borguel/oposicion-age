"""Pruebas del endpoint público /estadisticas-publicas: cifras agregadas
entre todos los usuarios (nunca datos de un usuario concreto), sin
autenticación, y cacheadas en memoria unos minutos para no lanzar dos
aggregation queries de Firestore en cada visita a la home."""
import app as app_module


def _limpiar_cache():
    app_module._cache_estadisticas_publicas = None


def test_estadisticas_publicas_sin_autenticacion(client):
    _limpiar_cache()
    resp = client.get("/estadisticas-publicas")
    assert resp.status_code != 401


def test_estadisticas_publicas_cuenta_usuarios_y_tests(client, db):
    _limpiar_cache()
    db.sembrar(("usuarios", "u1"), {})
    db.sembrar(("usuarios", "u2"), {})
    db.sembrar(("usuarios", "u1", "tests", "t1"), {})
    db.sembrar(("usuarios", "u1", "tests", "t2"), {})
    db.sembrar(("usuarios", "u2", "tests", "t3"), {})

    resp = client.get("/estadisticas-publicas")
    assert resp.status_code == 200
    datos = resp.get_json()
    assert datos["total_usuarios"] == 2
    assert datos["total_tests"] == 3


def test_estadisticas_publicas_usa_cache(client, db):
    _limpiar_cache()
    db.sembrar(("usuarios", "u1"), {})
    primera = client.get("/estadisticas-publicas").get_json()
    assert primera["total_usuarios"] == 1

    db.sembrar(("usuarios", "u2"), {})
    segunda = client.get("/estadisticas-publicas").get_json()
    # Dentro de la ventana de caché: no ve el nuevo usuario todavía.
    assert segunda["total_usuarios"] == 1
