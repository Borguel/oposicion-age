"""Tu Tutor: chat conversacional unificado (antes eran dos herramientas
separadas -- Chat IA, con RAG real sobre el temario, y Asistente Premium,
sin RAG -- fusionadas en una sola ruta que decide por mensaje qué hace
falta, ver chat_controller.responder_tutor) y el historial de esas
conversaciones."""
import json

from flask import Blueprint, Response, g, jsonify, request, stream_with_context
from firebase_admin import firestore

from firebase_setup import db
from auth_utils import requiere_plan
from limites_uso import verificar_limite_uso, registrar_uso, devolver_uso
from oposiciones import coleccion_temario
from chat_controller import responder_tutor, responder_tutor_stream

bp = Blueprint("tu_tutor", __name__)

_ERROR_DEEPSEEK = (
    "El tutor ha tenido un problema técnico al generar la respuesta. "
    "Vuelve a intentarlo en unos segundos."
)


@bp.route("/tu-tutor", methods=["POST"])
@requiere_plan(db, "premium")
def tu_tutor_route():
    data = request.get_json()
    mensaje = data.get("mensaje")
    if not mensaje:
        return jsonify({"error": "Falta el mensaje"}), 400
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "chat_temario")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    chat_id = data.get("chat_id")
    respuesta, chat_id, _usar_rag = responder_tutor(
        mensaje=mensaje,
        db=db,
        usuario_id=g.uid,
        chat_id=chat_id,
        coleccion=coleccion_temario(g.oposicion),
        oposicion=g.oposicion
    )
    if respuesta is None:
        # No se registra uso: un fallo técnico de DeepSeek no debe consumir
        # el cupo de mensajes del usuario.
        return jsonify({"error": _ERROR_DEEPSEEK}), 502
    registrar_uso(db, g.uid, "chat_temario", g.plan_actual)
    return jsonify({"respuesta": respuesta, "chat_id": chat_id})


# Misma ruta que /tu-tutor pero en streaming (Server-Sent Events): cada
# fragmento de la respuesta se manda al frontend según va llegando de
# DeepSeek, para un efecto de "escritura" en vez de esperar a la respuesta
# completa. Los permisos/límites se comprueban ANTES de abrir el stream
# (igual que en la ruta normal); registrar_uso y el guardado en Firestore
# ocurren dentro del propio generador, solo si se completa con éxito.
@bp.route("/tu-tutor/stream", methods=["POST"])
@requiere_plan(db, "premium")
def tu_tutor_stream_route():
    data = request.get_json()
    mensaje = data.get("mensaje")
    if not mensaje:
        return jsonify({"error": "Falta el mensaje"}), 400
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "chat_temario")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    chat_id = data.get("chat_id")
    uid = g.uid
    plan_actual = g.plan_actual
    oposicion = g.oposicion

    # Uso cobrado por adelantado, no al llegar "fin": si el cliente corta la
    # conexión a mitad de respuesta, el generador de abajo no llega a su
    # registrar_uso y se podía saltar la cuota abortando en bucle. Si DeepSeek
    # falla del todo (evento "error", sin "fin"), se devuelve el uso.
    registrar_uso(db, uid, "chat_temario", plan_actual)

    def generar():
        exito = False
        for evento in responder_tutor_stream(
            mensaje=mensaje,
            db=db,
            usuario_id=uid,
            chat_id=chat_id,
            coleccion=coleccion_temario(oposicion),
            oposicion=oposicion
        ):
            if evento["tipo"] == "fin":
                exito = True
            yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
        # Si el cliente aborta a mitad, aquí no se llega (GeneratorExit en el
        # yield) y el uso se mantiene consumido a propósito. Solo se devuelve
        # ante un fallo real de DeepSeek, con el cliente aún conectado.
        if not exito:
            devolver_uso(db, uid, "chat_temario", plan_actual)

    return Response(
        stream_with_context(generar()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


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


@bp.route("/conversacion/<conversacion_id>", methods=["DELETE"])
@requiere_plan(db, "premium")
def eliminar_conversacion(conversacion_id):
    ref = db.collection("conversaciones_IA") \
            .document(g.uid) \
            .collection("conversaciones") \
            .document(conversacion_id)
    if not ref.get().exists:
        return jsonify({"error": "Conversación no encontrada"}), 404
    ref.delete()
    return jsonify({"ok": True})
