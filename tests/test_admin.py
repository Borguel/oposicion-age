"""Pruebas del panel de administración (blueprints/admin.py + requiere_admin).
Lo más importante: que NINGUNA ruta /admin/* sea accesible sin el custom
claim admin=true, y que las operaciones (soft delete, admin_override,
publicado, agregación de fallos) hagan lo que dicen."""
import json
from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def _como(admin=True, uid="admin1", email="admin@example.com"):
    decoded = {"uid": uid, "email": email}
    if admin:
        decoded["admin"] = True
    with patch("auth_utils.firebase_auth.verify_id_token", return_value=decoded):
        yield


_AUTH = {"Authorization": "Bearer x"}


def _sembrar_tema(db, coleccion="Temario AGE", publicado_bloque=True):
    db.sembrar((coleccion, "bloque_01"), {"titulo": "Bloque I", "publicado": publicado_bloque})
    db.sembrar((coleccion, "bloque_01", "temas", "tema_01"), {"titulo": "La Constitución"})
    db.sembrar((coleccion, "bloque_01", "temas", "tema_01", "subbloques", "sub_1"),
               {"titulo": "Estructura", "texto": "Texto del chunk 1."})


# ---------- Seguridad ----------
def test_sin_token_devuelve_401(client):
    resp = client.get("/admin/api/resumen")
    assert resp.status_code == 401


def test_usuario_no_admin_devuelve_403(client):
    with _como(admin=False):
        resp = client.get("/admin/api/resumen", headers=_AUTH)
    assert resp.status_code == 403


def test_admin_accede(client, db):
    with _como(admin=True):
        resp = client.get("/admin/api/resumen", headers=_AUTH)
    assert resp.status_code == 200
    assert "usuarios_totales" in resp.get_json()


# ---------- Dashboard ----------
def test_resumen_agrega_planes_y_fallos(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "suscripciones": {"AGE": {"plan": "premium"}}})
    db.sembrar(("usuarios", "u2"), {"email": "u2@x.com", "suscripciones": {"AGE": {"plan": "gratis"}}})
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "h1"),
               {"oposicion": "AGE", "tema_id": "bloque_01-tema_01", "veces_fallada": 3})
    db.sembrar(("usuarios", "u2", "preguntas_falladas", "h1"),
               {"oposicion": "AGE", "tema_id": "bloque_01-tema_01", "veces_fallada": 2})
    with _como():
        resp = client.get("/admin/api/resumen", headers=_AUTH)
    datos = resp.get_json()
    assert datos["usuarios_totales"] == 2
    assert datos["usuarios_por_plan"]["premium"] == 1
    assert datos["usuarios_por_plan"]["gratis"] == 1
    assert datos["top_temas_fallados"][0]["fallos"] == 5  # 3 + 2, agregado


# ---------- Temario ----------
def test_temario_arbol_y_chunks(client, db):
    _sembrar_tema(db)
    with _como():
        arbol = client.get("/admin/api/temario/AGE", headers=_AUTH).get_json()
        assert arbol["bloques"][0]["temas"][0]["num_chunks"] == 1
        tema = client.get("/admin/api/temario/AGE/bloque_01/tema_01", headers=_AUTH).get_json()
        assert tema["chunks"][0]["texto"] == "Texto del chunk 1."


def test_temario_editar_y_borrar_chunk(client, db):
    _sembrar_tema(db)
    with _como():
        client.put("/admin/api/temario/AGE/bloque_01/tema_01/sub_1",
                   json={"texto": "Texto corregido"}, headers=_AUTH)
        assert db.leer(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1"))["texto"] == "Texto corregido"
        client.delete("/admin/api/temario/AGE/bloque_01/tema_01/sub_1", headers=_AUTH)
        assert db.leer(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1")) is None


def test_temario_publicar_borrador_oculta_de_navegacion(client, db):
    _sembrar_tema(db)
    with _como():
        client.patch("/admin/api/temario/AGE/bloque_01/publicado",
                     json={"publicado": False}, headers=_AUTH)
    # Ahora un usuario normal no debe ver ese bloque en /temas-disponibles.
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "u1@x.com"}):
        temas = client.get("/temas-disponibles?oposicion=AGE", headers=_AUTH).get_json()["temas"]
    assert temas == []


# ---------- Preguntas ----------
def test_preguntas_listar_con_fallos_y_soft_delete(client, db):
    from banco_fallos import _id_pregunta
    enunciado = "¿Qué dice el artículo 1?"
    db.sembrar(("examenes_oficiales_AGE", "p1"), {
        "tipo": "pregunta", "pregunta": enunciado,
        "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"},
        "respuesta_correcta": "A", "tema_id": "bloque_01-tema_01", "examen": "AGE 2025",
    })
    # Un fallo de esa pregunta en el banco de un usuario (mismo hash).
    db.sembrar(("usuarios", "u1", "preguntas_falladas", _id_pregunta("AGE", enunciado)),
               {"oposicion": "AGE", "tema_id": "bloque_01-tema_01", "veces_fallada": 4})
    with _como():
        listado = client.get("/admin/api/preguntas?oposicion=AGE", headers=_AUTH).get_json()
        assert listado["preguntas"][0]["veces_fallada"] == 4
        # Soft delete: no borra, marca activa=false.
        client.delete("/admin/api/preguntas/p1?oposicion=AGE", headers=_AUTH)
    doc = db.leer(("examenes_oficiales_AGE", "p1"))
    assert doc is not None and doc["activa"] is False


def test_preguntas_crear_valida_opciones(client, db):
    with _como():
        mala = client.post("/admin/api/preguntas",
                           json={"oposicion": "AGE", "pregunta": "x", "opciones": {"A": "a"}, "respuesta_correcta": "A"},
                           headers=_AUTH)
        assert mala.status_code == 400
        buena = client.post("/admin/api/preguntas", json={
            "oposicion": "AGE", "pregunta": "¿Pregunta?",
            "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"}, "respuesta_correcta": "B",
            "tema_id": "bloque_01-tema_01",
        }, headers=_AUTH)
        assert buena.status_code == 201


# ---------- Usuarios ----------
def test_usuarios_cambiar_plan_guarda_admin_override(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "suscripciones": {"AGE": {"plan": "gratis"}}})
    with _como(uid="admin1", email="admin@x.com"):
        resp = client.patch("/admin/api/usuarios/u1/plan",
                            json={"plan": "premium", "oposicion": "AGE", "motivo": "problema con Stripe"},
                            headers=_AUTH)
    assert resp.status_code == 200
    datos = db.leer(("usuarios", "u1"))
    assert datos["suscripciones"]["AGE"]["plan"] == "premium"
    assert datos["admin_override"]["por"] == "admin1"
    assert datos["admin_override"]["motivo"] == "problema con Stripe"


def test_usuarios_resetear_racha(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "racha": {"racha_actual": 15}})
    with _como():
        client.post("/admin/api/usuarios/u1/resetear-racha", headers=_AUTH)
    assert db.leer(("usuarios", "u1"))["racha"]["racha_actual"] == 0


# ---------- Bootstrap (primer admin sin Shell) ----------
def test_bootstrap_desactivado_sin_secreto(client, monkeypatch):
    monkeypatch.delenv("ADMIN_BOOTSTRAP_SECRET", raising=False)
    resp = client.post("/admin/api/bootstrap", json={"uid": "u1", "secreto": "x"})
    assert resp.status_code == 404


def test_bootstrap_secreto_incorrecto(client, monkeypatch):
    monkeypatch.setenv("ADMIN_BOOTSTRAP_SECRET", "clave-buena")
    resp = client.post("/admin/api/bootstrap", json={"uid": "u1", "secreto": "clave-mala"})
    assert resp.status_code == 403


def test_bootstrap_asigna_claim(client, monkeypatch):
    monkeypatch.setenv("ADMIN_BOOTSTRAP_SECRET", "clave-buena")

    class _U:
        email = "yo@example.com"
        custom_claims = None

    llamado = {}

    def _set_claims(uid, claims):
        llamado["uid"] = uid
        llamado["claims"] = claims

    with patch("blueprints.admin.firebase_auth.get_user", return_value=_U()), \
         patch("blueprints.admin.firebase_auth.set_custom_user_claims", side_effect=_set_claims):
        resp = client.post("/admin/api/bootstrap",
                           json={"uid": "abc123", "secreto": "clave-buena"})
    assert resp.status_code == 200
    assert llamado["uid"] == "abc123"
    assert llamado["claims"]["admin"] is True


def test_bootstrap_por_get_desde_navegador(client, monkeypatch):
    monkeypatch.setenv("ADMIN_BOOTSTRAP_SECRET", "clave-buena")

    class _U:
        email = "yo@example.com"
        custom_claims = None

    llamado = {}
    with patch("blueprints.admin.firebase_auth.get_user", return_value=_U()), \
         patch("blueprints.admin.firebase_auth.set_custom_user_claims",
               side_effect=lambda uid, claims: llamado.update(uid=uid, claims=claims)):
        resp = client.get("/admin/api/bootstrap?uid=abc123&secreto=clave-buena")
    assert resp.status_code == 200
    assert llamado["claims"]["admin"] is True


# ---------- Reportes ----------
def test_usuario_reporta_y_admin_lo_revisa(client, db):
    # Un usuario normal reporta.
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "u1@x.com"}):
        r = client.post("/reportar-pregunta",
                        json={"pregunta_texto": "¿Pregunta con error?", "motivo": "La B también es correcta", "oposicion": "AGE"},
                        headers=_AUTH)
        assert r.status_code == 201
    # El admin la ve pendiente y la marca revisada.
    with _como():
        reportes = client.get("/admin/api/reportes?estado=pendiente", headers=_AUTH).get_json()["reportes"]
        assert len(reportes) == 1
        rid = reportes[0]["id"]
        assert reportes[0]["motivo"] == "La B también es correcta"
        client.patch(f"/admin/api/reportes/{rid}", json={"estado": "revisado"}, headers=_AUTH)
        pendientes = client.get("/admin/api/reportes?estado=pendiente", headers=_AUTH).get_json()["reportes"]
        assert pendientes == []
