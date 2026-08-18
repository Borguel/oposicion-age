"""Pruebas de la clasificación anónima y opcional (blueprints/ranking.py):
que nadie aparezca sin haberse apuntado, que el alias se valide, y que
salir del ranking oculte al usuario sin borrarle la racha."""
from unittest.mock import patch

from conftest import sembrar_usuario_activo


def test_ranking_vacio_si_nadie_se_ha_apuntado(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico", racha={"racha_actual": 5})
    usuario_autenticado(email_verified=True)
    resp = client.get("/ranking", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    datos = resp.get_json()
    assert datos["ranking"] == []
    assert datos["total_participantes"] == 0


def test_unirse_con_alias_invalido_devuelve_error(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    resp = client.post("/ranking/unirse", json={"alias": "ab"}, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 400


def test_unirse_aparece_en_el_ranking_con_alias_no_con_email(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    resp = client.post("/ranking/unirse", json={"alias": "Opositor Anónimo"}, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    resp = client.get("/ranking/mi-estado", headers={"Authorization": "Bearer x"})
    assert resp.get_json() == {"participa": True, "alias": "Opositor Anónimo"}

    resp = client.get("/ranking", headers={"Authorization": "Bearer x"})
    datos = resp.get_json()
    assert datos["ranking"] == [{"alias": "Opositor Anónimo", "racha_actual": 0, "tu": True}]
    assert "u1@example.com" not in str(datos)


def test_ranking_ordenado_por_racha_actual_descendente(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1")
    db.sembrar(("usuarios", "u2"), {"racha": {"racha_actual": 10}, "ranking_optin": True, "ranking_alias": "Rápido"})
    db.sembrar(("usuarios", "u3"), {"racha": {"racha_actual": 3}, "ranking_optin": True, "ranking_alias": "Lento"})
    usuario_autenticado(email_verified=True)
    resp = client.get("/ranking", headers={"Authorization": "Bearer x"})
    alias_en_orden = [p["alias"] for p in resp.get_json()["ranking"]]
    assert alias_en_orden == ["Rápido", "Lento"]


def test_ranking_usa_cache_dentro_del_ttl_y_recalcula_pasado_el_ttl(client, db, usuario_autenticado):
    # Mismo patrón que las cachés del panel admin (test_admin.py): sin
    # caché, /ranking recorría TODA la colección "usuarios" en cada carga.
    # Un cambio de racha directamente en el store (sin pasar por
    # /ranking/unirse ni /ranking/salir, que sí invalidan la caché
    # explícitamente) no debe verse hasta que venza el TTL.
    import blueprints.ranking as ranking_module
    import utils

    sembrar_usuario_activo(db, "u1", racha={"racha_actual": 1}, ranking_optin=True, ranking_alias="Constante")
    usuario_autenticado(email_verified=True)
    primero = client.get("/ranking", headers={"Authorization": "Bearer x"}).get_json()
    assert primero["ranking"][0]["racha_actual"] == 1

    # Cambio directo en el store, sin invalidar la caché a propósito.
    actual = db.leer(("usuarios", "u1"))
    db.sembrar(("usuarios", "u1"), {**actual, "racha": {"racha_actual": 99}})
    dentro_ttl = client.get("/ranking", headers={"Authorization": "Bearer x"}).get_json()
    assert dentro_ttl["ranking"][0]["racha_actual"] == 1  # todavía la cacheada

    ahora = utils.time.time()
    with patch("utils.time.time", return_value=ahora + ranking_module._TTL_CACHE_RANKING_SEGUNDOS + 1):
        tras_ttl = client.get("/ranking", headers={"Authorization": "Bearer x"}).get_json()
    assert tras_ttl["ranking"][0]["racha_actual"] == 99


def test_salir_del_ranking_lo_oculta_sin_borrar_la_racha(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    client.post("/ranking/unirse", json={"alias": "Temporal"}, headers={"Authorization": "Bearer x"})
    resp = client.post("/ranking/salir", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    resp = client.get("/ranking/mi-estado", headers={"Authorization": "Bearer x"})
    assert resp.get_json()["participa"] is False

    resp = client.get("/ranking", headers={"Authorization": "Bearer x"})
    assert resp.get_json()["ranking"] == []

    guardado = db.leer(("usuarios", "u1"))
    assert guardado["ranking_optin"] is False
