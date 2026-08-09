"""Rutas de consulta del catálogo de oposiciones y su temario."""
from flask import Blueprint, g, jsonify, request

from firebase_setup import db
from auth_utils import requiere_plan, requiere_login, obtener_oposicion_solicitada, obtener_identidad_desde_token
from oposiciones import OPOSICIONES, coleccion_temario, oposicion_valida
from utils import calcular_pesos_reales_por_bloque, tiene_preguntas_psicotecnicas, obtener_temas_navegables

bp = Blueprint("temario", __name__)


def _oposiciones_visibles_para_la_peticion():
    """IDs de OPOSICIONES que debe ver quien hace la petición.

    Sin sesión (o sesión sin ninguna oposición activada todavía): el
    catálogo público completo (AGE/GACE/Auxiliar -- todo lo que no esté
    marcado "oculta"), para poder elegir la primera -- ver
    /activar-oposicion. Las "oculta" (p. ej. METRO) NUNCA entran por aquí
    salvo que ya estén activadas, se activan solo a mano desde el panel
    admin.

    Con sesión y ya con AL MENOS una oposición pública activada
    (suscripciones.<ID>, ver activar_oposicion_usuario): solo las que el
    usuario ha activado él mismo -- ni el resto de públicas sin activar ni
    ninguna oculta que no se le haya concedido. Así cada cuenta ve solo la
    oposición (o las oposiciones) que ha elegido estudiar, no las 3 a la vez
    por defecto."""
    publicas = {oid for oid, datos in OPOSICIONES.items() if not datos.get("oculta")}
    identidad = obtener_identidad_desde_token(request)
    if not identidad:
        return publicas
    uid = identidad[0]
    doc = db.collection("usuarios").document(uid).get()
    activadas = set((doc.to_dict() or {}).get("suscripciones", {}).keys()) if doc.exists else set()
    activadas_publicas = activadas & publicas
    activadas_ocultas = activadas - publicas
    if not activadas_publicas:
        return publicas | activadas_ocultas
    return activadas_publicas | activadas_ocultas


@bp.route("/oposiciones-disponibles", methods=["GET"])
def obtener_oposiciones_disponibles():
    ids_visibles = _oposiciones_visibles_para_la_peticion()
    return jsonify({
        "oposiciones": [
            {
                "id": oid,
                "nombre": datos["nombre"],
                "simulacro_oficial": datos.get("simulacro_oficial"),
                # Si hay exámenes oficiales cargados y etiquetados con
                # tema_id para esta oposición, el frontend puede ofrecer el
                # reparto "realista" (ver utils.calcular_pesos_reales_por_bloque)
                # en Test Personalizado/Test Oficial -- si no (p. ej.
                # Auxiliar, sin exámenes cargados todavía), solo tiene
                # sentido el reparto equitativo.
                "tiene_pesos_reales": bool(calcular_pesos_reales_por_bloque(db, oid)),
                # Solo Auxiliar tiene preguntas psicotécnicas en su examen
                # oficial (ver cargar_examen_oficial_auxiliar.py) -- el
                # frontend usa esta flag para ofrecer el filtro "excluir
                # psicotécnicas" únicamente donde tiene sentido.
                "tiene_psicotecnicas": tiene_preguntas_psicotecnicas(db, oid),
            }
            for oid, datos in OPOSICIONES.items()
            if oid in ids_visibles
        ]
    })


@bp.route("/activar-oposicion", methods=["POST"])
@requiere_login(db)
def activar_oposicion():
    """Autoservicio: el propio usuario elige "quiero estudiar esta
    oposición" (p. ej. desde el selector de primeros pasos de Zona
    opositor) y eso da de alta suscripciones.<OP> con el plan gratis y
    arranca su prueba de 7 días PARA ESA OPOSICIÓN, sin que el admin tenga
    que hacer nada -- a diferencia de METRO (oculta, solo se concede a mano
    desde el panel), cualquier oposición pública puede activarse así.
    Idempotente: si ya la tenía activada, no hace nada (ver
    activar_oposicion_usuario)."""
    from registro_progreso_usuario import activar_oposicion_usuario

    data = request.get_json(silent=True) or {}
    oposicion = data.get("oposicion")
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    activar_oposicion_usuario(
        db, g.uid, oposicion,
        email=g.email, email_verificado=getattr(g, "email_verificado", True),
    )
    return jsonify({"mensaje": "Oposición activada"})


@bp.route("/temas-disponibles", methods=["GET"])
@requiere_plan(db, "basico", global_check=False)
def obtener_temas_disponibles():
    oposicion = obtener_oposicion_solicitada()
    coleccion = coleccion_temario(oposicion)
    # Bloques/temas marcados como borrador desde el panel admin
    # (publicado=false) no aparecen en la navegación normal de usuarios --
    # por defecto (sin el campo) se consideran publicados, para no ocultar
    # lo ya visible. Cacheada (ver utils.obtener_temas_navegables): antes
    # esta consulta N+1 (una lectura de "temas" por bloque) se repetía sin
    # caché en cada carga de Test Oficial/Test Personalizado.
    temas_disponibles = obtener_temas_navegables(db, coleccion)
    return jsonify({"temas": temas_disponibles, "oposicion": oposicion})


@bp.route("/progreso-usuario", methods=["GET"])
@requiere_plan(db, "basico", global_check=False)
def progreso_usuario():
    doc_user = db.collection("usuarios").document(g.uid)
    progreso = doc_user.get().to_dict()
    if not progreso:
        return jsonify({"error": "Usuario no encontrado"}), 404
    return jsonify({
        "tests_realizados": progreso.get("tests_realizados", 0),
        "puntuacion_media_test": progreso.get("puntuacion_media_test", 0),
        "ultimo_test": progreso.get("ultimo_test", {}),
        "total_aciertos": progreso.get("total_aciertos", 0),
        "esquemas_generados": progreso.get("esquemas_generados", 0)
    })


@bp.route("/avisos-oficiales", methods=["GET"])
@requiere_login(db)
def avisos_oficiales():
    """Avisos oficiales ya publicados (convocatorias, listas de admitidos,
    fechas de examen...) para la oposición pedida -- detectados por la
    vigilancia del BOE y aprobados a mano desde el panel de admin (ver
    vigilancia_boe.py); nunca llegan aquí sin ese OK previo."""
    from publicacion_estatica_boe import _oposiciones_de

    oposicion = obtener_oposicion_solicitada()
    avisos = []
    consulta = db.collection("avisos_oficiales").where("estado", "==", "publicado")
    for doc in consulta.stream():
        d = doc.to_dict() or {}
        if oposicion not in _oposiciones_de(d):
            continue
        avisos.append({
            "tipo": d.get("tipo", ""),
            "titulo": d.get("titulo", ""),
            "resumen": d.get("resumen", ""),
            "url_boe": d.get("url_boe", ""),
            "fecha_boe": d.get("fecha_boe", ""),
        })
    avisos.sort(key=lambda a: a.get("fecha_boe", ""), reverse=True)
    return jsonify({"avisos": avisos[:5]})
