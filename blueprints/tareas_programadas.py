"""Tareas activadas por un cron externo (GitHub Actions), no por un
usuario -- protegidas con un secreto propio (CRON_SECRET_KEY) en vez de
depender de un login, ya que quien llama no es una persona autenticada.
"""
import hmac
import logging
import os
from datetime import date, datetime

from flask import Blueprint, jsonify, request

from firebase_setup import db
from email_utils import (
    enviar_email_racha_en_riesgo,
    enviar_email_reengagement,
    enviar_email_prueba_terminando,
    enviar_email_prueba_terminada,
    enviar_email_activar_oposicion,
    enviar_email_alerta_coste_ia,
)
from marketing_utils import sincronizar_contacto as sincronizar_contacto_marketing
from planes import ORDEN_PLANES
from push_utils import enviar_push
from coste_ia import resumen_coste_usuario
from vigilancia_boe import (
    detectar_avisos_oficiales,
    detectar_cambios_leyes_vigiladas,
    verificar_bloque_temas_referenciados,
)

logger = logging.getLogger(__name__)
bp = Blueprint("tareas_programadas", __name__)

# Umbrales de días sin actividad para el email de reengagement: se manda
# solo justo al cruzar cada umbral (no cada día a partir de ahí), para no
# saturar a quien lleva mucho tiempo sin volver.
UMBRALES_REENGAGEMENT = {3, 7, 14, 30}

# Umbrales de días desde el registro para el email de "aún no has activado
# ninguna oposición": dos avisos espaciados en la primera semana (a los 2 y
# a los 6 días) -- suficiente margen para no molestar a quien ya iba a
# activarla por su cuenta, pero sin dejar pasar toda la ventana de la
# prueba gratuita sin insistir ni una vez.
UMBRALES_ACTIVACION = {2, 6}

# Umbral mínimo (€) para que un pico de gasto en IA merezca una alerta --
# evita ruido cuando el gasto total todavía es trivial (p. ej. pasar de
# 0,01€ a 0,05€ es "x5" pero irrelevante) -- y multiplicador sobre la media
# reciente que se considera "un pico". Configurables por si las tarifas o
# el volumen de uso cambian mucho.
UMBRAL_MINIMO_ALERTA_COSTE_IA_EUR = float(os.getenv("IA_ALERTA_GASTO_MINIMO_EUR", "1.0"))
UMBRAL_MULTIPLICADOR_ALERTA_COSTE_IA = float(os.getenv("IA_ALERTA_GASTO_MULTIPLICADOR", "3.0"))


def _clave_cron_valida():
    clave_esperada = os.getenv("CRON_SECRET_KEY")
    # hmac.compare_digest en vez de "==": una comparación de string normal
    # sale en cuanto encuentra el primer carácter distinto, así que el
    # tiempo de respuesta varía según cuántos caracteres iniciales acierte
    # quien prueba -- suficiente para, con muchos intentos, ir adivinando
    # CRON_SECRET_KEY carácter a carácter (timing attack). compare_digest
    # siempre tarda lo mismo, acierte o no.
    return bool(clave_esperada) and hmac.compare_digest(request.headers.get("X-Cron-Key", ""), clave_esperada)


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
    2 días antes de que termine, y el primer día después de haber terminado,
    para cada oposición del usuario cuya prueba cruce ese umbral -- cada
    oposición activada tiene su propia prueba independiente (ver
    activar_oposicion_usuario en registro_progreso_usuario.py), así que ya
    no es un único aviso por cuenta como antes. No avisa de una oposición ya
    contratada con Básico o Premium (el plan real de esa entrada ya no es
    "gratis", que es la única condición que necesita la prueba para haber
    llegado a arrancar en ella)."""
    if not _clave_cron_valida():
        return jsonify({"error": "No autorizado"}), 401

    hoy = date.today()
    terminando = 0
    terminada = 0

    for doc in db.collection("usuarios").stream():
        datos = doc.to_dict() or {}
        email = datos.get("email")
        if not email:
            continue
        nombre = datos.get("nombre") or ""

        for sub in (datos.get("suscripciones", {}) or {}).values():
            prueba_fin = (sub or {}).get("prueba_fin")
            if not prueba_fin:
                continue
            plan_pago = (sub or {}).get("plan", "gratis")
            if ORDEN_PLANES.get(plan_pago, 0) >= ORDEN_PLANES["basico"]:
                continue

            try:
                fin_fecha = date.fromisoformat(prueba_fin[:10])
            except ValueError:
                continue

            dias_restantes = (fin_fecha - hoy).days
            if dias_restantes == 2:
                enviar_email_prueba_terminando(email, dias_restantes, nombre=nombre)
                terminando += 1
            elif dias_restantes == -1:
                enviar_email_prueba_terminada(email, nombre=nombre)
                sincronizar_contacto_marketing(email, nombre=nombre, estado="sin_suscripcion")
                terminada += 1

    logger.info("Recordatorios de prueba enviados: %s terminando, %s terminada", terminando, terminada)
    return jsonify({"terminando": terminando, "terminada": terminada})


@bp.route("/tareas/recordatorios-activacion", methods=["POST"])
def enviar_recordatorios_activacion():
    """Avisa a quien se registró pero nunca llegó a activar ninguna
    oposición (suscripciones vacío): sin ese paso la cuenta no tiene
    ninguna herramienta disponible y la prueba gratuita ni siquiera ha
    arrancado (ver activar_oposicion_usuario en
    registro_progreso_usuario.py) -- este hueco no lo cubre ningún otro
    cron: los recordatorios de racha exigen tener ya una racha empezada, y
    los de fin de prueba exigen tener ya una oposición con prueba_fin, así
    que una cuenta completamente en blanco no recibía nada más después del
    correo de bienvenida único del registro."""
    if not _clave_cron_valida():
        return jsonify({"error": "No autorizado"}), 401

    hoy = date.today()
    avisados = 0

    for doc in db.collection("usuarios").stream():
        datos = doc.to_dict() or {}
        email = datos.get("email")
        if not email or datos.get("suscripciones"):
            continue

        fecha_creacion_str = datos.get("fecha_creacion")
        if not fecha_creacion_str:
            continue
        try:
            fecha_creacion = datetime.fromisoformat(fecha_creacion_str).date()
        except ValueError:
            continue

        dias_desde_registro = (hoy - fecha_creacion).days
        if dias_desde_registro not in UMBRALES_ACTIVACION:
            continue

        nombre = datos.get("nombre") or ""
        enviar_email_activar_oposicion(email, nombre=nombre)
        avisados += 1

    logger.info("Recordatorios de activación enviados: %s", avisados)
    return jsonify({"avisados": avisados})


@bp.route("/tareas/vigilar-gasto-ia", methods=["POST"])
def vigilar_gasto_ia():
    """Compara el gasto en IA de HOY con la media de los últimos días y
    avisa por email al dueño de la web si hay un pico anómalo (posible
    abuso o un bug), antes de que llegue como sorpresa en la factura de
    DeepSeek. coste_ia.py solo guarda un total por MES (no por día) para no
    añadir una escritura extra en el camino caliente de cada petición que
    usa IA -- aquí se toma una foto diaria de ese total acumulado y el
    gasto de hoy se calcula por diferencia con la foto de ayer, guardada en
    config/coste_ia_alerta."""
    if not _clave_cron_valida():
        return jsonify({"error": "No autorizado"}), 401

    hoy = date.today().isoformat()
    ref = db.collection("config").document("coste_ia_alerta")
    estado = ref.get().to_dict() or {}

    if estado.get("fecha") == hoy:
        return jsonify({"mensaje": "Ya comprobado hoy"}), 200

    total_acumulado_mes = 0.0
    for doc in db.collection("usuarios").stream():
        coste_mes, _coste_total, _tokens = resumen_coste_usuario(doc.to_dict() or {})
        total_acumulado_mes += coste_mes

    fecha_anterior = estado.get("fecha")
    total_anterior = estado.get("total_acumulado_mes", 0.0) or 0.0
    mes_actual = datetime.utcnow().strftime("%Y-%m")
    gasto_hoy = total_acumulado_mes - total_anterior
    # Sin foto previa, o foto de un mes distinto (el total del mes se
    # reinicia a 0 cada mes -- la resta no significaría "gasto de hoy" en
    # ninguno de los dos casos): se guarda la foto de hoy como referencia y
    # se sale sin avisar, no hay nada útil que comparar todavía.
    if not fecha_anterior or gasto_hoy < 0 or not fecha_anterior.startswith(mes_actual):
        gasto_hoy = None

    historial = estado.get("historial") or []
    aviso_enviado = False
    if gasto_hoy is not None:
        media_reciente = sum(historial[-7:]) / len(historial[-7:]) if historial else 0.0
        si_pico = gasto_hoy >= UMBRAL_MINIMO_ALERTA_COSTE_IA_EUR and (
            media_reciente == 0 or gasto_hoy >= media_reciente * UMBRAL_MULTIPLICADOR_ALERTA_COSTE_IA
        )
        if si_pico:
            destinatario = os.getenv("ADMIN_ALERT_EMAIL") or os.getenv("BREVO_FROM_EMAIL", "dominatuopo@gmail.com")
            enviar_email_alerta_coste_ia(destinatario, gasto_hoy, media_reciente)
            aviso_enviado = True
        historial.append(round(gasto_hoy, 4))
        historial = historial[-14:]  # no crecer sin límite

    ref.set({"fecha": hoy, "total_acumulado_mes": total_acumulado_mes, "historial": historial})

    logger.info("Vigilancia de gasto en IA: hoy=%s€, aviso_enviado=%s", gasto_hoy, aviso_enviado)
    return jsonify({"gasto_hoy": gasto_hoy, "aviso_enviado": aviso_enviado})


@bp.route("/tareas/vigilar-boe", methods=["POST"])
def vigilar_boe():
    """Revisa el BOE (leyes vigiladas + sumario diario) y deja en Firestore
    propuestas/avisos PENDIENTES de revisión -- nunca publica nada solo, el
    dueño tiene que aprobarlos desde el panel de admin (ver vigilancia_boe.py
    y blueprints/admin.py)."""
    if not _clave_cron_valida():
        return jsonify({"error": "No autorizado"}), 401

    avisos_creados = detectar_avisos_oficiales(db)
    cambios_propuestos = detectar_cambios_leyes_vigiladas(db)
    # Chequeo de salud, no de vigilancia -- barato (solo lee Firestore, sin
    # llamadas al BOE ni a DeepSeek) así que se hace en cada ciclo diario.
    temas_faltantes = verificar_bloque_temas_referenciados(db)

    logger.info(
        "Vigilancia BOE: %s avisos oficiales nuevos, %s propuestas de cambio de temario, %s temas referenciados que ya no existen",
        avisos_creados, cambios_propuestos, len(temas_faltantes),
    )
    return jsonify({
        "avisos_creados": avisos_creados,
        "cambios_propuestos": cambios_propuestos,
        "temas_faltantes": len(temas_faltantes),
    })
