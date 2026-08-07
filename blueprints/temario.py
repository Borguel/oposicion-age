"""Rutas de consulta del catálogo de oposiciones y su temario."""
from flask import Blueprint, g, jsonify, request

from firebase_setup import db
from auth_utils import requiere_plan, requiere_login, obtener_oposicion_solicitada
from oposiciones import OPOSICIONES, coleccion_temario
from utils import calcular_pesos_reales_por_bloque, tiene_preguntas_psicotecnicas, obtener_temas_navegables

bp = Blueprint("temario", __name__)


@bp.route("/oposiciones-disponibles", methods=["GET"])
def obtener_oposiciones_disponibles():
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
        ]
    })


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
