"""Perfil/racha del usuario y todo lo relacionado con Stripe: crear
sesiones de pago/portal de facturación, y el webhook que mantiene las
suscripciones al día."""
import logging
import os
from datetime import date, datetime

import stripe
from firebase_admin import firestore
from flask import Blueprint, g, jsonify, request

from firebase_setup import db
from auth_utils import requiere_login, obtener_oposicion_solicitada
from registro_progreso_usuario import actualizar_suscripcion, obtener_perfil_usuario
from gestion_cuenta import exportar_datos_usuario, eliminar_cuenta_usuario
from oposiciones import OPOSICIONES, OPOSICION_POR_DEFECTO, oposicion_valida
from email_utils import (
    enviar_email_cancelacion_suscripcion,
    enviar_email_pago_fallido,
    enviar_email_reactivacion_suscripcion,
)
from marketing_utils import sincronizar_contacto as sincronizar_contacto_marketing
from promociones import leer_promocion, promocion_vigente
from utils import invalidar_cache, ejecutar_en_transaccion
from planes import ESTADOS_SUSCRIPCION_ACTIVA
import generacion_control

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
NOMBRE_PLAN = {"basico": "Básico", "premium": "Premium"}
# Mismas siglas cortas que ya usa el selector de oposición del frontend
# (frontend/assets/oposicion.js) -- se usan aquí para que el nombre del
# producto que ve el usuario en el Checkout/portal de Stripe distinga de
# qué oposición es cada suscripción (ver /crear-sesion-checkout).
SIGLAS_OPOSICION = {"AGE": "AGE", "GACE": "GACE", "AUXILIAR": "Auxiliar"}


def _invalidar_cache_admin_tras_cambio_suscripcion():
    """Los agregados del panel admin (dashboard, Bajas, Ingresos) se
    cachean unos minutos (ver _TTL_CACHE_ADMIN_SEGUNDOS en admin.py) para
    no recorrer TODA la colección de usuarios en cada apertura del panel.
    Se invalida aquí, justo al cancelar/reactivar una suscripción, para
    que una baja recién dada no tarde hasta 3 minutos en aparecer en
    "Bajas recientes" -- exactamente el problema que se pidió arreglar."""
    invalidar_cache(("admin_bajas", True))
    invalidar_cache(("admin_bajas", False))
    invalidar_cache(("admin_ingresos_filas",))
    for oid in OPOSICIONES:
        invalidar_cache(("admin_resumen", oid))


@bp.route("/mi-perfil", methods=["GET"])
@requiere_login(db)
def mi_perfil():
    oposicion = obtener_oposicion_solicitada()
    return jsonify(obtener_perfil_usuario(db, g.uid, oposicion=oposicion, es_admin=getattr(g, "es_admin", False)))


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


@bp.route("/mi-cuenta/contactar", methods=["POST"])
@requiere_login(db)
def contactar_soporte():
    data = request.get_json(silent=True) or {}
    mensaje = (data.get("mensaje") or "").strip()
    if not mensaje:
        return jsonify({"error": "Escribe tu consulta antes de enviarla."}), 400
    db.collection("mensajes_soporte").document().set({
        "uid": g.uid,
        "email": g.email,
        "mensaje": mensaje[:2000],
        "estado": "pendiente",
        "fecha": datetime.utcnow().isoformat(),
    })
    return jsonify({"mensaje": "Hemos recibido tu mensaje. Te responderemos por email."}), 201


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
        if stripe_customer_id:
            # El ID guardado puede quedar huérfano si se cambió de clave de
            # Stripe (p. ej. de test a live: ese Customer solo existe en la
            # cuenta antigua) -- se valida antes de reutilizarlo y, si ya no
            # existe, se trata como si no hubiera ninguno guardado. Solo se
            # asume "huérfano" con code == "resource_missing" (Sentry
            # PYTHON-FLASK-B); cualquier otro InvalidRequestError (p. ej. la
            # cuenta de Stripe mal configurada) es un fallo real y debe
            # seguir subiendo al except genérico de más abajo en vez de
            # camuflarse como un simple customer_id caducado.
            try:
                stripe.Customer.retrieve(stripe_customer_id)
            except stripe.InvalidRequestError as e:
                if getattr(e, "code", None) != "resource_missing":
                    raise
                logger.warning(
                    "[stripe_id_huerfano] customer_id huérfano detectado para uid=%s (id=%s); se regenera",
                    g.uid, stripe_customer_id,
                )
                stripe_customer_id = None
        if not stripe_customer_id:
            id_anterior = usuario.get("stripe_customer_id")
            customer = stripe.Customer.create(email=g.email, metadata={"uid": g.uid})
            stripe_customer_id = customer.id
            actualizar_suscripcion(db, g.uid, oposicion, stripe_customer_id=stripe_customer_id)
            if id_anterior:
                logger.warning(
                    "[stripe_id_huerfano] customer_id regenerado para uid=%s: %s -> %s",
                    g.uid, id_anterior, stripe_customer_id,
                )
        # El Price configurado (STRIPE_PRICE_ID_BASICO/PREMIUM) es uno solo,
        # compartido por las 3 oposiciones -- así que su Product en Stripe se
        # llama simplemente "Básico"/"Premium" y, en el portal de facturación,
        # dos suscripciones a oposiciones distintas del mismo plan son
        # indistinguibles entre sí (no hay forma de saber cuál cancelar).
        # Para arreglarlo sin tener que crear Products/Prices nuevos a mano en
        # el Dashboard, se genera un Price "al vuelo" (price_data) con el
        # mismo importe/moneda/periodicidad que el Price configurado pero un
        # nombre de producto que sí incluye la oposición -- así queda visible
        # en el Checkout y en el portal de Stripe.
        try:
            precio_base = stripe.Price.retrieve(price_id)
        except Exception:
            logger.exception("Error obteniendo el precio de Stripe %s", price_id)
            return jsonify({"error": "No se pudo iniciar el pago. Inténtalo de nuevo."}), 500
        nombre_producto = f"Domina tu Opo — Plan {NOMBRE_PLAN.get(plan, plan)} ({SIGLAS_OPOSICION.get(oposicion, oposicion)})"

        # La oposición viaja tanto en la metadata de la sesión de checkout
        # (solo disponible en el evento checkout.session.completed) como en
        # subscription_data.metadata, para que quede grabada en la propia
        # Subscription de Stripe y así los eventos posteriores
        # (customer.subscription.updated/deleted) también sepan a qué
        # oposición pertenecen. El plan (básico/premium) viaja igual, para no
        # depender de reconocer el price_id en el webhook -- ahora que cada
        # sesión genera un Price nuevo, el price_id ya no sirve para eso (ver
        # PRECIO_A_PLAN, que solo queda como fallback para suscripciones
        # antiguas creadas antes de este cambio).
        kwargs_checkout = dict(
            mode="subscription",
            customer=stripe_customer_id,
            line_items=[{
                "price_data": {
                    "currency": precio_base["currency"],
                    "unit_amount": precio_base["unit_amount"],
                    "recurring": {"interval": precio_base["recurring"]["interval"]},
                    "product_data": {"name": nombre_producto},
                },
                "quantity": 1,
            }],
            success_url=f"{FRONTEND_URL}/mi-cuenta/?checkout=success&oposicion={oposicion}",
            cancel_url=f"{FRONTEND_URL}/planes/?checkout=cancel&oposicion={oposicion}",
            client_reference_id=g.uid,
            metadata={"uid": g.uid, "plan": plan, "oposicion": oposicion},
            subscription_data={"metadata": {"uid": g.uid, "plan": plan, "oposicion": oposicion}}
        )
        # Descuento activo desde el panel de admin (ver promociones.py):
        # se aplica solo si la promoción es para ESTE plan y sigue vigente.
        promo = leer_promocion()
        if promocion_vigente(promo) and promo.get("plan") == plan and promo.get("stripe_promotion_code"):
            kwargs_checkout["discounts"] = [{"promotion_code": promo["stripe_promotion_code"]}]
        session = stripe.checkout.Session.create(**kwargs_checkout)
        return jsonify({"url": session.url})
    except Exception:
        logger.exception("Error creando sesión de Stripe Checkout")
        return jsonify({"error": "No se pudo iniciar el pago. Inténtalo de nuevo."}), 500


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
    except stripe.InvalidRequestError as e:
        if getattr(e, "code", None) != "resource_missing":
            logger.exception("Error cancelando suscripción de Stripe %s", subscription_id)
            return jsonify({"error": "No se pudo cancelar la suscripción. Inténtalo de nuevo."}), 500
        # La suscripción guardada ya no existe en Stripe (p. ej. quedó de
        # cuando la web usaba la clave de pruebas y se cambió a la de
        # producción) -- no hay nada que cancelar en Stripe, así que se
        # refleja localmente que ya no está activa en vez de dar un error
        # sobre algo que el usuario no puede arreglar.
        logger.warning(
            "[stripe_id_huerfano] stripe_subscription_id huérfano detectado para uid=%s (id=%s); se marca como cancelada localmente",
            g.uid, subscription_id,
        )
        actualizar_suscripcion(db, g.uid, oposicion, plan="gratis", subscription_status="canceled")
        _invalidar_cache_admin_tras_cambio_suscripcion()
        return jsonify({"mensaje": "Tu suscripción ya no estaba activa; tu cuenta ha quedado en el plan gratuito."})
    except Exception:
        logger.exception("Error cancelando suscripción de Stripe %s", subscription_id)
        return jsonify({"error": "No se pudo cancelar la suscripción. Inténtalo de nuevo."}), 500

    usuario_ref.collection("bajas_motivos").document().set({
        "oposicion": oposicion,
        "motivo": motivo,
        "comentario": comentario,
        "fecha": datetime.utcnow().isoformat(),
    })
    actualizar_suscripcion(db, g.uid, oposicion, cancelar_al_final_periodo=True)
    _invalidar_cache_admin_tras_cambio_suscripcion()

    periodo_fin = _current_period_end(subscription)
    fecha_fin_iso = datetime.utcfromtimestamp(periodo_fin).isoformat() if periodo_fin else None
    fecha_fin_legible = datetime.utcfromtimestamp(periodo_fin).strftime("%d/%m/%Y") if periodo_fin else None
    oposicion_nombre = OPOSICIONES.get(oposicion, {}).get("nombre", oposicion)
    enviar_email_cancelacion_suscripcion(g.email, oposicion_nombre, fecha_fin=fecha_fin_legible, motivo=motivo)

    return jsonify({
        "mensaje": "Tu suscripción se cancelará al final del periodo ya pagado.",
        "current_period_end": fecha_fin_iso
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
    except stripe.InvalidRequestError as e:
        if getattr(e, "code", None) != "resource_missing":
            logger.exception("Error reactivando suscripción de Stripe %s", subscription_id)
            return jsonify({"error": "No se pudo reactivar la suscripción. Inténtalo de nuevo."}), 500
        # Mismo caso huérfano que /cancelar-suscripcion (ver ese comentario):
        # la suscripción guardada ya no existe en Stripe, así que no hay
        # nada que "reactivar" de verdad -- sin este manejo, el error crudo
        # de Stripe ("No such subscription: ...") le llegaba tal cual al
        # usuario en vez de una explicación entendible.
        logger.warning(
            "[stripe_id_huerfano] stripe_subscription_id huérfano detectado para uid=%s (id=%s) al reactivar; se marca como cancelada localmente",
            g.uid, subscription_id,
        )
        actualizar_suscripcion(db, g.uid, oposicion, plan="gratis", subscription_status="canceled", cancelar_al_final_periodo=False)
        _invalidar_cache_admin_tras_cambio_suscripcion()
        return jsonify({
            "error": "No hemos encontrado ninguna suscripción activa que reactivar; tu cuenta ha quedado en el plan gratuito. Si quieres seguir con Premium o Básico, contrátalo de nuevo desde la página de planes."
        }), 400
    except Exception:
        logger.exception("Error reactivando suscripción de Stripe %s", subscription_id)
        return jsonify({"error": "No se pudo reactivar la suscripción. Inténtalo de nuevo."}), 500

    actualizar_suscripcion(db, g.uid, oposicion, cancelar_al_final_periodo=False)
    _invalidar_cache_admin_tras_cambio_suscripcion()
    oposicion_nombre = OPOSICIONES.get(oposicion, {}).get("nombre", oposicion)
    enviar_email_reactivacion_suscripcion(g.email, oposicion_nombre)
    sincronizar_contacto_marketing(g.email, oposicion=oposicion, estado="activo")
    return jsonify({"mensaje": "Tu suscripción se ha reactivado."})


@bp.route("/crear-sesion-portal", methods=["POST"])
@requiere_login(db)
def crear_sesion_portal():
    doc_ref = db.collection("usuarios").document(g.uid)
    usuario = doc_ref.get().to_dict() or {}
    stripe_customer_id = usuario.get("stripe_customer_id")
    if not stripe_customer_id:
        return jsonify({"error": "Todavía no tienes ninguna suscripción"}), 400
    try:
        session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=f"{FRONTEND_URL}/mi-cuenta/"
        )
        return jsonify({"url": session.url})
    except stripe.InvalidRequestError as e:
        if getattr(e, "code", None) != "resource_missing":
            logger.exception("Error creando sesión del portal de Stripe")
            return jsonify({"error": "No se pudo abrir el portal de facturación. Inténtalo de nuevo."}), 500
        # El customer guardado quedó huérfano (p. ej. de cuando la web usaba
        # la clave de pruebas de Stripe) -- no hay ninguna suscripción real
        # detrás de lo que muestre Firestore, así que se limpia el estado
        # local para que el usuario pueda volver a contratar un plan desde
        # cero en vez de quedarse atascado con un botón que siempre falla.
        # (No se crea un customer nuevo aquí como en /crear-sesion-checkout:
        # un customer recién creado no tendría ninguna suscripción/método de
        # pago que mostrar en el portal, así que no arreglaría nada.)
        logger.warning(
            "[stripe_id_huerfano] customer_id huérfano detectado para uid=%s (id=%s); se limpia el estado local",
            g.uid, stripe_customer_id,
        )
        doc_ref.update({"stripe_customer_id": firestore.DELETE_FIELD})
        for oposicion, sub in (usuario.get("suscripciones", {}) or {}).items():
            if (sub or {}).get("plan", "gratis") != "gratis":
                actualizar_suscripcion(db, g.uid, oposicion, plan="gratis", subscription_status="canceled", cancelar_al_final_periodo=False)
        return jsonify({"error": "No hemos encontrado ninguna suscripción de pago activa. Si quieres seguir con Premium o Básico, contrátalo de nuevo desde la página de planes."}), 400
    except Exception:
        logger.exception("Error creando sesión del portal de Stripe")
        return jsonify({"error": "No se pudo abrir el portal de facturación. Inténtalo de nuevo."}), 500


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


def reconciliar_suscripciones_con_stripe(db):
    """Red de seguridad frente a un webhook de Stripe perdido (el endpoint
    estuvo caído más allá de la ventana de reintentos de Stripe, ~3 días;
    o alguien borra a mano el registro de idempotencia en stripe_events/
    pensando que es limpieza) -- llamada desde un cron periódico (ver
    blueprints/tareas_programadas.py::reconciliar_stripe), no desde una
    petición de usuario.

    Sin esto, el subscription_status guardado en Firestore podía quedar
    desincronizado del real en Stripe INDEFINIDAMENTE (nada más vuelve a
    comprobarlo): un usuario cuya suscripción se cancela en Stripe -- por
    un impago, una disputa, o cancelada a mano desde el Dashboard de
    Stripe -- seguía con acceso de pago sin cobro real hasta que alguien
    lo notara manualmente en el panel admin.

    Solo revisa suscripciones con stripe_subscription_id y un
    subscription_status que hoy se considera "activo" (ver
    ESTADOS_SUSCRIPCION_ACTIVA) -- las ya marcadas como canceladas/
    impagadas no necesitan reconciliarse de nuevo. Reutiliza exactamente
    la misma lógica de cálculo de plan/periodo que el webhook customer.
    subscription.updated, para no divergir entre los dos caminos.

    Devuelve (revisadas, corregidas)."""
    revisadas = 0
    corregidas = 0
    for doc in db.collection("usuarios").stream():
        datos = doc.to_dict() or {}
        for oposicion, sub in (datos.get("suscripciones") or {}).items():
            sub = sub or {}
            subscription_id = sub.get("stripe_subscription_id")
            if not subscription_id or sub.get("subscription_status") not in ESTADOS_SUSCRIPCION_ACTIVA:
                continue
            revisadas += 1
            try:
                sub_stripe = stripe.Subscription.retrieve(subscription_id)
            except stripe.error.InvalidRequestError:
                # Ya no existe en Stripe (borrada de verdad, no solo
                # cancelada) -- se trata como cancelada aquí también.
                actualizar_suscripcion(
                    db, doc.id, oposicion, plan="gratis",
                    subscription_status="canceled", cancelar_al_final_periodo=False,
                )
                corregidas += 1
                continue
            except Exception:
                logger.exception(
                    "Error consultando Stripe al reconciliar uid=%s oposicion=%s sub=%s",
                    doc.id, oposicion, subscription_id,
                )
                continue

            estado_real = _sget(sub_stripe, "status")
            if estado_real == sub.get("subscription_status"):
                continue
            plan = PRECIO_A_PLAN.get(sub_stripe["items"]["data"][0]["price"]["id"], "gratis")
            periodo_fin = _current_period_end(sub_stripe)
            actualizar_suscripcion(
                db, doc.id, oposicion,
                plan=plan,
                subscription_status=estado_real,
                current_period_end=datetime.utcfromtimestamp(periodo_fin).isoformat() if periodo_fin else None,
                cancelar_al_final_periodo=_sget(sub_stripe, "cancel_at_period_end", False),
            )
            logger.warning(
                "Reconciliación Stripe: uid=%s oposicion=%s estado desincronizado (Firestore=%s, Stripe=%s) -- corregido",
                doc.id, oposicion, sub.get("subscription_status"), estado_real,
            )
            corregidas += 1

    return revisadas, corregidas


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
    tipo = event["type"]
    objeto = event["data"]["object"]

    # Reclamar el evento (comprobar que no existe + crearlo) en una única
    # transacción atómica: Stripe reintenta entregas del mismo evento, y un
    # simple get().exists() seguido de un set() al final dejaba una ventana
    # -- dos entregas casi simultáneas podían pasar la comprobación las dos
    # antes de que ninguna llegara a marcarlo, y procesarse por duplicado
    # (doble email, doble sincronización de marketing...). Si el
    # procesamiento de más abajo falla, se libera el reclamo (ver el except)
    # para que un reintento de Stripe pueda completarlo de verdad.
    def _reclamar_evento(transaction):
        doc = evento_ref.get(transaction=transaction)
        if doc.exists:
            return False
        transaction.set(evento_ref, {"type": tipo, "processed_at": datetime.utcnow().isoformat()})
        return True

    if not ejecutar_en_transaccion(db, _reclamar_evento):
        return jsonify({"mensaje": "Evento ya procesado"}), 200

    try:
        if tipo == "checkout.session.completed":
            metadata = _sget(objeto, "metadata", {}) or {}
            uid = _sget(objeto, "client_reference_id") or _sget(metadata, "uid")
            oposicion = _sget(metadata, "oposicion") or OPOSICION_POR_DEFECTO
            subscription_id = _sget(objeto, "subscription")
            if uid and subscription_id:
                subscription = stripe.Subscription.retrieve(subscription_id)
                # El plan viaja en la metadata de la propia sesión (puesta
                # ahí al crear el checkout) -- se prefiere sobre el price_id
                # porque, desde que cada sesión genera su Price al vuelo (ver
                # /crear-sesion-checkout), el price_id ya no es un valor fijo
                # reconocible en PRECIO_A_PLAN. Ese lookup por price_id queda
                # solo como fallback para suscripciones creadas antes de este
                # cambio.
                plan = _sget(metadata, "plan")
                if not plan:
                    price_id = subscription["items"]["data"][0]["price"]["id"]
                    plan = PRECIO_A_PLAN.get(price_id, "gratis")
                periodo_fin = _current_period_end(subscription)

                # Bug real (23/08/2026): /crear-sesion-checkout siempre crea
                # una sesión de Checkout NUEVA, nunca modifica la existente
                # -- así que cambiar de plan (p. ej. Básico -> Premium) para
                # la MISMA oposición no sustituía nada: dejaba la
                # suscripción anterior huérfana en Stripe, cobrando en
                # paralelo con la nueva, sin que la web volviera a
                # mencionarla en ningún sitio. Se cancela aquí, justo cuando
                # la nueva ya está confirmada y activa -- no antes de crear
                # el checkout, para no dejar al usuario sin ninguna
                # suscripción si abandona el pago a mitad.
                usuario_antes = db.collection("usuarios").document(uid).get().to_dict() or {}
                sub_anterior_id = ((usuario_antes.get("suscripciones") or {}).get(oposicion) or {}).get("stripe_subscription_id")
                if sub_anterior_id and sub_anterior_id != subscription_id:
                    try:
                        stripe.Subscription.delete(sub_anterior_id)
                    except Exception:
                        logger.exception(
                            "No se pudo cancelar la suscripción anterior %s de uid=%s al cambiar de plan en %s",
                            sub_anterior_id, uid, oposicion,
                        )

                actualizar_suscripcion(
                    db, uid, oposicion,
                    plan=plan,
                    stripe_customer_id=_sget(objeto, "customer"),
                    stripe_subscription_id=subscription_id,
                    subscription_status=subscription["status"],
                    current_period_end=datetime.utcfromtimestamp(periodo_fin).isoformat() if periodo_fin else None,
                    cancelar_al_final_periodo=_sget(subscription, "cancel_at_period_end", False)
                )
                usuario = db.collection("usuarios").document(uid).get().to_dict() or {}
                sincronizar_contacto_marketing(usuario.get("email"), oposicion=oposicion, estado="activo")
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
                # Igual que en checkout.session.completed: se prefiere el
                # plan de la metadata sobre el price_id, que ya no es fijo.
                plan = _sget(metadata, "plan")
                if not plan:
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
                email_usuario = (docs[0].to_dict() or {}).get("email")
                sincronizar_contacto_marketing(email_usuario, oposicion=oposicion, estado="sin_suscripcion")
                # Bug real (24/08/2026): Stripe puede borrar la suscripción
                # en cualquier momento (no solo al final del periodo ya
                # pagado -- también por una disputa/chargeback, por
                # ejemplo), y hasta ahora nada avisaba a una generación
                # premium en curso (resumen/esquema/banco de preguntas o
                # tarjetas) de que el usuario acababa de perder el plan que
                # se lo permitía -- el hilo de fondo seguía gastando
                # llamadas a DeepSeek sobre una cuenta que ya no tiene
                # acceso. Mismo mecanismo que ya usa eliminar_documento_route
                # al borrar un documento suelto (ver generacion_control.py),
                # aquí a nivel de usuario entero porque no se sabe de
                # antemano qué documento_id/herramienta tenía en marcha.
                generacion_control.solicitar_parada_todas(docs[0].id)
        elif tipo == "invoice.payment_failed":
            customer_id = _sget(objeto, "customer")
            subscription_id = _sget(objeto, "subscription")
            oposicion = OPOSICION_POR_DEFECTO
            if subscription_id:
                try:
                    sub_obj = stripe.Subscription.retrieve(subscription_id)
                    oposicion = _sget(_sget(sub_obj, "metadata", {}) or {}, "oposicion") or OPOSICION_POR_DEFECTO
                except Exception:
                    # Best-effort: si Stripe falla aquí, se sigue tratando el
                    # pago fallido con la oposición por defecto en vez de
                    # perder el evento entero -- pero sin log, un fallo
                    # persistente (p. ej. credenciales caducadas) quedaba
                    # invisible, y el email de "pago fallido" podía salir
                    # mencionando la oposición equivocada sin que nadie se
                    # enterase.
                    logger.warning("No se pudo leer la oposición de la suscripción %s en invoice.payment_failed", subscription_id, exc_info=True)
            docs = list(db.collection("usuarios").where("stripe_customer_id", "==", customer_id).limit(1).stream())
            if docs:
                actualizar_suscripcion(db, docs[0].id, oposicion, subscription_status="past_due")
                email_usuario = (docs[0].to_dict() or {}).get("email")
                oposicion_nombre = OPOSICIONES.get(oposicion, {}).get("nombre", oposicion)
                enviar_email_pago_fallido(email_usuario, oposicion_nombre)
                sincronizar_contacto_marketing(email_usuario, oposicion=oposicion, estado="pago_fallido")
    except Exception:
        # logger.exception ya vuelca el traceback completo (y lo manda a
        # Sentry si está configurado). Se responde 500 sin el detalle interno
        # del error para que Stripe reintente el evento, sin exponer trazas.
        # Se libera el reclamo de arriba -- si no, el reintento de Stripe se
        # encontraría el evento ya marcado y lo daría por procesado sin
        # haberlo completado nunca.
        logger.exception("Error procesando webhook de Stripe (%s)", tipo)
        evento_ref.delete()
        return jsonify({"error": "Error interno procesando el evento"}), 500

    # Los 4 tipos de evento de arriba cambian el plan/estado de una
    # suscripción -- este es el camino MÁS habitual en producción para que
    # cambie de verdad (renovaciones, altas y pagos fallidos reales sí
    # llegan por aquí, no por los botones de cancelar/reactivar de la app).
    _invalidar_cache_admin_tras_cambio_suscripcion()
    return jsonify({"mensaje": "Evento procesado"}), 200
