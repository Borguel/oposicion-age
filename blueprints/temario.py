"""Rutas de consulta del catálogo de oposiciones y su temario."""
from flask import Blueprint, g, jsonify

from firebase_setup import db
from auth_utils import requiere_login, obtener_oposicion_solicitada
from oposiciones import OPOSICIONES, coleccion_temario

bp = Blueprint("temario", __name__)


@bp.route("/oposiciones-disponibles", methods=["GET"])
def obtener_oposiciones_disponibles():
    return jsonify({
        "oposiciones": [
            {"id": oid, "nombre": datos["nombre"], "simulacro_oficial": datos.get("simulacro_oficial")}
            for oid, datos in OPOSICIONES.items()
        ]
    })


@bp.route("/temas-disponibles", methods=["GET"])
@requiere_login(db)
def obtener_temas_disponibles():
    oposicion = obtener_oposicion_solicitada()
    coleccion = coleccion_temario(oposicion)
    temas_disponibles = []
    bloques = db.collection(coleccion).stream()
    for bloque in bloques:
        bloque_id = bloque.id
        bloque_titulo = (bloque.to_dict() or {}).get("titulo", bloque_id)
        temas_ref = db.collection(coleccion).document(bloque_id).collection("temas").stream()
        for tema in temas_ref:
            tema_data = tema.to_dict()
            tema_id = tema.id
            titulo = tema_data.get("titulo", f"{tema_id}")
            temas_disponibles.append({
                "id": f"{bloque_id}-{tema_id}",
                "titulo": titulo,
                "bloque_id": bloque_id,
                "bloque_titulo": bloque_titulo
            })
    return jsonify({"temas": temas_disponibles, "oposicion": oposicion})


@bp.route("/progreso-usuario", methods=["GET"])
@requiere_login(db)
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
