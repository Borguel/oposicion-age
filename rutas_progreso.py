
from flask import request, jsonify, g
from firebase_admin import firestore
from registro_progreso_usuario import (
    inicializar_estadisticas_usuario,
    actualizar_estadisticas_test,
    actualizar_estadisticas_esquema,
    obtener_resumen_progreso,
    actualizar_estadisticas_pdf
)
from guardar_resultado import obtener_estadisticas_completas_usuario
from auth_utils import requiere_login, requiere_plan, obtener_oposicion_solicitada
import random

def registrar_rutas_progreso(app, db):
    @app.route("/registrar-usuario", methods=["POST"])
    @requiere_login(db)
    def registrar_usuario():
        # requiere_login ya crea el documento del usuario si no existía.
        # Aquí solo completamos los datos básicos del perfil (si se mandan).
        datos = request.get_json(silent=True) or {}
        campos_permitidos = ("nombre", "apellidos", "telefono", "direccion")
        actualizacion = {}
        for campo in campos_permitidos:
            valor = datos.get(campo)
            if isinstance(valor, str) and valor.strip():
                actualizacion[campo] = valor.strip()
        if actualizacion:
            db.collection("usuarios").document(g.uid).update(actualizacion)
        return jsonify({"mensaje": "Usuario registrado correctamente"})

    @app.route("/actualizar-progreso-test", methods=["POST"])
    @requiere_login(db)
    def actualizar_progreso_test():
        datos = request.get_json()
        metadatos = datos.get("metadatos", {})

        tiempo_min = metadatos.get("tiempo", 0)
        tiempo_en_segundos = int(tiempo_min * 60)

        actualizar_estadisticas_test(
            db=db,
            usuario_id=g.uid,
            oposicion=obtener_oposicion_solicitada(),
            aciertos=metadatos.get("aciertos", 0),
            fallos=metadatos.get("fallos", 0),
            temas=metadatos.get("temas", []),
            tiempo_en_segundos=tiempo_en_segundos
        )

        return jsonify({"mensaje": "Progreso de test actualizado"})

    @app.route("/actualizar-progreso-esquema", methods=["POST"])
    @requiere_login(db)
    def actualizar_progreso_esquema():
        datos = request.get_json()
        metadatos = datos.get("metadatos", {})

        actualizar_estadisticas_esquema(
            db=db,
            usuario_id=g.uid,
            oposicion=obtener_oposicion_solicitada(),
            temas=metadatos.get("temas", [])
        )

        return jsonify({"mensaje": "Progreso de esquema actualizado"})

    @app.route("/actualizar-progreso-pdf", methods=["POST"])
    @requiere_plan(db, "premium", global_check=True)
    def actualizar_progreso_pdf():
        datos = request.get_json()
        tipo_pdf = datos.get("tipo_pdf")

        if not tipo_pdf:
            return jsonify({"error": "Falta tipo_pdf"}), 400

        if tipo_pdf not in ["test_pdf", "resumen_pdf", "esquema_pdf", "tarjetas_pdf"]:
            return jsonify({"error": "Tipo PDF no válido"}), 400

        actualizar_estadisticas_pdf(db, g.uid, tipo_pdf)
        return jsonify({"mensaje": f"Progreso de {tipo_pdf} actualizado"})

    @app.route("/resumen-progreso", methods=["GET"])
    @requiere_login(db)
    def obtener_resumen_progreso_route():
        resumen = obtener_resumen_progreso(db, g.uid, oposicion=obtener_oposicion_solicitada())
        return jsonify({"resumen": resumen})

    @app.route("/estadisticas-completas", methods=["GET"])
    @requiere_login(db)
    def obtener_estadisticas_completas():
        estadisticas = obtener_estadisticas_completas_usuario(db, g.uid, oposicion=obtener_oposicion_solicitada())
        return jsonify({"estadisticas": estadisticas})

    @app.route("/ultimo-test", methods=["GET"])
    @requiere_login(db)
    def obtener_ultimo_test():
        oposicion = obtener_oposicion_solicitada()
        try:
            tests_ref = db.collection("usuarios").document(g.uid).collection("tests")
            # Se filtra por oposición sin combinarlo con order_by (eso exigiría
            # crear un índice compuesto en Firestore); como no son muchos tests
            # por usuario, se ordena en Python tras traerlos.
            tests = [t.to_dict() for t in tests_ref.where("oposicion", "==", oposicion).stream()]

            if not tests:
                return jsonify({"mensaje": "No se encontró test anterior", "test": []}), 404

            test_data = max(tests, key=lambda t: t.get("fecha", ""))
            return jsonify({"test": test_data.get("preguntas", [])})
        except Exception as e:
            return jsonify({"error": f"Error buscando test: {str(e)}"}), 500

    @app.route("/test-desde-historial", methods=["GET"])
    @requiere_login(db)
    def generar_test_desde_historial():
        cantidad = int(request.args.get("cantidad", 10))
        oposicion = obtener_oposicion_solicitada()

        try:
            tests_ref = db.collection("usuarios").document(g.uid).collection("tests") \
                .where("oposicion", "==", oposicion).stream()
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
    @requiere_plan(db, "premium", global_check=True)
    def obtener_contenido_pdf_guardado():
        tipo_contenido = request.args.get("tipo_contenido")  # tests_pdf, resumenes_pdf, esquemas_pdf, tarjetas_pdf
        limite = int(request.args.get("limite", 10))

        if not tipo_contenido:
            return jsonify({"error": "Falta tipo_contenido"}), 400

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
            contenido_ref = db.collection("usuarios").document(g.uid).collection(coleccion)
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
    @requiere_login(db)
    def obtener_progreso_general():
        try:
            oposicion = obtener_oposicion_solicitada()
            # Obtener estadísticas básicas
            resumen = obtener_resumen_progreso(db, g.uid, oposicion=oposicion)

            # Obtener estadísticas completas (incluye conteos reales de documentos)
            estadisticas_completas = obtener_estadisticas_completas_usuario(db, g.uid, oposicion=oposicion)

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
