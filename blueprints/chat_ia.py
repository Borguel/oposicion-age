"""Chat conversacional sobre el TEMARIO oficial (no sobre un PDF subido --
eso vive en blueprints/pdf_ia.py) y el historial de esas conversaciones."""
from flask import Blueprint, g, jsonify, request
from firebase_admin import firestore

from firebase_setup import db
from auth_utils import requiere_plan
from limites_uso import verificar_limite_uso, registrar_uso
from oposiciones import coleccion_temario
from chat_controller import responder_chat, consultar_asistente_examen

bp = Blueprint("chat_ia", __name__)


@bp.route("/chat", methods=["POST"])
@requiere_plan(db, "premium")
def chat_route():
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "chat_temario")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    data = request.get_json()
    mensaje = data.get("mensaje")
    temas = data.get("temas", [])
    chat_id = data.get("chat_id")
    respuesta, chat_id = responder_chat(
        mensaje=mensaje,
        temas=temas,
        db=db,
        usuario_id=g.uid,
        chat_id=chat_id,
        coleccion=coleccion_temario(g.oposicion)
    )
    registrar_uso(db, g.uid, "chat_temario", g.plan_actual)
    return jsonify({"respuesta": respuesta, "chat_id": chat_id})


@bp.route("/consultar-asistente-examen", methods=["POST"])
@requiere_plan(db, "premium")
def ruta_asistente_examen():
    data = request.get_json()
    mensaje = data.get("mensaje", "")
    if not mensaje:
        return jsonify({"error": "Falta el mensaje"}), 400
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "chat_temario")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    try:
        respuesta = consultar_asistente_examen(mensaje, oposicion=g.oposicion)
        registrar_uso(db, g.uid, "chat_temario", g.plan_actual)
        return jsonify({"respuesta": respuesta})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/conversaciones", methods=["GET"])
@requiere_plan(db, "premium")
def obtener_conversaciones_usuario():
    docs = db.collection("conversaciones_IA") \
             .document(g.uid) \
             .collection("conversaciones") \
             .order_by("timestamp_inicio", direction=firestore.Query.DESCENDING) \
             .stream()
    resultado = []
    for doc in docs:
        data = doc.to_dict()
        resultado.append({
            "id": doc.id,
            "titulo": data.get("titulo", "Sin título"),
            "timestamp_inicio": data.get("timestamp_inicio")
        })
    return jsonify({"conversaciones": resultado})


@bp.route("/conversacion/<conversacion_id>", methods=["GET"])
@requiere_plan(db, "premium")
def obtener_conversacion(conversacion_id):
    doc = db.collection("conversaciones_IA") \
            .document(g.uid) \
            .collection("conversaciones") \
            .document(conversacion_id) \
            .get()
    if not doc.exists:
        return jsonify({"error": "Conversación no encontrada"}), 404
    return jsonify(doc.to_dict())
