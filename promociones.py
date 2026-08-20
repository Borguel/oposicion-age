"""Lectura de la promoción/descuento activo -- compartido entre
blueprints/admin.py (panel de gestión) y blueprints/pagos.py (aplicar el
descuento en Stripe Checkout), para que ambos lean exactamente la misma
noción de "vigente" sin duplicar la comprobación de fecha_fin.

Módulo hoja a propósito (solo depende de firebase_setup y datetime), igual
que planes.py: admin.py y pagos.py no se importan entre sí, así que esto
tiene que vivir en un tercer sitio neutral."""
from datetime import datetime

from firebase_setup import db

PLANES_PROMOCIONABLES = ("basico", "premium")


def leer_promocion():
    doc = db.collection("config").document("promocion").get()
    d = doc.to_dict() or {} if doc.exists else {}
    return {
        "activo": bool(d.get("activo", False)),
        "plan": d.get("plan", "premium"),
        "descuento_pct": int(d.get("descuento_pct", 0) or 0),
        "duracion_texto": d.get("duracion_texto", ""),
        "fecha_fin": d.get("fecha_fin", ""),
        "stripe_promotion_code": d.get("stripe_promotion_code", ""),
        "mensaje": d.get("mensaje", ""),
        "fuente": d.get("fuente", "default"),
        "animacion": d.get("animacion", "ninguna"),
    }


def promocion_vigente(promo):
    """Activa Y, si tiene fecha de fin, que todavía no haya pasado.

    Falla CERRADO ante una fecha_fin ilegible (auditoría de agosto de
    2026): antes, un valor corrupto en fecha_fin (p. ej. una edición
    manual mal hecha en el panel) hacía que la promoción se tratara como
    vigente PARA SIEMPRE en vez de caducada -- coste económico real y
    silencioso (descuento aplicándose indefinidamente) para un caso que
    no debería colar como "sin fecha de fin"."""
    if not promo.get("activo"):
        return False
    fecha_fin = promo.get("fecha_fin")
    if not fecha_fin:
        return True
    try:
        return datetime.utcnow() < datetime.fromisoformat(fecha_fin)
    except (TypeError, ValueError):
        return False
