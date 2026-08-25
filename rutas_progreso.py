
import logging
from datetime import datetime
from flask import request, jsonify, g
from firebase_admin import firestore
from registro_progreso_usuario import (
    inicializar_estadisticas_usuario,
    actualizar_estadisticas_test,
    actualizar_estadisticas_esquema,
    obtener_resumen_progreso,
    actualizar_estadisticas_pdf,
    revertir_estadisticas_test,
)
from guardar_resultado import obtener_estadisticas_completas_usuario
from banco_favoritas import marcar_favorita, desmarcar_favorita, listar_favoritas
from banco_fallos import listar_fallos
from push_utils import VAPID_PUBLIC_KEY, push_disponible, guardar_suscripcion, borrar_suscripcion
from auth_utils import requiere_login, requiere_plan, obtener_oposicion_solicitada
from planes import ORDEN_PLANES, resolver_plan_efectivo
from utils import calcular_resultado_test
from validacion_perfil import nombre_valido, telefono_valido, direccion_valida
import random

logger = logging.getLogger(__name__)

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
        #
        # Validado por campo (ver validacion_perfil.py) antes de guardar: sin
        # esto, cualquiera podía registrar "nombre"/"apellidos" con un enlace,
        # HTML o una fórmula de hoja de cálculo, que luego se enseña tal cual
        # en el panel admin, en las exportaciones CSV (usuarios.csv,
        # ingresos.csv) y en el saludo de los correos transaccionales.
        datos = request.get_json(silent=True) or {}
        validadores = {
            "nombre": nombre_valido,
            "apellidos": nombre_valido,
            "telefono": telefono_valido,
            "direccion": direccion_valida,
        }
        actualizacion = {}
        for campo, es_valido in validadores.items():
            valor = datos.get(campo)
            if not isinstance(valor, str) or not valor.strip():
                continue
            valor = valor.strip()
            if not es_valido(valor):
                return jsonify({"error": f"El campo '{campo}' no es válido."}), 400
            actualizacion[campo] = valor
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
    @requiere_plan(db, "basico", global_check=False)
    def obtener_resumen_progreso_route():
        resumen = obtener_resumen_progreso(db, g.uid, oposicion=obtener_oposicion_solicitada())
        return jsonify({"resumen": resumen})

    @app.route("/estadisticas-completas", methods=["GET"])
    @requiere_plan(db, "basico", global_check=False)
    def obtener_estadisticas_completas():
        estadisticas = obtener_estadisticas_completas_usuario(db, g.uid, oposicion=obtener_oposicion_solicitada())
        return jsonify({"estadisticas": estadisticas})

    @app.route("/fecha-examen", methods=["GET"])
    @requiere_plan(db, "basico", global_check=False)
    def obtener_fecha_examen():
        oposicion = obtener_oposicion_solicitada()
        doc = db.collection("usuarios").document(g.uid).get()
        datos = doc.to_dict() or {}
        fecha = (datos.get("fechas_examen") or {}).get(oposicion)
        return jsonify({"fecha_examen": fecha})

    @app.route("/fecha-examen", methods=["POST"])
    @requiere_plan(db, "basico", global_check=False)
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
    @requiere_plan(db, "basico", global_check=False)
    def marcar_favorita_route():
        datos = request.get_json(silent=True) or {}
        pregunta = datos.get("pregunta") or {}
        if not pregunta.get("pregunta"):
            return jsonify({"error": "Falta la pregunta a marcar"}), 400
        marcar_favorita(db, g.uid, obtener_oposicion_solicitada(), pregunta)
        return jsonify({"mensaje": "Pregunta marcada como favorita"})

    @app.route("/desmarcar-favorita", methods=["POST"])
    @requiere_plan(db, "basico", global_check=False)
    def desmarcar_favorita_route():
        datos = request.get_json(silent=True) or {}
        texto = (datos.get("pregunta") or "").strip()
        if not texto:
            return jsonify({"error": "Falta el texto de la pregunta"}), 400
        desmarcar_favorita(db, g.uid, obtener_oposicion_solicitada(), texto)
        return jsonify({"mensaje": "Pregunta desmarcada"})

    @app.route("/preguntas-favoritas", methods=["GET"])
    @requiere_plan(db, "basico", global_check=False)
    def preguntas_favoritas_route():
        favoritas = listar_favoritas(db, g.uid, obtener_oposicion_solicitada())
        return jsonify({"favoritas": favoritas})

    @app.route("/preguntas-falladas", methods=["GET"])
    @requiere_plan(db, "basico", global_check=False)
    def preguntas_falladas_route():
        falladas = listar_fallos(db, g.uid, obtener_oposicion_solicitada())
        return jsonify({"falladas": falladas})

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
    @requiere_plan(db, "basico", global_check=False)
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
        except Exception:
            logger.exception("Error buscando el último test")
            return jsonify({"error": "No se pudo buscar el último test."}), 500

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
            "marcadas_duda": datos.get("marcadas_duda", []),
            "indice_actual": datos.get("indice_actual", 0),
            "modo_cronometrado": bool(datos.get("modo_cronometrado", False)),
            "tiempo_restante_segundos": datos.get("tiempo_restante_segundos"),
            "tiempo_transcurrido_segundos": datos.get("tiempo_transcurrido_segundos"),
            "fecha_actualizacion": ahora,
        }
        # documento_id puede llegar más tarde que la creación del borrador:
        # con el arranque temprano de un test grande desde PDF (ver
        # frontend/subida-pdf-generar-test/script.js), el test se crea en
        # cuanto llegan las primeras preguntas, ANTES de que el backend
        # termine de generar el resto y por tanto antes de que el frontend
        # conozca el documento_id real (solo viaja en el evento SSE "fin")
        # -- bug real: el borrador se creaba con documento_id nulo para
        # siempre, así que "Mis documentos" nunca podía ofrecer "Continuar"
        # para ese documento. Se admite corregirlo en CUALQUIER
        # autoguardado posterior, no solo en la creación; condicionado a
        # que venga en la petición para no borrar el que ya hubiera si un
        # autoguardado de otro punto (que nunca lo manda, como el de cada
        # respuesta) no lo incluye.
        if datos.get("documento_id") is not None:
            campos_variables["documento_id"] = datos.get("documento_id")

        try:
            # "contenido" (las preguntas en sí) solo se manda una vez, en el
            # primer autoguardado de este test_id -- a partir de ahí basta con
            # actualizar los campos que cambian en cada pregunta/tick. Ese
            # primer guardado SÍ exige plan (evita poder "vivir" indefinidamente
            # de un único test ya generado, vía autosave, una vez caducada la
            # prueba/suscripción); los guardados posteriores del mismo test_id
            # no, para no perder un test que ya se estaba haciendo
            # legítimamente si el plan caduca a mitad de la resolución.
            if datos.get("contenido") is not None or not test_ref.get().exists:
                if not getattr(g, "es_admin", False):
                    usuario = db.collection("usuarios").document(g.uid).get().to_dict() or {}
                    plan_actual, _sub = resolver_plan_efectivo(usuario, oposicion=obtener_oposicion_solicitada())
                    if ORDEN_PLANES.get(plan_actual, 0) < ORDEN_PLANES["basico"]:
                        return jsonify({"error": "Requiere plan superior", "plan_actual": plan_actual, "plan_requerido": "basico"}), 403
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
                    **campos_variables,
                })
            else:
                test_ref.set(campos_variables, merge=True)
            return jsonify({"mensaje": "ok"})
        except Exception:
            logger.exception("Error autoguardando el test")
            return jsonify({"error": "No se pudo autoguardar el test."}), 500

    @app.route("/mis-tests", methods=["GET"])
    @requiere_plan(db, "basico", global_check=False)
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
        except Exception:
            logger.exception("Error listando 'mis tests'")
            return jsonify({"error": "No se pudieron listar los tests."}), 500

    @app.route("/mi-test/<test_id>", methods=["GET"])
    @requiere_plan(db, "basico", global_check=False)
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
        except Exception:
            logger.exception("Error obteniendo el test %s", test_id)
            return jsonify({"error": "No se pudo obtener el test."}), 500

    @app.route("/mi-test/<test_id>", methods=["DELETE"])
    @requiere_plan(db, "basico", global_check=False)
    def borrar_mi_test(test_id):
        try:
            test_ref = db.collection("usuarios").document(g.uid).collection("tests").document(test_id)
            # Bug real (24/08/2026): borrar un test solo quitaba el
            # documento, pero su contribución a estadisticas.{oposicion}
            # (tests_realizados, total_aciertos/fallos, rendimiento_por_tema
            # -- que /analisis-rendimiento lee directamente -- etc.) se
            # quedaba contando para siempre. Solo se revierte si el test
            # llegó a FINALIZARSE (un borrador "en_progreso" nunca llegó a
            # sumarse, ver actualizar_estadisticas_test/guardar_resultado.py).
            test_doc = test_ref.get()
            if test_doc.exists:
                datos_test = test_doc.to_dict() or {}
                if datos_test.get("estado", "finalizado") == "finalizado":
                    try:
                        revertir_estadisticas_test(db, g.uid, datos_test.get("oposicion", ""), datos_test)
                    except Exception:
                        logger.exception("No se pudieron revertir las estadísticas del test %s", test_id)
            test_ref.delete()
            return jsonify({"mensaje": "Test borrado"})
        except Exception:
            logger.exception("Error borrando el test %s", test_id)
            return jsonify({"error": "No se pudo borrar el test."}), 500

    @app.route("/test-desde-historial", methods=["GET"])
    @requiere_plan(db, "basico", global_check=False)
    def generar_test_desde_historial():
        # Bug real (ronda de auditoría #5): int() sin capturar -- un
        # ?cantidad=abc daba un 500 genérico (ValueError sin controlar) en
        # vez de degradar al valor por defecto, como ya hacen las rutas
        # equivalentes de blueprints/pdf_ia.py para este mismo parámetro.
        try:
            cantidad = int(request.args.get("cantidad", 10))
        except (TypeError, ValueError):
            cantidad = 10
        oposicion = obtener_oposicion_solicitada()

        try:
            tests_ref = db.collection("usuarios").document(g.uid).collection("tests") \
                .where("oposicion", "==", oposicion).stream()
            preguntas = []
            for test in tests_ref:
                test_data = test.to_dict()
                preguntas.extend(test_data.get("preguntas", []))
        except Exception:
            logger.exception("Error leyendo tests para generar test desde historial")
            return jsonify({"error": "No se pudieron leer los tests del historial."}), 500

        if not preguntas:
            return jsonify({"test": [], "mensaje": "No se encontraron preguntas anteriores"}), 404

        random.shuffle(preguntas)
        seleccionadas = preguntas[:cantidad]

        return jsonify({"test": seleccionadas})

    @app.route("/contenido-pdf-guardado", methods=["GET"])
    @requiere_plan(db, "premium", global_check=True)
    def obtener_contenido_pdf_guardado():
        tipo_contenido = request.args.get("tipo_contenido")  # tests_pdf, resumenes_pdf, esquemas_pdf, tarjetas_pdf
        # Bug real (ronda de auditoría #5): mismo caso que en
        # /test-desde-historial -- un ?limite=abc daba un 500 genérico en
        # vez de degradar al valor por defecto.
        try:
            limite = int(request.args.get("limite", 10))
        except (TypeError, ValueError):
            limite = 10

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

        except Exception:
            logger.exception("Error obteniendo contenido PDF guardado")
            return jsonify({"error": "No se pudo obtener el contenido guardado."}), 500

    @app.route("/progreso-general", methods=["GET"])
    @requiere_plan(db, "basico", global_check=False)
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

        except Exception:
            logger.exception("Error calculando progreso general")
            return jsonify({"error": "No se pudo calcular el progreso general."}), 500
