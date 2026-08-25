"""Pruebas del panel de administración (blueprints/admin.py + requiere_admin).
Lo más importante: que NINGUNA ruta /admin/* sea accesible sin el custom
claim admin=true, y que las operaciones (soft delete, admin_override,
publicado, agregación de fallos) hagan lo que dicen."""
import json
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

import blueprints.admin as admin_module
from conftest import sembrar_usuario_activo


def _con_sesion_usuario(cliente, uid="u1", email="u1@example.com"):
    """Sesión de un usuario normal (no admin) -- para probar rutas como
    /cancelar-suscripcion, protegidas por requiere_login, no
    requiere_permiso/requiere_admin."""
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email})
    parche.start()
    return parche


@contextmanager
def _como(admin=True, uid="admin1", email="admin@example.com", permisos=None):
    decoded = {"uid": uid, "email": email}
    if admin:
        decoded["admin"] = True
    if permisos:
        decoded["permisos"] = permisos
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


# ---------- Roles / permisos granulares ----------
def test_permiso_reportes_accede_solo_a_reportes(client, db):
    # Un moderador con solo 'reportes' entra a reportes pero no al temario.
    with _como(admin=False, uid="mod1", permisos=["reportes"]):
        assert client.get("/admin/api/reportes?estado=pendiente", headers=_AUTH).status_code == 200
        assert client.get("/admin/api/temario/AGE", headers=_AUTH).status_code == 403
        assert client.get("/admin/api/usuarios", headers=_AUTH).status_code == 403


def test_permiso_temario_puede_editar_pero_no_usuarios(client, db):
    _sembrar_tema(db)
    with _como(admin=False, uid="ed1", permisos=["temario"]):
        assert client.get("/admin/api/temario/AGE", headers=_AUTH).status_code == 200
        assert client.get("/admin/api/usuarios", headers=_AUTH).status_code == 403


def test_sin_permisos_todo_403(client, db):
    with _como(admin=False, uid="x", permisos=[]):
        assert client.get("/admin/api/resumen", headers=_AUTH).status_code == 403
        assert client.get("/admin/api/reportes", headers=_AUTH).status_code == 403


def test_asignar_roles_requiere_admin_total(client, db):
    # Un usuario con permiso 'usuarios' NO puede repartir roles (eso es solo
    # del super-admin).
    with _como(admin=False, uid="u", permisos=["usuarios"]):
        r = client.patch("/admin/api/usuarios/otro/roles", json={"permisos": ["temario"]}, headers=_AUTH)
    assert r.status_code == 403


def test_admin_asigna_roles(client, db):
    class _U:
        custom_claims = None
    llamado = {}
    with _como(admin=True), \
         patch("blueprints.admin.firebase_auth.get_user", return_value=_U()), \
         patch("blueprints.admin.firebase_auth.set_custom_user_claims",
               side_effect=lambda uid, claims: llamado.update(claims=claims)):
        r = client.patch("/admin/api/usuarios/otro/roles",
                         json={"permisos": ["temario", "reportes", "inventado"]}, headers=_AUTH)
    assert r.status_code == 200
    assert set(llamado["claims"]["permisos"]) == {"temario", "reportes"}  # 'inventado' se descarta


# ---------- Crear usuarios ----------
def test_crear_usuario_da_de_alta_y_pone_roles(client, db):
    creado = type("U", (), {"uid": "new1"})()
    claims = {}
    with _como(admin=True), \
         patch("blueprints.admin.firebase_auth.create_user", return_value=creado), \
         patch("blueprints.admin.firebase_auth.set_custom_user_claims",
               side_effect=lambda uid, c: claims.update(c)):
        r = client.post("/admin/api/usuarios", json={
            "email": "nuevo@x.com", "password": "secreto123", "nombre": "Nuevo",
            "permisos": ["reportes"],
        }, headers=_AUTH)
    assert r.status_code == 201
    assert claims == {"permisos": ["reportes"]}
    assert db.leer(("usuarios", "new1"))["email"] == "nuevo@x.com"


def test_crear_usuario_valida_email_y_password(client, db):
    with _como(admin=True):
        assert client.post("/admin/api/usuarios", json={"email": "malo", "password": "secreto123"}, headers=_AUTH).status_code == 400
        assert client.post("/admin/api/usuarios", json={"email": "ok@x.com", "password": "123"}, headers=_AUTH).status_code == 400


def test_crear_usuario_requiere_admin_total(client, db):
    with _como(admin=False, permisos=["usuarios"]):
        r = client.post("/admin/api/usuarios", json={"email": "ok@x.com", "password": "secreto123"}, headers=_AUTH)
    assert r.status_code == 403


# ---------- Analítica de contenido ----------
def test_analitica_agrega_rendimiento_y_sin_actividad(client, db):
    _sembrar_tema(db)  # bloque_01 / tema_01 (con contenido) + tema sin actividad
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_02"), {"titulo": "Sin tocar"})
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "estadisticas": {"AGE": {
        "rendimiento_por_tema": {"bloque_01-tema_01": {"aciertos": 7, "fallos": 3, "blancos": 0}}}}})
    db.sembrar(("usuarios", "u2"), {"email": "u2@x.com", "estadisticas": {"AGE": {
        "rendimiento_por_tema": {"bloque_01-tema_01": {"aciertos": 1, "fallos": 9, "blancos": 0}}}}})
    with _como():
        d = client.get("/admin/api/analitica-contenido?oposicion=AGE", headers=_AUTH).get_json()
    tema = d["temas"][0]
    assert tema["tema_id"] == "bloque_01-tema_01"
    assert tema["intentos"] == 20  # (7+3) + (1+9)
    assert tema["tasa_acierto"] == 40.0  # 8 aciertos / 20 respondidas
    sin = [t["tema_id"] for t in d["sin_actividad"]]
    assert "bloque_01-tema_02" in sin


# ---------- Banco de preguntas (Test Personalizado) ----------
def test_banco_preguntas_requiere_permiso_temario(client, db):
    with _como(admin=False, permisos=["reportes"]):
        r = client.get("/admin/api/banco-preguntas", headers=_AUTH)
    assert r.status_code == 403


def test_banco_preguntas_totales_por_oposicion(client, db):
    db.sembrar(("banco_preguntas_ia_AGE", "p1"), {"tema_id": "bloque_01-tema_01"})
    db.sembrar(("banco_preguntas_ia_AGE", "p2"), {"tema_id": "bloque_01-tema_01"})
    db.sembrar(("banco_preguntas_ia_GACE", "p1"), {"tema_id": "bloque_01-tema_01"})
    with _como():
        d = client.get("/admin/api/banco-preguntas?oposicion=AGE", headers=_AUTH).get_json()
    assert d["totales_por_oposicion"] == {"AGE": 2, "GACE": 1, "AUXILIAR": 0, "METRO": 0}
    assert d["total_oposicion"] == 2
    assert d["oposicion"] == "AGE"


def test_banco_preguntas_desglose_por_bloque_y_tema(client, db):
    db.sembrar(("Temario AGE", "bloque_01"), {"titulo": "Bloque I"})
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01"), {"titulo": "La Constitución"})
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_02"), {"titulo": "El Gobierno"})
    db.sembrar(("Temario AGE", "bloque_02"), {"titulo": "Bloque II"})
    db.sembrar(("Temario AGE", "bloque_02", "temas", "tema_01"), {"titulo": "La Unión Europea"})

    db.sembrar(("banco_preguntas_ia_AGE", "p1"), {"tema_id": "bloque_01-tema_01"})
    db.sembrar(("banco_preguntas_ia_AGE", "p2"), {"tema_id": "bloque_01-tema_01"})
    db.sembrar(("banco_preguntas_ia_AGE", "p3"), {"tema_id": "bloque_01-tema_02"})
    db.sembrar(("banco_preguntas_ia_AGE", "p4"), {"tema_id": "bloque_02-tema_01"})
    db.sembrar(("banco_preguntas_ia_AGE", "p5"), {"tema_id": None})  # pregunta antigua sin tema_id

    with _como():
        d = client.get("/admin/api/banco-preguntas?oposicion=AGE", headers=_AUTH).get_json()

    por_tema = {t["tema_id"]: t for t in d["por_tema"]}
    assert por_tema["bloque_01-tema_01"]["total"] == 2
    assert por_tema["bloque_01-tema_01"]["titulo"] == "La Constitución"
    assert por_tema["bloque_01-tema_01"]["bloque_titulo"] == "Bloque I"
    assert por_tema["bloque_01-tema_02"]["total"] == 1
    assert por_tema["bloque_02-tema_01"]["total"] == 1
    assert por_tema[""]["titulo"] == "Sin tema identificado"

    por_bloque = {b["titulo"]: b["total"] for b in d["por_bloque"]}
    assert por_bloque["Bloque I"] == 3
    assert por_bloque["Bloque II"] == 1
    assert por_bloque["Sin bloque identificado"] == 1


def test_banco_preguntas_oposicion_invalida_cae_a_age(client, db):
    db.sembrar(("banco_preguntas_ia_AGE", "p1"), {"tema_id": "bloque_01-tema_01"})
    with _como():
        d = client.get("/admin/api/banco-preguntas?oposicion=NOEXISTE", headers=_AUTH).get_json()
    assert d["oposicion"] == "AGE"


def test_banco_preguntas_usa_cache_dentro_del_ttl(client, db):
    # Mismo patrón que test_resumen_usa_cache_dentro_del_ttl: sin caché,
    # cada carga del panel recorría la colección entera del banco más un
    # .get() por tema/bloque -- ver _titulos_tema_y_bloque_batch.
    db.sembrar(("banco_preguntas_ia_AGE", "p1"), {"tema_id": "bloque_01-tema_01"})
    with _como():
        primero = client.get("/admin/api/banco-preguntas?oposicion=AGE", headers=_AUTH).get_json()
    assert primero["total_oposicion"] == 1

    db.sembrar(("banco_preguntas_ia_AGE", "p2"), {"tema_id": "bloque_01-tema_01"})
    with _como():
        segundo = client.get("/admin/api/banco-preguntas?oposicion=AGE", headers=_AUTH).get_json()
    assert segundo["total_oposicion"] == 1  # todavía dentro del TTL


def test_banco_preguntas_recalcula_pasado_el_ttl(client, db):
    import utils
    db.sembrar(("banco_preguntas_ia_AGE", "p1"), {"tema_id": "bloque_01-tema_01"})
    with _como():
        client.get("/admin/api/banco-preguntas?oposicion=AGE", headers=_AUTH)
    db.sembrar(("banco_preguntas_ia_AGE", "p2"), {"tema_id": "bloque_01-tema_01"})
    ahora = utils.time.time()
    with patch("utils.time.time", return_value=ahora + admin_module._TTL_CACHE_ADMIN_SEGUNDOS + 1), _como():
        tras_ttl = client.get("/admin/api/banco-preguntas?oposicion=AGE", headers=_AUTH).get_json()
    assert tras_ttl["total_oposicion"] == 2


# ---------- Bloquear / eliminar / soporte ----------
def test_resetear_limites_pone_a_cero(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "limites_uso": {"resumen": {"periodo": "2026-07-13", "contador": 5}}})
    with _como():
        client.post("/admin/api/usuarios/u1/resetear-limites", headers=_AUTH)
    assert db.leer(("usuarios", "u1"))["limites_uso"] == {}


def test_bloqueo_llama_a_update_user(client, db):
    llamado = {}
    with _como(admin=True), \
         patch("blueprints.admin.firebase_auth.update_user",
               side_effect=lambda uid, **kw: llamado.update(uid=uid, **kw)):
        r = client.patch("/admin/api/usuarios/u1/bloqueo", json={"bloqueado": True}, headers=_AUTH)
    assert r.status_code == 200
    assert llamado == {"uid": "u1", "disabled": True}


def test_no_puedo_bloquearme_a_mi_mismo(client, db):
    with _como(admin=True, uid="admin1"):
        r = client.patch("/admin/api/usuarios/admin1/bloqueo", json={"bloqueado": True}, headers=_AUTH)
    assert r.status_code == 400


def test_bloqueo_requiere_admin_total(client, db):
    with _como(admin=False, permisos=["usuarios"]):
        r = client.patch("/admin/api/usuarios/u1/bloqueo", json={"bloqueado": True}, headers=_AUTH)
    assert r.status_code == 403


def test_ranking_demo_sembrar_crea_30_participantes_en_su_propia_coleccion(client, db):
    with _como():
        r = client.post("/admin/api/ranking/demo", headers=_AUTH)
    assert r.status_code == 200
    creados = [db.leer(("ranking_demo", f"{i:02d}")) for i in range(1, 31)]
    assert all(d is not None for d in creados)
    # Nunca apellidos ni nada más allá de un nombre de pila -- el ranking
    # es anónimo por diseño (ver blueprints/ranking.py).
    assert all(" " not in d["alias"] for d in creados)
    assert all(isinstance(d["racha_actual"], int) for d in creados)


def test_ranking_demo_sembrar_no_toca_la_coleccion_usuarios(client, db):
    # Regresión: la primera versión de esto escribía en "usuarios" y hacía
    # que el admin viera usuarios falsos mezclados con los reales.
    db.sembrar(("usuarios", "real1"), {"email": "real1@x.com"})
    with _como():
        client.post("/admin/api/ranking/demo", headers=_AUTH)
    todos_usuarios = [doc.to_dict() for doc in db.collection("usuarios").stream()]
    assert len(todos_usuarios) == 1
    assert todos_usuarios[0]["email"] == "real1@x.com"


def test_ranking_demo_sembrar_requiere_admin_total(client, db):
    with _como(admin=False, permisos=["usuarios"]):
        r = client.post("/admin/api/ranking/demo", headers=_AUTH)
    assert r.status_code == 403


def test_ranking_demo_borrar_elimina_las_30_entradas_pero_no_las_reales(client, db):
    db.sembrar(("usuarios", "real1"), {
        "email": "real1@x.com", "ranking_optin": True, "ranking_alias": "Opositor de verdad",
        "racha": {"racha_actual": 5},
    })
    with _como():
        client.post("/admin/api/ranking/demo", headers=_AUTH)
        r = client.delete("/admin/api/ranking/demo", headers=_AUTH)
    assert r.status_code == 200
    assert all(db.leer(("ranking_demo", f"{i:02d}")) is None for i in range(1, 31))
    assert db.leer(("usuarios", "real1")) is not None


def test_ranking_demo_borrar_limpia_tambien_los_restos_del_diseno_anterior(client, db):
    # Antes de mover esto a su propia colección, se sembraba directamente
    # en "usuarios/demo_ranking_NN" -- si alguien llegó a usar esa versión,
    # borrar debe limpiarlo también, no solo la colección nueva.
    for i in range(1, 31):
        db.sembrar(("usuarios", f"demo_ranking_{i:02d}"), {"es_demo_ranking": True, "ranking_optin": True})
    db.sembrar(("usuarios", "real1"), {"email": "real1@x.com"})
    with _como():
        r = client.delete("/admin/api/ranking/demo", headers=_AUTH)
    assert r.status_code == 200
    assert all(db.leer(("usuarios", f"demo_ranking_{i:02d}")) is None for i in range(1, 31))
    assert db.leer(("usuarios", "real1")) is not None


def test_ranking_demo_borrar_requiere_admin_total(client, db):
    with _como(admin=False, permisos=["usuarios"]):
        r = client.delete("/admin/api/ranking/demo", headers=_AUTH)
    assert r.status_code == 403


def test_ranking_demo_estado_refleja_cuantos_hay(client, db):
    with _como():
        r0 = client.get("/admin/api/ranking/demo", headers=_AUTH).get_json()
        assert r0["cantidad"] == 0
        client.post("/admin/api/ranking/demo", headers=_AUTH)
        r1 = client.get("/admin/api/ranking/demo", headers=_AUTH).get_json()
        assert r1["cantidad"] == 30
        client.delete("/admin/api/ranking/demo", headers=_AUTH)
        r2 = client.get("/admin/api/ranking/demo", headers=_AUTH).get_json()
        assert r2["cantidad"] == 0


def test_ranking_demo_estado_requiere_admin_total(client, db):
    with _como(admin=False, permisos=["usuarios"]):
        r = client.get("/admin/api/ranking/demo", headers=_AUTH)
    assert r.status_code == 403


def test_generar_enlace_password(client, db):
    reg = type("R", (), {"email": "u1@x.com", "custom_claims": None})()
    with _como(), \
         patch("blueprints.admin.firebase_auth.get_user", return_value=reg), \
         patch("blueprints.admin.firebase_auth.generate_password_reset_link", return_value="https://reset/abc"):
        r = client.post("/admin/api/usuarios/u1/enlace", json={"tipo": "password"}, headers=_AUTH).get_json()
    assert r["enlace"] == "https://reset/abc"


def test_generar_enlace_para_cuenta_admin_bloqueado_sin_ser_admin(client, db):
    # Bug real de seguridad (24/08/2026): un miembro del equipo con solo el
    # permiso "usuarios" (no super-admin) podía generar un enlace de
    # restablecer contraseña para OTRA cuenta de administrador -- y con
    # eso, tomar el control total del panel.
    reg_admin = type("R", (), {"email": "otro-admin@x.com", "custom_claims": {"admin": True}})()
    with _como(admin=False, permisos=["usuarios"]), \
         patch("blueprints.admin.firebase_auth.get_user", return_value=reg_admin), \
         patch("blueprints.admin.firebase_auth.generate_password_reset_link") as mock_generar:
        r = client.post("/admin/api/usuarios/admin2/enlace", json={"tipo": "password"}, headers=_AUTH)
    assert r.status_code == 403
    mock_generar.assert_not_called()


def test_generar_enlace_para_cuenta_con_permisos_de_equipo_bloqueado_sin_ser_admin(client, db):
    # Mismo caso con un objetivo que no es super-admin pero sí tiene algún
    # permiso de equipo (p. ej. moderador de "reportes") -- también debe
    # exigirse ser super-admin para generarle el enlace.
    reg_equipo = type("R", (), {"email": "moderador@x.com", "custom_claims": {"permisos": ["reportes"]}})()
    with _como(admin=False, permisos=["usuarios"]), \
         patch("blueprints.admin.firebase_auth.get_user", return_value=reg_equipo), \
         patch("blueprints.admin.firebase_auth.generate_password_reset_link") as mock_generar:
        r = client.post("/admin/api/usuarios/moderador1/enlace", json={"tipo": "password"}, headers=_AUTH)
    assert r.status_code == 403
    mock_generar.assert_not_called()


def test_generar_enlace_para_cuenta_admin_permitido_siendo_admin(client, db):
    # Un super-admin sí puede generar el enlace para otra cuenta de
    # administrador (caso legítimo: recuperar el acceso de un compañero).
    reg_admin = type("R", (), {"email": "otro-admin@x.com", "custom_claims": {"admin": True}})()
    with _como(admin=True), \
         patch("blueprints.admin.firebase_auth.get_user", return_value=reg_admin), \
         patch("blueprints.admin.firebase_auth.generate_password_reset_link", return_value="https://reset/abc"):
        r = client.post("/admin/api/usuarios/admin2/enlace", json={"tipo": "password"}, headers=_AUTH)
    assert r.status_code == 200
    assert r.get_json()["enlace"] == "https://reset/abc"


def test_eliminar_usuario(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com"})
    llamado = {}
    with _como(admin=True, uid="admin1"), \
         patch("blueprints.admin.eliminar_cuenta_usuario" if False else "gestion_cuenta.eliminar_cuenta_usuario",
               side_effect=lambda db_, uid: llamado.update(uid=uid)):
        r = client.delete("/admin/api/usuarios/u1", headers=_AUTH)
    assert r.status_code == 200
    assert llamado["uid"] == "u1"


def test_no_puedo_eliminarme_a_mi_mismo(client, db):
    db.sembrar(("usuarios", "admin1"), {"email": "a@x.com"})
    with _como(admin=True, uid="admin1"):
        r = client.delete("/admin/api/usuarios/admin1", headers=_AUTH)
    assert r.status_code == 400


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


def test_resumen_separa_a_quien_no_ha_activado_ninguna_oposicion(client, db):
    # Registrarse sin activar ninguna oposición todavía (p. ej. recién dado
    # de alta, sin haber elegido nada en Zona Opositor) resolvía al mismo
    # "gratis" que quien SÍ activó una y se quedó sin plan de pago -- dos
    # situaciones muy distintas de cara a captación, mezcladas en un único
    # número. Aquí u1 nunca ha activado nada (sin "suscripciones" siquiera)
    # y u2 sí activó AGE, con su prueba ya terminada sin pagar.
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com"})
    db.sembrar(("usuarios", "u2"), {"email": "u2@x.com", "suscripciones": {"AGE": {"plan": "gratis"}}})
    with _como():
        resp = client.get("/admin/api/resumen", headers=_AUTH)
    datos = resp.get_json()
    assert datos["usuarios_por_plan"]["sin activar"] == 1
    assert datos["usuarios_por_plan"]["gratis"] == 1


def test_resumen_desglosa_reportes_pendientes_por_bandeja(client, db):
    # El dashboard necesita el desglose (no solo la suma) para poder avisar
    # en cada pestaña -- "Preguntas reportadas" y "Mensajes de soporte" -- de
    # cuál de las dos tiene algo nuevo, sin que un admin tenga que entrar a
    # mirar las dos para saberlo.
    db.sembrar(("errores_generacion", "r1"), {"fuente": "usuario_admin", "estado": "pendiente"})
    db.sembrar(("errores_generacion", "r2"), {"fuente": "usuario_admin", "estado": "pendiente"})
    db.sembrar(("errores_generacion", "r3"), {"fuente": "usuario_admin", "estado": "revisado"})
    db.sembrar(("mensajes_soporte", "s1"), {"estado": "pendiente"})
    db.sembrar(("mensajes_soporte", "s2"), {"estado": "revisado"})
    with _como():
        d = client.get("/admin/api/resumen", headers=_AUTH).get_json()
    assert d["reportes_pendientes_preguntas"] == 2
    assert d["reportes_pendientes_soporte"] == 1
    assert d["reportes_pendientes"] == 3


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


def test_detalle_usuario_incluye_apellidos_telefono_direccion(client, db):
    # Estos 3 campos se guardan desde /registrar-usuario (ver
    # rutas_progreso.py) pero hasta ahora la ficha del panel admin no los
    # devolvía -- se veían en Firestore pero nunca en el panel.
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@x.com", "nombre": "Virginia", "apellidos": "García López",
        "telefono": "+34 600 11 22 33", "direccion": "Calle Falsa 123",
    })
    with _como():
        d = client.get("/admin/api/usuarios/u1", headers=_AUTH).get_json()
    assert d["apellidos"] == "García López"
    assert d["telefono"] == "+34 600 11 22 33"
    assert d["direccion"] == "Calle Falsa 123"


def test_detalle_usuario_apellidos_telefono_direccion_vacios_si_no_se_rellenaron(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com"})
    with _como():
        d = client.get("/admin/api/usuarios/u1", headers=_AUTH).get_json()
    assert d["apellidos"] == ""
    assert d["telefono"] == ""
    assert d["direccion"] == ""


def test_detalle_usuario_email_verificado_viene_de_firebase_auth_no_de_firestore(client, db):
    # email_verificado no se guarda nunca en Firestore -- viene de la cuenta
    # real de Firebase Auth (registro.email_verified), no de datos.get(...).
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "email_verificado": True})

    class _Reg:
        custom_claims = None
        email_verified = False
    with _como(), patch("blueprints.admin.firebase_auth.get_user", return_value=_Reg()):
        d = client.get("/admin/api/usuarios/u1", headers=_AUTH).get_json()
    assert d["email_verificado"] is False

    class _RegVerificado:
        custom_claims = None
        email_verified = True
    db.sembrar(("usuarios", "u2"), {"email": "u2@x.com"})
    with _como(), patch("blueprints.admin.firebase_auth.get_user", return_value=_RegVerificado()):
        d2 = client.get("/admin/api/usuarios/u2", headers=_AUTH).get_json()
    assert d2["email_verificado"] is True


def test_detalle_usuario_email_verificado_falso_si_firebase_auth_falla(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com"})
    with _como(), patch("blueprints.admin.firebase_auth.get_user", side_effect=RuntimeError("caído")):
        d = client.get("/admin/api/usuarios/u1", headers=_AUTH).get_json()
    assert d["email_verificado"] is False


def test_detalle_usuario_incluye_contenido_y_rendimiento(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@x.com",
        "estadisticas": {"AGE": {"rendimiento_por_tema": {
            "tema_01": {"aciertos": 8, "fallos": 2, "blancos": 0},
            "tema_02": {"aciertos": 2, "fallos": 3, "blancos": 5},
        }}},
    })
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"nombre": "apuntes.pdf"})
    db.sembrar(("usuarios", "u1", "tarjetas_pdf", "t1"), {"tarjetas": [{}, {}, {}]})
    db.sembrar(("usuarios", "u1", "preguntas_favoritas", "f1"), {"oposicion": "AGE"})
    with _como():
        d = client.get("/admin/api/usuarios/u1", headers=_AUTH).get_json()
    assert d["contenido_creado"]["documentos"] == 1
    assert d["contenido_creado"]["tarjetas"] == 3
    assert d["contenido_creado"]["favoritas"] == 1
    assert d["rendimiento"]["aciertos"] == 10
    assert d["rendimiento"]["contestadas"] == 20
    assert d["rendimiento"]["porcentaje"] == 50


def test_usuarios_lista_incluye_uso_y_ordena_por_uso(client, db):
    from datetime import date
    hoy = date.today().isoformat()
    # u_bajo: poco uso; u_alto: casi al tope del cupo de test personalizado.
    db.sembrar(("usuarios", "u_bajo"), {"email": "bajo@x.com", "suscripciones": {"AGE": {"plan": "basico"}},
                                        "ultima_actividad": "2026-07-14"})
    db.sembrar(("usuarios", "u_alto"), {"email": "alto@x.com", "suscripciones": {"AGE": {"plan": "basico"}},
                                        "ultima_actividad": "2026-07-01",
                                        "limites_uso": {"test_avanzado_verificado": {"dia": {"clave": hoy, "contador": 50}}}})
    with _como():
        d = client.get("/admin/api/usuarios?orden=uso", headers=_AUTH).get_json()
    # El de más uso va primero al ordenar por uso.
    assert d["usuarios"][0]["email"] == "alto@x.com"
    assert d["usuarios"][0]["uso_pct"] == 100
    assert d["usuarios"][1]["uso_pct"] == 0


def test_detalle_usuario_incluye_uso_herramientas(client, db):
    from datetime import date
    hoy = date.today().isoformat()
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@x.com",
        "suscripciones": {"AGE": {"plan": "basico"}},
        "limites_uso": {"test_avanzado_verificado": {"dia": {"clave": hoy, "contador": 25}}},
    })
    with _como():
        d = client.get("/admin/api/usuarios/u1", headers=_AUTH).get_json()
    filas = {f["id"]: f for f in d["uso_herramientas"]["filas"]}
    tp = filas["test_avanzado_verificado"]
    assert tp["consumido"] == 25
    assert tp["limite"] == 50  # básico por defecto
    assert tp["porcentaje"] == 50
    assert tp["unidad"] == "preguntas"
    # Tu Tutor no está incluido en básico -> límite 0.
    assert filas["chat_temario"]["limite"] == 0


def test_notas_anadir_y_eliminar(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com"})
    with _como():
        r = client.post("/admin/api/usuarios/u1/notas", json={"texto": "Primera nota"}, headers=_AUTH)
        assert r.status_code == 201
        nota_id = r.get_json()["nota"]["id"]
        client.post("/admin/api/usuarios/u1/notas", json={"texto": "Segunda"}, headers=_AUTH)
        d = client.get("/admin/api/usuarios/u1", headers=_AUTH).get_json()
        assert len(d["notas_lista"]) == 2
        client.delete(f"/admin/api/usuarios/u1/notas/{nota_id}", headers=_AUTH)
        d = client.get("/admin/api/usuarios/u1", headers=_AUTH).get_json()
        textos = [n["texto"] for n in d["notas_lista"]]
        assert textos == ["Segunda"]


def test_notas_legacy_se_migra_a_lista(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "notas_admin": "Nota antigua"})
    with _como():
        d = client.get("/admin/api/usuarios/u1", headers=_AUTH).get_json()
        assert d["notas_lista"][0]["id"] == "legacy"
        assert d["notas_lista"][0]["texto"] == "Nota antigua"
        client.delete("/admin/api/usuarios/u1/notas/legacy", headers=_AUTH)
        d = client.get("/admin/api/usuarios/u1", headers=_AUTH).get_json()
        assert d["notas_lista"] == []


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
    sembrar_usuario_activo(db, "u1")
    with _como():
        client.patch("/admin/api/temario/AGE/bloque_01/publicado",
                     json={"publicado": False}, headers=_AUTH)
    # Ahora un usuario normal no debe ver ese bloque en /temas-disponibles.
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "u1@x.com", "email_verified": True}):
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


def test_usuarios_otorgar_prueba_fija_prueba_fin(client, db):
    # Sin oposicion en el body, se aplica a AGE (OPOSICION_POR_DEFECTO) --
    # cada oposición tiene su propia prueba, ver planes.prueba_activa.
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com"})
    with _como():
        resp = client.patch("/admin/api/usuarios/u1/prueba", json={"dias": 14}, headers=_AUTH)
    assert resp.status_code == 200
    datos = db.leer(("usuarios", "u1"))
    sub = datos["suscripciones"]["AGE"]
    assert sub["prueba_fin"] == resp.get_json()["prueba_fin"]
    assert sub["plan"] == "gratis"
    from datetime import datetime
    dias_restantes = (datetime.fromisoformat(sub["prueba_fin"]) - datetime.utcnow()).days
    assert 12 <= dias_restantes <= 14


def test_usuarios_otorgar_prueba_usuario_inexistente(client, db):
    with _como():
        resp = client.patch("/admin/api/usuarios/fantasma/prueba", json={"dias": 7}, headers=_AUTH)
    assert resp.status_code == 404


def test_usuarios_otorgar_prueba_dias_invalidos(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com"})
    with _como():
        resp = client.patch("/admin/api/usuarios/u1/prueba", json={"dias": 0}, headers=_AUTH)
    assert resp.status_code == 400


def test_usuarios_detalle_incluye_en_prueba(client, db):
    from datetime import datetime, timedelta
    prueba_fin = (datetime.utcnow() + timedelta(days=3)).isoformat()
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@x.com",
        "suscripciones": {"AGE": {"plan": "gratis", "prueba_fin": prueba_fin}},
    })
    with _como():
        d = client.get("/admin/api/usuarios/u1", headers=_AUTH).get_json()
    assert d["en_prueba"] is True
    assert d["prueba_fin"] == prueba_fin
    assert d["plan"] == "premium"


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


def test_bootstrap_rechaza_get(client, monkeypatch):
    # GET se quitó tras la auditoría de agosto de 2026: un secreto en la URL
    # queda registrado en el historial del navegador y en los logs de acceso
    # del servidor de forma indefinida -- ahora solo se acepta por POST.
    monkeypatch.setenv("ADMIN_BOOTSTRAP_SECRET", "clave-buena")
    resp = client.get("/admin/api/bootstrap?uid=abc123&secreto=clave-buena")
    assert resp.status_code == 405


# ---------- Utilidades nuevas (1,2,3,5,16) ----------
def test_resumen_agrega_coste_ia(client, db):
    from datetime import datetime
    mes = datetime.utcnow().strftime("%Y-%m")
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "coste_ia": {mes: {"tokens_in": 1000, "tokens_out": 500, "coste": 0.02}}})
    db.sembrar(("usuarios", "u2"), {"email": "u2@x.com", "coste_ia": {mes: {"tokens_in": 100, "tokens_out": 50, "coste": 0.003}}})
    with _como():
        d = client.get("/admin/api/resumen", headers=_AUTH).get_json()
    assert d["coste_ia_mes"] == round(0.02 + 0.003, 2)
    assert d["top_gastadores_ia"][0]["uid"] == "u1"


def test_detalle_usuario_incluye_coste_ia(client, db):
    from datetime import datetime
    mes = datetime.utcnow().strftime("%Y-%m")
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "coste_ia": {mes: {"tokens_in": 1000, "tokens_out": 500, "coste": 0.02}}})
    with _como():
        d = client.get("/admin/api/usuarios/u1", headers=_AUTH).get_json()
    assert d["coste_ia_mes"] == 0.02
    assert d["tokens_ia_total"] == 1500


def test_detalle_usuario_incluye_coste_ia_diario(client, db):
    from datetime import datetime
    hoy = datetime.utcnow().strftime("%Y-%m-%d")
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "coste_ia_dias": {
        hoy: {"tokens_in": 200, "tokens_out": 100, "llamadas": 3, "coste": 0.004},
    }})
    with _como():
        d = client.get("/admin/api/usuarios/u1", headers=_AUTH).get_json()
    assert d["coste_ia_historico_diario"] == [
        {"dia": hoy, "coste": 0.004, "tokens": 300, "tokens_in": 200, "tokens_out": 100, "llamadas": 3},
    ]


def test_detalle_usuario_oculta_coste_ia_a_admin_parcial(client, db):
    # Un admin con solo el permiso "usuarios" (soporte) puede ver y
    # gestionar la ficha, pero no cuánto gasta la web en IA por ese
    # usuario -- eso queda reservado al admin TOTAL.
    from datetime import datetime
    mes = datetime.utcnow().strftime("%Y-%m")
    hoy = datetime.utcnow().strftime("%Y-%m-%d")
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@x.com",
        "coste_ia": {mes: {"tokens_in": 1000, "tokens_out": 500, "coste": 0.02}},
        "coste_ia_dias": {hoy: {"tokens_in": 100, "tokens_out": 50, "llamadas": 1, "coste": 0.002}},
    })
    with _como(admin=False, uid="soporte1", permisos=["usuarios"]):
        resp = client.get("/admin/api/usuarios/u1", headers=_AUTH)
        d = resp.get_json()
    assert resp.status_code == 200
    assert d["coste_ia_mes"] is None
    assert d["coste_ia_total"] is None
    assert d["tokens_ia_total"] is None
    assert d["coste_ia_historico"] is None
    assert d["coste_ia_historico_diario"] is None
    # El contenido creado y el rendimiento NO son datos monetarios -- un
    # admin de soporte sí los necesita para ayudar al usuario, así que
    # siguen viéndose con normalidad.
    assert d["contenido_creado"] is not None
    assert d["rendimiento"] is not None


def test_resumen_calcula_mrr(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "a@x.com", "suscripciones": {"AGE": {"plan": "premium"}}})
    db.sembrar(("usuarios", "u2"), {"email": "b@x.com", "suscripciones": {"AGE": {"plan": "basico"}, "GACE": {"plan": "premium"}}})
    with _como():
        d = client.get("/admin/api/resumen", headers=_AUTH).get_json()
    assert d["suscripciones_pago"] == 3
    assert d["mrr"] == round(9.99 + 4.99 + 9.99, 2)


# ---------- Caché de las vistas agregadas (escalabilidad) ----------
# El dashboard, Ingresos y la lista de Usuarios recorren TODA la colección
# de usuarios; sin caché, cada apertura del panel repite ese barrido
# completo -- con muchos usuarios eso significa lecturas reales de
# Firestore (coste) y tiempo de respuesta crecientes. Estas pruebas
# verifican que la caché de verdad evita recalcular dentro del TTL, y que
# sí recalcula pasado el TTL o tras una invalidación explícita.
def test_resumen_usa_cache_dentro_del_ttl(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "a@x.com"})
    with _como():
        primero = client.get("/admin/api/resumen?oposicion=AGE", headers=_AUTH).get_json()
    assert primero["usuarios_totales"] == 1

    # Usuario añadido directamente en el store, sin pasar por ninguna ruta
    # -- si la caché funciona, la siguiente llamada dentro del TTL no debe
    # verlo todavía.
    db.sembrar(("usuarios", "u2"), {"email": "b@x.com"})
    with _como():
        segundo = client.get("/admin/api/resumen?oposicion=AGE", headers=_AUTH).get_json()
    assert segundo["usuarios_totales"] == 1


def test_resumen_recalcula_pasado_el_ttl(client, db):
    import utils
    db.sembrar(("usuarios", "u1"), {"email": "a@x.com"})
    with _como():
        client.get("/admin/api/resumen?oposicion=AGE", headers=_AUTH)
    db.sembrar(("usuarios", "u2"), {"email": "b@x.com"})
    ahora = utils.time.time()
    with patch("utils.time.time", return_value=ahora + admin_module._TTL_CACHE_ADMIN_SEGUNDOS + 1), _como():
        tras_ttl = client.get("/admin/api/resumen?oposicion=AGE", headers=_AUTH).get_json()
    assert tras_ttl["usuarios_totales"] == 2


def test_cancelar_suscripcion_invalida_la_cache_de_bajas_e_ingresos(client, db):
    # El propio flujo de cancelar/reactivar invalida la caché al momento
    # (ver _invalidar_cache_admin_tras_cambio_suscripcion en pagos.py) --
    # sin esto, la baja recién dada no aparecería en "Bajas recientes"
    # hasta que venciera el TTL, justo el problema que se pidió arreglar.
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "premium", "stripe_subscription_id": "sub_1"}},
    })
    with _como():
        antes = client.get("/admin/api/ingresos", headers=_AUTH).get_json()
    assert antes["total"] == 1
    assert antes["filas"][0]["estado_cliente"] == "activo"

    parche = _con_sesion_usuario(client, uid="u1", email="u1@example.com")
    try:
        with patch("blueprints.pagos.stripe.Subscription.modify", return_value={}), \
             patch("blueprints.pagos.enviar_email_cancelacion_suscripcion"):
            client.post(
                "/cancelar-suscripcion",
                json={"oposicion": "AGE", "motivo": "precio"},
                headers={"Authorization": "Bearer x"},
            )
    finally:
        parche.stop()

    with _como():
        despues = client.get("/admin/api/ingresos", headers=_AUTH).get_json()
    # Sin invalidación, esto seguiría devolviendo "activo" (el valor
    # cacheado de la llamada de arriba) en vez de "cancelando".
    assert despues["filas"][0]["estado_cliente"] == "cancelando"


def test_ingresos_lista_una_fila_por_suscripcion_de_pago(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "a@x.com", "fecha_creacion": "2025-01-01T00:00:00",
        "suscripciones": {
            "AGE": {
                "plan": "premium", "subscription_status": "active",
                "current_period_end": "2026-09-01T00:00:00", "cancelar_al_final_periodo": False,
            },
        },
    })
    db.sembrar(("usuarios", "u2"), {
        "email": "b@x.com", "fecha_creacion": "2025-02-01T00:00:00",
        "suscripciones": {
            "AGE": {"plan": "basico", "subscription_status": "past_due"},
            "GACE": {"plan": "gratis"},  # no es de pago -- no debe aparecer
        },
    })
    with _como():
        d = client.get("/admin/api/ingresos", headers=_AUTH).get_json()
    assert d["total"] == 2
    assert d["resumen"]["mrr"] == round(9.99 + 4.99, 2)
    assert d["resumen"]["suscripciones"] == 2
    filas_por_email = {f["email"]: f for f in d["filas"]}
    assert filas_por_email["a@x.com"]["estado_cliente"] == "activo"
    assert filas_por_email["a@x.com"]["estado_suscripcion"] == "active"
    assert filas_por_email["a@x.com"]["precio"] == 9.99
    assert filas_por_email["b@x.com"]["estado_suscripcion"] == "past_due"
    assert all(f["oposicion"] == "AGE" for f in d["filas"])


def test_ingresos_filtra_por_busqueda_y_plan(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "premium@x.com", "suscripciones": {"AGE": {"plan": "premium"}}})
    db.sembrar(("usuarios", "u2"), {"email": "basico@x.com", "suscripciones": {"AGE": {"plan": "basico"}}})
    with _como():
        d = client.get("/admin/api/ingresos?plan=basico", headers=_AUTH).get_json()
    assert d["total"] == 1
    assert d["filas"][0]["email"] == "basico@x.com"


def test_ingresos_detecta_cancelando_baja_y_prueba(client, db):
    # "activo" (u1) ya lo cubre el test de arriba. Aquí los otros 3 estados
    # de cliente: cancelando (de pago con baja programada), baja (ya de
    # vuelta a gratis tras haber pagado) y prueba (dentro de los 7 días
    # gratis, sin haber pagado nunca).
    db.sembrar(("usuarios", "u_cancelando"), {
        "email": "cancelando@x.com",
        "suscripciones": {"AGE": {"plan": "premium", "cancelar_al_final_periodo": True, "current_period_end": "2026-09-01T00:00:00"}},
    })
    db.sembrar(("usuarios", "u_baja"), {
        "email": "baja@x.com",
        "suscripciones": {"AGE": {"plan": "gratis", "subscription_status": "canceled", "stripe_subscription_id": "sub_1"}},
    })
    en_el_futuro = (datetime.utcnow() + timedelta(days=3)).isoformat()
    db.sembrar(("usuarios", "u_prueba"), {
        "email": "prueba@x.com",
        "suscripciones": {"AGE": {"plan": "gratis", "prueba_fin": en_el_futuro}},
    })
    db.sembrar(("usuarios", "u_sin_nada"), {"email": "nunca@x.com", "suscripciones": {"AGE": {"plan": "gratis"}}})

    with _como():
        d = client.get("/admin/api/ingresos", headers=_AUTH).get_json()
    por_email = {f["email"]: f for f in d["filas"]}
    assert "nunca@x.com" not in por_email  # nunca pagó ni está en prueba -- no aporta nada, se omite
    assert por_email["cancelando@x.com"]["estado_cliente"] == "cancelando"
    assert por_email["cancelando@x.com"]["precio"] == 9.99  # sigue pagando hasta que venza
    assert por_email["baja@x.com"]["estado_cliente"] == "baja"
    assert por_email["baja@x.com"]["precio"] == 0
    assert por_email["prueba@x.com"]["estado_cliente"] == "prueba"
    assert por_email["prueba@x.com"]["plan"] == "premium"  # la prueba da acceso Premium
    assert por_email["prueba@x.com"]["precio"] == 0
    # El resumen desglosa por estado y el MRR/ARPU solo cuentan a quien paga de verdad.
    assert d["resumen"]["por_estado"] == {"activo": 0, "cancelando": 1, "baja": 1, "prueba": 1}
    assert d["resumen"]["mrr"] == 9.99
    assert d["resumen"]["suscripciones"] == 1
    assert d["resumen"]["arpu"] == 9.99


def test_ingresos_filtra_por_estado(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "activo@x.com", "suscripciones": {"AGE": {"plan": "premium"}}})
    db.sembrar(("usuarios", "u2"), {
        "email": "cancelando@x.com",
        "suscripciones": {"AGE": {"plan": "basico", "cancelar_al_final_periodo": True}},
    })
    with _como():
        d = client.get("/admin/api/ingresos?estado=cancelando", headers=_AUTH).get_json()
    assert d["total"] == 1
    assert d["filas"][0]["email"] == "cancelando@x.com"


def test_ingresos_rechaza_estado_no_valido(client, db):
    with _como():
        resp = client.get("/admin/api/ingresos?estado=inventado", headers=_AUTH)
    assert resp.status_code == 400


def test_export_ingresos_csv(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "a@x.com", "suscripciones": {"AGE": {"plan": "premium"}}})
    with _como():
        resp = client.get("/admin/api/ingresos/export", headers=_AUTH)
    assert resp.status_code == 200
    assert "text/csv" in resp.content_type
    assert "a@x.com" in resp.get_data(as_text=True)


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


def test_export_usuarios_csv_neutraliza_inyeccion_de_formula(client, db):
    """CSV/Formula Injection: un "nombre" que empiece por "=" (o "+", "-",
    "@") se interpreta como fórmula al abrir el CSV en Excel/Sheets -- debe
    salir con una comilla simple por delante para que se trate como texto
    literal, no como fórmula (ver blueprints/admin.py._celda_csv_segura)."""
    db.sembrar(("usuarios", "u1"), {
        "email": "atacante@x.com", "nombre": '=HYPERLINK("http://evil.example","click")',
        "suscripciones": {"AGE": {"plan": "premium"}},
    })
    with _como():
        resp = client.get("/admin/api/usuarios/export", headers=_AUTH)
    texto = resp.get_data(as_text=True)
    assert ",=HYPERLINK" not in texto  # nunca cruda justo tras el separador de columna
    assert "'=HYPERLINK" in texto  # protegida con comilla simple por delante


def test_reportes_adjuntan_pregunta_oficial(client, db):
    enunciado = "¿Pregunta oficial?"
    db.sembrar(("examenes_oficiales_AGE", "p1"), {
        "tipo": "pregunta", "pregunta": enunciado,
        "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"}, "respuesta_correcta": "C",
    })
    db.sembrar(("errores_generacion", "r1"), {
        "fuente": "usuario_admin", "pregunta_texto": enunciado, "oposicion": "AGE", "detalle": "dudosa",
        "estado": "pendiente", "fecha": "2026-01-01",
    })
    with _como():
        reportes = client.get("/admin/api/reportes?estado=pendiente", headers=_AUTH).get_json()["reportes"]
    assert reportes[0]["pregunta_oficial"]["respuesta_correcta"] == "C"


def test_reportes_y_soporte_incluyen_uid_para_abrir_la_ficha(client, db):
    # El panel necesita el uid (no solo el email, que ni siquiera se guarda
    # en los reportes de preguntas) para poder abrir la ficha del usuario
    # que reportó/escribió directamente desde la lista.
    db.sembrar(("errores_generacion", "r1"), {
        "fuente": "usuario_admin", "pregunta_texto": "¿Pregunta?", "oposicion": "AGE",
        "detalle": "dudosa", "estado": "pendiente", "fecha": "2026-01-01", "uid": "u1",
    })
    db.sembrar(("mensajes_soporte", "s1"), {
        "uid": "u2", "email": "u2@x.com", "mensaje": "Hola", "estado": "pendiente", "fecha": "2026-01-01",
    })
    with _como():
        reportes = client.get("/admin/api/reportes?estado=pendiente", headers=_AUTH).get_json()["reportes"]
        mensajes = client.get("/admin/api/soporte?estado=pendiente", headers=_AUTH).get_json()["mensajes"]
    assert reportes[0]["uid"] == "u1"
    assert mensajes[0]["uid"] == "u2"


def test_reportes_paginados(client, db):
    # Antes traía TODOS los reportes de golpe sin límite -- con muchos
    # acumulados, cada carga del panel iba leyendo (y facturando) cada vez
    # más documentos de Firestore. 25 reportes -> 2 páginas de 20.
    for i in range(25):
        db.sembrar(("errores_generacion", f"r{i}"), {
            "fuente": "usuario_admin", "pregunta_texto": f"Pregunta {i}", "oposicion": "AGE", "detalle": "dudosa",
            "estado": "pendiente", "fecha": f"2026-01-{i + 1:02d}",
        })
    with _como():
        pagina1 = client.get("/admin/api/reportes?estado=pendiente", headers=_AUTH).get_json()
        pagina2 = client.get("/admin/api/reportes?estado=pendiente&pagina=2", headers=_AUTH).get_json()

    assert pagina1["total"] == 25
    assert pagina1["pagina"] == 1
    assert len(pagina1["reportes"]) == 20
    assert len(pagina2["reportes"]) == 5
    # Sin solape entre páginas.
    ids_pagina1 = {r["id"] for r in pagina1["reportes"]}
    ids_pagina2 = {r["id"] for r in pagina2["reportes"]}
    assert not (ids_pagina1 & ids_pagina2)


# ---------- Calidad IA (auto-rechazos de la verificación, fuente="auto_verificacion") ----------
def test_errores_ia_no_mezcla_reportes_de_usuario(client, db):
    db.sembrar(("errores_generacion", "auto1"), {
        "fuente": "auto_verificacion", "tema_id": "bloque_05-tema_01", "tipo_error": "desfase_legal",
        "pregunta_texto": "¿Pregunta generada?", "detalle": "El artículo citado no existe en el texto.",
        "intento_numero": 1, "resuelto": False,
    })
    db.sembrar(("errores_generacion", "usr1"), {
        "fuente": "usuario_admin", "pregunta_texto": "¿Pregunta reportada?", "oposicion": "AGE",
        "detalle": "dudosa", "estado": "pendiente", "fecha": "2026-01-01",
    })
    with _como():
        d = client.get("/admin/api/errores-ia", headers=_AUTH).get_json()
    assert len(d["entradas"]) == 1
    assert d["entradas"][0]["tema_id"] == "bloque_05-tema_01"
    assert d["entradas"][0]["tipo_error"] == "desfase_legal"
    assert d["entradas"][0]["detalle"] == "El artículo citado no existe en el texto."


def test_errores_ia_filtra_por_tipo_y_pendientes(client, db):
    db.sembrar(("errores_generacion", "a1"), {
        "fuente": "auto_verificacion", "tema_id": "bloque_05-tema_01", "tipo_error": "desfase_legal",
        "detalle": "x", "resuelto": False,
    })
    db.sembrar(("errores_generacion", "a2"), {
        "fuente": "auto_verificacion", "tema_id": "bloque_02-tema_03", "tipo_error": "ambiguedad",
        "detalle": "y", "resuelto": False,
    })
    db.sembrar(("errores_generacion", "a3"), {
        "fuente": "auto_verificacion", "tema_id": "bloque_05-tema_01", "tipo_error": "desfase_legal",
        "detalle": "z", "resuelto": True,
    })
    with _como():
        solo_desfase = client.get("/admin/api/errores-ia?tipo_error=desfase_legal&resuelto=todos", headers=_AUTH).get_json()
        solo_pendientes = client.get("/admin/api/errores-ia?resuelto=pendiente", headers=_AUTH).get_json()
        solo_resueltos = client.get("/admin/api/errores-ia?resuelto=resuelto", headers=_AUTH).get_json()
    assert {e["id"] for e in solo_desfase["entradas"]} == {"a1", "a3"}
    assert {e["id"] for e in solo_pendientes["entradas"]} == {"a1", "a2"}
    assert {e["id"] for e in solo_resueltos["entradas"]} == {"a3"}


def test_errores_ia_resumen_cuenta_por_tipo_y_tema_sin_aplicar_filtros(client, db):
    # El resumen (para ver de un vistazo si algo se concentra en un tema
    # concreto) se calcula sobre TODO lo leído, no sobre lo ya filtrado --
    # si no, cambiar el filtro de tipo_error también movería el propio
    # resumen que ayuda a decidir qué filtro mirar.
    for i in range(3):
        db.sembrar(("errores_generacion", f"a{i}"), {
            "fuente": "auto_verificacion", "tema_id": "bloque_05-tema_02", "tipo_error": "desfase_legal",
            "detalle": "x", "resuelto": False,
        })
    db.sembrar(("errores_generacion", "b1"), {
        "fuente": "auto_verificacion", "tema_id": "bloque_01-tema_01", "tipo_error": "ambiguedad",
        "detalle": "y", "resuelto": False,
    })
    with _como():
        d = client.get("/admin/api/errores-ia?tipo_error=ambiguedad", headers=_AUTH).get_json()
    assert len(d["entradas"]) == 1  # el filtro sí se aplicó a la lista
    assert d["resumen"]["por_tipo"] == {"desfase_legal": 3, "ambiguedad": 1}
    assert {"tema_id": "bloque_05-tema_02", "total": 3} in d["resumen"]["top_temas"]


def test_errores_ia_marcar_resuelto(client, db):
    db.sembrar(("errores_generacion", "a1"), {
        "fuente": "auto_verificacion", "tema_id": "bloque_05-tema_01", "tipo_error": "desfase_legal",
        "detalle": "x", "resuelto": False,
    })
    with _como():
        r = client.patch("/admin/api/errores-ia/a1", json={"resuelto": True}, headers=_AUTH)
        assert r.status_code == 200
        pendientes = client.get("/admin/api/errores-ia?resuelto=pendiente", headers=_AUTH).get_json()
    assert pendientes["entradas"] == []
    assert db.leer(("errores_generacion", "a1"))["resuelto"] is True


def test_errores_ia_marcar_resuelto_inexistente_da_404(client, db):
    with _como():
        r = client.patch("/admin/api/errores-ia/no-existe", json={"resuelto": True}, headers=_AUTH)
    assert r.status_code == 404


def test_permiso_temario_puede_ver_errores_ia(client, db):
    with _como(admin=False, uid="ed1", permisos=["temario"]):
        assert client.get("/admin/api/errores-ia", headers=_AUTH).status_code == 200
    with _como(admin=False, uid="rep1", permisos=["reportes"]):
        assert client.get("/admin/api/errores-ia", headers=_AUTH).status_code == 403


def test_errores_ia_filtra_por_oposicion(client, db):
    db.sembrar(("errores_generacion", "a1"), {
        "fuente": "auto_verificacion", "tema_id": "bloque_05-tema_01", "tipo_error": "desfase_legal",
        "oposicion": "AGE", "detalle": "x", "resuelto": False,
    })
    db.sembrar(("errores_generacion", "a2"), {
        "fuente": "auto_verificacion", "tema_id": "bloque_05-tema_01", "tipo_error": "desfase_legal",
        "oposicion": "GACE", "detalle": "y", "resuelto": False,
    })
    # Documento anterior a que se empezara a guardar la oposición (16/08/2026)
    # -- no debe aparecer bajo ningún filtro concreto, solo bajo "todas".
    db.sembrar(("errores_generacion", "a3"), {
        "fuente": "auto_verificacion", "tema_id": "bloque_05-tema_01", "tipo_error": "desfase_legal",
        "detalle": "z", "resuelto": False,
    })
    with _como():
        solo_age = client.get("/admin/api/errores-ia?resuelto=todos&oposicion=AGE", headers=_AUTH).get_json()
        todas = client.get("/admin/api/errores-ia?resuelto=todos&oposicion=todas", headers=_AUTH).get_json()
    assert {e["id"] for e in solo_age["entradas"]} == {"a1"}
    assert {e["id"] for e in todas["entradas"]} == {"a1", "a2", "a3"}


def test_errores_ia_exportar_csv_respeta_los_filtros(client, db):
    db.sembrar(("errores_generacion", "a1"), {
        "fuente": "auto_verificacion", "tema_id": "bloque_05-tema_01", "tipo_error": "desfase_legal",
        "oposicion": "AGE", "pregunta_texto": "¿Pregunta 1?", "detalle": "motivo uno", "resuelto": False,
    })
    db.sembrar(("errores_generacion", "a2"), {
        "fuente": "auto_verificacion", "tema_id": "bloque_02-tema_01", "tipo_error": "ambiguedad",
        "oposicion": "GACE", "pregunta_texto": "¿Pregunta 2?", "detalle": "motivo dos", "resuelto": False,
    })
    with _como():
        r = client.get("/admin/api/errores-ia/export?resuelto=todos&tipo_error=desfase_legal", headers=_AUTH)
    assert r.status_code == 200
    assert "text/csv" in r.content_type
    cuerpo = r.get_data(as_text=True)
    assert "¿Pregunta 1?" in cuerpo
    assert "motivo uno" in cuerpo
    assert "¿Pregunta 2?" not in cuerpo  # filtrada por tipo_error, no exportada


def test_errores_ia_exportar_requiere_permiso_temario(client, db):
    with _como(admin=False, uid="rep1", permisos=["reportes"]):
        r = client.get("/admin/api/errores-ia/export", headers=_AUTH)
    assert r.status_code == 403


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
    # Sentry sin configurar es OPCIONAL: no debe contar como crítico.
    critico = {s["nombre"]: s["critico"] for s in servicios}
    assert critico["IA (DeepSeek)"] is True
    assert critico["Errores (Sentry)"] is False


def test_sistema_diagnostico(client, db, monkeypatch):
    for k in ("DEEPSEEK_API_KEY", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
              "BREVO_API_KEY", "BREVO_FROM_EMAIL"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("STRIPE_PRICE_ID_BASICO", "price_basico")
    monkeypatch.setenv("STRIPE_PRICE_ID_PREMIUM", "price_premium")
    db.sembrar(("errores_generacion", "r1"), {"fuente": "usuario_admin", "estado": "pendiente"})
    db.sembrar(("config", "banner"), {"activo": True})
    with _como():
        d = client.get("/admin/api/sistema", headers=_AUTH).get_json()["diagnostico"]
    assert d["todo_ok"] is True  # todos los críticos configurados
    assert d["reportes_pendientes"] == 1
    assert d["banner_activo"] is True


def test_sistema_detecta_price_id_con_formato_invalido(client, db, monkeypatch):
    # Caso real de julio 2026: el ID de Producto de Stripe (prod_...) quedó
    # pegado por error donde iba el ID de Precio (price_...) -- el checkout
    # fallaba en producción pero este panel lo daba por bien configurado
    # porque antes solo comprobaba que la variable no estuviera vacía.
    monkeypatch.setenv("STRIPE_PRICE_ID_BASICO", "prod_UuRQjxkUdQgoYu")
    monkeypatch.setenv("STRIPE_PRICE_ID_PREMIUM", "price_premium")
    with _como():
        servicios = client.get("/admin/api/sistema", headers=_AUTH).get_json()["servicios"]
    por_nombre = {s["nombre"]: s["ok"] for s in servicios}
    assert por_nombre["Precios de planes"] is False


def test_limites_obtener_devuelve_defaults(client, db):
    with _como():
        cfg = client.get("/admin/api/limites", headers=_AUTH).get_json()
    assert cfg["tools"]["test_avanzado_verificado"]["premium"] == {"periodo": "dia", "limite": 1500}
    assert cfg["max_paginas"]["premium"] == 200
    assert any(m["id"] == "test_avanzado_verificado" for m in cfg["meta"])


def test_limites_guardar_y_afecta_a_la_cuota(client, db):
    from limites_uso import verificar_limite_uso
    with _como():
        r = client.put("/admin/api/limites", json={
            "tools": {"test_avanzado_verificado": {"basico": {"periodo": "dia", "limite": 1}}},
            "max_paginas": {"basico": 999},
        }, headers=_AUTH)
        assert r.status_code == 200
    # El override se guarda y ya cuenta como límite efectivo.
    guardado = db.leer(("config", "limites"))
    assert guardado["tools"]["test_avanzado_verificado"]["basico"]["limite"] == 1
    assert guardado["max_paginas"]["basico"] == 999
    # Y verificar_limite_uso lo respeta (1 uso permitido, el 2º ya bloquea).
    from datetime import date
    db.sembrar(("usuarios", "u9"), {"limites_uso": {"test_avanzado_verificado": {"dia": {"clave": date.today().isoformat(), "contador": 1}}}})
    permitido, _m, _u, limite = verificar_limite_uso(db, "u9", "basico", "test_avanzado_verificado")
    assert permitido is False
    assert limite == 1


def test_limites_solo_admin_total(client, db):
    # Un usuario con permiso "usuarios" (no admin total) no puede tocar límites.
    with _como(admin=False, permisos=["usuarios"]):
        r = client.get("/admin/api/limites", headers=_AUTH)
    assert r.status_code == 403


def test_banner_guardar_y_lectura_publica(client, db):
    with _como():
        client.put(
            "/admin/api/banner",
            json={"activo": True, "texto": "Hola", "tipo": "aviso", "fuente": "elegante", "animacion": "parpadeo"},
            headers=_AUTH,
        )
    # Lectura pública sin token.
    pub = client.get("/banner-global").get_json()
    assert pub["activo"] is True and pub["texto"] == "Hola" and pub["tipo"] == "aviso"
    assert pub["fuente"] == "elegante" and pub["animacion"] == "parpadeo"
    # Desactivado -> no expone el texto.
    with _como():
        client.put("/admin/api/banner", json={"activo": False, "texto": "Hola"}, headers=_AUTH)
    assert client.get("/banner-global").get_json() == {"activo": False}


def test_banner_fuente_animacion_invalidas_caen_a_valor_por_defecto(client, db):
    with _como():
        r = client.put(
            "/admin/api/banner",
            json={"activo": True, "texto": "Hola", "fuente": "no-existe", "animacion": "no-existe"},
            headers=_AUTH,
        )
    assert r.status_code == 200
    d = r.get_json()
    assert d["fuente"] == "default" and d["animacion"] == "ninguna"


def test_promocion_guardar_y_lectura_publica(client, db):
    with _como():
        r = client.put(
            "/admin/api/promocion",
            json={
                "activo": True, "plan": "premium", "descuento_pct": 20,
                "duracion_texto": "2 meses", "fecha_fin": "2099-01-01T00:00:00",
                "stripe_promotion_code": "promo_abc123", "mensaje": "Oferta especial",
                "fuente": "impacto", "animacion": "deslizante",
            },
            headers=_AUTH,
        )
    assert r.status_code == 200
    pub = client.get("/promocion-activa").get_json()
    assert pub["activo"] is True
    assert pub["plan"] == "premium"
    assert pub["descuento_pct"] == 20
    assert pub["stripe_promotion_code"] == "promo_abc123"
    assert pub["fuente"] == "impacto" and pub["animacion"] == "deslizante"


def test_promocion_fuente_animacion_invalidas_caen_a_valor_por_defecto(client, db):
    with _como():
        r = client.put(
            "/admin/api/promocion",
            json={"activo": True, "plan": "premium", "fuente": "no-existe", "animacion": "no-existe"},
            headers=_AUTH,
        )
    assert r.status_code == 200
    d = r.get_json()
    assert d["fuente"] == "default" and d["animacion"] == "ninguna"


def test_promocion_caducada_no_se_expone_aunque_siga_activa(client, db):
    with _como():
        client.put(
            "/admin/api/promocion",
            json={"activo": True, "plan": "premium", "descuento_pct": 15, "fecha_fin": "2000-01-01T00:00:00"},
            headers=_AUTH,
        )
    assert client.get("/promocion-activa").get_json() == {"activo": False}


def test_promocion_desactivada_no_se_expone(client, db):
    with _como():
        client.put("/admin/api/promocion", json={"activo": False, "plan": "premium"}, headers=_AUTH)
    assert client.get("/promocion-activa").get_json() == {"activo": False}


def test_promocion_sin_admin_devuelve_403(client, db):
    with _como(admin=False):
        r = client.put("/admin/api/promocion", json={"activo": True}, headers=_AUTH)
    assert r.status_code == 403


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


def test_auditoria_paginada(client, db):
    for i in range(60):
        db.sembrar(("admin_auditoria", f"a{i}"), {
            "accion": "algo", "objetivo": str(i), "email_admin": "admin@x.com",
            "fecha": f"2026-01-{(i % 28) + 1:02d}T00:00:0{i % 10}",
        })
    with _como():
        pagina1 = client.get("/admin/api/auditoria", headers=_AUTH).get_json()
        pagina2 = client.get("/admin/api/auditoria?pagina=2", headers=_AUTH).get_json()

    assert pagina1["total"] == 60
    assert len(pagina1["entradas"]) == 50
    assert len(pagina2["entradas"]) == 10
    objetivos_pagina1 = {e["objetivo"] for e in pagina1["entradas"]}
    objetivos_pagina2 = {e["objetivo"] for e in pagina2["entradas"]}
    assert not (objetivos_pagina1 & objetivos_pagina2)


# ---------- Reportes ----------
def test_usuario_reporta_y_admin_lo_revisa(client, db):
    # Un usuario normal reporta.
    sembrar_usuario_activo(db, "u1")
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "u1@x.com", "email_verified": True}):
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


# ---------- Bajas (motivos de cancelación) ----------
def test_bajas_requiere_permiso_reportes(client, db):
    with _como(admin=False, uid="x", permisos=[]):
        assert client.get("/admin/api/bajas", headers=_AUTH).status_code == 403
    with _como(admin=False, uid="mod1", permisos=["reportes"]):
        assert client.get("/admin/api/bajas", headers=_AUTH).status_code == 200


def test_bajas_agrega_motivos_de_todos_los_usuarios_sin_exponer_el_uid(client, db):
    # bajas_motivos es una subcolección por usuario -- se agrega con
    # collection_group, igual que preguntas_falladas, sin decir qué usuario
    # canceló qué (ver _bajas_agregadas en blueprints/admin.py).
    db.sembrar(("usuarios", "u1", "bajas_motivos", "b1"),
               {"motivo": "precio", "comentario": "Muy caro para mí", "oposicion": "AGE", "fecha": "2026-01-01T00:00:00"})
    db.sembrar(("usuarios", "u2", "bajas_motivos", "b1"),
               {"motivo": "precio", "comentario": "", "oposicion": "AGE", "fecha": "2026-01-02T00:00:00"})
    db.sembrar(("usuarios", "u2", "bajas_motivos", "b2"),
               {"motivo": "no_lo_uso", "comentario": "Ya no tengo tiempo", "oposicion": "GACE", "fecha": "2026-01-03T00:00:00"})

    with _como():
        d = client.get("/admin/api/bajas", headers=_AUTH).get_json()

    assert d["total"] == 3
    assert d["por_motivo"]["precio"] == 2
    assert d["por_motivo"]["no_lo_uso"] == 1
    assert d["por_motivo"]["otro"] == 0  # motivos sin ninguna baja siguen apareciendo, a 0
    assert d["por_oposicion"] == {"AGE": 2, "GACE": 1}
    # Solo se listan los comentarios no vacíos, más reciente primero, y sin uid/email.
    assert len(d["comentarios_recientes"]) == 2
    assert d["comentarios_recientes"][0]["comentario"] == "Ya no tengo tiempo"
    assert all("uid" not in c and "email" not in c for c in d["comentarios_recientes"])


def test_bajas_sin_ninguna_no_falla(client, db):
    with _como():
        d = client.get("/admin/api/bajas", headers=_AUTH).get_json()
    assert d["total"] == 0
    assert d["comentarios_recientes"] == []


def test_bajas_incluye_recientes_con_usuario_solo_si_hay_permiso_usuarios(client, db):
    # "recientes" (con uid/email, para poder hacer seguimiento) solo se
    # calcula si quien pide la lista tiene permiso 'usuarios' -- con solo
    # 'reportes' se sigue viendo el agregado anónimo de siempre, sin la
    # lista nominal.
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@x.com", "nombre": "Ana",
        "suscripciones": {"AGE": {"plan": "premium", "cancelar_al_final_periodo": True, "current_period_end": "2026-09-01T00:00:00"}},
    })
    db.sembrar(("usuarios", "u1", "bajas_motivos", "b1"), {
        "motivo": "precio", "comentario": "Muy caro", "oposicion": "AGE", "fecha": "2026-01-01T00:00:00",
    })
    with _como(admin=False, uid="mod1", permisos=["reportes"]):
        sin_permiso = client.get("/admin/api/bajas", headers=_AUTH).get_json()
    assert "recientes" not in sin_permiso

    with _como():
        con_permiso = client.get("/admin/api/bajas", headers=_AUTH).get_json()
    assert len(con_permiso["recientes"]) == 1
    fila = con_permiso["recientes"][0]
    assert fila["uid"] == "u1"
    assert fila["email"] == "u1@x.com"
    assert fila["motivo"] == "precio"
    # Sigue en premium (cancelar_al_final_periodo=True, no "gratis" todavía)
    # -- la baja está programada pero aún no es efectiva.
    assert fila["efectiva"] is False


def test_bajas_recientes_marca_efectiva_cuando_ya_volvio_a_gratis(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "suscripciones": {"AGE": {"plan": "gratis"}}})
    db.sembrar(("usuarios", "u1", "bajas_motivos", "b1"), {
        "motivo": "precio", "comentario": "", "oposicion": "AGE", "fecha": "2026-01-01T00:00:00",
    })
    with _como():
        d = client.get("/admin/api/bajas", headers=_AUTH).get_json()
    assert d["recientes"][0]["efectiva"] is True


# ---------- Vigilancia BOE: cambios de temario propuestos ----------
def test_cambios_temario_requiere_permiso_temario(client, db):
    with _como(admin=False, uid="mod1", permisos=["reportes"]):
        assert client.get("/admin/api/cambios-temario?estado=pendiente", headers=_AUTH).status_code == 403


def test_cambios_temario_lista_solo_el_estado_pedido(client, db):
    db.sembrar(("cambios_temario_propuestos", "c1"), {
        "oposicion": "AGE", "bloque_id": "bloque_01", "tema_id": "tema_01", "subbloque_id": "sub_1",
        "ley_nombre": "TREBEP", "resumen": "El plazo cambia.", "texto_eliminar": "quince días",
        "texto_anadir": "veinte días", "estado": "pendiente", "fecha_deteccion": "2026-01-01T00:00:00",
    })
    db.sembrar(("cambios_temario_propuestos", "c2"), {"estado": "descartado", "fecha_deteccion": "2026-01-01T00:00:00"})
    with _como():
        d = client.get("/admin/api/cambios-temario?estado=pendiente", headers=_AUTH).get_json()
    assert len(d["cambios"]) == 1
    assert d["cambios"][0]["id"] == "c1"
    assert d["cambios"][0]["resumen"] == "El plazo cambia."


def test_cambios_temario_aprobar_aplica_el_cambio_al_chunk(client, db):
    _sembrar_tema(db)  # texto = "Texto del chunk 1."
    db.sembrar(("cambios_temario_propuestos", "c1"), {
        "oposicion": "AGE", "bloque_id": "bloque_01", "tema_id": "tema_01", "subbloque_id": "sub_1",
        "resumen": "Cambia el chunk", "texto_eliminar": "chunk 1", "texto_anadir": "chunk actualizado",
        "estado": "pendiente",
    })
    with _como():
        resp = client.patch("/admin/api/cambios-temario/c1", json={"estado": "aprobado"}, headers=_AUTH)
    assert resp.status_code == 200
    chunk = db.leer(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1"))
    assert chunk["texto"] == "Texto del chunk actualizado."
    propuesta = db.leer(("cambios_temario_propuestos", "c1"))
    assert propuesta["estado"] == "aprobado"
    assert propuesta["revisado_por"] == "admin1"
    assert propuesta["revisado_por_email"] == "admin@example.com"
    with _como():
        d = client.get("/admin/api/cambios-temario?estado=aprobado", headers=_AUTH).get_json()
    assert d["cambios"][0]["revisado_por_email"] == "admin@example.com"
    assert d["cambios"][0]["fecha_revision"]


def test_cambios_temario_aprobar_falla_si_el_chunk_ya_no_coincide(client, db):
    _sembrar_tema(db)
    db.sembrar(("cambios_temario_propuestos", "c1"), {
        "oposicion": "AGE", "bloque_id": "bloque_01", "tema_id": "tema_01", "subbloque_id": "sub_1",
        "resumen": "Cambia el chunk", "texto_eliminar": "un texto que ya no está", "texto_anadir": "nuevo",
        "estado": "pendiente",
    })
    with _como():
        resp = client.patch("/admin/api/cambios-temario/c1", json={"estado": "aprobado"}, headers=_AUTH)
    assert resp.status_code == 409
    # No se ha tocado el chunk ni el estado de la propuesta.
    chunk = db.leer(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1"))
    assert chunk["texto"] == "Texto del chunk 1."
    assert db.leer(("cambios_temario_propuestos", "c1"))["estado"] == "pendiente"


def test_cambios_temario_descartar_no_toca_el_chunk(client, db):
    _sembrar_tema(db)
    db.sembrar(("cambios_temario_propuestos", "c1"), {
        "oposicion": "AGE", "bloque_id": "bloque_01", "tema_id": "tema_01", "subbloque_id": "sub_1",
        "texto_eliminar": "chunk 1", "texto_anadir": "chunk actualizado", "estado": "pendiente",
    })
    with _como():
        resp = client.patch("/admin/api/cambios-temario/c1", json={"estado": "descartado"}, headers=_AUTH)
    assert resp.status_code == 200
    chunk = db.leer(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1"))
    assert chunk["texto"] == "Texto del chunk 1."
    assert db.leer(("cambios_temario_propuestos", "c1"))["estado"] == "descartado"


# ---------- Vigilancia BOE: avisos oficiales ----------
def test_avisos_oficiales_requiere_permiso_reportes(client, db):
    with _como(admin=False, uid="mod1", permisos=["temario"]):
        assert client.get("/admin/api/avisos-oficiales?estado=pendiente", headers=_AUTH).status_code == 403


def test_avisos_oficiales_crear_manual_requiere_permiso_reportes(client, db):
    with _como(admin=False, uid="mod1", permisos=["temario"]):
        resp = client.post("/admin/api/avisos-oficiales", json={
            "oposicion": "AGE", "tipo": "fecha_examen", "titulo": "x",
        }, headers=_AUTH)
    assert resp.status_code == 403


def test_avisos_oficiales_crear_manual_ok(client, db):
    with _como():
        resp = client.post("/admin/api/avisos-oficiales", json={
            "oposicion": "AGE", "tipo": "fecha_examen",
            "titulo": "Llamamiento extraordinario del ejercicio único",
            "resumen": "Repesca para aspirantes convocados el 24 de julio.",
            "url_boe": "https://run.gob.es/hsblF8yLcR",
            "fecha_boe": "20260715",
        }, headers=_AUTH)
    assert resp.status_code == 201
    aid = resp.get_json()["id"]
    d = db.leer(("avisos_oficiales", aid))
    assert d["oposiciones"] == ["AGE"]
    assert d["tipo"] == "fecha_examen"
    assert d["titulo"] == "Llamamiento extraordinario del ejercicio único"
    assert d["url_boe"] == "https://run.gob.es/hsblF8yLcR"
    assert d["fecha_boe"] == "20260715"
    assert d["estado"] == "pendiente"
    assert d["creado_manualmente_por"] == "admin1"


def test_avisos_oficiales_crear_manual_rellena_resumen_y_fecha_por_defecto(client, db):
    with _como():
        resp = client.post("/admin/api/avisos-oficiales", json={
            "oposicion": "GACE", "tipo": "convocatoria", "titulo": "Título sin resumen",
        }, headers=_AUTH)
    assert resp.status_code == 201
    d = db.leer(("avisos_oficiales", resp.get_json()["id"]))
    assert d["resumen"] == "Título sin resumen"
    assert d["fecha_boe"]  # se rellena con la fecha de hoy


def test_avisos_oficiales_crear_manual_con_varias_oposiciones(client, db):
    with _como():
        resp = client.post("/admin/api/avisos-oficiales", json={
            "oposiciones": ["AGE", "GACE"], "tipo": "llamamiento_extraordinario",
            "titulo": "Llamamiento extraordinario (AGE y GACE)",
        }, headers=_AUTH)
    assert resp.status_code == 201
    d = db.leer(("avisos_oficiales", resp.get_json()["id"]))
    assert d["oposiciones"] == ["AGE", "GACE"]


def test_avisos_oficiales_crear_manual_rechaza_sin_ninguna_oposicion(client, db):
    with _como():
        resp = client.post("/admin/api/avisos-oficiales", json={
            "oposiciones": [], "tipo": "convocatoria", "titulo": "x",
        }, headers=_AUTH)
    assert resp.status_code == 400


def test_avisos_oficiales_crear_manual_rechaza_oposicion_invalida(client, db):
    with _como():
        resp = client.post("/admin/api/avisos-oficiales", json={
            "oposicion": "NO_EXISTE", "tipo": "convocatoria", "titulo": "x",
        }, headers=_AUTH)
    assert resp.status_code == 400


def test_avisos_oficiales_crear_manual_rechaza_tipo_invalido(client, db):
    with _como():
        resp = client.post("/admin/api/avisos-oficiales", json={
            "oposicion": "AGE", "tipo": "lo-que-sea", "titulo": "x",
        }, headers=_AUTH)
    assert resp.status_code == 400


def test_avisos_oficiales_crear_manual_rechaza_titulo_vacio(client, db):
    with _como():
        resp = client.post("/admin/api/avisos-oficiales", json={
            "oposicion": "AGE", "tipo": "convocatoria", "titulo": "   ",
        }, headers=_AUTH)
    assert resp.status_code == 400


def test_avisos_oficiales_publicar_y_descartar(client, db):
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposicion": "GACE", "tipo": "convocatoria", "titulo": "Convocatoria GACE 2026",
        "resumen": "Nueva convocatoria.", "url_boe": "https://boe.es/x", "estado": "pendiente",
    })
    with _como():
        resp = client.patch("/admin/api/avisos-oficiales/a1", json={"estado": "publicado"}, headers=_AUTH)
        assert resp.status_code == 200
        d = client.get("/admin/api/avisos-oficiales?estado=publicado", headers=_AUTH).get_json()
    assert len(d["avisos"]) == 1
    assert d["avisos"][0]["titulo"] == "Convocatoria GACE 2026"
    assert d["avisos"][0]["revisado_por_email"] == "admin@example.com"
    assert db.leer(("avisos_oficiales", "a1"))["revisado_por"] == "admin1"


def test_avisos_oficiales_estado_invalido_rechaza(client, db):
    db.sembrar(("avisos_oficiales", "a1"), {"estado": "pendiente"})
    with _como():
        resp = client.patch("/admin/api/avisos-oficiales/a1", json={"estado": "lo-que-sea"}, headers=_AUTH)
    assert resp.status_code == 400


def test_avisos_oficiales_publicar_dispara_pagina_estatica_y_email(client, db):
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposicion": "AGE", "tipo": "convocatoria", "titulo": "Convocatoria AGE 2026",
        "url_boe": "https://boe.es/x", "estado": "pendiente",
    })
    with patch("publicacion_estatica_boe.actualizar_pagina_estatica_avisos") as mock_pagina, \
         patch("publicacion_estatica_boe.actualizar_pagina_avisos_general") as mock_hub, \
         patch("publicacion_estatica_boe.notificar_usuarios_aviso_oficial") as mock_notificar, \
         _como():
        resp = client.patch("/admin/api/avisos-oficiales/a1", json={"estado": "publicado"}, headers=_AUTH)

    assert resp.status_code == 200
    mock_pagina.assert_called_once_with(db, "AGE")
    mock_hub.assert_called_once_with(db)
    mock_notificar.assert_called_once()
    aviso_pasado = mock_notificar.call_args.args[1]
    assert aviso_pasado["titulo"] == "Convocatoria AGE 2026"
    assert aviso_pasado["estado"] == "publicado"


def test_avisos_oficiales_publicar_con_varias_oposiciones_regenera_las_paginas_de_todas(client, db):
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposiciones": ["AGE", "GACE"], "tipo": "llamamiento_extraordinario",
        "titulo": "Llamamiento extraordinario (AGE y GACE)", "estado": "pendiente",
    })
    with patch("publicacion_estatica_boe.actualizar_pagina_estatica_avisos") as mock_pagina, \
         patch("publicacion_estatica_boe.actualizar_pagina_avisos_general") as mock_hub, \
         patch("publicacion_estatica_boe.notificar_usuarios_aviso_oficial") as mock_notificar, \
         _como():
        resp = client.patch("/admin/api/avisos-oficiales/a1", json={"estado": "publicado"}, headers=_AUTH)

    assert resp.status_code == 200
    assert {c.args[1] for c in mock_pagina.call_args_list} == {"AGE", "GACE"}
    mock_hub.assert_called_once_with(db)
    mock_notificar.assert_called_once()  # una sola vez, no una por oposición


def test_avisos_oficiales_no_redispara_al_volver_a_guardar_publicado(client, db):
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposicion": "AGE", "tipo": "convocatoria", "titulo": "Convocatoria AGE 2026",
        "url_boe": "https://boe.es/x", "estado": "publicado",
    })
    with patch("publicacion_estatica_boe.actualizar_pagina_estatica_avisos") as mock_pagina, \
         patch("publicacion_estatica_boe.notificar_usuarios_aviso_oficial") as mock_notificar, \
         _como():
        resp = client.patch("/admin/api/avisos-oficiales/a1", json={"estado": "publicado"}, headers=_AUTH)

    assert resp.status_code == 200
    mock_pagina.assert_not_called()
    mock_notificar.assert_not_called()


def test_avisos_oficiales_descartar_no_dispara_pagina_ni_email(client, db):
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposicion": "AGE", "tipo": "convocatoria", "titulo": "Convocatoria AGE 2026",
        "url_boe": "https://boe.es/x", "estado": "pendiente",
    })
    with patch("publicacion_estatica_boe.actualizar_pagina_estatica_avisos") as mock_pagina, \
         patch("publicacion_estatica_boe.notificar_usuarios_aviso_oficial") as mock_notificar, \
         _como():
        resp = client.patch("/admin/api/avisos-oficiales/a1", json={"estado": "descartado"}, headers=_AUTH)

    assert resp.status_code == 200
    mock_pagina.assert_not_called()
    mock_notificar.assert_not_called()


def test_avisos_oficiales_crear_manual_con_tipo_personalizado_y_url_inap(client, db):
    with _como():
        resp = client.post("/admin/api/avisos-oficiales", json={
            "oposicion": "AGE", "tipo": "otro", "tipo_personalizado": "Repesca especial",
            "titulo": "x", "url_inap": "https://run.gob.es/algo-concreto",
        }, headers=_AUTH)
    assert resp.status_code == 201
    d = db.leer(("avisos_oficiales", resp.get_json()["id"]))
    assert d["tipo_personalizado"] == "Repesca especial"
    assert d["url_inap"] == "https://run.gob.es/algo-concreto"


def test_avisos_oficiales_listar_incluye_tipo_personalizado_y_url_inap(client, db):
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposicion": "AGE", "tipo": "otro", "tipo_personalizado": "Repesca especial",
        "titulo": "x", "url_inap": "https://run.gob.es/algo", "estado": "pendiente",
    })
    with _como():
        d = client.get("/admin/api/avisos-oficiales?estado=pendiente", headers=_AUTH).get_json()
    assert d["avisos"][0]["tipo_personalizado"] == "Repesca especial"
    assert d["avisos"][0]["url_inap"] == "https://run.gob.es/algo"


def test_avisos_oficiales_editar_requiere_permiso_reportes(client, db):
    db.sembrar(("avisos_oficiales", "a1"), {"oposicion": "AGE", "tipo": "convocatoria", "titulo": "x", "estado": "pendiente"})
    with _como(admin=False, uid="mod1", permisos=["temario"]):
        resp = client.put("/admin/api/avisos-oficiales/a1", json={"titulo": "y"}, headers=_AUTH)
    assert resp.status_code == 403


def test_avisos_oficiales_editar_corrige_contenido(client, db):
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposicion": "AGE", "tipo": "convocatoria", "titulo": "Título con typo",
        "url_boe": "https://boe.es/mal", "estado": "pendiente",
    })
    with _como():
        resp = client.put("/admin/api/avisos-oficiales/a1", json={
            "oposicion": "AGE", "tipo": "convocatoria", "titulo": "Título corregido",
            "url_boe": "https://boe.es/bien", "url_inap": "https://run.gob.es/x",
        }, headers=_AUTH)
    assert resp.status_code == 200
    d = db.leer(("avisos_oficiales", "a1"))
    assert d["titulo"] == "Título corregido"
    assert d["url_boe"] == "https://boe.es/bien"
    assert d["url_inap"] == "https://run.gob.es/x"
    assert d["estado"] == "pendiente"  # el PUT no toca el estado
    assert d["editado_por"] == "admin1"


def test_avisos_oficiales_editar_uno_ya_publicado_regenera_pagina_pero_no_reenvia_email(client, db):
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposicion": "AGE", "tipo": "convocatoria", "titulo": "Título con typo",
        "url_boe": "https://boe.es/mal", "estado": "publicado",
    })
    with patch("publicacion_estatica_boe.actualizar_pagina_estatica_avisos") as mock_pagina, \
         patch("publicacion_estatica_boe.actualizar_pagina_avisos_general") as mock_hub, \
         patch("publicacion_estatica_boe.notificar_usuarios_aviso_oficial") as mock_notificar, \
         _como():
        resp = client.put("/admin/api/avisos-oficiales/a1", json={
            "oposicion": "AGE", "tipo": "convocatoria", "titulo": "Título corregido",
            "url_boe": "https://boe.es/bien",
        }, headers=_AUTH)
    assert resp.status_code == 200
    mock_pagina.assert_called_once_with(db, "AGE")
    mock_hub.assert_called_once_with(db)
    mock_notificar.assert_not_called()


def test_avisos_oficiales_editar_quitando_una_oposicion_regenera_tambien_su_pagina(client, db):
    # Si se quita GACE de la lista, su página tiene que regenerarse para
    # que el aviso desaparezca de ahí (no solo la de las que quedan).
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposiciones": ["AGE", "GACE"], "tipo": "convocatoria", "titulo": "x", "estado": "publicado",
    })
    with patch("publicacion_estatica_boe.actualizar_pagina_estatica_avisos") as mock_pagina, \
         patch("publicacion_estatica_boe.actualizar_pagina_avisos_general") as mock_hub, \
         _como():
        resp = client.put("/admin/api/avisos-oficiales/a1", json={
            "oposiciones": ["AGE"], "titulo": "x",
        }, headers=_AUTH)
    assert resp.status_code == 200
    assert {c.args[1] for c in mock_pagina.call_args_list} == {"AGE", "GACE"}
    mock_hub.assert_called_once_with(db)
    assert db.leer(("avisos_oficiales", "a1"))["oposiciones"] == ["AGE"]


def test_avisos_oficiales_editar_uno_pendiente_no_regenera_pagina(client, db):
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposicion": "AGE", "tipo": "convocatoria", "titulo": "x", "estado": "pendiente",
    })
    with patch("publicacion_estatica_boe.actualizar_pagina_estatica_avisos") as mock_pagina, _como():
        resp = client.put("/admin/api/avisos-oficiales/a1", json={
            "oposicion": "AGE", "tipo": "convocatoria", "titulo": "y",
        }, headers=_AUTH)
    assert resp.status_code == 200
    mock_pagina.assert_not_called()


def test_avisos_oficiales_editar_no_encontrado(client, db):
    with _como():
        resp = client.put("/admin/api/avisos-oficiales/no-existe", json={"titulo": "y"}, headers=_AUTH)
    assert resp.status_code == 404


def test_avisos_oficiales_editar_rechaza_titulo_vacio(client, db):
    db.sembrar(("avisos_oficiales", "a1"), {"oposicion": "AGE", "tipo": "convocatoria", "titulo": "x", "estado": "pendiente"})
    with _como():
        resp = client.put("/admin/api/avisos-oficiales/a1", json={"titulo": "   "}, headers=_AUTH)
    assert resp.status_code == 400


def test_avisos_oficiales_editar_rechaza_tipo_invalido(client, db):
    db.sembrar(("avisos_oficiales", "a1"), {"oposicion": "AGE", "tipo": "convocatoria", "titulo": "x", "estado": "pendiente"})
    with _como():
        resp = client.put("/admin/api/avisos-oficiales/a1", json={"tipo": "lo-que-sea"}, headers=_AUTH)
    assert resp.status_code == 400


def test_vigilancia_boe_salud_devuelve_lo_guardado_por_el_chequeo(client, db):
    db.sembrar(("config", "vigilancia_boe"), {
        "temas_faltantes": [{"oposicion": "GACE", "bloque_id": "bloque_09", "tema_id": "tema_99"}],
        "temas_faltantes_fecha": "2026-07-23T00:00:00",
    })
    with _como():
        resp = client.get("/admin/api/vigilancia-boe-salud", headers=_AUTH)
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["temas_faltantes"] == [{"oposicion": "GACE", "bloque_id": "bloque_09", "tema_id": "tema_99"}]
    assert d["fecha"] == "2026-07-23T00:00:00"


def test_vigilancia_boe_salud_sin_datos_previos_devuelve_vacio(client, db):
    with _como():
        resp = client.get("/admin/api/vigilancia-boe-salud", headers=_AUTH)
    assert resp.status_code == 200
    assert resp.get_json() == {"temas_faltantes": [], "fecha": ""}


def test_vigilancia_boe_salud_requiere_permiso_reportes(client, db):
    with _como(admin=False, uid="mod1", permisos=["temario"]):
        assert client.get("/admin/api/vigilancia-boe-salud", headers=_AUTH).status_code == 403


def test_resumen_incluye_pendientes_de_vigilancia_boe(client, db):
    db.sembrar(("cambios_temario_propuestos", "c1"), {"estado": "pendiente"})
    db.sembrar(("avisos_oficiales", "a1"), {"estado": "pendiente"})
    db.sembrar(("avisos_oficiales", "a2"), {"estado": "publicado"})
    with _como():
        d = client.get("/admin/api/resumen", headers=_AUTH).get_json()
    assert d["cambios_temario_pendientes"] == 1
    assert d["avisos_oficiales_pendientes"] == 1
