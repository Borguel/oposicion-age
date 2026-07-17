import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

# Logging estructurado (con nivel y hora) en vez de print(): así se puede
# filtrar por gravedad y, sobre todo, se ve en los logs de Render con
# marca de tiempo real en vez de perderse entre el resto de la salida.
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()

# Sentry es opcional: sin SENTRY_DSN esto no hace nada (ni falla), así que
# no bloquea el despliegue hasta que se cree una cuenta y se configure la
# variable. Con DSN, cualquier excepción no controlada (y los logger.error/
# logger.exception de cada módulo) llegan también a Sentry, no solo a los logs.
sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[FlaskIntegration(), LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)],
        traces_sample_rate=0.0,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
    )
    logger.info("Sentry activado")
else:
    logger.info("SENTRY_DSN no configurada: Sentry desactivado (los errores solo van a los logs)")

logger.info("Clave OpenAI: %s", "configurada" if os.getenv("OPENAI_API_KEY") else "no configurada")
logger.info("Clave DeepSeek: %s", "configurada" if os.getenv("DEEPSEEK_API_KEY") else "no configurada")

# db se inicializa en firebase_setup.py (import ahí arriba de todo, antes de
# que ningún blueprint lo necesite).
from firebase_setup import db

# Inicializar Flask
app = Flask(__name__)

# Render sirve la app detrás de su propio proxy inverso: sin esto,
# request.remote_addr (y por tanto la clave del rate-limiter por IP) sería
# siempre la IP interna del proxy, no la del cliente real -- todas las
# peticiones compartirían un único cupo y el límite no serviría para frenar a
# un solo abusador. x_for=1 = confiar en un único proxy por delante (el de
# Render), leyendo la IP real de la primera entrada de X-Forwarded-For.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
cors_origins_env = os.getenv("CORS_ORIGINS", "")
cors_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
if not cors_origins:
    cors_origins = ["http://localhost:8080", "http://127.0.0.1:8080"]
CORS(app, origins=cors_origins)
logger.info("CORS activado para: %s", cors_origins)

# Cabeceras de seguridad para las respuestas de la API (el frontend estático
# no pasa por Flask -- sus cabeceras equivalentes, incluida la CSP, se
# configuran en render.yaml). force_https=False porque Render ya sirve todo
# por HTTPS en el borde y forzar la redirección dentro de la propia app
# puede acabar en bucle si el proxy le habla por HTTP puertas adentro.
Talisman(
    app,
    force_https=False,
    content_security_policy={"default-src": "'none'"},
    referrer_policy="strict-origin-when-cross-origin",
    frame_options="DENY",
)

# Límite de peticiones por IP para tráfico que no pasa por el control de
# cuota de IA de limites_uso.py (que solo cubre a usuarios ya logueados):
# sobre todo /health, que no exige autenticación y hace una lectura real a
# Firestore en cada llamada. storage_uri="memory://" porque Render (plan
# gratuito) corre un único proceso -- no hace falta un backend compartido
# como Redis para que el límite sea efectivo.
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per hour"],
    storage_uri="memory://",
    # Desactivado en tests (ver conftest.py): con cientos de peticiones de
    # test client en una misma sesión de pytest, todas "desde la misma IP",
    # se dispararía el límite real y los tests empezarían a fallar por un
    # 429 que no tiene nada que ver con lo que cada test comprueba.
    enabled=os.getenv("RATELIMIT_ENABLED", "true").lower() != "false",
)

# Tamaño máximo de subida (20 MB): un PDF de exámenes normal pesa unos pocos
# MB incluso con muchas páginas, así que esto solo frena subidas anómalas
# (ficheros gigantes) antes de que lleguen a ocupar memoria del servidor.
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024


@app.errorhandler(413)
def fichero_demasiado_grande(_error):
    return jsonify({"error": "El archivo es demasiado grande (máximo 20 MB)."}), 413

# Protección por API key: se activa automáticamente en cuanto se defina
# API_SECRET_KEY en el entorno. Mientras no exista, el comportamiento no
# cambia respecto a antes (rutas abiertas), para no romper el despliegue
# actual hasta que el frontend envíe la cabecera X-API-Key.
API_SECRET_KEY = os.getenv("API_SECRET_KEY")
if API_SECRET_KEY:
    logger.info("Protección por API key activada")
else:
    logger.warning("API_SECRET_KEY no configurada: las rutas quedan abiertas sin autenticación")

@app.before_request
def verificar_api_key():
    if not API_SECRET_KEY:
        return
    if request.method == "OPTIONS":
        return
    if request.path in ("/", "/health", "/webhook-stripe", "/tareas/recordatorios-racha", "/recuperar-contrasena"):
        return
    if request.headers.get("X-API-Key") != API_SECRET_KEY:
        return jsonify({"error": "No autorizado"}), 401


@app.teardown_request
def _volcar_coste_ia(_exc=None):
    # Al terminar cada petición, vuelca a Firestore el consumo de tokens de
    # DeepSeek acumulado durante ella (ver coste_ia.py). Best-effort: nunca
    # afecta a la respuesta ya enviada.
    from coste_ia import flush_coste
    flush_coste(db)

# === Rutas: cada área de la app vive en su propio blueprint (blueprints/) ===
from blueprints.temario import bp as temario_bp
from blueprints.test_ia import bp as test_ia_bp
from blueprints.tu_tutor import bp as tu_tutor_bp
from blueprints.pdf_ia import bp as pdf_ia_bp
from blueprints.pagos import bp as pagos_bp
from blueprints.ranking import bp as ranking_bp
from blueprints.tareas_programadas import bp as tareas_programadas_bp
from blueprints.admin import bp as admin_bp
from blueprints.auth_publico import bp as auth_publico_bp

app.register_blueprint(temario_bp)
app.register_blueprint(test_ia_bp)
app.register_blueprint(tu_tutor_bp)
app.register_blueprint(pdf_ia_bp)
app.register_blueprint(pagos_bp)
app.register_blueprint(ranking_bp)
app.register_blueprint(tareas_programadas_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(auth_publico_bp)

# /recuperar-contrasena es pública (nadie ha iniciado sesión todavía) y
# siempre responde igual exista o no el correo, así que el único freno ante
# un abuso (spam de resets, sondear correos por tiempos de respuesta) es un
# límite de peticiones más estricto que el general de la app. Se aplica a
# todo el blueprint (incluida /enviar-verificacion-email, que sí exige
# sesión) para que reenviar el correo de verificación no pueda usarse para
# bombardear una bandeja ajena tampoco.
limiter.limit("8 per hour")(auth_publico_bp)

# Guardado y progreso (rutas_progreso.py ya registra las suyas directamente
# sobre `app`, con el mismo patrón de "función que recibe app y db").
from save_controller import guardar_test_route, guardar_esquema_route
from rutas_progreso import registrar_rutas_progreso

app.add_url_rule("/guardar-test", view_func=guardar_test_route(db), methods=["POST"])
app.add_url_rule("/guardar-esquema", view_func=guardar_esquema_route(db), methods=["POST"])
registrar_rutas_progreso(app, db)


@app.route("/", methods=["GET"])
def raiz():
    # No se expone la lista completa de rutas al público: era información
    # innecesaria que le daba a cualquiera el mapa entero de la API. El
    # listado solo se devuelve a quien presente la API key (útil para
    # depurar), y si no hay API key configurada se responde un OK escueto.
    if API_SECRET_KEY and request.headers.get("X-API-Key") == API_SECRET_KEY:
        rutas = [rule.rule for rule in app.url_map.iter_rules()]
        return jsonify({"rutas_disponibles": rutas})
    return jsonify({"estado": "ok", "servicio": "oposicion-age-api"})


_VARIABLES_CRITICAS = [
    "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
    "DEEPSEEK_API_KEY", "BREVO_API_KEY",
]


@app.route("/health", methods=["GET"])
@limiter.limit("30 per minute")
def estado_salud():
    """Sin autenticación a propósito: la usa el monitor externo (GitHub
    Actions, o el que sea) para comprobar que el backend responde, y de
    paso sirve de "keep-alive" en el plan gratuito de Render, que duerme
    el servicio tras un rato de inactividad.

    Además de comprobar Firestore con una lectura real, comprueba que las
    variables de entorno de Stripe/DeepSeek/Brevo están configuradas
    -- SIN hacer ninguna llamada de red real a esos servicios (más lento,
    más caro en cada ping, y un fallo transitorio ajeno marcaría el
    backend entero como "unhealthy" sin que lo esté). El caso real que
    esto detecta es una variable de entorno que se quedó sin rellenar
    tras un redeploy, no una caída puntual de un proveedor externo.

    La lectura de Firestore lleva timeout=10: sin él, si la conexión se
    queda colgada en vez de fallar rápido (p. ej. al probar sin el proxy
    de salida con IP estática, ver firebase_setup.py), un solo hilo
    atascado podía dejar sin respuesta a TODA la web, no solo a esta
    ruta -- ver también `threaded=True` en app.run() más abajo."""
    faltantes = [var for var in _VARIABLES_CRITICAS if not os.getenv(var)]
    try:
        next(db.collection("usuarios").limit(1).stream(timeout=10), None)
    except Exception:
        logger.exception("Fallo en /health comprobando Firestore")
        return jsonify({"estado": "error", "firestore": "error", "variables_faltantes": faltantes}), 503
    if faltantes:
        logger.warning("/health: variables de entorno sin configurar: %s", faltantes)
        return jsonify({"estado": "error", "firestore": "ok", "variables_faltantes": faltantes}), 503
    return jsonify({"estado": "ok"})


if __name__ == "__main__":
    # threaded=True: sin esto, el servidor de desarrollo de Flask es de un
    # solo hilo -- una sola petición que se quede colgada (p. ej. una
    # conexión a Firestore sin proxy que no falla rápido, ver /health más
    # arriba) bloquea TODA la web para todo el mundo, no solo esa ruta.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
