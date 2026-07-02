
from flask import request, jsonify
from firebase_admin import firestore
from registro_progreso_usuario import (
    inicializar_estadisticas_usuario,
    actualizar_estadisticas_test,
    actualizar_estadisticas_esquema,
    obtener_resumen_progreso,
    actualizar_estadisticas_pdf
)
from guardar_resultado import obtener_estadisticas_completas_usuario
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

    @app.route("/actualizar-progreso-pdf", methods=["POST"])
    def actualizar_progreso_pdf():
        datos = request.get_json()
        usuario_id = datos.get("usuario_id")
        tipo_pdf = datos.get("tipo_pdf")

        if not usuario_id or not tipo_pdf:
            return jsonify({"error": "Falta usuario_id o tipo_pdf"}), 400

        if tipo_pdf not in ["test_pdf", "resumen_pdf", "esquema_pdf", "tarjetas_pdf"]:
            return jsonify({"error": "Tipo PDF no válido"}), 400

        actualizar_estadisticas_pdf(db, usuario_id, tipo_pdf)
        return jsonify({"mensaje": f"Progreso de {tipo_pdf} actualizado"})

    @app.route("/resumen-progreso", methods=["GET"])
    def obtener_resumen_progreso_route():
        usuario_id = request.args.get("usuario_id")
        if not usuario_id:
            return jsonify({"error": "Falta usuario_id"}), 400

        resumen = obtener_resumen_progreso(db, usuario_id)
        return jsonify({"resumen": resumen})

    @app.route("/estadisticas-completas", methods=["GET"])
    def obtener_estadisticas_completas():
        usuario_id = request.args.get("usuario_id")
        if not usuario_id:
            return jsonify({"error": "Falta usuario_id"}), 400

        estadisticas = obtener_estadisticas_completas_usuario(db, usuario_id)
        return jsonify({"estadisticas": estadisticas})

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

    @app.route("/contenido-pdf-guardado", methods=["GET"])
    def obtener_contenido_pdf_guardado():
        usuario_id = request.args.get("usuario_id")
        tipo_contenido = request.args.get("tipo_contenido")  # tests_pdf, resumenes_pdf, esquemas_pdf, tarjetas_pdf
        limite = int(request.args.get("limite", 10))

        if not usuario_id or not tipo_contenido:
            return jsonify({"error": "Falta usuario_id o tipo_contenido"}), 400

        try:
            # Mapear tipo_contenido a la colección correspondiente
            colecciones_map = {
                "tests_pdf": "tests_pdf",
                "resumenes_pdf": "resumenes_pdf", 
                "esquemas_pdf": "esquemas_pdf",
                "tarjetas_pdf": "tarjetas_pdf"
            }

            if tipo_contenido not in colecciones_map:
                return jsonify({"error": "Tipo de contenido no válido"}), 400

            coleccion = colecciones_map[tipo_contenido]
            contenido_ref = db.collection("usuarios").document(usuario_id).collection(coleccion)
            query = contenido_ref.order_by("fecha", direction=firestore.Query.DESCENDING).limit(limite).stream()
            
            documentos = []
            for doc in query:
                doc_data = doc.to_dict()
                doc_data["id"] = doc.id
                documentos.append(doc_data)

            return jsonify({"contenido": documentos})

        except Exception as e:
            return jsonify({"error": f"Error obteniendo contenido PDF: {str(e)}"}), 500

    @app.route("/progreso-general", methods=["GET"])
    def obtener_progreso_general():
        usuario_id = request.args.get("usuario_id")
        if not usuario_id:
            return jsonify({"error": "Falta usuario_id"}), 400

        try:
            # Obtener estadísticas básicas
            resumen = obtener_resumen_progreso(db, usuario_id)
            
            # Obtener estadísticas completas (incluye conteos reales de documentos)
            estadisticas_completas = obtener_estadisticas_completas_usuario(db, usuario_id)
            
            # Calcular métricas adicionales
            total_actividades = (
                resumen.get("tests_realizados", 0) +
                resumen.get("esquemas_realizados", 0) +
                resumen.get("tests_pdf_realizados", 0) +
                resumen.get("resumenes_pdf_realizados", 0) +
                resumen.get("esquemas_pdf_realizados", 0) +
                resumen.get("tarjetas_pdf_realizados", 0)
            )
            
            progreso = {
                "resumen_basico": resumen,
                "estadisticas_detalladas": estadisticas_completas,
                "metricas_avanzadas": {
                    "total_actividades": total_actividades,
                    "tasa_aprobacion": round((resumen.get("tests_aprobados", 0) / resumen.get("tests_realizados", 1)) * 100, 2) if resumen.get("tests_realizados", 0) > 0 else 0,
                    "tiempo_promedio_test": round(resumen.get("tiempo_total", 0) / resumen.get("tests_realizados", 1), 2) if resumen.get("tests_realizados", 0) > 0 else 0,
                    "productividad_total": total_actividades
                }
            }
            
            return jsonify({"progreso": progreso})
            
        except Exception as e:
            return jsonify({"error": f"Error calculando progreso general: {str(e)}"}), 500