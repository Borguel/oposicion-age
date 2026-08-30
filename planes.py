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


def prueba_activa(sub_oposicion):
    """¿Sigue dentro de los 7 días de prueba gratuita DE UNA OPOSICIÓN
    CONCRETA? `sub_oposicion` es la entrada suscripciones.<OP> de esa
    oposición (o {}/None) -- cada oposición arranca su propia prueba al
    activarse (ver registro_progreso_usuario.activar_oposicion_usuario), no
    hay una única prueba compartida por toda la cuenta."""
    fin = (sub_oposicion or {}).get("prueba_fin")
    if not fin:
        return False
    try:
        return datetime.utcnow() < datetime.fromisoformat(fin)
    except (TypeError, ValueError):
        return False


def acceso_temporal_activo(sub_oposicion):
    """¿Sigue vigente un acceso temporal concedido A MANO por un admin
    (panel "Planes del cliente"), con el nivel de plan que se eligió al
    concederlo (básico o premium)? Deliberadamente NO es lo mismo que
    prueba_activa/prueba_fin -- prueba_fin es la prueba gratuita real que
    arranca sola al activar una oposición y dispara el correo de "tu
    prueba está a punto de terminar" (blueprints/tareas_programadas.py);
    reutilizarla para un regalo de soporte enviaría ese correo por algo
    que no es una prueba real. `acceso_temporal` vive en su propio campo,
    independiente, para que un admin pueda regalar acceso sin arrastrar
    ese efecto secundario.

    Devuelve (activo, plan) -- plan es None si no hay ninguno vigente."""
    temporal = (sub_oposicion or {}).get("acceso_temporal") or {}
    hasta = temporal.get("hasta")
    plan = temporal.get("plan")
    if not hasta or not plan:
        return False, None
    try:
        if datetime.utcnow() < datetime.fromisoformat(hasta):
            return True, plan
    except (TypeError, ValueError):
        pass
    return False, None


def resumen_prueba_cuenta(datos_usuario):
    """(en_prueba, prueba_fin) agregados a nivel de CUENTA, solo para vistas
    globales que no pueden anclarse a una oposición concreta (panel admin:
    lista y ficha de usuarios). "en_prueba" es True si CUALQUIER oposición
    activada por el usuario sigue dentro de su ventana de prueba, y
    prueba_fin es la fecha de fin más lejana entre esas -- no un campo real
    guardado en Firestore, se calcula al vuelo a partir de suscripciones."""
    fines_activos = [
        sub.get("prueba_fin")
        for sub in ((datos_usuario or {}).get("suscripciones", {}) or {}).values()
        if prueba_activa(sub)
    ]
    if not fines_activos:
        return False, None
    return True, max(fines_activos)


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
    (el de una oposición concreta si se pasa `oposicion`, o el mejor entre
    TODAS sus oposiciones activadas si no) o, si ese plan es menor que
    premium y esa oposición todavía está dentro de sus propios 7 días de
    prueba gratuita, "premium" con subscription_status "trialing" (para que
    pase igual la comprobación de suscripción activa en auth_utils).

    La prueba es POR OPOSICIÓN (ver prueba_activa): cada una arranca la
    suya al activarse (registro_progreso_usuario.activar_oposicion_usuario),
    así que ya no hace falta comprobar aparte si el usuario paga en otra
    oposición distinta -- una oposición sin activar sencillamente no tiene
    prueba_fin propio, y no se ve empujada por la de ninguna otra.

    No "degrada" nunca a quien ya pagó premium y sigue dentro de la
    ventana de prueba: la prueba solo sirve para SUBIR el plan efectivo,
    nunca para bajarlo."""
    suscripciones = (datos_usuario or {}).get("suscripciones", {}) or {}

    def _con_prueba(plan, sub):
        candidatos = [(plan, sub)]
        if prueba_activa(sub):
            candidatos.append(("premium", {**sub, "subscription_status": "trialing"}))
        activo, plan_temporal = acceso_temporal_activo(sub)
        if activo:
            candidatos.append((plan_temporal, {**sub, "subscription_status": "trialing"}))
        return max(candidatos, key=lambda c: ORDEN_PLANES.get(c[0], 0))

    if oposicion:
        sub = suscripciones.get(oposicion, {}) or {}
        return _con_prueba(sub.get("plan", "gratis"), sub)

    # Sin oposición concreta (herramientas globales, p. ej. subir un PDF
    # propio): el mejor plan efectivo entre todas las oposiciones activadas,
    # resolviendo la prueba de cada una por separado antes de comparar.
    mejor, mejor_sub = "gratis", {}
    for sub in suscripciones.values():
        plan, sub_resuelta = _con_prueba(sub.get("plan", "gratis"), sub)
        if ORDEN_PLANES.get(plan, 0) > ORDEN_PLANES.get(mejor, 0):
            mejor, mejor_sub = plan, sub_resuelta
    return mejor, mejor_sub
