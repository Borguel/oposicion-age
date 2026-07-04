"""Tareas activadas por un cron externo (GitHub Actions), no por un
usuario -- protegidas con un secreto propio (CRON_SECRET_KEY) en vez de
depender de un login, ya que quien llama no es una persona autenticada.
"""
import logging
import os
from datetime import date

from flask import Blueprint, jsonify, request

from firebase_setup import db
from email_utils import enviar_email_racha_en_riesgo, enviar_email_reengagement

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
            en_riesgo += 1
        elif dias_sin_actividad in UMBRALES_REENGAGEMENT:
            enviar_email_reengagement(email, dias_sin_actividad, nombre=nombre)
            reengagement += 1

    logger.info("Recordatorios de racha enviados: %s en riesgo, %s reengagement", en_riesgo, reengagement)
    return jsonify({"en_riesgo": en_riesgo, "reengagement": reengagement})
