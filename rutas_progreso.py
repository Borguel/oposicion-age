from flask import request, jsonify
from firebase_admin import firestore

def registrar_rutas_progreso(app, db):
    @app.route("/registrar-usuario", methods=["POST"])
    def registrar_usuario():
        datos = request.get_json()
        usuario_id = datos.get("usuario_id")

        if not usuario_id:
            return jsonify({"error": "Falta usuario_id"}), 400

        doc_ref = db.collection("usuarios").document(usuario_id)
        if doc_ref.get().exists:
            return jsonify({"mensaje": "El usuario ya existe"}), 200

        doc_ref.set({
            "usuario_id": usuario_id,
            "total_tests": 0,
            "total_aciertos": 0,
            "total_fallos": 0,
            "total_esquemas": 0,
            "temas_test": [],
            "temas_esquema": [],
            "tiempo_total": 0,
            "historial_tests": [],
            "historial_esquemas": [],
            "ultima_actualizacion": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"mensaje": "Usuario registrado correctamente"})

    @app.route("/actualizar-progreso-test", methods=["POST"])
    def actualizar_progreso_test():
        datos = request.get_json()
        usuario_id = datos.get("usuario_id")
        metadatos = datos.get("metadatos", {})
        if not usuario_id:
            return jsonify({"error": "Falta usuario_id"}), 400

        doc_ref = db.collection("usuarios").document(usuario_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"error": "Usuario no encontrado"}), 404

        data = doc.to_dict()
        doc_ref.update({
            "total_tests": data.get("total_tests", 0) + 1,
            "total_aciertos": data.get("total_aciertos", 0) + metadatos.get("aciertos", 0),
            "total_fallos": data.get("total_fallos", 0) + metadatos.get("fallos", 0),
            "tiempo_total": data.get("tiempo_total", 0) + metadatos.get("tiempo", 0),
            "temas_test": list(set(data.get("temas_test", []) + metadatos.get("temas", []))),
            "historial_tests": firestore.ArrayUnion([{
                "fecha": firestore.SERVER_TIMESTAMP,
                "aciertos": metadatos.get("aciertos"),
                "fallos": metadatos.get("fallos"),
                "tiempo": metadatos.get("tiempo"),
                "temas": metadatos.get("temas")
            }]),
            "ultima_actualizacion": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"mensaje": "Progreso de test actualizado"})

    @app.route("/actualizar-progreso-esquema", methods=["POST"])
    def actualizar_progreso_esquema():
        datos = request.get_json()
        usuario_id = datos.get("usuario_id")
        metadatos = datos.get("metadatos", {})
        if not usuario_id:
            return jsonify({"error": "Falta usuario_id"}), 400

        doc_ref = db.collection("usuarios").document(usuario_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"error": "Usuario no encontrado"}), 404

        data = doc.to_dict()
        doc_ref.update({
            "total_esquemas": data.get("total_esquemas", 0) + 1,
            "temas_esquema": list(set(data.get("temas_esquema", []) + metadatos.get("temas", []))),
            "historial_esquemas": firestore.ArrayUnion([{
                "fecha": firestore.SERVER_TIMESTAMP,
                "temas": metadatos.get("temas")
            }]),
            "ultima_actualizacion": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"mensaje": "Progreso de esquema actualizado"})

    @app.route("/resumen-progreso", methods=["GET"])
    def obtener_resumen_progreso_route():
        usuario_id = request.args.get("usuario_id")
        if not usuario_id:
            return jsonify({"error": "Falta usuario_id"}), 400

        doc_ref = db.collection("usuarios").document(usuario_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"error": "Usuario no encontrado"}), 404

        datos = doc.to_dict()
        return jsonify({"resumen": datos})

