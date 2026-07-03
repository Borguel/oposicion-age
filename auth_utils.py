from functools import wraps

from firebase_admin import auth as firebase_auth
from flask import g, jsonify, request

from registro_progreso_usuario import inicializar_estadisticas_usuario
from oposiciones import OPOSICION_POR_DEFECTO, oposicion_valida

ORDEN_PLANES = {"gratis": 0, "basico": 1, "premium": 2}
ESTADOS_SUSCRIPCION_ACTIVA = {"active", "trialing"}


def obtener_uid_desde_token(req):
    """Verifica el Firebase ID token del header Authorization: Bearer <token>.
    Devuelve el uid verificado o None si falta o es inválido."""
    header = req.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[len("Bearer "):].strip()
    if not token:
        return None
    try:
        decoded = firebase_auth.verify_id_token(token)
    except Exception:
        return None
    return decoded.get("uid"), decoded.get("email")


def obtener_oposicion_solicitada(default=OPOSICION_POR_DEFECTO):
    """Lee sobre qué oposición pide contenido la petición actual (query string
    ?oposicion=, cuerpo JSON o formulario). Si no viene ninguna o no es una
    oposición conocida, se usa la de por defecto (AGE) para no romper
    llamadas de un frontend todavía no actualizado."""
    valor = request.args.get("oposicion")
    if not valor and request.is_json:
        valor = (request.get_json(silent=True) or {}).get("oposicion")
    if not valor and request.form:
        valor = request.form.get("oposicion")
    return valor if valor and oposicion_valida(valor) else default


def requiere_login(db):
    def decorador(f):
        @wraps(f)
        def envoltura(*args, **kwargs):
            resultado = obtener_uid_desde_token(request)
            if not resultado or not resultado[0]:
                return jsonify({"error": "No autenticado"}), 401
            uid, email = resultado
            inicializar_estadisticas_usuario(db, uid, email=email)
            g.uid = uid
            g.email = email
            return f(*args, **kwargs)
        return envoltura
    return decorador


def _mejor_plan(suscripciones):
    """El plan más alto entre todas las oposiciones activas del usuario."""
    mejor = "gratis"
    mejor_sub = {}
    for datos in (suscripciones or {}).values():
        plan = datos.get("plan", "gratis")
        if ORDEN_PLANES.get(plan, 0) > ORDEN_PLANES.get(mejor, 0):
            mejor = plan
            mejor_sub = datos
    return mejor, mejor_sub


def requiere_plan(db, minimo, global_check=False):
    """Exige que el usuario tenga, como mínimo, el plan `minimo`.

    Por defecto (global_check=False) se comprueba sobre la oposición
    concreta que pide la petición (?oposicion= / body.oposicion), porque la
    herramienta lee el temario oficial de esa oposición (test, esquema,
    chat con temario...). Deja la oposición resuelta en g.oposicion para que
    la propia ruta no tenga que volver a calcularla.

    Con global_check=True (herramientas que no dependen de ningún temario
    oficial, como resumir un PDF que sube el propio usuario) basta con que
    tenga ese plan en CUALQUIERA de sus oposiciones contratadas."""
    def decorador(f):
        @wraps(f)
        @requiere_login(db)
        def envoltura(*args, **kwargs):
            doc = db.collection("usuarios").document(g.uid).get()
            datos = doc.to_dict() or {}
            suscripciones = datos.get("suscripciones", {}) or {}

            if global_check:
                plan_actual, sub = _mejor_plan(suscripciones)
            else:
                g.oposicion = obtener_oposicion_solicitada()
                sub = suscripciones.get(g.oposicion, {}) or {}
                plan_actual = sub.get("plan", "gratis")

            if ORDEN_PLANES.get(plan_actual, 0) < ORDEN_PLANES.get(minimo, 0):
                return jsonify({"error": "Requiere plan superior", "plan_actual": plan_actual, "plan_requerido": minimo}), 403
            if minimo != "gratis" and sub.get("subscription_status") not in ESTADOS_SUSCRIPCION_ACTIVA:
                return jsonify({"error": "Suscripción inactiva", "plan_actual": plan_actual, "plan_requerido": minimo}), 403
            return f(*args, **kwargs)
        return envoltura
    return decorador
