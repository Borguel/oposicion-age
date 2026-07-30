"""Constantes y resolución de plan efectivo de un usuario -- compartido
entre auth_utils.py (verificación de acceso en cada ruta), registro_progreso_usuario.py
(/mi-perfil) y blueprints/admin.py (ficha de usuario), para que la prueba
gratuita de 7 días se calcule en un único sitio y no pueda quedar
desincronizada entre ellos.

Módulo hoja a propósito (solo depende de datetime): auth_utils.py ya
importa de registro_progreso_usuario.py, así que si este cálculo viviera
en auth_utils.py, registro_progreso_usuario.py no podría importarlo sin
crear un ciclo."""
from datetime import datetime

ORDEN_PLANES = {"gratis": 0, "basico": 1, "premium": 2}
ESTADOS_SUSCRIPCION_ACTIVA = {"active", "trialing"}
DURACION_PRUEBA_DIAS = 7


def prueba_activa(datos_usuario):
    """¿Sigue dentro de los 7 días de prueba gratuita? `datos_usuario` es el
    dict completo del documento usuarios/{uid} (necesita el campo
    prueba_fin, fijado una única vez al crear la cuenta)."""
    fin = (datos_usuario or {}).get("prueba_fin")
    if not fin:
        return False
    try:
        return datetime.utcnow() < datetime.fromisoformat(fin)
    except (TypeError, ValueError):
        return False


def mejor_plan(suscripciones):
    """El plan más alto entre todas las oposiciones activas del usuario."""
    mejor = "gratis"
    mejor_sub = {}
    for datos in (suscripciones or {}).values():
        plan = datos.get("plan", "gratis")
        if ORDEN_PLANES.get(plan, 0) > ORDEN_PLANES.get(mejor, 0):
            mejor = plan
            mejor_sub = datos
    return mejor, mejor_sub


def tiene_plan_de_pago_activo(datos_usuario):
    """¿Es ya cliente de pago en ALGUNA oposición (suscripción real, no la
    prueba gratuita)? Se usa para no seguir tratando como "usuario nuevo en
    periodo de prueba" a quien ya paga por otra oposición: no debe ver ni el
    aviso de cuenta atrás de la prueba ni el de "tu prueba ha terminado" al
    mirar una oposición que todavía no ha contratado."""
    suscripciones = (datos_usuario or {}).get("suscripciones", {}) or {}
    return any(
        datos.get("plan", "gratis") != "gratis" and datos.get("subscription_status") in ESTADOS_SUSCRIPCION_ACTIVA
        for datos in suscripciones.values()
    )


def resolver_plan_efectivo(datos_usuario, oposicion=None):
    """Plan real que debe aplicarse a un usuario: su mejor plan de pago
    (global, o el de una oposición concreta si se pasa `oposicion`) o, si
    ese plan es menor que premium y todavía está dentro de la prueba
    gratuita de 7 días, "premium" con subscription_status "trialing" (para
    que pase igual la comprobación de suscripción activa en auth_utils).

    No "degrada" nunca a quien ya pagó premium y sigue dentro de la
    ventana de prueba: la prueba solo sirve para SUBIR el plan efectivo,
    nunca para bajarlo.

    La prueba tampoco se aplica a quien YA es cliente de pago en otra
    oposición (tiene_plan_de_pago_activo): esa prueba de 7 días es para
    captar cuentas nuevas que todavía no han pagado nada, no un regalo
    adicional cada vez que alguien que ya paga explora una oposición más --
    para esa persona, no tener plan aquí debe verse como "actívalo cuando
    quieras", nunca como "tu prueba ha terminado"."""
    suscripciones = (datos_usuario or {}).get("suscripciones", {}) or {}
    if oposicion:
        sub = suscripciones.get(oposicion, {}) or {}
        plan = sub.get("plan", "gratis")
    else:
        plan, sub = mejor_plan(suscripciones)

    if (
        ORDEN_PLANES.get(plan, 0) < ORDEN_PLANES["premium"]
        and prueba_activa(datos_usuario)
        and not tiene_plan_de_pago_activo(datos_usuario)
    ):
        return "premium", {**sub, "subscription_status": "trialing"}
    return plan, sub
