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
import threading
from datetime import datetime, timedelta

from utils import ejecutar_en_transaccion

logger = logging.getLogger(__name__)


def _precio(env, defecto):
    try:
        return float(os.getenv(env, defecto))
    except (TypeError, ValueError):
        return float(defecto)


# € por cada 1.000.000 de tokens. Valores por defecto según las tarifas
# oficiales de DeepSeek para deepseek-v4-flash (el modelo usado en toda la
# app salvo que TUTOR_MODELO_IA diga lo contrario -- ver chat_controller.py),
# convertidas de dólares a euros al cambio aproximado (~0,92 €/$).
#
# DeepSeek factura el TOKEN DE ENTRADA a dos tarifas muy distintas según si
# hace "cache hit" en su caché de contexto (frecuentísimo aquí: el mismo
# documento/fragmento se reenvía en muchas llamadas seguidas de una misma
# generación) o "cache miss". Antes esta estimación usaba SIEMPRE el precio
# de cache miss para toda la entrada ("para que quedara siempre por lo
# alto"), pero en la práctica eso la dejaba muy por encima del gasto real:
# las exportaciones de uso reales de DeepSeek (04/08/2026) muestran 91-95%
# de aciertos de caché en el tráfico real de la app. Ahora se mezcla el
# precio de entrada asumiendo una proporción de aciertos de caché realista
# pero conservadora (algo por debajo de lo observado, para no quedarse
# corto): sigue siendo una ESTIMACIÓN -- no hay forma de saber el acierto
# real de cada llamada sin que DeepSeek lo devuelva en el usage. Solo
# alimenta el panel admin y la alerta interna de gasto diario; nunca se
# muestra a usuarios.
#
# NUEVA TARIFA con franja horaria (16/08/2026): a partir de esta fecha
# DeepSeek factura distinto en horas "peak" (01:00-04:00 y 06:00-10:00 UTC)
# que en el resto del día ("off-peak"), con la peak en torno al doble de
# cara. Precios oficiales ($/M -> €/M al cambio ~0,92 €/$):
#   off-peak: entrada MISS $0,22 -> ~0,2024 €/M | entrada HIT $0,007 -> ~0,00644 €/M | salida $0,66 -> ~0,6072 €/M
#   peak:     entrada MISS $0,44 -> ~0,4048 €/M | entrada HIT $0,014 -> ~0,01288 €/M | salida $1,32 -> ~1,2144 €/M
# Se mezclan igual que el acierto de caché: una proporción asumida
# (conservadora, ajustable por variable de entorno) de tráfico que cae en
# horas peak. Los opositores estudian sobre todo por la tarde/noche en hora
# española (claramente off-peak en UTC), pero el tramo peak 06:00-10:00 UTC
# coincide con la franja de estudio matutina antes de trabajar, así que no
# se asume 0%.
PRECIO_INPUT_CACHE_MISS_OFFPEAK_EUR_MILLON = _precio("IA_PRECIO_INPUT_OFFPEAK_EUR_MILLON", 0.2024)
PRECIO_INPUT_CACHE_HIT_OFFPEAK_EUR_MILLON = _precio("IA_PRECIO_INPUT_CACHE_HIT_OFFPEAK_EUR_MILLON", 0.00644)
PRECIO_OUTPUT_OFFPEAK_EUR_MILLON = _precio("IA_PRECIO_OUTPUT_OFFPEAK_EUR_MILLON", 0.6072)
PRECIO_INPUT_CACHE_MISS_PEAK_EUR_MILLON = _precio("IA_PRECIO_INPUT_PEAK_EUR_MILLON", 0.4048)
PRECIO_INPUT_CACHE_HIT_PEAK_EUR_MILLON = _precio("IA_PRECIO_INPUT_CACHE_HIT_PEAK_EUR_MILLON", 0.01288)
PRECIO_OUTPUT_PEAK_EUR_MILLON = _precio("IA_PRECIO_OUTPUT_PEAK_EUR_MILLON", 1.2144)
RATIO_HORA_PICO_ASUMIDA = _precio("IA_RATIO_HORA_PICO_ASUMIDA", 0.25)

PRECIO_INPUT_CACHE_MISS_EUR_MILLON = round(
    RATIO_HORA_PICO_ASUMIDA * PRECIO_INPUT_CACHE_MISS_PEAK_EUR_MILLON
    + (1 - RATIO_HORA_PICO_ASUMIDA) * PRECIO_INPUT_CACHE_MISS_OFFPEAK_EUR_MILLON,
    6,
)
PRECIO_INPUT_CACHE_HIT_EUR_MILLON = round(
    RATIO_HORA_PICO_ASUMIDA * PRECIO_INPUT_CACHE_HIT_PEAK_EUR_MILLON
    + (1 - RATIO_HORA_PICO_ASUMIDA) * PRECIO_INPUT_CACHE_HIT_OFFPEAK_EUR_MILLON,
    6,
)
PRECIO_OUTPUT_EUR_MILLON = round(
    RATIO_HORA_PICO_ASUMIDA * PRECIO_OUTPUT_PEAK_EUR_MILLON
    + (1 - RATIO_HORA_PICO_ASUMIDA) * PRECIO_OUTPUT_OFFPEAK_EUR_MILLON,
    6,
)
RATIO_CACHE_HIT_ASUMIDO = _precio("IA_RATIO_CACHE_HIT_ASUMIDO", 0.90)
PRECIO_INPUT_EUR_MILLON = round(
    RATIO_CACHE_HIT_ASUMIDO * PRECIO_INPUT_CACHE_HIT_EUR_MILLON
    + (1 - RATIO_CACHE_HIT_ASUMIDO) * PRECIO_INPUT_CACHE_MISS_EUR_MILLON,
    6,
)


def coste_estimado(tokens_in, tokens_out):
    """€ estimados para un consumo de tokens dado."""
    return round(
        (tokens_in or 0) / 1_000_000 * PRECIO_INPUT_EUR_MILLON
        + (tokens_out or 0) / 1_000_000 * PRECIO_OUTPUT_EUR_MILLON,
        6,
    )


def _sumar_a_g(tin, tout, llamadas):
    """Suma tokens al acumulador de la petición (flask.g). Debe llamarse
    desde el hilo de la petición (donde g está disponible)."""
    from flask import g, has_request_context
    if not has_request_context() or not getattr(g, "uid", None):
        return
    acc = getattr(g, "_coste_ia", None)
    if acc is None:
        acc = {"in": 0, "out": 0, "llamadas": 0}
        g._coste_ia = acc
    acc["in"] += tin
    acc["out"] += tout
    acc["llamadas"] += llamadas


def acumular_usage(usage):
    """Suma el consumo de una llamada al acumulador de la petición (g). No
    escribe en Firestore. Silencioso si no hay petición o usuario."""
    if not usage:
        return
    try:
        _sumar_a_g(int(usage.get("prompt_tokens", 0) or 0),
                   int(usage.get("completion_tokens", 0) or 0), 1)
    except Exception:
        logger.debug("No se pudo acumular el usage de IA", exc_info=True)


class AcumuladorTokens:
    """Acumulador seguro entre hilos. Las llamadas a DeepSeek que se hacen en
    hilos de trabajo (ThreadPoolExecutor del generador de test personalizado)
    no ven flask.g, así que suman aquí; al terminar, el hilo de la petición
    llama a volcar_a_peticion() para pasar el total a g y que el
    teardown_request lo guarde."""

    def __init__(self):
        self._lock = threading.Lock()
        self.tin = 0
        self.tout = 0
        self.llamadas = 0

    def add(self, usage):
        if not usage:
            return
        with self._lock:
            self.tin += int(usage.get("prompt_tokens", 0) or 0)
            self.tout += int(usage.get("completion_tokens", 0) or 0)
            self.llamadas += 1

    def volcar_a_peticion(self):
        try:
            with self._lock:
                _sumar_a_g(self.tin, self.tout, self.llamadas)
        except Exception:
            logger.debug("No se pudo volcar el acumulador de tokens", exc_info=True)

    def volcar_directo(self, db, uid):
        """Vuelca lo acumulado directamente al documento del usuario, sin pasar
        por flask.g. Necesario cuando la generación corre en un hilo de fondo
        desligado de la petición (el Test Personalizado genera en un
        threading.Thread propio, ver blueprints/test_ia.py), donde flask.g no
        está disponible y volcar_a_peticion() no tendría efecto."""
        try:
            with self._lock:
                tin, tout, llamadas = self.tin, self.tout, self.llamadas
            guardar_coste_directo(db, uid, tin, tout, llamadas)
        except Exception:
            logger.debug("No se pudo volcar el acumulador de tokens (directo)", exc_info=True)


# Cuántos días de histórico diario se conservan (usuarios/{uid}.coste_ia_dias)
# -- a diferencia del histórico mensual (coste_ia), que se guarda para
# siempre, el diario se poda en cada escritura para no crecer sin límite;
# 35 días cubre "el mes en curso completo" con margen de sobra para el
# selector "por día" del panel de admin.
LIMITE_DIAS_HISTORICO = 35


def _incrementar_mes(db, uid, tin, tout, llamadas):
    """Suma el consumo indicado al contador del mes Y del día actuales del
    usuario, en usuarios/{uid}.coste_ia.{YYYY-MM} y
    usuarios/{uid}.coste_ia_dias.{YYYY-MM-DD}.

    Lectura+escritura dentro de una transacción de Firestore (bug real,
    ronda de auditoría #5): el comentario original de esta función asumía
    que el consumo de un mismo usuario siempre se vuelca desde un único
    hilo por petición, pero eso no cubre el caso real -- volcar_directo se
    llama también desde hilos de fondo (resumen/esquema/tarjetas/test
    desde PDF, Test Personalizado) que corren mientras el usuario sigue
    usando la web. Si un mismo usuario dispara dos herramientas de IA casi
    a la vez, dos llamadas a esta función podían leer el mismo contador
    antes de que ninguna escribiera, perdiéndose uno de los dos
    incrementos -- infravalorando en silencio el gasto real que alimenta
    tanto el panel admin como la alerta anti-abuso de picos de gasto."""
    ahora = datetime.utcnow()
    mes = ahora.strftime("%Y-%m")
    dia = ahora.strftime("%Y-%m-%d")
    ref = db.collection("usuarios").document(uid)

    def _sumar(transaction):
        doc = ref.get(transaction=transaction)
        if not doc.exists:
            return
        datos = doc.to_dict() or {}

        actual_mes = (datos.get("coste_ia") or {}).get(mes) or {}
        tin_mes = (actual_mes.get("tokens_in", 0) or 0) + tin
        tout_mes = (actual_mes.get("tokens_out", 0) or 0) + tout
        llamadas_mes = (actual_mes.get("llamadas", 0) or 0) + llamadas

        dias = dict(datos.get("coste_ia_dias") or {})
        actual_dia = dias.get(dia) or {}
        tin_dia = (actual_dia.get("tokens_in", 0) or 0) + tin
        tout_dia = (actual_dia.get("tokens_out", 0) or 0) + tout
        llamadas_dia = (actual_dia.get("llamadas", 0) or 0) + llamadas
        dias[dia] = {
            "tokens_in": tin_dia, "tokens_out": tout_dia, "llamadas": llamadas_dia,
            "coste": coste_estimado(tin_dia, tout_dia),
        }
        limite = (ahora - timedelta(days=LIMITE_DIAS_HISTORICO)).strftime("%Y-%m-%d")
        dias = {d: v for d, v in dias.items() if d >= limite}

        transaction.update(ref, {
            f"coste_ia.{mes}.tokens_in": tin_mes,
            f"coste_ia.{mes}.tokens_out": tout_mes,
            f"coste_ia.{mes}.llamadas": llamadas_mes,
            f"coste_ia.{mes}.coste": coste_estimado(tin_mes, tout_mes),
            "coste_ia_dias": dias,
        })

    ejecutar_en_transaccion(db, _sumar)


def guardar_coste_directo(db, uid, tin, tout, llamadas):
    """Vuelca un consumo de tokens al contador del usuario sin depender de
    flask.g. Pensado para hilos de fondo. Nunca debe romper el flujo que la
    llama."""
    try:
        if not uid or (not tin and not tout):
            return
        _incrementar_mes(db, uid, int(tin or 0), int(tout or 0), int(llamadas or 0))
    except Exception:
        logger.debug("No se pudo guardar el coste de IA (directo)", exc_info=True)


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
        _incrementar_mes(db, uid, acc["in"], acc["out"], acc["llamadas"])
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
