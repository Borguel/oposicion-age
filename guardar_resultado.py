from datetime import datetime
from firebase_admin import firestore
from registro_progreso_usuario import actualizar_estadisticas_test, actualizar_estadisticas_esquema, registrar_actividad_racha
from oposiciones import OPOSICION_POR_DEFECTO
from documentos_pdf import marcar_generado
from banco_fallos import actualizar_banco_fallos

def guardar_resultado_en_firestore(db, tipo, contenido, usuario_id="usuario_prueba", metadatos=None, oposicion=OPOSICION_POR_DEFECTO, test_id=None):
    metadatos = metadatos or {}
    doc_user = db.collection("usuarios").document(usuario_id)
    registrar_actividad_racha(db, usuario_id)

    if tipo == "test":
        respuestas = metadatos.get("respuestas", [])
        tipo_test = metadatos.get("tipo", "personalizado")
        actualizar_banco_fallos(db, usuario_id, oposicion, tipo_test, contenido, respuestas)
        aciertos, fallos, blancos = 0, 0, 0
        for i, p in enumerate(contenido):
            correcta = p.get("respuesta_correcta")
            seleccion = respuestas[i] if i < len(respuestas) else None
            if seleccion == correcta:
                aciertos += 1
            elif not seleccion:
                blancos += 1
            else:
                fallos += 1

        puntuacion = round(aciertos - (fallos / 3), 2)

        # Calcular resultado
        total_preguntas = aciertos + fallos
        resultado = "aprobado" if total_preguntas > 0 and (aciertos / total_preguntas) >= 0.5 else "suspendido"
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
                    "acierto": (respuestas[i] if i < len(respuestas) else None) == p.get("respuesta_correcta")
                } for i, p in enumerate(contenido)
            ]
        })

        # Actualizar resumen del usuario para esta oposición
        actualizar_estadisticas_test(db, usuario_id, oposicion, aciertos, fallos, temas_efectivos, metadatos.get("tiempo", 0), tipo_test, puntuacion, rendimiento_temas)

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
        actualizar_estadisticas_usuario(db, usuario_id, "test_pdf")
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
        actualizar_estadisticas_usuario(db, usuario_id, "resumen_pdf")
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
        actualizar_estadisticas_usuario(db, usuario_id, "esquema_pdf")
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
        actualizar_estadisticas_usuario(db, usuario_id, "tarjetas_pdf")
        if documento_id:
            marcar_generado(db, usuario_id, documento_id, "tarjetas_pdf", num_tarjetas_nuevas=len(contenido))

def actualizar_estadisticas_usuario(db, usuario_id, tipo):
    """Actualizar estadísticas del usuario cuando guarda contenido desde PDF (NUEVO)"""
    try:
        user_ref = db.collection("usuarios").document(usuario_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            # Crear documento de usuario si no existe
            user_ref.set({
                "fecha_creacion": datetime.utcnow().isoformat(),
                "tests_pdf_realizados": 0,
                "resumenes_pdf_realizados": 0,
                "esquemas_pdf_realizados": 0,
                "tarjetas_pdf_realizados": 0,
                "total_archivos_procesados": 0,
                "ultima_actividad": datetime.utcnow().isoformat()
            })
            return
        
        # Actualizar contadores según el tipo
        field_updates = {
            "ultima_actividad": datetime.utcnow().isoformat()
        }
        
        if tipo == "test_pdf":
            field_updates["tests_pdf_realizados"] = firestore.Increment(1)
        elif tipo == "resumen_pdf":
            field_updates["resumenes_pdf_realizados"] = firestore.Increment(1)
        elif tipo == "esquema_pdf":
            field_updates["esquemas_pdf_realizados"] = firestore.Increment(1)
        elif tipo == "tarjetas_pdf":
            field_updates["tarjetas_pdf_realizados"] = firestore.Increment(1)
        
        field_updates["total_archivos_procesados"] = firestore.Increment(1)
        
        user_ref.update(field_updates)
        
    except Exception as e:
        print(f"❌ Error actualizando estadísticas del usuario: {e}")

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

        # Contar elementos en cada subcolección
        tests_pdf_count = len(list(user_ref.collection("tests_pdf").stream()))
        resumenes_pdf_count = len(list(user_ref.collection("resumenes_pdf").stream()))
        esquemas_pdf_count = len(list(user_ref.collection("esquemas_pdf").stream()))
        tarjetas_pdf_count = len(list(user_ref.collection("tarjetas_pdf").stream()))

        estadisticas = {
            "oposicion": oposicion,
            # Estadísticas del temario oficial de esta oposición
            "tests_realizados": stats.get("tests_realizados", 0),
            "tests_aprobados": stats.get("tests_aprobados", 0),
            "tests_suspendidos": stats.get("tests_suspendidos", 0),
            "total_aciertos": stats.get("total_aciertos", 0),
            "total_fallos": stats.get("total_fallos", 0),
            "puntuacion_media_test": stats.get("puntuacion_media_test", 0),
            "esquemas_realizados": stats.get("esquemas_realizados", 0),
            "tiempo_total": stats.get("tiempo_total", 0),

            # Estadísticas desde PDF (globales, no dependen de la oposición)
            "tests_pdf_realizados": datos.get("tests_pdf_realizados", 0),
            "resumenes_pdf_realizados": datos.get("resumenes_pdf_realizados", 0),
            "esquemas_pdf_realizados": datos.get("esquemas_pdf_realizados", 0),
            "tarjetas_pdf_realizados": datos.get("tarjetas_pdf_realizados", 0),
            "total_archivos_procesados": datos.get("total_archivos_procesados", 0),

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
            "ultima_actividad": datos.get("ultima_actividad"),
            "fecha_creacion": datos.get("fecha_creacion")
        }

        return estadisticas

    except Exception as e:
        print(f"❌ Error obteniendo estadísticas del usuario: {e}")
        return {"error": str(e)}