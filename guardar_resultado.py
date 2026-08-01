import logging
from datetime import datetime
from firebase_admin import firestore
from registro_progreso_usuario import actualizar_estadisticas_test, actualizar_estadisticas_esquema, actualizar_estadisticas_pdf, registrar_actividad_racha
from oposiciones import OPOSICION_POR_DEFECTO
from documentos_pdf import marcar_generado
from banco_fallos import actualizar_banco_fallos, _id_pregunta
from utils import calcular_resultado_test

logger = logging.getLogger(__name__)


def _actualizar_contadores_preguntas(db, oposicion, contenido, respuestas, excluir_dudas, es_duda):
    """Fase 1 de calibración de dificultad: por cada pregunta corregida en el
    test, acumula en preguntas/{id} cuántas veces se ha respondido y cuántas
    se ha acertado (id = mismo hash de contenido que usa banco_fallos, ya que
    aquí tampoco llega un id estable de Firestore desde el banco de origen).
    Solo telemetría para fases futuras -- un fallo aquí nunca debe impedir
    que el usuario reciba la corrección de su test."""
    try:
        batch = db.batch()
        coleccion_preguntas = db.collection("preguntas")
        total = 0
        aciertos = 0
        for i, p in enumerate(contenido):
            if excluir_dudas and es_duda(i):
                continue
            texto = p.get("pregunta")
            if not texto:
                continue
            seleccion = respuestas[i] if i < len(respuestas) else None
            acierto = seleccion == p.get("respuesta_correcta")
            datos = {"total_respuestas": firestore.Increment(1)}
            if acierto:
                datos["total_aciertos"] = firestore.Increment(1)
                aciertos += 1
            batch.set(coleccion_preguntas.document(_id_pregunta(oposicion, texto)), datos, merge=True)
            total += 1
        if total:
            batch.commit()
            logger.info("[calibracion] batch escrito: %d preguntas actualizadas, %d aciertos", total, aciertos)
    except Exception:
        logger.warning("[calibracion] fallo al actualizar contadores de preguntas (no bloqueante)", exc_info=True)


def guardar_resultado_en_firestore(db, tipo, contenido, usuario_id="usuario_prueba", metadatos=None, oposicion=OPOSICION_POR_DEFECTO, test_id=None, marcadas_duda=None):
    metadatos = metadatos or {}
    doc_user = db.collection("usuarios").document(usuario_id)
    registrar_actividad_racha(db, usuario_id)

    if tipo == "test":
        respuestas = metadatos.get("respuestas", [])
        tipo_test = metadatos.get("tipo", "personalizado")
        actualizar_banco_fallos(db, usuario_id, oposicion, tipo_test, contenido, respuestas)

        marcadas_duda = marcadas_duda or []

        def es_duda(i):
            return bool(marcadas_duda[i]) if i < len(marcadas_duda) else False

        # Una pregunta marcada como "duda" no cuenta para la nota final (como
        # una pregunta anulada en un examen oficial: ni acierto ni fallo, ni
        # en el numerador ni en el denominador) -- salvo que se hayan marcado
        # TODAS las del test, en cuyo caso no queda ninguna con la que
        # calcular nada y se cuentan todas para no guardar un resultado vacío.
        hay_alguna_duda = any(es_duda(i) for i in range(len(contenido)))
        excluir_dudas = hay_alguna_duda and any(not es_duda(i) for i in range(len(contenido)))
        if hay_alguna_duda and not excluir_dudas:
            logger.warning("guardar_resultado: todas las preguntas se marcaron como duda, se cuentan igualmente para la nota (usuario=%s)", usuario_id)

        aciertos, fallos, blancos = 0, 0, 0
        for i, p in enumerate(contenido):
            if excluir_dudas and es_duda(i):
                continue
            correcta = p.get("respuesta_correcta")
            seleccion = respuestas[i] if i < len(respuestas) else None
            if seleccion == correcta:
                aciertos += 1
            elif not seleccion:
                blancos += 1
            else:
                fallos += 1

        _actualizar_contadores_preguntas(db, oposicion, contenido, respuestas, excluir_dudas, es_duda)

        puntuacion, _nota_sobre_10, resultado = calcular_resultado_test(aciertos, fallos, blancos)

        total_preguntas = aciertos + fallos
        porcentaje_acierto = round((aciertos / total_preguntas) * 100, 1) if total_preguntas else 0.0

        # Temas "efectivos" del test: los elegidos explícitamente en el
        # formulario (metadatos.temas) UNIDOS a los que trae cada pregunta en
        # su propio tema_id. Así un test "oficial" o "inteligente" (donde no
        # siempre se elige tema a mano) también puede contar para las
        # estadísticas de "temas estudiados" si sus preguntas sí lo indican.
        temas_metadatos = metadatos.get("temas", [])
        temas_preguntas = [p.get("tema_id") for p in contenido if p.get("tema_id")]
        temas_efectivos = list(dict.fromkeys([*temas_metadatos, *temas_preguntas]))

        # Rendimiento por tema (solo de las preguntas que sí traen tema_id),
        # para poder saber no solo qué temas se han tocado sino en cuáles se
        # acierta más o menos -- útil para futuras recomendaciones de estudio.
        rendimiento_temas = {}
        for i, p in enumerate(contenido):
            if excluir_dudas and es_duda(i):
                continue
            tema_id = p.get("tema_id")
            if not tema_id:
                continue
            seleccion = respuestas[i] if i < len(respuestas) else None
            entrada = rendimiento_temas.setdefault(tema_id, {"aciertos": 0, "fallos": 0, "blancos": 0})
            if not seleccion:
                entrada["blancos"] += 1
            elif seleccion == p.get("respuesta_correcta"):
                entrada["aciertos"] += 1
            else:
                entrada["fallos"] += 1

        # Guardar en subcolección tests (con la oposición a la que pertenece,
        # para poder filtrar "repetir test"/"preguntas falladas" por oposición).
        # Si test_id viene informado (el test se autoguardó "en_progreso" con
        # ese mismo id mientras se hacía), se reutiliza el mismo documento en
        # vez de crear uno nuevo -- así finalizar un test reanudado no deja un
        # borrador duplicado suelto.
        test_ref = doc_user.collection("tests").document(test_id) if test_id else doc_user.collection("tests").document()
        test_ref.set({
            "fecha": datetime.utcnow().isoformat(),
            "tipo": tipo_test,
            "oposicion": oposicion,
            "estado": "finalizado",
            "num_preguntas": len(contenido),
            "aciertos": aciertos,
            "fallos": fallos,
            "blancos": blancos,
            "porcentaje_acierto": porcentaje_acierto,
            "puntuacion_final": puntuacion,
            "tiempo": metadatos.get("tiempo", 0),
            "temas": temas_efectivos,
            "resultado": resultado,
            "preguntas": [
                {
                    "pregunta": p.get("pregunta"),
                    "respuesta_correcta": p.get("respuesta_correcta"),
                    "respuesta_usuario": respuestas[i] if i < len(respuestas) else None,
                    "opciones": p.get("opciones"),
                    "explicacion": p.get("explicacion", "Sin explicación."),
                    "tema_id": p.get("tema_id"),
                    "acierto": (respuestas[i] if i < len(respuestas) else None) == p.get("respuesta_correcta"),
                    "marcada_duda": bool(marcadas_duda[i]) if marcadas_duda and i < len(marcadas_duda) else False,
                } for i, p in enumerate(contenido)
            ]
        })

        # Actualizar resumen del usuario para esta oposición
        actualizar_estadisticas_test(db, usuario_id, oposicion, aciertos, fallos, temas_efectivos, metadatos.get("tiempo", 0), tipo_test, puntuacion, rendimiento_temas, blancos)

    elif tipo == "esquema":
        esquema_ref = doc_user.collection("esquemas").document()
        esquema_ref.set({
            "fecha": datetime.utcnow().isoformat(),
            "temas": metadatos.get("temas", []),
            "oposicion": oposicion,
            "contenido": contenido
        })

        actualizar_estadisticas_esquema(db, usuario_id, oposicion, metadatos.get("temas", []))

    # ===================================================================
    # NUEVOS TIPOS PARA CONTENIDO DESDE PDF
    # ===================================================================
    
    elif tipo == "test_pdf":
        # Guardar test generado desde PDF
        documento_id = metadatos.get("documento_id")
        test_pdf_ref = doc_user.collection("tests_pdf").document()
        test_pdf_ref.set({
            "fecha": datetime.utcnow().isoformat(),
            "nombre_archivo": metadatos.get("nombre_archivo", "documento.pdf"),
            "documento_id": documento_id,
            "preguntas": contenido,
            "num_preguntas": len(contenido),
            "tipo": "test_pdf",
            "metadatos": metadatos
        })
        actualizar_estadisticas_pdf(db, usuario_id, "test_pdf")
        if documento_id:
            marcar_generado(db, usuario_id, documento_id, "test_pdf")

    elif tipo == "resumen_pdf":
        # Guardar resumen generado desde PDF
        documento_id = metadatos.get("documento_id")
        resumen_pdf_ref = doc_user.collection("resumenes_pdf").document()
        resumen_pdf_ref.set({
            "fecha": datetime.utcnow().isoformat(),
            "nombre_archivo": metadatos.get("nombre_archivo", "documento.pdf"),
            "documento_id": documento_id,
            "resumen": contenido,
            "longitud": len(contenido),
            "tipo": "resumen_pdf",
            "metadatos": metadatos
        })
        actualizar_estadisticas_pdf(db, usuario_id, "resumen_pdf")
        if documento_id:
            marcar_generado(db, usuario_id, documento_id, "resumen_pdf")

    elif tipo == "esquema_pdf":
        # Guardar esquema generado desde PDF
        documento_id = metadatos.get("documento_id")
        esquema_pdf_ref = doc_user.collection("esquemas_pdf").document()
        esquema_pdf_ref.set({
            "fecha": datetime.utcnow().isoformat(),
            "nombre_archivo": metadatos.get("nombre_archivo", "documento.pdf"),
            "documento_id": documento_id,
            "esquema": contenido,
            "longitud": len(contenido),
            "tipo": "esquema_pdf",
            "metadatos": metadatos
        })
        actualizar_estadisticas_pdf(db, usuario_id, "esquema_pdf")
        if documento_id:
            marcar_generado(db, usuario_id, documento_id, "esquema_pdf")

    elif tipo == "tarjetas_pdf":
        # Guardar tarjetas generadas desde PDF
        documento_id = metadatos.get("documento_id")
        tarjetas_pdf_ref = doc_user.collection("tarjetas_pdf").document()
        tarjetas_pdf_ref.set({
            "fecha": datetime.utcnow().isoformat(),
            "nombre_archivo": metadatos.get("nombre_archivo", "documento.pdf"),
            "documento_id": documento_id,
            "tarjetas": contenido,
            "num_tarjetas": len(contenido),
            "tipo": "tarjetas_pdf",
            "metadatos": metadatos
        })
        actualizar_estadisticas_pdf(db, usuario_id, "tarjetas_pdf")
        if documento_id:
            marcar_generado(db, usuario_id, documento_id, "tarjetas_pdf", num_tarjetas_nuevas=len(contenido))

def _total_blancos_usuario(user_ref, oposicion):
    """Suma las preguntas dejadas en blanco en todos los tests finalizados de
    esta oposición. Se recorre la subcolección "tests" en vez de mantener un
    contador acumulado aparte (como total_aciertos/total_fallos) porque cada
    documento de test ya guarda su propio campo "blancos" desde el principio,
    así que sumar sobre lo ya existente da la cifra correcta también para
    tests guardados antes de añadir esta estadística, sin necesitar una
    migración de datos."""
    total = 0
    for doc in user_ref.collection("tests").where("oposicion", "==", oposicion).stream():
        datos_test = doc.to_dict() or {}
        if datos_test.get("estado", "finalizado") == "en_progreso":
            continue
        total += datos_test.get("blancos", 0) or 0
    return total


# Función auxiliar para obtener estadísticas completas del usuario
def obtener_estadisticas_completas_usuario(db, usuario_id, oposicion=OPOSICION_POR_DEFECTO):
    """Obtener estadísticas completas del usuario para UNA OPOSICIÓN (test,
    esquemas...), incluyendo además el contenido desde PDF (que es global,
    no depende de la oposición)."""
    try:
        user_ref = db.collection("usuarios").document(usuario_id)
        user_doc = user_ref.get()

        if not user_doc.exists:
            return {
                "error": "Usuario no encontrado"
            }

        datos = user_doc.to_dict()
        stats = (datos.get("estadisticas", {}) or {}).get(oposicion, {}) or {}

        # Contar elementos en cada subcolección con una consulta de
        # agregación (.count()) en vez de traer todos los documentos
        # completos solo para contarlos con len(list(...)).
        tests_pdf_count = user_ref.collection("tests_pdf").count().get()[0][0].value
        resumenes_pdf_count = user_ref.collection("resumenes_pdf").count().get()[0][0].value
        esquemas_pdf_count = user_ref.collection("esquemas_pdf").count().get()[0][0].value
        tarjetas_pdf_count = user_ref.collection("tarjetas_pdf").count().get()[0][0].value

        estadisticas = {
            "oposicion": oposicion,
            # Estadísticas del temario oficial de esta oposición
            "tests_realizados": stats.get("tests_realizados", 0),
            "tests_aprobados": stats.get("tests_aprobados", 0),
            "tests_suspendidos": stats.get("tests_suspendidos", 0),
            "total_aciertos": stats.get("total_aciertos", 0),
            "total_fallos": stats.get("total_fallos", 0),
            "total_blancos": _total_blancos_usuario(user_ref, oposicion),
            "puntuacion_media_test": stats.get("puntuacion_media_test", 0),
            "esquemas_realizados": stats.get("esquemas_realizados", 0),
            "tiempo_total": stats.get("tiempo_total", 0),

            # Estadísticas desde PDF (globales, no dependen de la oposición)
            "tests_pdf_realizados": datos.get("tests_pdf_realizados", 0),
            "resumenes_pdf_realizados": datos.get("resumenes_pdf_realizados", 0),
            "esquemas_pdf_realizados": datos.get("esquemas_pdf_realizados", 0),
            "tarjetas_pdf_realizados": datos.get("tarjetas_pdf_realizados", 0),
            "total_archivos_procesados": datos.get("total_archivos_procesados", 0),
            "paginas_analizadas": datos.get("paginas_analizadas", 0),

            # Conteos reales de documentos
            "total_tests_pdf": tests_pdf_count,
            "total_resumenes_pdf": resumenes_pdf_count,
            "total_esquemas_pdf": esquemas_pdf_count,
            "total_tarjetas_pdf": tarjetas_pdf_count,

            # Información adicional (de esta oposición)
            "temas_test": stats.get("temas_test", []),
            "temas_esquemas": stats.get("temas_esquemas", []),
            "rendimiento_por_tema": stats.get("rendimiento_por_tema", {}),
            "ultimo_test": stats.get("ultimo_test", {}),
            "historial_tests": stats.get("historial_tests", []),
            "ultima_actividad": datos.get("ultima_actividad"),
            "fecha_creacion": datos.get("fecha_creacion")
        }

        return estadisticas

    except Exception as e:
        logger.exception("Error obteniendo estadísticas del usuario")
        return {"error": str(e)}