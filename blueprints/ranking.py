"""Clasificación de racha de estudio: anónima y estrictamente opcional.

Solo aparecen usuarios que se han apuntado explícitamente, siempre con
un alias elegido por ellos mismos -- nunca su nombre real ni su correo.
"""
import re

from flask import Blueprint, g, jsonify, request

from firebase_setup import db
from auth_utils import requiere_plan
from utils import _desde_cache_o_calcular, invalidar_cache

bp = Blueprint("ranking", __name__)

ALIAS_MIN = 3
ALIAS_MAX = 20
ALIAS_REGEX = re.compile(r"^[\w áéíóúÁÉÍÓÚñÑüÜ]+$")

# TTL corto (no los 180s del panel admin): a diferencia de un dashboard
# interno, aquí el "desfase" lo nota directamente el propio usuario (su
# racha no sube en el ranking justo después de hacer un test) -- se prioriza
# que se note poco sobre exprimir la caché al máximo, aunque siga evitando
# el barrido completo de la colección "usuarios" en cada carga de la página.
_TTL_CACHE_RANKING_SEGUNDOS = 60


def _participantes_ranking():
    """Lista de {uid, alias, racha_actual} de todos los apuntados al
    ranking, ordenada de mayor a menor racha -- la parte cara (recorre TODA
    la colección "usuarios"), cacheada aparte de tu_posicion/tu_racha/top
    (que son por usuario y se recalculan en cada petición sobre esta misma
    lista, sin volver a tocar Firestore).

    Incluye también los participantes de demostración (colección aparte
    "ranking_demo", ver blueprints/admin.py -- se guardan fuera de
    "usuarios" a propósito: los primeros intentos los guardaban como
    documentos sueltos en "usuarios", y eso inflaba el número de usuarios
    reales que ve el admin en su propio panel. "uid" lleva el prefijo
    "demo_" para que nunca pueda coincidir con un uid real de Firebase Auth
    (así "tu_posicion"/"tu_racha" más abajo nunca confunden a un
    participante de demostración con el usuario que consulta)."""
    def _calcular():
        participantes = []
        for doc in db.collection("usuarios").where("ranking_optin", "==", True).stream():
            datos = doc.to_dict() or {}
            participantes.append({
                "uid": doc.id,
                "alias": datos.get("ranking_alias") or "Opositor/a",
                "racha_actual": (datos.get("racha") or {}).get("racha_actual", 0)
            })
        for doc in db.collection("ranking_demo").stream():
            datos = doc.to_dict() or {}
            participantes.append({
                "uid": f"demo_{doc.id}",
                "alias": datos.get("alias") or "Opositor/a",
                "racha_actual": datos.get("racha_actual", 0)
            })
        participantes.sort(key=lambda p: p["racha_actual"], reverse=True)
        return participantes
    return _desde_cache_o_calcular(("ranking_participantes",), _calcular, ttl_segundos=_TTL_CACHE_RANKING_SEGUNDOS)


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
    # Sin esto, quien se acaba de apuntar no se vería a sí mismo en el
    # ranking hasta que venciera el TTL -- peor primera impresión posible
    # justo para la acción que se acaba de pedir.
    invalidar_cache(("ranking_participantes",))
    return jsonify({"mensaje": "ok", "alias": alias})


@bp.route("/ranking/salir", methods=["POST"])
@requiere_plan(db, "basico", global_check=True)
def salir_ranking():
    db.collection("usuarios").document(g.uid).update({"ranking_optin": False})
    invalidar_cache(("ranking_participantes",))
    return jsonify({"mensaje": "ok"})


@bp.route("/ranking", methods=["GET"])
@requiere_plan(db, "basico", global_check=True)
def obtener_ranking():
    participantes = _participantes_ranking()

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
