"""Regresión: al finalizar un test con preguntas que traen imagen (hoy, solo
la prueba de razonamiento espacial de Metro -- ver
cargar_psicotecnico_metro.py), el campo "imagen" tiene que sobrevivir al
guardado en usuarios/{uid}/tests/{id}. Si no, "Repetir test" (que reconstruye
las preguntas a partir de ese documento guardado, ver repetir-test/script.js)
se queda sin figura que mostrar -- bug real reportado por el usuario:
funcionaba en el test recién generado pero no al repetirlo desde Mis Tests."""

from conftest import sembrar_usuario_activo


def test_guardar_test_conserva_la_imagen_de_cada_pregunta(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    contenido = [
        {
            "pregunta": "¿Cuántos cubos hay en la figura?",
            "respuesta_correcta": "A",
            "opciones": {"A": "12", "B": "10", "C": "14", "D": "9"},
            "imagen": "/assets/psicotecnico-metro/gen_cubos_51.png",
        },
        {
            "pregunta": "Sin figura",
            "respuesta_correcta": "A",
            "opciones": {"A": "x", "B": "y"},
        },
    ]
    respuestas = ["A", "A"]
    usuario_autenticado()
    resp = client.post("/guardar-test?oposicion=METRO", json={
        "test_id": "t1",
        "contenido": contenido,
        "respuestas": respuestas,
        "metadatos": {"tipo": "psicotecnico", "tiempo": 0},
    }, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    guardado = db.leer(("usuarios", "u1", "tests", "t1"))
    assert guardado["preguntas"][0]["imagen"] == "/assets/psicotecnico-metro/gen_cubos_51.png"
    # una pregunta sin imagen no debe romperse ni inventarse una
    assert guardado["preguntas"][1]["imagen"] == ""
