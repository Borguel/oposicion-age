from functools import wraps

from firebase_admin import auth as firebase_auth
from flask import g, jsonify, request

from registro_progreso_usuario import inicializar_estadisticas_usuario

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


def requiere_plan(db, minimo):
    def decorador(f):
        @wraps(f)
        @requiere_login(db)
        def envoltura(*args, **kwargs):
            doc = db.collection("usuarios").document(g.uid).get()
            datos = doc.to_dict() or {}
            plan_actual = datos.get("plan", "gratis")
            if ORDEN_PLANES.get(plan_actual, 0) < ORDEN_PLANES.get(minimo, 0):
                return jsonify({"error": "Requiere plan superior", "plan_actual": plan_actual, "plan_requerido": minimo}), 403
            if minimo != "gratis" and datos.get("subscription_status") not in ESTADOS_SUSCRIPCION_ACTIVA:
                return jsonify({"error": "Suscripción inactiva", "plan_actual": plan_actual, "plan_requerido": minimo}), 403
            return f(*args, **kwargs)
        return envoltura
    return decorador
