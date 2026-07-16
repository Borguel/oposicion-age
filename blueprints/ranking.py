"""Clasificación de racha de estudio: anónima y estrictamente opcional.

Solo aparecen usuarios que se han apuntado explícitamente, siempre con
un alias elegido por ellos mismos -- nunca su nombre real ni su correo.
"""
import re

from flask import Blueprint, g, jsonify, request

from firebase_setup import db
from auth_utils import requiere_plan

bp = Blueprint("ranking", __name__)

ALIAS_MIN = 3
ALIAS_MAX = 20
ALIAS_REGEX = re.compile(r"^[\w áéíóúÁÉÍÓÚñÑüÜ]+$")


def _alias_valido(alias):
    return ALIAS_MIN <= len(alias) <= ALIAS_MAX and bool(ALIAS_REGEX.match(alias))


@bp.route("/ranking/mi-estado", methods=["GET"])
@requiere_plan(db, "basico", global_check=True)
def mi_estado_ranking():
    datos = db.collection("usuarios").document(g.uid).get().to_dict() or {}
    return jsonify({
        "participa": bool(datos.get("ranking_optin")),
        "alias": datos.get("ranking_alias") or ""
    })


@bp.route("/ranking/unirse", methods=["POST"])
@requiere_plan(db, "basico", global_check=True)
def unirse_ranking():
    alias = ((request.get_json(silent=True) or {}).get("alias") or "").strip()
    if not _alias_valido(alias):
        return jsonify({"error": f"El alias debe tener entre {ALIAS_MIN} y {ALIAS_MAX} caracteres (letras, números y espacios)."}), 400
    db.collection("usuarios").document(g.uid).update({
        "ranking_optin": True,
        "ranking_alias": alias
    })
    return jsonify({"mensaje": "ok", "alias": alias})


@bp.route("/ranking/salir", methods=["POST"])
@requiere_plan(db, "basico", global_check=True)
def salir_ranking():
    db.collection("usuarios").document(g.uid).update({"ranking_optin": False})
    return jsonify({"mensaje": "ok"})


@bp.route("/ranking", methods=["GET"])
@requiere_plan(db, "basico", global_check=True)
def obtener_ranking():
    participantes = []
    for doc in db.collection("usuarios").where("ranking_optin", "==", True).stream():
        datos = doc.to_dict() or {}
        participantes.append({
            "uid": doc.id,
            "alias": datos.get("ranking_alias") or "Opositor/a",
            "racha_actual": (datos.get("racha") or {}).get("racha_actual", 0)
        })
    participantes.sort(key=lambda p: p["racha_actual"], reverse=True)

    tu_posicion = next((i + 1 for i, p in enumerate(participantes) if p["uid"] == g.uid), None)
    tu_racha = next((p["racha_actual"] for p in participantes if p["uid"] == g.uid), None)
    top = [
        {"alias": p["alias"], "racha_actual": p["racha_actual"], "tu": p["uid"] == g.uid}
        for p in participantes[:50]
    ]

    return jsonify({
        "ranking": top,
        "total_participantes": len(participantes),
        "tu_posicion": tu_posicion,
        "tu_racha": tu_racha
    })
