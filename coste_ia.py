"""Contabilidad del gasto en IA (tokens de DeepSeek) por usuario.

Cómo funciona:
- deepseek_utils, tras cada respuesta de la API, llama a `acumular_usage` con
  el bloque `usage` (prompt_tokens/completion_tokens). Eso NO escribe en
  Firestore: solo suma en un acumulador guardado en `flask.g` para la
  petición actual (best-effort; fuera de una petición no hace nada, así que
  scripts y tests no se ven afectados).
- Al terminar la petición, un `teardown_request` en app.py llama a
  `flush_coste(db)`, que vuelca ese acumulado al contador del mes del usuario
  en `usuarios/{uid}.coste_ia.{YYYY-MM}`.

Los precios son configurables por variable de entorno para poder ajustarlos
sin tocar código si cambian las tarifas de DeepSeek.
"""
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


def _precio(env, defecto):
    try:
        return float(os.getenv(env, defecto))
    except (TypeError, ValueError):
        return float(defecto)


# € por cada 1.000.000 de tokens. Valores por defecto aproximados y
# conservadores de deepseek-chat (entrada ~0,25 €/M, salida ~1,00 €/M).
PRECIO_INPUT_EUR_MILLON = _precio("IA_PRECIO_INPUT_EUR_MILLON", 0.25)
PRECIO_OUTPUT_EUR_MILLON = _precio("IA_PRECIO_OUTPUT_EUR_MILLON", 1.00)


def coste_estimado(tokens_in, tokens_out):
    """€ estimados para un consumo de tokens dado."""
    return round(
        (tokens_in or 0) / 1_000_000 * PRECIO_INPUT_EUR_MILLON
        + (tokens_out or 0) / 1_000_000 * PRECIO_OUTPUT_EUR_MILLON,
        6,
    )


def acumular_usage(usage):
    """Suma el consumo de una llamada al acumulador de la petición (g). No
    escribe en Firestore. Silencioso si no hay petición o usuario."""
    if not usage:
        return
    try:
        from flask import g, has_request_context
        if not has_request_context():
            return
        if not getattr(g, "uid", None):
            return
        acc = getattr(g, "_coste_ia", None)
        if acc is None:
            acc = {"in": 0, "out": 0, "llamadas": 0}
            g._coste_ia = acc
        acc["in"] += int(usage.get("prompt_tokens", 0) or 0)
        acc["out"] += int(usage.get("completion_tokens", 0) or 0)
        acc["llamadas"] += 1
    except Exception:
        logger.debug("No se pudo acumular el usage de IA", exc_info=True)


def flush_coste(db):
    """Vuelca lo acumulado en g al contador del mes del usuario. Se llama en
    teardown_request. Nunca debe romper la petición."""
    try:
        from flask import g, has_request_context
        if not has_request_context():
            return
        acc = getattr(g, "_coste_ia", None)
        uid = getattr(g, "uid", None)
        if not acc or not uid or (acc["in"] == 0 and acc["out"] == 0):
            return
        g._coste_ia = None  # evitar doble volcado si algo re-entrara
        mes = datetime.utcnow().strftime("%Y-%m")
        ref = db.collection("usuarios").document(uid)
        doc = ref.get()
        if not doc.exists:
            return
        actual = ((doc.to_dict() or {}).get("coste_ia") or {}).get(mes) or {}
        tin = (actual.get("tokens_in", 0) or 0) + acc["in"]
        tout = (actual.get("tokens_out", 0) or 0) + acc["out"]
        llamadas = (actual.get("llamadas", 0) or 0) + acc["llamadas"]
        ref.update({
            f"coste_ia.{mes}.tokens_in": tin,
            f"coste_ia.{mes}.tokens_out": tout,
            f"coste_ia.{mes}.llamadas": llamadas,
            f"coste_ia.{mes}.coste": coste_estimado(tin, tout),
        })
    except Exception:
        logger.debug("No se pudo volcar el coste de IA", exc_info=True)


def resumen_coste_usuario(datos):
    """A partir del documento de un usuario, devuelve (coste_mes_actual,
    coste_total, tokens_total) sobre su mapa coste_ia."""
    mes = datetime.utcnow().strftime("%Y-%m")
    coste_ia = datos.get("coste_ia") or {}
    coste_mes = round((coste_ia.get(mes) or {}).get("coste", 0) or 0, 4)
    coste_total = 0.0
    tokens_total = 0
    for m in coste_ia.values():
        coste_total += (m or {}).get("coste", 0) or 0
        tokens_total += ((m or {}).get("tokens_in", 0) or 0) + ((m or {}).get("tokens_out", 0) or 0)
    return round(coste_mes, 4), round(coste_total, 4), tokens_total
