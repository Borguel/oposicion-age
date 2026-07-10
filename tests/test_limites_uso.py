"""Pruebas de limites_uso.py: la cuota de usos de IA por usuario y plan.
Un fallo aquí puede significar dos cosas caras: usuarios de pago
bloqueados sin motivo, o cuotas que no frenan nada y dejan la puerta
abierta al gasto en la API de IA."""
from datetime import date

from limites_uso import verificar_limite_uso, registrar_uso, max_paginas_para_plan


def test_plan_sin_esta_herramienta_queda_bloqueado(db):
    # El plan gratis tiene 0 usos de chat_pdf configurados (a diferencia de
    # pdf_ia, que sí incluye 2 usos/mes en gratis).
    permitido, mensaje, usados, limite = verificar_limite_uso(db, "u1", "gratis", "chat_pdf")
    assert permitido is False
    assert "no incluye esta herramienta" in mensaje


def test_usuario_nuevo_sin_uso_previo_puede_usarla(db):
    permitido, mensaje, usados, limite = verificar_limite_uso(db, "u1", "basico", "pdf_ia")
    assert permitido is True
    assert mensaje is None
    assert usados == 0


def test_bloquea_al_alcanzar_el_limite_mensual(db):
    clave_mes = date.today().strftime("%Y-%m")
    db.sembrar(("usuarios", "u1"), {"limites_uso": {"pdf_ia": {"periodo": clave_mes, "contador": 15}}})
    permitido, mensaje, usados, limite = verificar_limite_uso(db, "u1", "basico", "pdf_ia")
    assert permitido is False
    assert usados == 15
    assert limite == 15
    assert "mensuales" in mensaje


def test_contador_de_un_periodo_anterior_no_cuenta(db):
    # Un contador de "2020-01" no debe bloquear a nadie en el periodo actual.
    db.sembrar(("usuarios", "u1"), {"limites_uso": {"pdf_ia": {"periodo": "2020-01", "contador": 999}}})
    permitido, _mensaje, usados, _limite = verificar_limite_uso(db, "u1", "basico", "pdf_ia")
    assert permitido is True
    assert usados == 0


def test_registrar_uso_incrementa_el_contador(db):
    registrar_uso(db, "u1", "pdf_ia", "basico")
    registrar_uso(db, "u1", "pdf_ia", "basico")
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["pdf_ia"]["contador"] == 2


def test_registrar_uso_reinicia_el_contador_en_un_periodo_nuevo(db):
    db.sembrar(("usuarios", "u1"), {"limites_uso": {"pdf_ia": {"periodo": "2020-01", "contador": 14}}})
    registrar_uso(db, "u1", "pdf_ia", "basico")
    datos = db.leer(("usuarios", "u1"))
    assert datos["limites_uso"]["pdf_ia"]["contador"] == 1


def test_plan_premium_tiene_cuota_diaria_no_mensual(db):
    hoy = date.today().isoformat()
    db.sembrar(("usuarios", "u1"), {"limites_uso": {"pdf_ia": {"periodo": hoy, "contador": 60}}})
    permitido, _mensaje, _usados, limite = verificar_limite_uso(db, "u1", "premium", "pdf_ia")
    assert permitido is False
    assert limite == 60


def test_max_paginas_por_plan_tiene_valor_por_defecto_para_plan_desconocido():
    assert max_paginas_para_plan("plan-inexistente") == max_paginas_para_plan("gratis")


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
