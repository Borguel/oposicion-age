"""Pruebas de /mi-perfil: en particular, que un administrador (custom
claim de Firebase) nunca vea el banner ni la pantalla de bloqueo de
prueba/plan en el frontend, aunque su cuenta no tenga ninguna
suscripción de pago -- mismo bypass que ya tiene requiere_plan() para
las rutas protegidas (ver auth_utils.py)."""

from conftest import sembrar_usuario_activo


def test_mi_perfil_usuario_normal_sin_plan_ni_prueba_da_gratis(client, db, usuario_autenticado):
    db.sembrar(("usuarios", "u1"), {"suscripciones": {}})
    usuario_autenticado()
    resp = client.get("/mi-perfil?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert resp.get_json()["plan"] == "gratis"


def test_mi_perfil_admin_sin_plan_ni_prueba_da_premium(client, db, usuario_autenticado):
    db.sembrar(("usuarios", "adm"), {"suscripciones": {}})
    usuario_autenticado(uid="adm", email="adm@example.com", admin=True)
    resp = client.get("/mi-perfil?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    datos = resp.get_json()
    assert datos["plan"] == "premium"
    assert datos["subscription_status"] == "active"


def test_mi_perfil_admin_sin_documento_de_usuario_da_premium(client, db, usuario_autenticado):
    usuario_autenticado(uid="fantasma_admin", email="fantasma@example.com", admin=True)
    resp = client.get("/mi-perfil?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert resp.get_json()["plan"] == "premium"


def test_mi_perfil_admin_con_plan_de_pago_sigue_dando_premium(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "adm2", plan="premium", email="adm2@example.com")
    usuario_autenticado(uid="adm2", email="adm2@example.com", admin=True)
    resp = client.get("/mi-perfil?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.get_json()["plan"] == "premium"


def test_mi_perfil_sincroniza_el_email_si_cambio_en_firebase_auth(client, db, usuario_autenticado):
    # Bug real (25/08/2026, auditoría): usuarios/{uid}.email solo se
    # escribía una vez, al crear el documento -- cambiar de correo desde Mi
    # Cuenta (verifyBeforeUpdateEmail) actualiza Firebase Auth, pero nada
    # volvía a sincronizar este campo en Firestore, así que el panel admin y
    # las exportaciones seguían mostrando el correo antiguo para siempre.
    db.sembrar(("usuarios", "u1"), {"email": "viejo@example.com", "suscripciones": {}})
    usuario_autenticado(email="nuevo@example.com")
    resp = client.get("/mi-perfil?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert resp.get_json()["email"] == "nuevo@example.com"
    assert db.leer(("usuarios", "u1"))["email"] == "nuevo@example.com"


def test_mi_perfil_con_el_mismo_email_no_cambia_nada(client, db, usuario_autenticado):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "suscripciones": {}})
    usuario_autenticado()  # mismo email por defecto: u1@example.com
    resp = client.get("/mi-perfil?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.get_json()["email"] == "u1@example.com"
    assert db.leer(("usuarios", "u1"))["email"] == "u1@example.com"
