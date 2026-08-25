"""Validación de parámetros de query en rutas_progreso.py: /test-desde-historial
y /contenido-pdf-guardado hacían int(request.args.get(...)) sin capturar
excepciones -- un parámetro no numérico daba un 500 genérico (bug real,
ronda de auditoría #5) en vez de degradar al valor por defecto, como ya
hacen las rutas equivalentes de blueprints/pdf_ia.py para este mismo
parámetro."""
from conftest import sembrar_usuario_activo


def test_test_desde_historial_con_cantidad_no_numerica_no_revienta(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    db.sembrar(("usuarios", "u1", "tests", "t1"), {
        "oposicion": "AGE",
        "preguntas": [{"pregunta": "p1", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}}],
    })
    usuario_autenticado()
    resp = client.get("/test-desde-historial?oposicion=AGE&cantidad=abc", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert len(resp.get_json()["test"]) == 1  # se usa el valor por defecto (10), no revienta


def test_contenido_pdf_guardado_con_limite_no_numerico_no_revienta(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="premium")
    db.sembrar(("usuarios", "u1", "resumenes_pdf", "r1"), {"fecha": "2026-01-01T00:00:00", "titulo": "Resumen 1"})
    usuario_autenticado()
    resp = client.get(
        "/contenido-pdf-guardado?tipo_contenido=resumenes_pdf&limite=abc",
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 200
    assert len(resp.get_json()["contenido"]) == 1  # se usa el valor por defecto (10), no revienta
