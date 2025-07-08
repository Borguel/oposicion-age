from flask import request, jsonify
from firebase_admin import firestore
from registro_progreso_usuario import (
    inicializar_estadisticas_usuario,
    actualizar_estadisticas_test,
    actualizar_estadisticas_esquema,
    obtener_resumen_progreso
)
import random

def registrar_rutas_progreso(app, db):
    @app.route("/registrar-usuario", methods=["POST"])
    def registrar_usuario():
        datos = request.get_json()
        usuario_id = datos.get("usuario_id")

        if not usuario_id:
            return jsonify({"error": "Falta usuario_id"}), 400

        inicializar_estadisticas_usuario(db, usuario_id)
        return jsonify({"mensaje": "Usuario registrado correctamente"})

    @app.route("/actualizar-progreso-test", methods=["POST"])
    def actualizar_progreso_test():
        datos = request.get_json()
        usuario_id = datos.get("usuario_id")
        metadatos = datos.get("metadatos", {})

        if not usuario_id:
            return jsonify({"error": "Falta usuario_id"}), 400

        tiempo_min = metadatos.get("tiempo", 0)
        tiempo_en_segundos = int(tiempo_min * 60)

        actualizar_estadisticas_test(
            db=db,
            usuario_id=usuario_id,
            aciertos=metadatos.get("aciertos", 0),
            fallos=metadatos.get("fallos", 0),
            temas=metadatos.get("temas", []),
            tiempo_en_segundos=tiempo_en_segundos
        )

        return jsonify({"mensaje": "Progreso de test actualizado"})

    @app.route("/actualizar-progreso-esquema", methods=["POST"])
    def actualizar_progreso_esquema():
        datos = request.get_json()
        usuario_id = datos.get("usuario_id")
        metadatos = datos.get("metadatos", {})

        if not usuario_id:
            return jsonify({"error": "Falta usuario_id"}), 400

        actualizar_estadisticas_esquema(
            db=db,
            usuario_id=usuario_id,
            temas=metadatos.get("temas", [])
        )

        return jsonify({"mensaje": "Progreso de esquema actualizado"})

    @app.route("/resumen-progreso", methods=["GET"])
    def obtener_resumen_progreso_route():
        usuario_id = request.args.get("usuario_id")
        if not usuario_id:
            return jsonify({"error": "Falta usuario_id"}), 400

        resumen = obtener_resumen_progreso(db, usuario_id)
        return jsonify({"resumen": resumen})

    @app.route("/ultimo-test", methods=["GET"])
    def obtener_ultimo_test():
        usuario_id = request.args.get("usuario_id")
        if not usuario_id:
            return jsonify({"error": "Falta usuario_id"}), 400

        try:
            tests_ref = db.collection("usuarios").document(usuario_id).collection("tests")
            query = tests_ref.order_by("fecha", direction=firestore.Query.DESCENDING).limit(1).stream()
            test = next(query, None)

            if not test:
                return jsonify({"mensaje": "No se encontró test anterior", "test": []}), 404

            test_data = test.to_dict()
            return jsonify({"test": test_data.get("preguntas", [])})
        except Exception as e:
            return jsonify({"error": f"Error buscando test: {str(e)}"}), 500

    @app.route("/test-desde-historial", methods=["GET"])
    def generar_test_desde_historial():
        usuario_id = request.args.get("usuario_id")
        cantidad = int(request.args.get("cantidad", 10))

        if not usuario_id:
            return jsonify({"error": "Falta usuario_id"}), 400

        try:
            tests_ref = db.collection("usuarios").document(usuario_id).collection("tests").stream()
            preguntas = []
            for test in tests_ref:
                test_data = test.to_dict()
                preguntas.extend(test_data.get("preguntas", []))
        except Exception as e:
            return jsonify({"error": f"Error leyendo tests: {str(e)}"}), 500

        if not preguntas:
            return jsonify({"test": [], "mensaje": "No se encontraron preguntas anteriores"}), 404

        random.shuffle(preguntas)
        seleccionadas = preguntas[:cantidad]

        return jsonify({"test": seleccionadas})
