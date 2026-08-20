"""Pruebas de promociones.py: decide si el descuento activo se aplica de
verdad en el checkout de Stripe (blueprints/pagos.py) y en el panel de
admin. Un fallo aquí es dinero -- un descuento que no debería aplicarse
aplicándose, o al revés."""
from datetime import datetime, timedelta

from promociones import leer_promocion, promocion_vigente


def test_leer_promocion_valores_por_defecto_sin_documento(db):
    promo = leer_promocion()
    assert promo["activo"] is False
    assert promo["plan"] == "premium"
    assert promo["descuento_pct"] == 0
    assert promo["fecha_fin"] == ""
    assert promo["stripe_promotion_code"] == ""


def test_leer_promocion_lee_lo_guardado(db):
    db.sembrar(("config", "promocion"), {
        "activo": True, "plan": "basico", "descuento_pct": 20,
        "fecha_fin": "2026-12-31T00:00:00", "stripe_promotion_code": "promo_123",
    })
    promo = leer_promocion()
    assert promo["activo"] is True
    assert promo["plan"] == "basico"
    assert promo["descuento_pct"] == 20
    assert promo["stripe_promotion_code"] == "promo_123"


def test_promocion_inactiva_no_esta_vigente():
    assert promocion_vigente({"activo": False, "fecha_fin": ""}) is False


def test_promocion_activa_sin_fecha_fin_esta_vigente_indefinidamente():
    assert promocion_vigente({"activo": True, "fecha_fin": ""}) is True


def test_promocion_activa_con_fecha_fin_futura_esta_vigente():
    manana = (datetime.utcnow() + timedelta(days=1)).isoformat()
    assert promocion_vigente({"activo": True, "fecha_fin": manana}) is True


def test_promocion_activa_con_fecha_fin_pasada_no_esta_vigente():
    ayer = (datetime.utcnow() - timedelta(days=1)).isoformat()
    assert promocion_vigente({"activo": True, "fecha_fin": ayer}) is False


def test_promocion_con_fecha_fin_corrupta_falla_cerrado():
    # Antes de la auditoría de agosto de 2026 esto devolvía True (fallaba
    # ABIERTO): una fecha_fin ilegible dejaba el descuento aplicándose para
    # siempre en vez de tratarse como caducado. Ahora falla CERRADO -- una
    # fecha que no se puede interpretar es, a efectos de vigencia, lo mismo
    # que una promoción caducada.
    assert promocion_vigente({"activo": True, "fecha_fin": "no-es-una-fecha"}) is False


def test_promocion_con_fecha_fin_de_tipo_no_string_falla_cerrado():
    # fromisoformat espera un string -- un número o un dict ahí (dato
    # corrupto de verdad, no solo mal formado) debe fallar cerrado igual.
    assert promocion_vigente({"activo": True, "fecha_fin": 12345}) is False
