"""Tareas activadas por un cron externo (GitHub Actions), no por un
usuario -- protegidas con un secreto propio (CRON_SECRET_KEY) en vez de
depender de un login, ya que quien llama no es una persona autenticada.
"""
import logging
import os
from datetime import date

import requests
from flask import Blueprint, jsonify, request

from firebase_setup import db
from email_utils import (
    enviar_email_racha_en_riesgo,
    enviar_email_reengagement,
    enviar_email_prueba_terminando,
    enviar_email_prueba_terminada,
)
from planes import ORDEN_PLANES, mejor_plan
from push_utils import enviar_push

logger = logging.getLogger(__name__)
bp = Blueprint("tareas_programadas", __name__)

# Umbrales de días sin actividad para el email de reengagement: se manda
# solo justo al cruzar cada umbral (no cada día a partir de ahí), para no
# saturar a quien lleva mucho tiempo sin volver.
UMBRALES_REENGAGEMENT = {3, 7, 14, 30}


def _clave_cron_valida():
    clave_esperada = os.getenv("CRON_SECRET_KEY")
    return bool(clave_esperada) and request.headers.get("X-Cron-Key") == clave_esperada


@bp.route("/tareas/recordatorios-racha", methods=["POST"])
def enviar_recordatorios_racha():
    if not _clave_cron_valida():
        return jsonify({"error": "No autorizado"}), 401

    hoy = date.today()
    en_riesgo = 0
    reengagement = 0

    for doc in db.collection("usuarios").stream():
        datos = doc.to_dict() or {}
        email = datos.get("email")
        if not email:
            continue

        racha = datos.get("racha") or {}
        ultima_fecha_str = racha.get("ultima_fecha")
        if not ultima_fecha_str:
            continue
        try:
            ultima_fecha = date.fromisoformat(ultima_fecha_str)
        except ValueError:
            continue

        dias_sin_actividad = (hoy - ultima_fecha).days
        nombre = datos.get("nombre") or ""

        if dias_sin_actividad == 1 and racha.get("racha_actual", 0) > 0:
            enviar_email_racha_en_riesgo(email, racha["racha_actual"], nombre=nombre)
            for suscripcion in datos.get("push_subscriptions", []):
                enviar_push(
                    suscripcion,
                    "🔥 No pierdas tu racha",
                    f"Llevas {racha['racha_actual']} días seguidos estudiando. Haz un test hoy para no perderla.",
                )
            en_riesgo += 1
        elif dias_sin_actividad in UMBRALES_REENGAGEMENT:
            enviar_email_reengagement(email, dias_sin_actividad, nombre=nombre)
            reengagement += 1

    logger.info("Recordatorios de racha enviados: %s en riesgo, %s reengagement", en_riesgo, reengagement)
    return jsonify({"en_riesgo": en_riesgo, "reengagement": reengagement})


@bp.route("/tareas/recordatorios-prueba", methods=["POST"])
def enviar_recordatorios_prueba():
    """Avisa por email del final de la prueba gratuita Premium (planes.py):
    2 días antes de que termine, y el primer día después de haber terminado
    si el usuario sigue sin ningún plan de pago. No avisa a quien ya
    contrató Básico o Premium (mejor_plan mira solo las suscripciones
    reales, sin la prueba, así que un plan de pago vigente lo excluye sin
    necesidad de comprobar nada más)."""
    if not _clave_cron_valida():
        return jsonify({"error": "No autorizado"}), 401

    hoy = date.today()
    terminando = 0
    terminada = 0

    for doc in db.collection("usuarios").stream():
        datos = doc.to_dict() or {}
        email = datos.get("email")
        prueba_fin = datos.get("prueba_fin")
        if not email or not prueba_fin:
            continue

        plan_pago, _sub = mejor_plan(datos.get("suscripciones"))
        if ORDEN_PLANES.get(plan_pago, 0) >= ORDEN_PLANES["basico"]:
            continue

        try:
            fin_fecha = date.fromisoformat(prueba_fin[:10])
        except ValueError:
            continue

        dias_restantes = (fin_fecha - hoy).days
        nombre = datos.get("nombre") or ""

        if dias_restantes == 2:
            enviar_email_prueba_terminando(email, dias_restantes, nombre=nombre)
            terminando += 1
        elif dias_restantes == -1:
            enviar_email_prueba_terminada(email, nombre=nombre)
            terminada += 1

    logger.info("Recordatorios de prueba enviados: %s terminando, %s terminada", terminando, terminada)
    return jsonify({"terminando": terminando, "terminada": terminada})


@bp.route("/tareas/diagnostico-red-google", methods=["GET"])
def diagnostico_red_google():
    """Diagnóstico temporal: reproduce desde el propio proceso en
    producción, con visibilidad completa (código, cabeceras), la misma
    petición HTTP que falla dentro de firebase_admin al verificar un ID
    token (CertificateFetchError) -- sin esto, la excepción de la librería
    no dice si el 403 viene de verdad de Google o de algo intermedio antes
    de llegar a Google. Acepta la clave por querystring (no solo por
    cabecera, a diferencia del resto de /tareas/*) para poder abrirlo
    directamente desde el navegador sin herramientas adicionales."""
    clave_esperada = os.getenv("CRON_SECRET_KEY")
    if not clave_esperada or request.args.get("clave") != clave_esperada:
        return jsonify({"error": "No autorizado"}), 401

    url = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
    try:
        resp = requests.get(url, timeout=10)
        return jsonify({
            "ok": True,
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
            "cuerpo_recortado": resp.text[:300],
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
