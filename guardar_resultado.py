from datetime import datetime
from firebase_admin import firestore
from registro_progreso_usuario import actualizar_estadisticas_test, actualizar_estadisticas_esquema
from oposiciones import OPOSICION_POR_DEFECTO

def guardar_resultado_en_firestore(db, tipo, contenido, usuario_id="usuario_prueba", metadatos=None, oposicion=OPOSICION_POR_DEFECTO):
    metadatos = metadatos or {}
    doc_user = db.collection("usuarios").document(usuario_id)

    if tipo == "test":
        respuestas = metadatos.get("respuestas", [])
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

        # Guardar en subcolección tests (con la oposición a la que pertenece,
        # para poder filtrar "repetir test"/"preguntas falladas" por oposición)
        test_ref = doc_user.collection("tests").document()
        test_ref.set({
            "fecha": datetime.utcnow().isoformat(),
            "tipo": metadatos.get("tipo", "personalizado"),
            "oposicion": oposicion,
            "aciertos": aciertos,
            "fallos": fallos,
            "blancos": blancos,
            "puntuacion_final": puntuacion,
            "tiempo": metadatos.get("tiempo", 0),
            "temas": metadatos.get("temas", []),
            "resultado": resultado,
            "preguntas": [
                {
                    "pregunta": p.get("pregunta"),
                    "respuesta_correcta": p.get("respuesta_correcta"),
                    "respuesta_usuario": respuestas[i] if i < len(respuestas) else None,
                    "opciones": p.get("opciones"),
                    "explicacion": p.get("explicacion", "Sin explicación.")
                } for i, p in enumerate(contenido)
            ]
        })

        # Actualizar resumen del usuario para esta oposición
        actualizar_estadisticas_test(db, usuario_id, oposicion, aciertos, fallos, metadatos.get("temas", []), metadatos.get("tiempo", 0), metadatos.get("tipo", "personalizado"), puntuacion)

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
        test_pdf_ref = doc_user.collection("tests_pdf").document()
        test_pdf_ref.set({
            "fecha": datetime.utcnow().isoformat(),
            "nombre_archivo": metadatos.get("nombre_archivo", "documento.pdf"),
            "preguntas": contenido,
            "num_preguntas": len(contenido),
            "tipo": "test_pdf",
            "metadatos": metadatos
        })
        actualizar_estadisticas_usuario(db, usuario_id, "test_pdf")

    elif tipo == "resumen_pdf":
        # Guardar resumen generado desde PDF
        resumen_pdf_ref = doc_user.collection("resumenes_pdf").document()
        resumen_pdf_ref.set({
            "fecha": datetime.utcnow().isoformat(),
            "nombre_archivo": metadatos.get("nombre_archivo", "documento.pdf"),
            "resumen": contenido,
            "longitud": len(contenido),
            "tipo": "resumen_pdf",
            "metadatos": metadatos
        })
        actualizar_estadisticas_usuario(db, usuario_id, "resumen_pdf")

    elif tipo == "esquema_pdf":
        # Guardar esquema generado desde PDF
        esquema_pdf_ref = doc_user.collection("esquemas_pdf").document()
        esquema_pdf_ref.set({
            "fecha": datetime.utcnow().isoformat(),
            "nombre_archivo": metadatos.get("nombre_archivo", "documento.pdf"),
            "esquema": contenido,
            "longitud": len(contenido),
            "tipo": "esquema_pdf",
            "metadatos": metadatos
        })
        actualizar_estadisticas_usuario(db, usuario_id, "esquema_pdf")

    elif tipo == "tarjetas_pdf":
        # Guardar tarjetas generadas desde PDF
        tarjetas_pdf_ref = doc_user.collection("tarjetas_pdf").document()
        tarjetas_pdf_ref.set({
            "fecha": datetime.utcnow().isoformat(),
            "nombre_archivo": metadatos.get("nombre_archivo", "documento.pdf"),
            "tarjetas": contenido,
            "num_tarjetas": len(contenido),
            "tipo": "tarjetas_pdf",
            "metadatos": metadatos
        })
        actualizar_estadisticas_usuario(db, usuario_id, "tarjetas_pdf")

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
            "ultimo_test": stats.get("ultimo_test", {}),
            "ultima_actividad": datos.get("ultima_actividad"),
            "fecha_creacion": datos.get("fecha_creacion")
        }

        return estadisticas

    except Exception as e:
        print(f"❌ Error obteniendo estadísticas del usuario: {e}")
        return {"error": str(e)}