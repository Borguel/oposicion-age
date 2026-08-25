"""Pruebas de registrar_actividad_racha (registro_progreso_usuario.py):
la racha de estudio motivacional de Mi Cuenta."""
from datetime import date, timedelta

from registro_progreso_usuario import registrar_actividad_racha


def test_primera_actividad_arranca_la_racha_en_uno(db):
    registrar_actividad_racha(db, "u1")
    racha = db.leer(("usuarios", "u1"))["racha"]
    assert racha["racha_actual"] == 1
    assert racha["racha_maxima"] == 1
    assert racha["ultima_fecha"] == date.today().isoformat()


def test_llamar_dos_veces_el_mismo_dia_no_suma_dos_veces(db):
    registrar_actividad_racha(db, "u1")
    registrar_actividad_racha(db, "u1")
    racha = db.leer(("usuarios", "u1"))["racha"]
    assert racha["racha_actual"] == 1


def test_dia_consecutivo_suma_uno(db):
    ayer = (date.today() - timedelta(days=1)).isoformat()
    db.sembrar(("usuarios", "u1"), {"racha": {"ultima_fecha": ayer, "racha_actual": 3, "racha_maxima": 5}})
    registrar_actividad_racha(db, "u1")
    racha = db.leer(("usuarios", "u1"))["racha"]
    assert racha["racha_actual"] == 4
    assert racha["racha_maxima"] == 5  # el máximo no baja, y 4 no lo supera


def test_hueco_de_mas_de_un_dia_reinicia_la_racha_a_uno(db):
    hace_tres_dias = (date.today() - timedelta(days=3)).isoformat()
    db.sembrar(("usuarios", "u1"), {"racha": {"ultima_fecha": hace_tres_dias, "racha_actual": 10, "racha_maxima": 10}})
    registrar_actividad_racha(db, "u1")
    racha = db.leer(("usuarios", "u1"))["racha"]
    assert racha["racha_actual"] == 1
    assert racha["racha_maxima"] == 10  # el máximo histórico se conserva


def test_nueva_racha_puede_superar_el_maximo_anterior(db):
    ayer = (date.today() - timedelta(days=1)).isoformat()
    db.sembrar(("usuarios", "u1"), {"racha": {"ultima_fecha": ayer, "racha_actual": 5, "racha_maxima": 5}})
    registrar_actividad_racha(db, "u1")
    racha = db.leer(("usuarios", "u1"))["racha"]
    assert racha["racha_actual"] == 6
    assert racha["racha_maxima"] == 6


def test_fecha_guardada_con_formato_invalido_no_rompe_se_trata_como_racha_nueva(db):
    db.sembrar(("usuarios", "u1"), {"racha": {"ultima_fecha": "no-es-una-fecha", "racha_actual": 7, "racha_maxima": 7}})
    registrar_actividad_racha(db, "u1")
    racha = db.leer(("usuarios", "u1"))["racha"]
    assert racha["racha_actual"] == 1
    assert racha["racha_maxima"] == 7


def test_registrar_actividad_racha_pasa_de_verdad_por_una_transaccion(db):
    # Lectura+cálculo+escritura en una única transacción de Firestore
    # (25/08/2026, auditoría -- higiene): sin esto, dos guardados casi
    # simultáneos del mismo usuario podían leer la misma racha_actual antes
    # de que ninguno escribiera, y el segundo pisaba el incremento del
    # primero en vez de sumarse. No es practicable simular con hilos una
    # condición de carrera real en este harness síncrono, así que se
    # comprueba en su lugar que de verdad pasa por db.transaction().
    llamadas = []
    transaction_original = db.transaction

    def transaction_espia():
        llamadas.append(1)
        return transaction_original()

    db.transaction = transaction_espia
    try:
        registrar_actividad_racha(db, "u1")
    finally:
        db.transaction = transaction_original

    assert len(llamadas) == 1
    assert db.leer(("usuarios", "u1"))["racha"]["racha_actual"] == 1
