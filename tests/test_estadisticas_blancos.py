"""Prueba de que /estadisticas-completas suma las preguntas en blanco de
todos los tests finalizados de la oposición (sin contar borradores
"en_progreso" ni tests de otra oposición)."""
from guardar_resultado import obtener_estadisticas_completas_usuario


def test_total_blancos_suma_tests_finalizados_de_la_oposicion(db):
    db.sembrar(("usuarios", "u1"), {"estadisticas": {"age": {"tests_realizados": 2}}})
    db.sembrar(("usuarios", "u1", "tests", "t1"), {"oposicion": "age", "estado": "finalizado", "blancos": 3})
    db.sembrar(("usuarios", "u1", "tests", "t2"), {"oposicion": "age", "estado": "finalizado", "blancos": 2})
    # No debe contar: borrador en progreso y test de otra oposición
    db.sembrar(("usuarios", "u1", "tests", "t3"), {"oposicion": "age", "estado": "en_progreso", "blancos": 10})
    db.sembrar(("usuarios", "u1", "tests", "t4"), {"oposicion": "gace", "estado": "finalizado", "blancos": 7})

    estadisticas = obtener_estadisticas_completas_usuario(db, "u1", oposicion="age")

    assert estadisticas["total_blancos"] == 5


def test_total_blancos_cero_sin_tests(db):
    db.sembrar(("usuarios", "u1"), {"estadisticas": {}})

    estadisticas = obtener_estadisticas_completas_usuario(db, "u1", oposicion="age")

    assert estadisticas["total_blancos"] == 0


def test_incluye_historial_tests_para_la_grafica_de_evolucion(db):
    # Bug: la ruta usada por la página de Estadísticas no devolvía
    # "historial_tests" aunque sí estuviera guardado, así que la gráfica de
    # "Evolución de tu nota" nunca tenía datos que pintar.
    historial = [{"fecha": "2026-01-01T00:00:00", "puntuacion_final": 7.5, "resultado": "aprobado"}]
    db.sembrar(("usuarios", "u1"), {"estadisticas": {"age": {"historial_tests": historial}}})

    estadisticas = obtener_estadisticas_completas_usuario(db, "u1", oposicion="age")

    assert estadisticas["historial_tests"] == historial
