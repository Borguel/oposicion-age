import os
import logging
import time
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_talisman import Talisman
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
from oposiciones import OPOSICIONES, coleccion_examenes_oficiales

# Inicializar Flask
app = Flask(__name__)
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
    if request.path in ("/", "/health", "/estadisticas-publicas", "/webhook-stripe", "/tareas/recordatorios-racha"):
        return
    if request.headers.get("X-API-Key") != API_SECRET_KEY:
        return jsonify({"error": "No autorizado"}), 401

# === Rutas: cada área de la app vive en su propio blueprint (blueprints/) ===
from blueprints.temario import bp as temario_bp
from blueprints.test_ia import bp as test_ia_bp
from blueprints.chat_ia import bp as chat_ia_bp
from blueprints.pdf_ia import bp as pdf_ia_bp
from blueprints.pagos import bp as pagos_bp
from blueprints.ranking import bp as ranking_bp
from blueprints.tareas_programadas import bp as tareas_programadas_bp

app.register_blueprint(temario_bp)
app.register_blueprint(test_ia_bp)
app.register_blueprint(chat_ia_bp)
app.register_blueprint(pdf_ia_bp)
app.register_blueprint(pagos_bp)
app.register_blueprint(ranking_bp)
app.register_blueprint(tareas_programadas_bp)

# Guardado y progreso (rutas_progreso.py ya registra las suyas directamente
# sobre `app`, con el mismo patrón de "función que recibe app y db").
from save_controller import guardar_test_route, guardar_esquema_route
from rutas_progreso import registrar_rutas_progreso

app.add_url_rule("/guardar-test", view_func=guardar_test_route(db), methods=["POST"])
app.add_url_rule("/guardar-esquema", view_func=guardar_esquema_route(db), methods=["POST"])
registrar_rutas_progreso(app, db)


@app.route("/", methods=["GET"])
def listar_rutas():
    rutas = [rule.rule for rule in app.url_map.iter_rules()]
    return jsonify({"rutas_disponibles": rutas})


@app.route("/health", methods=["GET"])
def estado_salud():
    """Sin autenticación a propósito: la usa el monitor externo (GitHub
    Actions, o el que sea) para comprobar que el backend responde, y de
    paso sirve de "keep-alive" en el plan gratuito de Render, que duerme
    el servicio tras un rato de inactividad."""
    try:
        next(db.collection("usuarios").limit(1).stream(), None)
        return jsonify({"estado": "ok"})
    except Exception:
        logger.exception("Fallo en /health comprobando Firestore")
        return jsonify({"estado": "error"}), 503


_cache_estadisticas_publicas = None
_CACHE_ESTADISTICAS_PUBLICAS_SEGUNDOS = 300


@app.route("/estadisticas-publicas", methods=["GET"])
def estadisticas_publicas():
    """Cifras agregadas de uso real de toda la plataforma (nunca datos de
    un usuario concreto), para una fila de "prueba social" en la home. Sin
    autenticación a propósito -- es información pública y agregada.
    Cacheada en memoria unos minutos para no lanzar dos aggregation
    queries de Firestore en cada visita a la home."""
    global _cache_estadisticas_publicas
    ahora = time.time()
    if _cache_estadisticas_publicas and ahora - _cache_estadisticas_publicas["momento"] < _CACHE_ESTADISTICAS_PUBLICAS_SEGUNDOS:
        return jsonify(_cache_estadisticas_publicas["datos"])
    try:
        total_preguntas_oficiales = sum(
            db.collection(coleccion_examenes_oficiales(op)).count().get()[0][0].value
            for op in OPOSICIONES
        )
        total_preguntas_generadas = db.collection_group("tests").sum("num_preguntas").get()[0][0].value or 0
        datos = {
            "total_preguntas_oficiales": total_preguntas_oficiales,
            "total_preguntas_generadas": int(total_preguntas_generadas),
        }
        _cache_estadisticas_publicas = {"momento": ahora, "datos": datos}
        return jsonify(datos)
    except Exception:
        logger.exception("Fallo calculando estadísticas públicas")
        return jsonify({"total_preguntas_oficiales": 0, "total_preguntas_generadas": 0})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
