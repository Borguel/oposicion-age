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


def test_resumen_salud_contenido_detecta_temas_sin_fichas(client, db):
    # Un tema con ficha y otro sin ninguna.
    db.sembrar(("Temario AGE", "bloque_01"), {"titulo": "Bloque I", "publicado": True})
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01"), {"titulo": "Con contenido"})
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "s1"), {"texto": "hola"})
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_02"), {"titulo": "Vacío"})
    with _como():
        datos = client.get("/admin/api/resumen?oposicion=AGE", headers=_AUTH).get_json()
    salud = datos["salud_contenido"]
    assert salud["temas_total"] == 2
    sin = [t["tema"] for t in salud["temas_sin_contenido"]]
    assert sin == ["tema_02"]


def test_detalle_usuario_agrega_tests_y_racha(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@x.com",
        "suscripciones": {"AGE": {"plan": "premium"}},
        "racha": {"racha_actual": 7},
        "estadisticas": {"AGE": {"historial_tests": [{"nota": 8}, {"nota": 9}]}},
    })
    with _como():
        d = client.get("/admin/api/usuarios/u1", headers=_AUTH).get_json()
    assert d["tests_total"] == 2
    assert d["racha_actual"] == 7
    assert d["ultima_nota"] == 9
    assert d["plan"] == "premium"


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


# ---------- Utilidades nuevas (1,2,3,5,16) ----------
def test_resumen_calcula_mrr(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "a@x.com", "suscripciones": {"AGE": {"plan": "premium"}}})
    db.sembrar(("usuarios", "u2"), {"email": "b@x.com", "suscripciones": {"AGE": {"plan": "basico"}, "GACE": {"plan": "premium"}}})
    with _como():
        d = client.get("/admin/api/resumen", headers=_AUTH).get_json()
    assert d["suscripciones_pago"] == 3
    assert d["mrr"] == round(9.99 + 4.99 + 9.99, 2)


def test_toggle_admin_asigna_y_protege_autobloqueo(client, db):
    class _U:
        email = "otro@x.com"
        custom_claims = None
    llamado = {}
    with _como(uid="admin1"), \
         patch("blueprints.admin.firebase_auth.get_user", return_value=_U()), \
         patch("blueprints.admin.firebase_auth.set_custom_user_claims",
               side_effect=lambda uid, claims: llamado.update(claims=claims)):
        ok = client.patch("/admin/api/usuarios/otro/admin", json={"admin": True}, headers=_AUTH)
        assert ok.status_code == 200
        assert llamado["claims"]["admin"] is True
        # No puede quitarse admin a sí mismo.
        propio = client.patch("/admin/api/usuarios/admin1/admin", json={"admin": False}, headers=_AUTH)
        assert propio.status_code == 400


def test_reactivar_pregunta(client, db):
    db.sembrar(("examenes_oficiales_AGE", "p1"), {"tipo": "pregunta", "pregunta": "x", "activa": False})
    with _como():
        client.post("/admin/api/preguntas/p1/reactivar?oposicion=AGE", headers=_AUTH)
    assert db.leer(("examenes_oficiales_AGE", "p1"))["activa"] is True


def test_export_usuarios_csv(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "a@x.com", "suscripciones": {"AGE": {"plan": "premium"}}})
    with _como():
        resp = client.get("/admin/api/usuarios/export", headers=_AUTH)
    assert resp.status_code == 200
    assert "text/csv" in resp.content_type
    assert "a@x.com" in resp.get_data(as_text=True)


def test_reportes_adjuntan_pregunta_oficial(client, db):
    enunciado = "¿Pregunta oficial?"
    db.sembrar(("examenes_oficiales_AGE", "p1"), {
        "tipo": "pregunta", "pregunta": enunciado,
        "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"}, "respuesta_correcta": "C",
    })
    db.sembrar(("reportes_preguntas", "r1"), {
        "pregunta_texto": enunciado, "oposicion": "AGE", "motivo": "dudosa", "estado": "pendiente", "fecha": "2026-01-01",
    })
    with _como():
        reportes = client.get("/admin/api/reportes?estado=pendiente", headers=_AUTH).get_json()["reportes"]
    assert reportes[0]["pregunta_oficial"]["respuesta_correcta"] == "C"


# ---------- Editor temario, import, sistema, banner, notas ----------
def test_crear_bloque_y_tema_y_renombrar(client, db):
    with _como():
        assert client.post("/admin/api/temario/AGE/nuevo-bloque",
                           json={"id": "bloque_09", "titulo": "Nuevo"}, headers=_AUTH).status_code == 201
        assert client.post("/admin/api/temario/AGE/bloque_09/nuevo-tema",
                           json={"id": "tema_01", "titulo": "T"}, headers=_AUTH).status_code == 201
        client.patch("/admin/api/temario/AGE/bloque_09", json={"titulo": "Renombrado"}, headers=_AUTH)
        client.patch("/admin/api/temario/AGE/bloque_09/tema_01/titulo", json={"titulo": "Tema nuevo"}, headers=_AUTH)
    assert db.leer(("Temario AGE", "bloque_09"))["titulo"] == "Renombrado"
    assert db.leer(("Temario AGE", "bloque_09", "temas", "tema_01"))["titulo"] == "Tema nuevo"


def test_crear_bloque_rechaza_id_invalido(client, db):
    with _como():
        r = client.post("/admin/api/temario/AGE/nuevo-bloque", json={"id": "con/barra"}, headers=_AUTH)
    assert r.status_code == 400


def test_importar_preguntas_lote(client, db):
    lote = {
        "oposicion": "AGE", "examen": "AGE 2025",
        "preguntas": [
            {"pregunta": "¿P1?", "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"}, "respuesta_correcta": "A"},
            {"pregunta": "", "opciones": {"A": "a"}, "respuesta_correcta": "Z"},  # inválida
        ],
    }
    with _como():
        r = client.post("/admin/api/preguntas/importar", json=lote, headers=_AUTH).get_json()
    assert r["creadas"] == 1
    assert len(r["errores"]) == 1 and r["errores"][0]["indice"] == 1


def test_sistema_reporta_servicios(client, db, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    with _como():
        servicios = client.get("/admin/api/sistema", headers=_AUTH).get_json()["servicios"]
    por_nombre = {s["nombre"]: s["ok"] for s in servicios}
    assert por_nombre["IA (DeepSeek)"] is True
    assert por_nombre["Errores (Sentry)"] is False


def test_banner_guardar_y_lectura_publica(client, db):
    with _como():
        client.put("/admin/api/banner", json={"activo": True, "texto": "Hola", "tipo": "aviso"}, headers=_AUTH)
    # Lectura pública sin token.
    pub = client.get("/banner-global").get_json()
    assert pub["activo"] is True and pub["texto"] == "Hola" and pub["tipo"] == "aviso"
    # Desactivado -> no expone el texto.
    with _como():
        client.put("/admin/api/banner", json={"activo": False, "texto": "Hola"}, headers=_AUTH)
    assert client.get("/banner-global").get_json() == {"activo": False}


def test_notas_internas_usuario(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com"})
    with _como():
        client.patch("/admin/api/usuarios/u1/notas", json={"notas": "cliente VIP"}, headers=_AUTH)
        d = client.get("/admin/api/usuarios/u1", headers=_AUTH).get_json()
    assert d["notas_admin"] == "cliente VIP"


# ---------- Auditoría (9) ----------
def test_cambio_de_plan_queda_en_auditoria(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "suscripciones": {"AGE": {"plan": "gratis"}}})
    with _como(uid="admin1", email="admin@x.com"):
        client.patch("/admin/api/usuarios/u1/plan",
                     json={"plan": "premium", "oposicion": "AGE", "motivo": "regalo"}, headers=_AUTH)
        entradas = client.get("/admin/api/auditoria", headers=_AUTH).get_json()["entradas"]
    assert entradas[0]["accion"] == "usuario_cambiar_plan"
    assert entradas[0]["objetivo"] == "u1"
    assert entradas[0]["email_admin"] == "admin@x.com"
    assert "premium" in entradas[0]["detalle"]


def test_auditoria_ordena_reciente_primero(client, db):
    with _como():
        client.post("/admin/api/preguntas", json={
            "oposicion": "AGE", "pregunta": "¿P1?",
            "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"}, "respuesta_correcta": "A",
        }, headers=_AUTH)
        client.post("/admin/api/preguntas", json={
            "oposicion": "AGE", "pregunta": "¿P2?",
            "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"}, "respuesta_correcta": "A",
        }, headers=_AUTH)
        entradas = client.get("/admin/api/auditoria", headers=_AUTH).get_json()["entradas"]
    assert len(entradas) == 2
    assert entradas[0]["fecha"] >= entradas[1]["fecha"]


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
