"""Pruebas de limites_uso.py: la cuota de usos de IA por usuario y plan.
Un fallo aquí puede significar dos cosas caras: usuarios de pago
bloqueados sin motivo, o cuotas que no frenan nada y dejan la puerta
abierta al gasto en la API de IA."""
from datetime import date

from limites_uso import (
    verificar_limite_uso, registrar_uso, devolver_uso, max_paginas_para_plan,
    intentar_consumir_uso, intentar_consumir_varios,
)


def test_plan_sin_esta_herramienta_queda_bloqueado(db):
    # Las herramientas de PDF/chat son exclusivas de Premium: básico tiene
    # 0 usos de chat_pdf configurados a propósito.
    permitido, mensaje, usados, limite = verificar_limite_uso(db, "u1", "basico", "chat_pdf")
    assert permitido is False
    assert "no incluye esta herramienta" in mensaje


def test_usuario_nuevo_sin_uso_previo_puede_usarla(db):
    permitido, mensaje, usados, limite = verificar_limite_uso(db, "u1", "basico", "analisis_ia")
    assert permitido is True
    assert mensaje is None
    assert usados == 0


def test_bloquea_al_alcanzar_el_limite_diario(db):
    # Test Oficial cuenta por día (cupo bajo y visible a propósito: 50/día en básico).
    clave_dia = date.today().isoformat()
    db.sembrar(("usuarios", "u1"), {"limites_uso": {"test_oficial": {"periodo": clave_dia, "contador": 50}}})
    permitido, mensaje, usados, limite = verificar_limite_uso(db, "u1", "basico", "test_oficial")
    assert permitido is False
    assert usados == 50
    assert limite == 50
    assert "diario" in mensaje


def test_contador_de_un_periodo_anterior_no_cuenta(db):
    # Un contador de "2020-01" no debe bloquear a nadie en el periodo actual.
    db.sembrar(("usuarios", "u1"), {"limites_uso": {"pdf_ia": {"periodo": "2020-01", "contador": 999}}})
    permitido, _mensaje, usados, _limite = verificar_limite_uso(db, "u1", "premium", "pdf_ia")
    assert permitido is True
    assert usados == 0


def test_registrar_uso_incrementa_el_contador(db):
    registrar_uso(db, "u1", "pdf_ia", "basico")
    registrar_uso(db, "u1", "pdf_ia", "basico")
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["pdf_ia"]["contador"] == 2


def test_registrar_uso_cobra_por_cantidad(db):
    # El Test Personalizado cobra tantas unidades como preguntas: un test de
    # 100 gasta 100, no 1.
    registrar_uso(db, "u1", "test_avanzado_verificado", "premium", cantidad=100)
    registrar_uso(db, "u1", "test_avanzado_verificado", "premium", cantidad=10)
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["test_avanzado_verificado"]["contador"] == 110


def test_devolver_uso_devuelve_la_misma_cantidad(db):
    registrar_uso(db, "u1", "test_avanzado_verificado", "premium", cantidad=50)
    devolver_uso(db, "u1", "test_avanzado_verificado", "premium", cantidad=50)
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["test_avanzado_verificado"]["contador"] == 0


def test_registrar_uso_reinicia_el_contador_en_un_periodo_nuevo(db):
    db.sembrar(("usuarios", "u1"), {"limites_uso": {"pdf_ia": {"periodo": "2020-01", "contador": 14}}})
    registrar_uso(db, "u1", "pdf_ia", "basico")
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["pdf_ia"]["contador"] == 1


def test_plan_premium_tiene_cuota_diaria_no_mensual(db):
    hoy = date.today().isoformat()
    db.sembrar(("usuarios", "u1"), {"limites_uso": {"pdf_ia": {"periodo": hoy, "contador": 100}}})
    permitido, _mensaje, _usados, limite = verificar_limite_uso(db, "u1", "premium", "pdf_ia")
    assert permitido is False
    assert limite == 100


def test_devolver_uso_resta_uno_al_contador(db):
    # Cobro por adelantado (2) y luego devolución de uno (generación fallida)
    # -> queda 1, como si solo se hubiera consumido el uso que sí produjo algo.
    registrar_uso(db, "u1", "test_avanzado_verificado", "basico")
    registrar_uso(db, "u1", "test_avanzado_verificado", "basico")
    devolver_uso(db, "u1", "test_avanzado_verificado", "basico")
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["test_avanzado_verificado"]["contador"] == 1


def test_devolver_uso_sin_cobro_previo_no_hace_nada(db):
    # Devolver cuando no hay ningún contador del periodo actual (usuario sin
    # uso previo) es un no-op: no crea una entrada ni deja nada raro.
    devolver_uso(db, "u1", "chat_temario", "premium")
    assert db.leer(("usuarios", "u1")) is None


def test_devolver_uso_no_baja_de_cero(db):
    # Con un contador del periodo actual ya en 0, devolver no debe dejarlo en
    # negativo (que luego daría al usuario "usos gratis" fantasma).
    hoy = date.today().isoformat()
    db.sembrar(("usuarios", "u1"), {"limites_uso": {"chat_temario": {"periodo": hoy, "contador": 0}}})
    devolver_uso(db, "u1", "chat_temario", "premium")
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["chat_temario"]["contador"] == 0


def test_devolver_uso_no_toca_un_contador_de_otro_periodo(db):
    # Si el periodo ya rotó entre el cobro y la devolución, ese contador es de
    # otro periodo y no debe tocarse.
    db.sembrar(("usuarios", "u1"), {"limites_uso": {"pdf_ia": {"periodo": "2020-01", "contador": 5}}})
    devolver_uso(db, "u1", "pdf_ia", "basico")
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["pdf_ia"] == {"periodo": "2020-01", "contador": 5}


def test_max_paginas_por_plan_tiene_valor_por_defecto_para_plan_desconocido():
    assert max_paginas_para_plan("plan-inexistente") == max_paginas_para_plan("basico")


def test_intentar_consumir_uso_incrementa_si_hay_hueco(db):
    permitido, mensaje, usados, limite = intentar_consumir_uso(db, "u1", "premium", "pdf_ia")
    assert permitido is True
    assert mensaje is None
    assert usados == 0
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["pdf_ia"]["contador"] == 1


def test_intentar_consumir_uso_no_incrementa_si_ya_esta_al_limite(db):
    clave_dia = date.today().isoformat()
    db.sembrar(("usuarios", "u1"), {"limites_uso": {"test_oficial": {"periodo": clave_dia, "contador": 50}}})
    permitido, mensaje, usados, limite = intentar_consumir_uso(db, "u1", "basico", "test_oficial")
    assert permitido is False
    assert usados == 50
    assert limite == 50
    assert "diario" in mensaje
    # No debe haber tocado el contador: sigue en 50, no 51.
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["test_oficial"]["contador"] == 50


def test_intentar_consumir_uso_plan_sin_esta_herramienta_queda_bloqueado(db):
    permitido, mensaje, usados, limite = intentar_consumir_uso(db, "u1", "basico", "chat_pdf")
    assert permitido is False
    assert "no incluye esta herramienta" in mensaje
    assert db.leer(("usuarios", "u1")) is None


def test_intentar_consumir_uso_cobra_por_cantidad(db):
    permitido, _mensaje, _usados, _limite = intentar_consumir_uso(
        db, "u1", "premium", "test_avanzado_verificado", cantidad=100
    )
    assert permitido is True
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["test_avanzado_verificado"]["contador"] == 100


def test_intentar_consumir_uso_pasa_de_verdad_por_una_transaccion(db):
    # Mismo motivo que test_registrar_uso_pasa_de_verdad_por_una_transaccion:
    # comprueba que la comprobación Y el incremento van dentro de
    # db.transaction() -- lo que los hace atómicos frente a otra petición
    # concurrente en producción -- y no como dos pasos sueltos (un get() y
    # luego un update() aparte), que es exactamente el hueco de
    # concurrencia que esta función existe para cerrar.
    llamadas = []
    transaction_original = db.transaction

    def transaction_espia():
        llamadas.append(1)
        return transaction_original()

    db.transaction = transaction_espia
    try:
        intentar_consumir_uso(db, "u1", "premium", "pdf_ia")
    finally:
        db.transaction = transaction_original

    assert len(llamadas) == 1
    assert db.leer(("usuarios", "u1"))["limites_uso"]["pdf_ia"]["contador"] == 1


def test_intentar_consumir_varios_incrementa_todos_si_hay_hueco(db):
    permitido, mensaje = intentar_consumir_varios(
        db, "u1", "premium",
        [("test_avanzado_verificado", 20), ("test_avanzado_verificado_mensual", 20)],
    )
    assert permitido is True
    assert mensaje is None
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["test_avanzado_verificado"]["contador"] == 20
    assert datos["limites_uso"]["test_avanzado_verificado_mensual"]["contador"] == 20


def test_intentar_consumir_varios_es_todo_o_nada(db):
    # test_avanzado_verificado_mensual (básico) ya está al límite (400): el
    # otro cupo (diario, con hueco de sobra) NO debe incrementarse tampoco.
    clave_mes = date.today().strftime("%Y-%m")
    db.sembrar(("usuarios", "u1"), {
        "limites_uso": {"test_avanzado_verificado_mensual": {"periodo": clave_mes, "contador": 400}},
    })
    permitido, mensaje = intentar_consumir_varios(
        db, "u1", "basico",
        [("test_avanzado_verificado", 10), ("test_avanzado_verificado_mensual", 10)],
    )
    assert permitido is False
    assert "mensual" in mensaje
    datos = db.leer(("usuarios", "u1"))
    # El cupo diario, que sí tenía hueco, no debe haberse tocado.
    assert "test_avanzado_verificado" not in datos["limites_uso"]
    assert datos["limites_uso"]["test_avanzado_verificado_mensual"]["contador"] == 400


def test_registrar_uso_pasa_de_verdad_por_una_transaccion(db):
    # No es practicable simular con hilos una condición de carrera real en
    # este harness síncrono -- esta prueba comprueba en su lugar que
    # registrar_uso pasa de verdad por db.transaction() (la vía que la
    # hace atómica frente a otra petición concurrente en producción, con
    # @firestore.transactional) en vez de seguir haciendo un get()+update()
    # suelto como antes.
    llamadas = []
    transaction_original = db.transaction

    def transaction_espia():
        llamadas.append(1)
        return transaction_original()

    db.transaction = transaction_espia
    try:
        registrar_uso(db, "u1", "pdf_ia", "basico")
    finally:
        db.transaction = transaction_original

    assert len(llamadas) == 1
    assert db.leer(("usuarios", "u1"))["limites_uso"]["pdf_ia"]["contador"] == 1
