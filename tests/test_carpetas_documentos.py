"""Pruebas del catálogo de carpetas de Mis Documentos (documentos_pdf.py +
rutas de blueprints/pdf_ia.py): crear una carpeta debe hacerla aparecer
aunque no tenga documentos dentro todavía, borrarla debe dejar "sin
carpeta" a los documentos que tuviera en vez de borrarlos, y editarla
(nombre y/o color) debe reasignar los documentos que tuviera al nombre
nuevo sin perder ninguno."""

from documentos_pdf import listar_carpetas, crear_carpeta, eliminar_carpeta, renombrar_carpeta
from conftest import sembrar_usuario_activo


def test_carpeta_recien_creada_aparece_vacia(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    crear_carpeta(db, "u1", "Tema 1")
    assert listar_carpetas(db, "u1") == [{"nombre": "Tema 1", "color": "azul"}]


def test_crear_carpeta_con_nombre_vacio_no_hace_nada(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    resultado = crear_carpeta(db, "u1", "   ")
    assert resultado is None
    assert listar_carpetas(db, "u1") == []


def test_listar_carpetas_incluye_las_ya_usadas_por_documentos_antiguos(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"carpeta": "Carpeta antigua"})
    assert listar_carpetas(db, "u1") == [{"nombre": "Carpeta antigua", "color": "azul"}]


def test_eliminar_carpeta_deja_sin_carpeta_los_documentos_dentro(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "carpetas_documentos": ["Tema 1"]})
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"carpeta": "Tema 1"})
    eliminar_carpeta(db, "u1", "Tema 1")
    assert listar_carpetas(db, "u1") == []
    assert db.leer(("usuarios", "u1", "documentos", "d1"))["carpeta"] == ""


def test_ruta_crear_carpeta_devuelve_error_si_esta_vacio(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    resp = client.post("/carpetas-documentos", json={"nombre": ""}, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 400


def test_ruta_crear_y_ver_carpeta_en_mis_documentos(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    resp = client.post("/carpetas-documentos", json={"nombre": "Constitución"}, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert resp.get_json()["nombre"] == "Constitución"

    resp = client.get("/mis-documentos", headers={"Authorization": "Bearer x"})
    assert resp.get_json()["carpetas"] == [{"nombre": "Constitución", "color": "azul"}]


def test_ruta_eliminar_carpeta(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    client.post("/carpetas-documentos", json={"nombre": "Temporal"}, headers={"Authorization": "Bearer x"})
    resp = client.delete("/carpetas-documentos", json={"nombre": "Temporal"}, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    resp = client.get("/mis-documentos", headers={"Authorization": "Bearer x"})
    assert resp.get_json()["carpetas"] == []


# ---------- Editar carpeta (renombrar_carpeta / PATCH /carpetas-documentos) ----------

def test_renombrar_carpeta_reasigna_los_documentos_al_nombre_nuevo(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "carpetas_documentos": ["Tema 1"]})
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"carpeta": "Tema 1"})
    db.sembrar(("usuarios", "u1", "documentos", "d2"), {"carpeta": "Tema 1"})
    resultado = renombrar_carpeta(db, "u1", "Tema 1", "Tema 1 (repaso)", "verde")
    assert resultado == "Tema 1 (repaso)"
    assert listar_carpetas(db, "u1") == [{"nombre": "Tema 1 (repaso)", "color": "verde"}]
    assert db.leer(("usuarios", "u1", "documentos", "d1"))["carpeta"] == "Tema 1 (repaso)"
    assert db.leer(("usuarios", "u1", "documentos", "d2"))["carpeta"] == "Tema 1 (repaso)"


def test_renombrar_carpeta_solo_color_no_toca_los_documentos(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "carpetas_documentos": ["Tema 1"]})
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"carpeta": "Tema 1"})
    resultado = renombrar_carpeta(db, "u1", "Tema 1", "Tema 1", "morado")
    assert resultado == "Tema 1"
    assert listar_carpetas(db, "u1") == [{"nombre": "Tema 1", "color": "morado"}]
    assert db.leer(("usuarios", "u1", "documentos", "d1"))["carpeta"] == "Tema 1"


def test_renombrar_carpeta_rechaza_nombre_vacio(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "carpetas_documentos": ["Tema 1"]})
    assert renombrar_carpeta(db, "u1", "Tema 1", "   ", "azul") == "vacio"
    assert listar_carpetas(db, "u1") == [{"nombre": "Tema 1", "color": "azul"}]


def test_renombrar_carpeta_rechaza_color_invalido(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "carpetas_documentos": ["Tema 1"]})
    assert renombrar_carpeta(db, "u1", "Tema 1", "Tema 1", "rojo") == "color_invalido"


def test_renombrar_carpeta_rechaza_nombre_duplicado(db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "carpetas_documentos": ["Tema 1", "Tema 2"],
    })
    resultado = renombrar_carpeta(db, "u1", "Tema 1", "Tema 2", "azul")
    assert resultado == "duplicado"
    # No se ha tocado nada: ambas carpetas siguen con su nombre de antes.
    nombres = {c["nombre"] for c in listar_carpetas(db, "u1")}
    assert nombres == {"Tema 1", "Tema 2"}


def test_ruta_editar_carpeta(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    client.post("/carpetas-documentos", json={"nombre": "Temporal"}, headers={"Authorization": "Bearer x"})
    resp = client.patch(
        "/carpetas-documentos",
        json={"nombre_actual": "Temporal", "nombre_nuevo": "Definitiva", "color": "turquesa"},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"mensaje": "ok", "nombre": "Definitiva", "color": "turquesa"}

    resp = client.get("/mis-documentos", headers={"Authorization": "Bearer x"})
    assert resp.get_json()["carpetas"] == [{"nombre": "Definitiva", "color": "turquesa"}]


def test_ruta_editar_carpeta_devuelve_409_si_el_nombre_ya_existe(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    client.post("/carpetas-documentos", json={"nombre": "A"}, headers={"Authorization": "Bearer x"})
    client.post("/carpetas-documentos", json={"nombre": "B"}, headers={"Authorization": "Bearer x"})
    resp = client.patch(
        "/carpetas-documentos",
        json={"nombre_actual": "A", "nombre_nuevo": "B", "color": "azul"},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 409


def test_ruta_editar_carpeta_devuelve_400_si_el_color_no_es_valido(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1")
    usuario_autenticado(email_verified=True)
    client.post("/carpetas-documentos", json={"nombre": "A"}, headers={"Authorization": "Bearer x"})
    resp = client.patch(
        "/carpetas-documentos",
        json={"nombre_actual": "A", "nombre_nuevo": "A", "color": "rojo"},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 400
