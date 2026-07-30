import logging
import time
from functools import wraps

from firebase_admin import auth as firebase_auth
from flask import g, jsonify, request

from registro_progreso_usuario import inicializar_estadisticas_usuario
from oposiciones import OPOSICION_POR_DEFECTO, oposicion_valida
from planes import ORDEN_PLANES, ESTADOS_SUSCRIPCION_ACTIVA, resolver_plan_efectivo
from planes import mejor_plan as _mejor_plan  # alias: admin.py y tests ya importan este nombre

logger = logging.getLogger(__name__)


def _verificar_id_token(token, log_prefix=""):
    """verify_id_token() con un reintento ante fallos de red al obtener los
    certificados públicos de Google (CertificateFetchError) -- confirmado en
    producción: un corte de conexión saliente de un par de segundos entre
    Render y googleapis.com hacía fallar TODAS las peticiones autenticadas
    de golpe ("No autenticado" para cualquiera, incluido un administrador
    con la cuenta perfectamente al día), y se resolvía solo en la siguiente
    petición. Un solo reintento con una pausa breve absorbe ese tipo de
    corte puntual sin esconder un token realmente inválido/caducado (esos
    fallan igual en el reintento) ni añadir demasiada latencia al caso normal."""
    intentos = (0, 0.4)
    ultimo_exc = None
    for espera in intentos:
        if espera:
            time.sleep(espera)
        try:
            return firebase_auth.verify_id_token(token, check_revoked=True)
        except firebase_auth.CertificateFetchError as exc:
            ultimo_exc = exc
            continue
        except Exception as exc:
            # Sin este log no había forma de distinguir un token realmente
            # inválido/caducado de, por ejemplo, un fallo transitorio de red
            # al comprobar la revocación contra Firebase -- ambos acababan
            # en el mismo "No autenticado" opaco para quien lo sufre y para
            # quien lo investiga después.
            logger.warning("%sFallo al verificar ID token: %s: %s", log_prefix, type(exc).__name__, exc)
            return None
    logger.warning("%sFallo al verificar ID token tras reintento: %s: %s", log_prefix, type(ultimo_exc).__name__, ultimo_exc)
    return None


def _decodificar_token_peticion(req):
    """Header Authorization: Bearer <token> ya verificado -- el dict crudo
    que devuelve Firebase (o None si falta la cabecera o el token no es
    válido), para que cada llamador saque los claims que necesite sin
    volver a verificar el token contra Firebase."""
    header = req.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[len("Bearer "):].strip()
    if not token:
        return None
    return _verificar_id_token(token)


def obtener_identidad_desde_token(req):
    """Verifica el Firebase ID token del header Authorization: Bearer <token>.
    Devuelve (uid, email, es_admin) o None si falta o es inválido."""
    decoded = _decodificar_token_peticion(req)
    if decoded is None:
        return None
    return decoded.get("uid"), decoded.get("email"), decoded.get("admin") is True


def obtener_uid_desde_token(req):
    """Compatibilidad: (uid, email) verificados o None."""
    ident = obtener_identidad_desde_token(req)
    return (ident[0], ident[1]) if ident else None


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
            decoded = _decodificar_token_peticion(request)
            if not decoded or not decoded.get("uid"):
                return jsonify({"error": "No autenticado"}), 401
            uid = decoded.get("uid")
            email = decoded.get("email")
            es_admin = decoded.get("admin") is True
            # email_verified: True de fábrica para Google (ya verifica la
            # dirección), el valor real del token para email+contraseña --
            # inicializar_estadisticas_usuario decide con esto (y con si el
            # dominio es de correo desechable) si la prueba gratuita de 7
            # días arranca ya o se queda pendiente de confirmar el correo.
            email_verificado = bool(decoded.get("email_verified"))
            inicializar_estadisticas_usuario(db, uid, email=email, email_verificado=email_verificado)
            g.uid = uid
            g.email = email
            g.es_admin = es_admin
            return f(*args, **kwargs)
        return envoltura
    return decorador


def requiere_admin(f):
    """Exige que quien llama sea administrador (custom claim admin:true en su
    token de Firebase). A diferencia de requiere_login/requiere_plan NO es una
    factoría (no necesita db): solo verifica el token y el claim. Devuelve 403
    -- no 401/redirección-- si el token es válido pero no es admin, porque
    puede estar perfectamente logueado, solo que sin permisos de admin.

    IMPORTANTE: es la ÚNICA barrera real del panel admin. El frontend solo
    oculta el enlace; toda ruta /admin/* debe llevar este decorador."""
    @wraps(f)
    def envoltura(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify({"error": "No autenticado"}), 401
        token = header[len("Bearer "):].strip()
        decoded = _verificar_id_token(token, log_prefix="requiere_admin: ")
        if decoded is None:
            return jsonify({"error": "No autenticado"}), 401
        if decoded.get("admin") is not True:
            return jsonify({"error": "Se requieren permisos de administrador"}), 403
        g.uid = decoded.get("uid")
        g.email = decoded.get("email")
        return f(*args, **kwargs)
    return envoltura


# Permisos granulares del panel. 'admin' (custom claim admin:true) es el
# super-admin y los tiene todos implícitamente. El resto se conceden sueltos
# vía el custom claim permisos:[...] para dar acceso parcial (p. ej. un
# moderador solo con 'reportes').
PERMISOS_VALIDOS = ("temario", "reportes", "usuarios")


def _decodificar_token_admin():
    """Verifica el token Bearer y devuelve (decoded, None) o (None, respuesta
    de error) para las rutas del panel. Deja el resultado listo para que los
    decoradores del panel no repitan la verificación."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None, (jsonify({"error": "No autenticado"}), 401)
    token = header[len("Bearer "):].strip()
    decoded = _verificar_id_token(token, log_prefix="Panel admin: ")
    if decoded is None:
        return None, (jsonify({"error": "No autenticado"}), 401)
    return decoded, None


def _permisos_de(decoded):
    """Conjunto de permisos efectivos del token. El super-admin los tiene
    todos."""
    if decoded.get("admin") is True:
        return set(PERMISOS_VALIDOS)
    brutos = decoded.get("permisos") or []
    if not isinstance(brutos, list):
        return set()
    return {p for p in brutos if p in PERMISOS_VALIDOS}


def requiere_permiso(*permisos):
    """Exige que quien llama tenga AL MENOS UNO de los permisos indicados (o
    sea super-admin). Si se llama con varios, equivale a 'cualquier miembro
    del equipo con alguno de estos permisos'. Deja en g: uid, email,
    es_admin y permisos (set)."""
    requeridos = set(permisos)

    def decorador(f):
        @wraps(f)
        def envoltura(*args, **kwargs):
            decoded, error = _decodificar_token_admin()
            if error:
                return error
            efectivos = _permisos_de(decoded)
            if not (requeridos & efectivos):
                return jsonify({"error": "No tienes permiso para esta acción"}), 403
            g.uid = decoded.get("uid")
            g.email = decoded.get("email")
            g.es_admin = decoded.get("admin") is True
            g.permisos = efectivos
            return f(*args, **kwargs)
        return envoltura
    return decorador


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

            # resolver_plan_efectivo ya tiene en cuenta la prueba gratuita de
            # 7 días (planes.py): si el usuario no tiene un plan de pago de
            # rango suficiente pero sigue dentro de la ventana de prueba, se
            # le trata como premium.
            if global_check:
                plan_actual, sub = resolver_plan_efectivo(datos)
            else:
                g.oposicion = obtener_oposicion_solicitada()
                plan_actual, sub = resolver_plan_efectivo(datos, oposicion=g.oposicion)

            # Los administradores (custom claim admin:true) tienen acceso
            # completo a todas las herramientas sin necesidad de una
            # suscripción de pago, para poder probar y dar soporte. Se les
            # trata como premium activo, saltando las dos comprobaciones de
            # abajo, pero manteniendo g.oposicion ya resuelta arriba.
            if getattr(g, "es_admin", False):
                g.plan_actual = "premium"
                return f(*args, **kwargs)

            g.plan_actual = plan_actual

            if ORDEN_PLANES.get(plan_actual, 0) < ORDEN_PLANES.get(minimo, 0):
                return jsonify({"error": "Requiere plan superior", "plan_actual": plan_actual, "plan_requerido": minimo}), 403
            if minimo != "gratis" and sub.get("subscription_status") not in ESTADOS_SUSCRIPCION_ACTIVA:
                return jsonify({"error": "Suscripción inactiva", "plan_actual": plan_actual, "plan_requerido": minimo}), 403
            return f(*args, **kwargs)
        return envoltura
    return decorador
