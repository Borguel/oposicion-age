"""Perfil/racha del usuario y todo lo relacionado con Stripe: crear
sesiones de pago/portal de facturación, y el webhook que mantiene las
suscripciones al día."""
import logging
import os
from datetime import date, datetime

import stripe
from flask import Blueprint, g, jsonify, request

from firebase_setup import db
from auth_utils import requiere_login, obtener_oposicion_solicitada
from registro_progreso_usuario import actualizar_suscripcion, obtener_perfil_usuario
from gestion_cuenta import exportar_datos_usuario, eliminar_cuenta_usuario
from oposiciones import OPOSICION_POR_DEFECTO, oposicion_valida

logger = logging.getLogger(__name__)

bp = Blueprint("pagos", __name__)

# Configuración de Stripe (pagos y suscripciones)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_IDS = {
    "basico": os.getenv("STRIPE_PRICE_ID_BASICO"),
    "premium": os.getenv("STRIPE_PRICE_ID_PREMIUM"),
}
PRECIO_A_PLAN = {v: k for k, v in STRIPE_PRICE_IDS.items() if v}
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8080")


@bp.route("/mi-perfil", methods=["GET"])
@requiere_login(db)
def mi_perfil():
    oposicion = obtener_oposicion_solicitada()
    return jsonify(obtener_perfil_usuario(db, g.uid, oposicion=oposicion))


@bp.route("/mi-racha", methods=["GET"])
@requiere_login(db)
def mi_racha():
    doc = db.collection("usuarios").document(g.uid).get()
    racha = (doc.to_dict() or {}).get("racha") or {}
    racha_actual = racha.get("racha_actual", 0)
    ultima_fecha_str = racha.get("ultima_fecha")
    # Si la última actividad fue hace más de un día, la racha ya está rota
    # aunque en Firestore no se "confirme" hasta la próxima actividad: se
    # calcula al vuelo para no mostrar un número desfasado.
    if ultima_fecha_str:
        try:
            dias_sin_actividad = (datetime.utcnow().date() - date.fromisoformat(ultima_fecha_str)).days
            if dias_sin_actividad > 1:
                racha_actual = 0
        except ValueError:
            pass
    return jsonify({
        "racha_actual": racha_actual,
        "racha_maxima": racha.get("racha_maxima", 0),
        "ultima_fecha": ultima_fecha_str
    })


@bp.route("/mi-cuenta/exportar-datos", methods=["GET"])
@requiere_login(db)
def exportar_datos():
    return jsonify(exportar_datos_usuario(db, g.uid))


@bp.route("/mi-cuenta", methods=["DELETE"])
@requiere_login(db)
def eliminar_cuenta():
    eliminar_cuenta_usuario(db, g.uid)
    return jsonify({"mensaje": "Cuenta eliminada"})


@bp.route("/crear-sesion-checkout", methods=["POST"])
@requiere_login(db)
def crear_sesion_checkout():
    data = request.get_json(silent=True) or {}
    plan = data.get("plan")
    oposicion = data.get("oposicion", OPOSICION_POR_DEFECTO)
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    price_id = STRIPE_PRICE_IDS.get(plan)
    if not price_id:
        return jsonify({"error": "Plan no válido"}), 400
    try:
        doc_ref = db.collection("usuarios").document(g.uid)
        usuario = doc_ref.get().to_dict() or {}
        stripe_customer_id = usuario.get("stripe_customer_id")
        if not stripe_customer_id:
            customer = stripe.Customer.create(email=g.email, metadata={"uid": g.uid})
            stripe_customer_id = customer.id
            actualizar_suscripcion(db, g.uid, oposicion, stripe_customer_id=stripe_customer_id)
        # La oposición viaja tanto en la metadata de la sesión de checkout
        # (solo disponible en el evento checkout.session.completed) como en
        # subscription_data.metadata, para que quede grabada en la propia
        # Subscription de Stripe y así los eventos posteriores
        # (customer.subscription.updated/deleted) también sepan a qué
        # oposición pertenecen.
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=stripe_customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{FRONTEND_URL}/mi-cuenta/?checkout=success&oposicion={oposicion}",
            cancel_url=f"{FRONTEND_URL}/planes/?checkout=cancel&oposicion={oposicion}",
            client_reference_id=g.uid,
            metadata={"uid": g.uid, "plan": plan, "oposicion": oposicion},
            subscription_data={"metadata": {"uid": g.uid, "plan": plan, "oposicion": oposicion}}
        )
        return jsonify({"url": session.url})
    except Exception as e:
        logger.exception("Error creando sesión de Stripe Checkout")
        return jsonify({"error": str(e)}), 500


MOTIVOS_BAJA_VALIDOS = {"precio", "no_lo_uso", "aprobado", "faltan_funciones", "otro"}


@bp.route("/cancelar-suscripcion", methods=["POST"])
@requiere_login(db)
def cancelar_suscripcion():
    """Cancela la suscripción de una oposición concreta al final del
    periodo ya pagado (nunca de inmediato, para no cortar algo que el
    usuario ya ha pagado) y guarda el motivo de la baja -- a diferencia de
    redirigir sin más al portal genérico de Stripe, esto da una
    oportunidad real de entender por qué se va alguien antes de que se
    vaya (ver auditoría de julio 2026)."""
    data = request.get_json(silent=True) or {}
    oposicion = data.get("oposicion", OPOSICION_POR_DEFECTO)
    motivo = data.get("motivo")
    comentario = (data.get("comentario") or "").strip()[:500]
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    if motivo not in MOTIVOS_BAJA_VALIDOS:
        return jsonify({"error": "Motivo no válido"}), 400

    usuario_ref = db.collection("usuarios").document(g.uid)
    usuario = usuario_ref.get().to_dict() or {}
    subscription_id = ((usuario.get("suscripciones") or {}).get(oposicion) or {}).get("stripe_subscription_id")
    if not subscription_id:
        return jsonify({"error": "No tienes ninguna suscripción activa para esta oposición"}), 400

    try:
        subscription = stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)
    except Exception as e:
        logger.exception("Error cancelando suscripción de Stripe %s", subscription_id)
        return jsonify({"error": str(e)}), 500

    usuario_ref.collection("bajas_motivos").document().set({
        "oposicion": oposicion,
        "motivo": motivo,
        "comentario": comentario,
        "fecha": datetime.utcnow().isoformat(),
    })
    actualizar_suscripcion(db, g.uid, oposicion, cancelar_al_final_periodo=True)

    periodo_fin = _current_period_end(subscription)
    return jsonify({
        "mensaje": "Tu suscripción se cancelará al final del periodo ya pagado.",
        "current_period_end": datetime.utcfromtimestamp(periodo_fin).isoformat() if periodo_fin else None
    })


@bp.route("/reactivar-suscripcion", methods=["POST"])
@requiere_login(db)
def reactivar_suscripcion():
    """Deshace una cancelación programada (/cancelar-suscripcion) antes de
    que llegue a hacerse efectiva -- la suscripción sigue activa y se
    renovará con normalidad."""
    data = request.get_json(silent=True) or {}
    oposicion = data.get("oposicion", OPOSICION_POR_DEFECTO)
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400

    usuario_ref = db.collection("usuarios").document(g.uid)
    usuario = usuario_ref.get().to_dict() or {}
    subscription_id = ((usuario.get("suscripciones") or {}).get(oposicion) or {}).get("stripe_subscription_id")
    if not subscription_id:
        return jsonify({"error": "No tienes ninguna suscripción activa para esta oposición"}), 400

    try:
        stripe.Subscription.modify(subscription_id, cancel_at_period_end=False)
    except Exception as e:
        logger.exception("Error reactivando suscripción de Stripe %s", subscription_id)
        return jsonify({"error": str(e)}), 500

    actualizar_suscripcion(db, g.uid, oposicion, cancelar_al_final_periodo=False)
    return jsonify({"mensaje": "Tu suscripción se ha reactivado."})


@bp.route("/crear-sesion-portal", methods=["POST"])
@requiere_login(db)
def crear_sesion_portal():
    usuario = db.collection("usuarios").document(g.uid).get().to_dict() or {}
    stripe_customer_id = usuario.get("stripe_customer_id")
    if not stripe_customer_id:
        return jsonify({"error": "Todavía no tienes ninguna suscripción"}), 400
    try:
        session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=f"{FRONTEND_URL}/mi-cuenta/"
        )
        return jsonify({"url": session.url})
    except Exception as e:
        logger.exception("Error creando sesión del portal de Stripe")
        return jsonify({"error": str(e)}), 500


def _sget(obj, key, default=None):
    """Equivalente a dict.get() pero que también funciona con los objetos
    de la librería de Stripe: en la versión que usamos, esos objetos
    soportan obj["clave"] pero NO tienen un método .get() real (lo
    resuelven vía __getattr__ y acaban lanzando AttributeError)."""
    try:
        valor = obj[key]
        return default if valor is None else valor
    except (KeyError, TypeError):
        return default


def _current_period_end(subscription_obj):
    """Extrae 'current_period_end' de una Subscription de Stripe.
    En versiones recientes de la API (>= 2025) ese campo ya no está en la
    propia suscripción, sino en cada "item" de la suscripción."""
    valor = _sget(subscription_obj, "current_period_end")
    if valor is None:
        items = _sget(_sget(subscription_obj, "items", {}), "data", [])
        if items:
            valor = _sget(items[0], "current_period_end")
    return valor


@bp.route("/webhook-stripe", methods=["POST"])
def webhook_stripe():
    payload = request.get_data()
    firma = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, firma, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.warning("Webhook de Stripe con firma inválida: %s", e)
        return jsonify({"error": "Firma inválida"}), 400

    evento_ref = db.collection("stripe_events").document(event["id"])
    if evento_ref.get().exists:
        return jsonify({"mensaje": "Evento ya procesado"}), 200

    tipo = event["type"]
    objeto = event["data"]["object"]

    try:
        if tipo == "checkout.session.completed":
            metadata = _sget(objeto, "metadata", {}) or {}
            uid = _sget(objeto, "client_reference_id") or _sget(metadata, "uid")
            oposicion = _sget(metadata, "oposicion") or OPOSICION_POR_DEFECTO
            subscription_id = _sget(objeto, "subscription")
            if uid and subscription_id:
                subscription = stripe.Subscription.retrieve(subscription_id)
                price_id = subscription["items"]["data"][0]["price"]["id"]
                plan = PRECIO_A_PLAN.get(price_id, "gratis")
                periodo_fin = _current_period_end(subscription)
                actualizar_suscripcion(
                    db, uid, oposicion,
                    plan=plan,
                    stripe_customer_id=_sget(objeto, "customer"),
                    stripe_subscription_id=subscription_id,
                    subscription_status=subscription["status"],
                    current_period_end=datetime.utcfromtimestamp(periodo_fin).isoformat() if periodo_fin else None,
                    cancelar_al_final_periodo=_sget(subscription, "cancel_at_period_end", False)
                )
        elif tipo == "customer.subscription.updated":
            customer_id = _sget(objeto, "customer")
            # La oposición viaja en la metadata de la propia Subscription
            # (puesta ahí al crear el checkout). Si falta -- suscripciones
            # creadas antes de que existiera esta metadata -- se asume AGE,
            # que era la única oposición que existía entonces.
            metadata = _sget(objeto, "metadata", {}) or {}
            oposicion = _sget(metadata, "oposicion") or OPOSICION_POR_DEFECTO
            docs = list(db.collection("usuarios").where("stripe_customer_id", "==", customer_id).limit(1).stream())
            if docs:
                price_id = objeto["items"]["data"][0]["price"]["id"]
                plan = PRECIO_A_PLAN.get(price_id, "gratis")
                periodo_fin = _current_period_end(objeto)
                actualizar_suscripcion(
                    db, docs[0].id, oposicion,
                    plan=plan,
                    stripe_subscription_id=_sget(objeto, "id"),
                    subscription_status=_sget(objeto, "status"),
                    current_period_end=datetime.utcfromtimestamp(periodo_fin).isoformat() if periodo_fin else None,
                    cancelar_al_final_periodo=_sget(objeto, "cancel_at_period_end", False)
                )
        elif tipo == "customer.subscription.deleted":
            customer_id = _sget(objeto, "customer")
            metadata = _sget(objeto, "metadata", {}) or {}
            oposicion = _sget(metadata, "oposicion") or OPOSICION_POR_DEFECTO
            docs = list(db.collection("usuarios").where("stripe_customer_id", "==", customer_id).limit(1).stream())
            if docs:
                actualizar_suscripcion(db, docs[0].id, oposicion, plan="gratis", subscription_status="canceled", cancelar_al_final_periodo=False)
        elif tipo == "invoice.payment_failed":
            customer_id = _sget(objeto, "customer")
            subscription_id = _sget(objeto, "subscription")
            oposicion = OPOSICION_POR_DEFECTO
            if subscription_id:
                try:
                    sub_obj = stripe.Subscription.retrieve(subscription_id)
                    oposicion = _sget(_sget(sub_obj, "metadata", {}) or {}, "oposicion") or OPOSICION_POR_DEFECTO
                except Exception:
                    pass
            docs = list(db.collection("usuarios").where("stripe_customer_id", "==", customer_id).limit(1).stream())
            if docs:
                actualizar_suscripcion(db, docs[0].id, oposicion, subscription_status="past_due")
    except Exception:
        # logger.exception ya vuelca el traceback completo (y lo manda a
        # Sentry si está configurado). Se responde 500 sin el detalle interno
        # del error para que Stripe reintente el evento, sin exponer trazas.
        logger.exception("Error procesando webhook de Stripe (%s)", tipo)
        return jsonify({"error": "Error interno procesando el evento"}), 500

    evento_ref.set({"type": tipo, "processed_at": datetime.utcnow().isoformat()})
    return jsonify({"mensaje": "Evento procesado"}), 200
