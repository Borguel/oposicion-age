"""Pruebas de limites_uso.py: la cuota de usos de IA por usuario y plan.
Un fallo aquí puede significar dos cosas caras: usuarios de pago
bloqueados sin motivo, o cuotas que no frenan nada y dejan la puerta
abierta al gasto en la API de IA."""
from datetime import date

from limites_uso import (
    verificar_limite_uso,
    registrar_uso,
    devolver_uso,
    reservar_uso,
    reservar_uso_multiple,
    max_paginas_para_plan,
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


def test_reservar_uso_incrementa_el_contador(db):
    permitido, mensaje, usados, limite = reservar_uso(db, "u1", "pdf_ia", "premium")
    assert permitido is True
    assert mensaje is None
    assert usados == 1
    assert limite == 100
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["pdf_ia"]["contador"] == 1


def test_reservar_uso_bloquea_al_alcanzar_el_limite(db):
    clave_dia = date.today().isoformat()
    db.sembrar(("usuarios", "u1"), {"limites_uso": {"pdf_ia": {"periodo": clave_dia, "contador": 100}}})
    permitido, mensaje, usados, limite = reservar_uso(db, "u1", "pdf_ia", "premium")
    assert permitido is False
    assert usados == 100
    assert limite == 100
    assert "diario" in mensaje
    # Bloqueado -> el contador no se ha tocado.
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["pdf_ia"]["contador"] == 100


def test_reservar_uso_cobra_por_cantidad(db):
    permitido, _mensaje, usados, _limite = reservar_uso(
        db, "u1", "test_avanzado_verificado", "premium", cantidad=100
    )
    assert permitido is True
    assert usados == 100
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["test_avanzado_verificado"]["contador"] == 100


def test_reservar_uso_no_supera_el_limite_aunque_quepa_parcialmente(db):
    # Si ya hay 45 usados de un límite de 50 y se piden 10 más (55 en
    # total), no se reserva NADA -- no tiene sentido "cobrar lo que quepa"
    # cuando cantidad representa preguntas de un único test.
    clave_dia = date.today().isoformat()
    db.sembrar(("usuarios", "u1"), {"limites_uso": {"test_avanzado_verificado": {"periodo": clave_dia, "contador": 45}}})
    permitido, mensaje, usados, limite = reservar_uso(db, "u1", "test_avanzado_verificado", "basico", cantidad=10)
    assert permitido is False
    assert usados == 45
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["test_avanzado_verificado"]["contador"] == 45


def test_reservar_uso_reinicia_el_contador_en_un_periodo_nuevo(db):
    db.sembrar(("usuarios", "u1"), {"limites_uso": {"pdf_ia": {"periodo": "2020-01", "contador": 99}}})
    permitido, _mensaje, usados, _limite = reservar_uso(db, "u1", "pdf_ia", "premium")
    assert permitido is True
    assert usados == 1


def test_reservar_uso_pasa_de_verdad_por_una_transaccion(db):
    # Igual que test_registrar_uso_pasa_de_verdad_por_una_transaccion: lo
    # importante de reservar_uso es que la comprobación del límite y el
    # incremento vayan en la MISMA transacción (eso es lo que cierra el
    # hueco de carrera entre verificar_limite_uso y registrar_uso por
    # separado). No es practicable simular con hilos una condición de
    # carrera real en este harness síncrono, así que se comprueba en su
    # lugar que de verdad pasa por db.transaction().
    llamadas = []
    transaction_original = db.transaction

    def transaction_espia():
        llamadas.append(1)
        return transaction_original()

    db.transaction = transaction_espia
    try:
        reservar_uso(db, "u1", "pdf_ia", "premium")
    finally:
        db.transaction = transaction_original

    assert len(llamadas) == 1
    assert db.leer(("usuarios", "u1"))["limites_uso"]["pdf_ia"]["contador"] == 1


def test_reservar_uso_bloqueado_por_plan_sin_herramienta(db):
    permitido, mensaje, usados, limite = reservar_uso(db, "u1", "chat_pdf", "basico")
    assert permitido is False
    assert "no incluye esta herramienta" in mensaje
    assert usados == 0
    assert limite == 0


def test_reservar_uso_multiple_incrementa_todos_los_tipos(db):
    # test_avanzado_verificado (cupo diario) y su _mensual conviven en el
    # mismo documento de usuario y se cobran juntos, como hace de verdad
    # /generar-test-avanzado.
    tipos = ("test_avanzado_verificado", "test_avanzado_verificado_mensual")
    permitido, mensaje = reservar_uso_multiple(db, "u1", tipos, "premium", cantidad=20)
    assert permitido is True
    assert mensaje is None
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["test_avanzado_verificado"]["contador"] == 20
    assert datos["limites_uso"]["test_avanzado_verificado_mensual"]["contador"] == 20


def test_reservar_uso_multiple_no_incrementa_ninguno_si_uno_supera_su_limite(db):
    # El cupo diario de básico es 50; si ya hay 45 usados y se piden 10 más,
    # el diario se pasaría -- y aunque el mensual tenga margine de sobra, NO
    # debe incrementarse tampoco: o se cobran los dos, o no se cobra ninguno.
    clave_dia = date.today().isoformat()
    clave_mes = date.today().strftime("%Y-%m")
    db.sembrar(("usuarios", "u1"), {"limites_uso": {
        "test_avanzado_verificado": {"periodo": clave_dia, "contador": 45},
        "test_avanzado_verificado_mensual": {"periodo": clave_mes, "contador": 0},
    }})
    tipos = ("test_avanzado_verificado", "test_avanzado_verificado_mensual")
    permitido, mensaje = reservar_uso_multiple(db, "u1", tipos, "basico", cantidad=10)
    assert permitido is False
    assert "diario" in mensaje
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["test_avanzado_verificado"]["contador"] == 45
    assert datos["limites_uso"]["test_avanzado_verificado_mensual"]["contador"] == 0


def test_reservar_uso_multiple_bloqueado_si_algun_tipo_no_esta_en_el_plan(db):
    # banco_pdf_mensual está a 0 en básico -- reservar_uso_multiple debe
    # bloquear el grupo entero (pdf_ia, que sí tendría cupo, no se cobra).
    permitido, mensaje = reservar_uso_multiple(db, "u1", ("pdf_ia", "banco_pdf_mensual"), "basico")
    assert permitido is False
    assert "no incluye esta herramienta" in mensaje
    assert db.leer(("usuarios", "u1")) is None


def test_reservar_uso_multiple_pasa_de_verdad_por_una_transaccion(db):
    llamadas = []
    transaction_original = db.transaction

    def transaction_espia():
        llamadas.append(1)
        return transaction_original()

    db.transaction = transaction_espia
    try:
        reservar_uso_multiple(db, "u1", ("pdf_ia", "banco_pdf_mensual"), "premium")
    finally:
        db.transaction = transaction_original

    assert len(llamadas) == 1
