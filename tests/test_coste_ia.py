"""Contabilidad del gasto en IA por usuario (coste_ia.py)."""
import coste_ia


def test_coste_estimado_usa_precios():
    # 1M tokens de entrada = PRECIO_INPUT; 1M de salida = PRECIO_OUTPUT.
    esperado = coste_ia.PRECIO_INPUT_EUR_MILLON + coste_ia.PRECIO_OUTPUT_EUR_MILLON
    assert coste_ia.coste_estimado(1_000_000, 1_000_000) == round(esperado, 6)
    assert coste_ia.coste_estimado(0, 0) == 0


def test_resumen_coste_usuario_suma_meses():
    datos = {"coste_ia": {
        "2026-06": {"tokens_in": 1000, "tokens_out": 500, "coste": 0.01},
        "2026-99": {"tokens_in": 2000, "tokens_out": 1000, "coste": 0.02},  # mes 'actual' ficticio
    }}
    from datetime import datetime
    mes = datetime.utcnow().strftime("%Y-%m")
    datos["coste_ia"][mes] = {"tokens_in": 300, "tokens_out": 100, "coste": 0.005}
    coste_mes, coste_total, tokens_total = coste_ia.resumen_coste_usuario(datos)
    assert coste_mes == 0.005
    assert round(coste_total, 3) == round(0.01 + 0.02 + 0.005, 3)
    assert tokens_total == 1500 + 3000 + 400


def test_acumulador_entre_hilos_vuelca_a_la_peticion(client, db):
    # Simula lo que hace el generador de test personalizado: varios hilos
    # suman tokens al acumulador y, al terminar, el hilo de la petición lo
    # vuelca a g para que el teardown lo guarde.
    import threading
    from datetime import datetime
    from flask import g
    import app as app_module
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com"})
    mes = datetime.utcnow().strftime("%Y-%m")
    with app_module.app.test_request_context("/"):
        g.uid = "u1"
        acc = coste_ia.AcumuladorTokens()
        hilos = [threading.Thread(target=acc.add, args=({"prompt_tokens": 100, "completion_tokens": 40},)) for _ in range(5)]
        for h in hilos: h.start()
        for h in hilos: h.join()
        acc.volcar_a_peticion()  # en el hilo de la petición
        coste_ia.flush_coste(db)
    doc = db.leer(("usuarios", "u1"))["coste_ia"][mes]
    assert doc["tokens_in"] == 500
    assert doc["tokens_out"] == 200
    assert doc["llamadas"] == 5


def test_volcar_directo_guarda_sin_contexto_de_peticion(db):
    # El Test Personalizado genera en un hilo de fondo desligado de la
    # petición (sin flask.g): el acumulador debe poder volcar DIRECTO al
    # documento del usuario con db+uid, sin depender de g.
    from datetime import datetime
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com"})
    mes = datetime.utcnow().strftime("%Y-%m")
    acc = coste_ia.AcumuladorTokens()
    acc.add({"prompt_tokens": 1000, "completion_tokens": 400})
    acc.add({"prompt_tokens": 500, "completion_tokens": 100})
    acc.volcar_directo(db, "u1")
    doc = db.leer(("usuarios", "u1"))["coste_ia"][mes]
    assert doc["tokens_in"] == 1500
    assert doc["tokens_out"] == 500
    assert doc["llamadas"] == 2
    assert doc["coste"] == coste_ia.coste_estimado(1500, 500)


def test_guardar_coste_directo_acumula_sobre_lo_existente(db):
    from datetime import datetime
    mes = datetime.utcnow().strftime("%Y-%m")
    db.sembrar(("usuarios", "u1"), {"coste_ia": {mes: {"tokens_in": 200, "tokens_out": 50, "llamadas": 1}}})
    coste_ia.guardar_coste_directo(db, "u1", 300, 100, 2)
    doc = db.leer(("usuarios", "u1"))["coste_ia"][mes]
    assert doc["tokens_in"] == 500
    assert doc["tokens_out"] == 150
    assert doc["llamadas"] == 3


def test_flush_coste_incrementa_el_mes(client, db):
    # Simula que durante una petición se acumuló consumo en g y que el
    # teardown lo vuelca al documento del usuario.
    from datetime import datetime
    from flask import g
    import app as app_module
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com"})
    mes = datetime.utcnow().strftime("%Y-%m")
    with app_module.app.test_request_context("/"):
        g.uid = "u1"
        coste_ia.acumular_usage({"prompt_tokens": 1000, "completion_tokens": 400})
        coste_ia.acumular_usage({"prompt_tokens": 500, "completion_tokens": 100})
        coste_ia.flush_coste(db)
    doc = db.leer(("usuarios", "u1"))["coste_ia"][mes]
    assert doc["tokens_in"] == 1500
    assert doc["tokens_out"] == 500
    assert doc["llamadas"] == 2
    assert doc["coste"] == coste_ia.coste_estimado(1500, 500)
