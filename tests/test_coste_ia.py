"""Contabilidad del gasto en IA por usuario (coste_ia.py)."""
import coste_ia


def test_coste_estimado_usa_precios():
    # 1M tokens de entrada = PRECIO_INPUT; 1M de salida = PRECIO_OUTPUT.
    esperado = coste_ia.PRECIO_INPUT_EUR_MILLON + coste_ia.PRECIO_OUTPUT_EUR_MILLON
    assert coste_ia.coste_estimado(1_000_000, 1_000_000) == round(esperado, 6)
    assert coste_ia.coste_estimado(0, 0) == 0


def test_precio_input_mezcla_cache_hit_y_miss_segun_el_ratio_asumido():
    # 04/08/2026: antes se usaba siempre el precio caro (cache miss) para
    # toda la entrada, lo que desfasaba el panel admin en un orden de
    # magnitud frente al gasto real de DeepSeek (91-95% de aciertos de
    # caché reales). Ahora PRECIO_INPUT_EUR_MILLON es una mezcla ponderada
    # por RATIO_CACHE_HIT_ASUMIDO.
    esperado = round(
        coste_ia.RATIO_CACHE_HIT_ASUMIDO * coste_ia.PRECIO_INPUT_CACHE_HIT_EUR_MILLON
        + (1 - coste_ia.RATIO_CACHE_HIT_ASUMIDO) * coste_ia.PRECIO_INPUT_CACHE_MISS_EUR_MILLON,
        6,
    )
    assert coste_ia.PRECIO_INPUT_EUR_MILLON == esperado
    # Debe quedar muy por debajo del precio de cache miss a secas (el
    # comportamiento antiguo), no solo ligeramente más barato.
    assert coste_ia.PRECIO_INPUT_EUR_MILLON < coste_ia.PRECIO_INPUT_CACHE_MISS_EUR_MILLON / 5


def test_precios_offpeak_y_peak_coinciden_con_la_tarifa_oficial_deepseek():
    # 16/08/2026: tarifa nueva de DeepSeek-v4-flash con franja horaria, al
    # cambio ~0,92 €/$. Pin literal (no derivado) para que un futuro cambio
    # de precio accidental en el código se note en el test, no solo en el
    # panel admin.
    assert coste_ia.PRECIO_INPUT_CACHE_MISS_OFFPEAK_EUR_MILLON == 0.2024
    assert coste_ia.PRECIO_INPUT_CACHE_HIT_OFFPEAK_EUR_MILLON == 0.00644
    assert coste_ia.PRECIO_OUTPUT_OFFPEAK_EUR_MILLON == 0.6072
    assert coste_ia.PRECIO_INPUT_CACHE_MISS_PEAK_EUR_MILLON == 0.4048
    assert coste_ia.PRECIO_INPUT_CACHE_HIT_PEAK_EUR_MILLON == 0.01288
    assert coste_ia.PRECIO_OUTPUT_PEAK_EUR_MILLON == 1.2144
    # Peak es ~2x off-peak en las tres tarifas, según la propia DeepSeek.
    assert coste_ia.PRECIO_OUTPUT_PEAK_EUR_MILLON == coste_ia.PRECIO_OUTPUT_OFFPEAK_EUR_MILLON * 2


def test_precio_output_mezcla_offpeak_y_peak_segun_el_ratio_asumido():
    esperado = round(
        coste_ia.RATIO_HORA_PICO_ASUMIDA * coste_ia.PRECIO_OUTPUT_PEAK_EUR_MILLON
        + (1 - coste_ia.RATIO_HORA_PICO_ASUMIDA) * coste_ia.PRECIO_OUTPUT_OFFPEAK_EUR_MILLON,
        6,
    )
    assert coste_ia.PRECIO_OUTPUT_EUR_MILLON == esperado


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


def test_incrementar_mes_pasa_de_verdad_por_una_transaccion(db):
    # Lectura+cálculo+escritura en una única transacción de Firestore (bug
    # real, ronda de auditoría #5): sin esto, dos hilos de fondo del mismo
    # usuario (p. ej. dos herramientas de IA disparadas casi a la vez)
    # podían leer el mismo contador antes de que ninguno escribiera, y uno
    # de los dos incrementos se perdía -- infravalorando el gasto real que
    # alimenta el panel admin y la alerta anti-abuso. No es practicable
    # simular con hilos una condición de carrera real en este harness
    # síncrono (mismo criterio que test_registrar_actividad_racha_pasa_de_
    # verdad_por_una_transaccion en test_racha.py), así que se comprueba en
    # su lugar que de verdad pasa por db.transaction().
    llamadas = []
    transaction_original = db.transaction

    def transaction_espia():
        llamadas.append(1)
        return transaction_original()

    db.sembrar(("usuarios", "u1"), {})
    db.transaction = transaction_espia
    try:
        coste_ia.guardar_coste_directo(db, "u1", 100, 50, 1)
    finally:
        db.transaction = transaction_original

    assert len(llamadas) == 1


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


def test_guardar_coste_directo_acumula_tambien_el_dia(db):
    from datetime import datetime
    hoy = datetime.utcnow().strftime("%Y-%m-%d")
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com"})
    coste_ia.guardar_coste_directo(db, "u1", 300, 100, 2)
    coste_ia.guardar_coste_directo(db, "u1", 100, 50, 1)
    dia = db.leer(("usuarios", "u1"))["coste_ia_dias"][hoy]
    assert dia["tokens_in"] == 400
    assert dia["tokens_out"] == 150
    assert dia["llamadas"] == 3
    assert dia["coste"] == coste_ia.coste_estimado(400, 150)


def test_incrementar_mes_poda_dias_mas_viejos_que_el_limite(db):
    from datetime import datetime, timedelta
    ahora = datetime.utcnow()
    hoy = ahora.strftime("%Y-%m-%d")
    dia_viejo = (ahora - timedelta(days=coste_ia.LIMITE_DIAS_HISTORICO + 5)).strftime("%Y-%m-%d")
    dia_reciente = (ahora - timedelta(days=2)).strftime("%Y-%m-%d")
    db.sembrar(("usuarios", "u1"), {"email": "u1@x.com", "coste_ia_dias": {
        dia_viejo: {"tokens_in": 10, "tokens_out": 5, "llamadas": 1, "coste": 0.001},
        dia_reciente: {"tokens_in": 20, "tokens_out": 10, "llamadas": 1, "coste": 0.002},
    }})
    coste_ia.guardar_coste_directo(db, "u1", 5, 2, 1)
    dias = db.leer(("usuarios", "u1"))["coste_ia_dias"]
    assert dia_viejo not in dias
    assert dia_reciente in dias
    assert hoy in dias
