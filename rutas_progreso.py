
from datetime import datetime
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
from banco_favoritas import marcar_favorita, desmarcar_favorita, listar_favoritas
from push_utils import VAPID_PUBLIC_KEY, push_disponible, guardar_suscripcion, borrar_suscripcion
from auth_utils import requiere_login, requiere_plan, obtener_oposicion_solicitada
from utils import calcular_resultado_test
import random

# Campos ligeros que devuelve /mis-tests -- deliberadamente sin el array
# completo de "preguntas"/"contenido", para no cargar cada test entero solo
# para listarlo (eso se pide aparte con /mi-test/<id> cuando hace falta).
CAMPOS_RESUMEN_MIS_TESTS = (
    "fecha", "tipo", "oposicion", "estado", "num_preguntas", "aciertos",
    "fallos", "blancos", "porcentaje_acierto", "resultado", "temas",
    "tiempo", "indice_actual", "pagina_origen"
)

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

    @app.route("/fecha-examen", methods=["GET"])
    @requiere_login(db)
    def obtener_fecha_examen():
        oposicion = obtener_oposicion_solicitada()
        doc = db.collection("usuarios").document(g.uid).get()
        datos = doc.to_dict() or {}
        fecha = (datos.get("fechas_examen") or {}).get(oposicion)
        return jsonify({"fecha_examen": fecha})

    @app.route("/fecha-examen", methods=["POST"])
    @requiere_login(db)
    def guardar_fecha_examen():
        oposicion = obtener_oposicion_solicitada()
        datos = request.get_json(silent=True) or {}
        fecha = (datos.get("fecha_examen") or "").strip()
        ref = db.collection("usuarios").document(g.uid)
        if fecha:
            try:
                datetime.strptime(fecha, "%Y-%m-%d")
            except ValueError:
                return jsonify({"error": "Formato de fecha no válido"}), 400
            ref.set({"fechas_examen": {oposicion: fecha}}, merge=True)
        else:
            ref.update({f"fechas_examen.{oposicion}": firestore.DELETE_FIELD})
        return jsonify({"mensaje": "Fecha de examen actualizada"})

    @app.route("/marcar-favorita", methods=["POST"])
    @requiere_login(db)
    def marcar_favorita_route():
        datos = request.get_json(silent=True) or {}
        pregunta = datos.get("pregunta") or {}
        if not pregunta.get("pregunta"):
            return jsonify({"error": "Falta la pregunta a marcar"}), 400
        marcar_favorita(db, g.uid, obtener_oposicion_solicitada(), pregunta)
        return jsonify({"mensaje": "Pregunta marcada como favorita"})

    @app.route("/desmarcar-favorita", methods=["POST"])
    @requiere_login(db)
    def desmarcar_favorita_route():
        datos = request.get_json(silent=True) or {}
        texto = (datos.get("pregunta") or "").strip()
        if not texto:
            return jsonify({"error": "Falta el texto de la pregunta"}), 400
        desmarcar_favorita(db, g.uid, obtener_oposicion_solicitada(), texto)
        return jsonify({"mensaje": "Pregunta desmarcada"})

    @app.route("/preguntas-favoritas", methods=["GET"])
    @requiere_login(db)
    def preguntas_favoritas_route():
        favoritas = listar_favoritas(db, g.uid, obtener_oposicion_solicitada())
        return jsonify({"favoritas": favoritas})

    @app.route("/notificaciones-push/clave-publica", methods=["GET"])
    def clave_publica_push_route():
        return jsonify({"clave_publica": VAPID_PUBLIC_KEY, "disponible": push_disponible()})

    @app.route("/notificaciones-push/suscribir", methods=["POST"])
    @requiere_login(db)
    def suscribir_push_route():
        suscripcion = request.get_json(silent=True) or {}
        if not suscripcion.get("endpoint"):
            return jsonify({"error": "Suscripción no válida"}), 400
        guardar_suscripcion(db, g.uid, suscripcion)
        return jsonify({"mensaje": "Notificaciones activadas"})

    @app.route("/notificaciones-push/desuscribir", methods=["POST"])
    @requiere_login(db)
    def desuscribir_push_route():
        datos = request.get_json(silent=True) or {}
        endpoint = datos.get("endpoint")
        if not endpoint:
            return jsonify({"error": "Falta el endpoint"}), 400
        borrar_suscripcion(db, g.uid, endpoint)
        return jsonify({"mensaje": "Notificaciones desactivadas"})

    @app.route("/ultimo-test", methods=["GET"])
    @requiere_login(db)
    def obtener_ultimo_test():
        oposicion = obtener_oposicion_solicitada()
        try:
            tests_ref = db.collection("usuarios").document(g.uid).collection("tests")
            # Se filtra por oposición sin combinarlo con order_by (eso exigiría
            # crear un índice compuesto en Firestore); como no son muchos tests
            # por usuario, se ordena en Python tras traerlos. Se excluyen los
            # que todavía están "en_progreso" (borradores autoguardados sin
            # terminar) para que "repetir último test" no coja uno sin acabar
            # -- los documentos antiguos, sin campo "estado", cuentan como ya
            # finalizados.
            tests = [
                t.to_dict() for t in tests_ref.where("oposicion", "==", oposicion).stream()
                if t.to_dict().get("estado", "finalizado") != "en_progreso"
            ]

            if not tests:
                return jsonify({"mensaje": "No se encontró test anterior", "test": []}), 404

            test_data = max(tests, key=lambda t: t.get("fecha", ""))
            return jsonify({"test": test_data.get("preguntas", [])})
        except Exception as e:
            return jsonify({"error": f"Error buscando test: {str(e)}"}), 500

    @app.route("/autosave-test", methods=["POST"])
    @requiere_login(db)
    def autosave_test():
        datos = request.get_json(silent=True) or {}
        test_id = datos.get("test_id")
        if not test_id:
            return jsonify({"error": "Falta test_id"}), 400

        test_ref = db.collection("usuarios").document(g.uid).collection("tests").document(test_id)
        ahora = datetime.utcnow().isoformat()

        campos_variables = {
            "respuestas_usuario": datos.get("respuestas_usuario", []),
            "marcadas_revision": datos.get("marcadas_revision", []),
            "indice_actual": datos.get("indice_actual", 0),
            "modo_cronometrado": bool(datos.get("modo_cronometrado", False)),
            "tiempo_restante_segundos": datos.get("tiempo_restante_segundos"),
            "tiempo_transcurrido_segundos": datos.get("tiempo_transcurrido_segundos"),
            "fecha_actualizacion": ahora,
        }

        try:
            # "contenido" (las preguntas en sí) solo se manda una vez, en el
            # primer autoguardado de este test_id -- a partir de ahí basta con
            # actualizar los campos que cambian en cada pregunta/tick.
            if datos.get("contenido") is not None or not test_ref.get().exists:
                test_ref.set({
                    "fecha": ahora,
                    "estado": "en_progreso",
                    "oposicion": datos.get("oposicion", obtener_oposicion_solicitada()),
                    "tipo": datos.get("tipo", "personalizado"),
                    "temas": datos.get("temas", []),
                    "num_preguntas": len(datos.get("contenido", []) or []),
                    "contenido": datos.get("contenido", []),
                    "tiempo_total_asignado_segundos": datos.get("tiempo_total_asignado_segundos"),
                    "pagina_origen": datos.get("pagina_origen", ""),
                    "documento_id": datos.get("documento_id"),
                    **campos_variables,
                })
            else:
                test_ref.set(campos_variables, merge=True)
            return jsonify({"mensaje": "ok"})
        except Exception as e:
            return jsonify({"error": f"Error autoguardando el test: {str(e)}"}), 500

    @app.route("/mis-tests", methods=["GET"])
    @requiere_login(db)
    def obtener_mis_tests():
        oposicion = obtener_oposicion_solicitada()
        estado_filtro = request.args.get("estado")  # "en_progreso" | "finalizado" | None (todos)
        tema_filtro = request.args.get("tema_id")
        tipo_filtro = request.args.get("tipo")
        try:
            tests_ref = db.collection("usuarios").document(g.uid).collection("tests")
            resultado = []
            for doc in tests_ref.where("oposicion", "==", oposicion).stream():
                d = doc.to_dict()
                estado = d.get("estado", "finalizado")
                if estado_filtro and estado != estado_filtro:
                    continue
                if tipo_filtro and d.get("tipo") != tipo_filtro:
                    continue
                if tema_filtro and tema_filtro not in (d.get("temas") or []):
                    continue
                resumen = {campo: d.get(campo) for campo in CAMPOS_RESUMEN_MIS_TESTS}
                resumen["estado"] = estado
                resumen["id"] = doc.id
                if estado == "finalizado":
                    # No nos fiamos del "resultado" tal cual guardado -- tests
                    # guardados antes de corregir la fórmula oficial pueden
                    # tenerlo mal, y aciertos/fallos/blancos sí son de fiar.
                    _, _, resumen["resultado"] = calcular_resultado_test(
                        d.get("aciertos", 0) or 0, d.get("fallos", 0) or 0, d.get("blancos", 0) or 0
                    )
                resultado.append(resumen)
            resultado.sort(key=lambda t: t.get("fecha") or "", reverse=True)
            return jsonify({"tests": resultado})
        except Exception as e:
            return jsonify({"error": f"Error listando tests: {str(e)}"}), 500

    @app.route("/mi-test/<test_id>", methods=["GET"])
    @requiere_login(db)
    def obtener_mi_test(test_id):
        try:
            # La propiedad ya está garantizada por vivir bajo la subcolección
            # de ESTE usuario -- no hace falta comprobar dueño aparte.
            doc = db.collection("usuarios").document(g.uid).collection("tests").document(test_id).get()
            if not doc.exists:
                return jsonify({"error": "Test no encontrado"}), 404
            datos = doc.to_dict()
            datos["id"] = doc.id
            datos.setdefault("estado", "finalizado")
            return jsonify({"test": datos})
        except Exception as e:
            return jsonify({"error": f"Error obteniendo el test: {str(e)}"}), 500

    @app.route("/mi-test/<test_id>", methods=["DELETE"])
    @requiere_login(db)
    def borrar_mi_test(test_id):
        try:
            db.collection("usuarios").document(g.uid).collection("tests").document(test_id).delete()
            return jsonify({"mensaje": "Test borrado"})
        except Exception as e:
            return jsonify({"error": f"Error borrando el test: {str(e)}"}), 500

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
