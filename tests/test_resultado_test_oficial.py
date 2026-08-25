"""Pruebas de que "aprobado/suspendido" se calcula con la misma fórmula
oficial (aciertos - fallos/3, sobre el total de preguntas) en todos los
sitios que lo usan -- antes había 3 versiones distintas que no siempre
coincidían entre sí (ver utils.calcular_resultado_test)."""

from conftest import sembrar_usuario_activo
from utils import calcular_resultado_test
from registro_progreso_usuario import actualizar_estadisticas_test, revertir_estadisticas_test, actualizar_estadisticas_esquema


def _contenido_con_aciertos_y_fallos(aciertos, fallos, blancos=0):
    """Genera `aciertos` preguntas acertadas + `fallos` falladas + `blancos`
    sin responder, cada una con una respuesta_correcta distinta para poder
    controlar el resultado exacto de cada una."""
    contenido = []
    respuestas = []
    for i in range(aciertos):
        contenido.append({"pregunta": f"acierto {i}", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}})
        respuestas.append("A")
    for i in range(fallos):
        contenido.append({"pregunta": f"fallo {i}", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}})
        respuestas.append("B")
    for i in range(blancos):
        contenido.append({"pregunta": f"blanco {i}", "respuesta_correcta": "A", "opciones": {"A": "x", "B": "y"}})
        respuestas.append(None)
    return contenido, respuestas


def test_calcular_resultado_test_claramente_aprobado():
    _, nota, resultado = calcular_resultado_test(9, 1, 0)
    assert resultado == "aprobado"
    assert nota >= 5


def test_calcular_resultado_test_caso_del_bug_reportado():
    # 6 aciertos, 4 fallos, 0 blancos: acierto en bruto 60% (parecería
    # aprobado con un umbral ingenuo), pero la nota oficial con
    # penalización es 4.68/10 -> debe ser "suspendido".
    puntuacion, nota, resultado = calcular_resultado_test(6, 4, 0)
    assert puntuacion == 4.67
    assert nota == 4.67
    assert resultado == "suspendido"


def test_calcular_resultado_test_frontera_exacta_en_5():
    # 10 preguntas, 10 aciertos, 0 fallos -> nota 10/10, claramente aprobado;
    # comprobamos que el umbral es >= 5, no > 5.
    _, nota, resultado = calcular_resultado_test(5, 0, 5)
    assert nota == 5.0
    assert resultado == "aprobado"


def test_calcular_resultado_test_blancos_cambian_el_resultado():
    # Mismos aciertos/fallos, pero con más preguntas en blanco el total
    # crece y la nota baja -- puede cambiar de aprobado a suspendido.
    _, nota_sin_blancos, resultado_sin_blancos = calcular_resultado_test(5, 0, 0)
    _, nota_con_blancos, resultado_con_blancos = calcular_resultado_test(5, 0, 5)
    assert resultado_sin_blancos == "aprobado"
    assert nota_con_blancos < nota_sin_blancos


def test_guardar_test_con_numeros_del_bug_guarda_suspendido(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    contenido, respuestas = _contenido_con_aciertos_y_fallos(aciertos=6, fallos=4)
    usuario_autenticado()
    resp = client.post("/guardar-test?oposicion=AGE", json={
        "contenido": contenido,
        "respuestas": respuestas,
        "metadatos": {"tipo": "personalizado", "tiempo": 0}
    }, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    listado = client.get("/mis-tests?oposicion=AGE", headers={"Authorization": "Bearer x"}).get_json()
    assert len(listado["tests"]) == 1
    test_guardado = listado["tests"][0]
    assert test_guardado["aciertos"] == 6
    assert test_guardado["fallos"] == 4
    assert test_guardado["resultado"] == "suspendido"


def test_mis_tests_autocura_un_resultado_guardado_mal(client, db, usuario_autenticado):
    # Simula un test guardado ANTES del arreglo: aciertos/fallos correctos
    # pero con el campo "resultado" mal calculado (como estaba el bug).
    sembrar_usuario_activo(db, "u1", plan="basico")
    db.sembrar(("usuarios", "u1", "tests", "t1"), {
        "oposicion": "AGE",
        "estado": "finalizado",
        "aciertos": 6,
        "fallos": 4,
        "blancos": 0,
        "resultado": "aprobado",  # valor viejo/incorrecto ya guardado
        "fecha": "2026-01-01T00:00:00",
    })
    usuario_autenticado()
    resp = client.get("/mis-tests?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    tests = resp.get_json()["tests"]
    assert len(tests) == 1
    assert tests[0]["resultado"] == "suspendido"


def test_actualizar_estadisticas_test_usa_formula_oficial(db):
    db.sembrar(("usuarios", "u1"), {})
    # Mismo caso del bug: debe contar como suspendido, no aprobado.
    actualizar_estadisticas_test(db, "u1", "AGE", aciertos=6, fallos=4, temas=[], tiempo_en_segundos=0, blancos=0)

    usuario = db.leer(("usuarios", "u1"))
    stats = usuario["estadisticas"]["AGE"]
    assert stats["tests_aprobados"] == 0
    assert stats["tests_suspendidos"] == 1
    assert stats["historial_tests"][-1]["resultado"] == "suspendido"


def test_actualizar_estadisticas_test_acumula_en_llamadas_sucesivas_y_usa_transaccion(db):
    # No es practicable simular con hilos una condición de carrera real en
    # este harness síncrono -- esta prueba comprueba (a) que la función
    # pasa de verdad por db.transaction() y (b) que dos llamadas sucesivas
    # siguen acumulando el mismo total que antes de hacerla transaccional
    # (regresión de comportamiento).
    db.sembrar(("usuarios", "u1"), {})
    llamadas = []
    transaction_original = db.transaction

    def transaction_espia():
        llamadas.append(1)
        return transaction_original()

    db.transaction = transaction_espia
    try:
        actualizar_estadisticas_test(db, "u1", "AGE", aciertos=8, fallos=2, temas=["tema_01"], tiempo_en_segundos=60, blancos=0)
        actualizar_estadisticas_test(db, "u1", "AGE", aciertos=5, fallos=5, temas=["tema_02"], tiempo_en_segundos=30, blancos=0)
    finally:
        db.transaction = transaction_original

    assert len(llamadas) == 2
    stats = db.leer(("usuarios", "u1"))["estadisticas"]["AGE"]
    assert stats["tests_realizados"] == 2
    assert stats["total_aciertos"] == 13
    assert stats["total_fallos"] == 7
    assert stats["tiempo_total"] == 90
    assert set(stats["temas_test"]) == {"tema_01", "tema_02"}
    assert len(stats["historial_tests"]) == 2


def _test_finalizado(aciertos, fallos, blancos, tiempo, resultado, preguntas=None):
    return {
        "estado": "finalizado", "oposicion": "AGE", "aciertos": aciertos, "fallos": fallos,
        "blancos": blancos, "tiempo": tiempo, "resultado": resultado, "preguntas": preguntas or [],
    }


def test_revertir_estadisticas_test_deshace_un_unico_test(db):
    # Bug real (24/08/2026): borrar un test no revertía nada de esto --
    # seguía contando en el resumen de progreso/análisis de rendimiento
    # después de haber desaparecido de "Mis tests".
    db.sembrar(("usuarios", "u1"), {})
    preguntas = [
        {"tema_id": "tema_01", "respuesta_usuario": "A", "acierto": True},
        {"tema_id": "tema_01", "respuesta_usuario": "B", "acierto": False},
        {"tema_id": "tema_02", "respuesta_usuario": None, "acierto": False},
    ]
    actualizar_estadisticas_test(
        db, "u1", "AGE", aciertos=1, fallos=1, temas=["tema_01", "tema_02"],
        tiempo_en_segundos=60, blancos=1,
        rendimiento_temas={"tema_01": {"aciertos": 1, "fallos": 1, "blancos": 0}, "tema_02": {"aciertos": 0, "fallos": 0, "blancos": 1}},
    )

    test = _test_finalizado(aciertos=1, fallos=1, blancos=1, tiempo=60, resultado="suspendido", preguntas=preguntas)
    revertir_estadisticas_test(db, "u1", "AGE", test)

    stats = db.leer(("usuarios", "u1"))["estadisticas"]["AGE"]
    assert stats["tests_realizados"] == 0
    assert stats["total_aciertos"] == 0
    assert stats["total_fallos"] == 0
    assert stats["tiempo_total"] == 0
    assert stats["tests_suspendidos"] == 0
    assert stats["rendimiento_por_tema"]["tema_01"] == {"aciertos": 0, "fallos": 0, "blancos": 0}
    assert stats["rendimiento_por_tema"]["tema_02"] == {"aciertos": 0, "fallos": 0, "blancos": 0}
    assert stats["puntuacion_media_test"] == 0


def test_revertir_estadisticas_test_solo_afecta_al_test_borrado(db):
    # Con dos tests guardados, borrar uno solo debe dejar intacta la
    # contribución del otro -- nunca decrementar por debajo de lo que
    # de verdad aporta el restante.
    db.sembrar(("usuarios", "u1"), {})
    preguntas_2 = [{"tema_id": "tema_01", "respuesta_usuario": "B", "acierto": False}]
    actualizar_estadisticas_test(
        db, "u1", "AGE", aciertos=1, fallos=0, temas=["tema_01"], tiempo_en_segundos=30, blancos=0,
        rendimiento_temas={"tema_01": {"aciertos": 1, "fallos": 0, "blancos": 0}}, puntuacion_final=1,
    )
    actualizar_estadisticas_test(
        db, "u1", "AGE", aciertos=0, fallos=1, temas=["tema_01"], tiempo_en_segundos=45, blancos=0,
        rendimiento_temas={"tema_01": {"aciertos": 0, "fallos": 1, "blancos": 0}}, puntuacion_final=-1,
    )

    test_a_borrar = _test_finalizado(aciertos=0, fallos=1, blancos=0, tiempo=45, resultado="suspendido", preguntas=preguntas_2)
    revertir_estadisticas_test(db, "u1", "AGE", test_a_borrar)

    stats = db.leer(("usuarios", "u1"))["estadisticas"]["AGE"]
    assert stats["tests_realizados"] == 1
    assert stats["total_aciertos"] == 1
    assert stats["total_fallos"] == 0
    assert stats["tiempo_total"] == 30
    assert stats["rendimiento_por_tema"]["tema_01"] == {"aciertos": 1, "fallos": 0, "blancos": 0}


def test_revertir_estadisticas_test_no_toca_temas_test_ni_historial(db):
    # Decisión deliberada (ver comentario junto a la función): temas_test
    # es un set deduplicado que no se puede revertir sin recorrer el resto
    # de tests, e historial_tests no guarda el id del test -- se dejan
    # intactos en vez de arriesgarse a borrar/perder la entrada equivocada.
    db.sembrar(("usuarios", "u1"), {})
    actualizar_estadisticas_test(db, "u1", "AGE", aciertos=1, fallos=0, temas=["tema_01"], tiempo_en_segundos=30, blancos=0)

    test = _test_finalizado(aciertos=1, fallos=0, blancos=0, tiempo=30, resultado="aprobado")
    revertir_estadisticas_test(db, "u1", "AGE", test)

    stats = db.leer(("usuarios", "u1"))["estadisticas"]["AGE"]
    assert stats["temas_test"] == ["tema_01"]
    assert len(stats["historial_tests"]) == 1


def test_revertir_estadisticas_test_nunca_deja_contadores_negativos(db):
    # Si por lo que sea los datos ya estaban por debajo (usuario sembrado a
    # mano en un test, datos inconsistentes preexistentes...), revertir no
    # debe dejar contadores negativos sin sentido.
    db.sembrar(("usuarios", "u1"), {})
    test = _test_finalizado(aciertos=5, fallos=5, blancos=0, tiempo=100, resultado="suspendido")
    revertir_estadisticas_test(db, "u1", "AGE", test)

    stats = db.leer(("usuarios", "u1"))["estadisticas"]["AGE"]
    assert stats["tests_realizados"] == 0
    assert stats["total_aciertos"] == 0
    assert stats["total_fallos"] == 0
    assert stats["tests_suspendidos"] == 0


def test_actualizar_estadisticas_esquema_pasa_de_verdad_por_una_transaccion(db):
    # Bug real (24/08/2026, auditoría de condiciones de carrera): a
    # diferencia de actualizar_estadisticas_test (su gemela, que sí ya era
    # transaccional), esta función hacía lectura+cálculo+escritura sueltos
    # -- dos guardados de esquema casi simultáneos (dos pestañas, un
    # reintento) podían perder un incremento o un tema, porque ambos
    # leían el mismo valor de partida y la segunda escritura pisaba a la
    # primera. No es practicable simular la condición de carrera real en
    # este harness síncrono -- este test comprueba (a) que la función pasa
    # de verdad por db.transaction() y (b) que dos llamadas sucesivas
    # siguen acumulando correctamente (regresión de comportamiento).
    db.sembrar(("usuarios", "u1"), {})
    llamadas = []
    transaction_original = db.transaction

    def transaction_espia():
        llamadas.append(1)
        return transaction_original()

    db.transaction = transaction_espia
    try:
        actualizar_estadisticas_esquema(db, "u1", "AGE", temas=["tema_01"])
        actualizar_estadisticas_esquema(db, "u1", "AGE", temas=["tema_02"])
    finally:
        db.transaction = transaction_original

    assert len(llamadas) == 2
    stats = db.leer(("usuarios", "u1"))["estadisticas"]["AGE"]
    assert stats["esquemas_realizados"] == 2
    assert set(stats["temas_esquemas"]) == {"tema_01", "tema_02"}


def test_actualizar_estadisticas_esquema_no_duplica_temas_repetidos(db):
    db.sembrar(("usuarios", "u1"), {})
    actualizar_estadisticas_esquema(db, "u1", "AGE", temas=["tema_01"])
    actualizar_estadisticas_esquema(db, "u1", "AGE", temas=["tema_01", "tema_02"])

    stats = db.leer(("usuarios", "u1"))["estadisticas"]["AGE"]
    assert stats["esquemas_realizados"] == 2
    assert sorted(stats["temas_esquemas"]) == ["tema_01", "tema_02"]
