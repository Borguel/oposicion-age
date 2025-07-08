from datetime import datetime
from firebase_admin import firestore

def guardar_resultado_en_firestore(db, tipo, contenido, usuario_id="usuario_prueba", metadatos=None):
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

        # Guardar en subcolección tests
        test_ref = doc_user.collection("tests").document()
        test_ref.set({
            "fecha": datetime.utcnow().isoformat(),
            "tipo": metadatos.get("tipo", "personalizado"),
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

        # Actualizar resumen general del usuario
        doc = doc_user.get()
        if not doc.exists:
            doc_user.set({})
            doc = doc_user.get()
        data = doc.to_dict()

        total_tests = data.get("tests_realizados", 0) + 1
        total_aciertos = data.get("total_aciertos", 0) + aciertos
        total_fallos = data.get("total_fallos", 0) + fallos
        temas_test = list(set(data.get("temas_test", []) + metadatos.get("temas", [])))
        tiempo_total = data.get("tiempo_total", 0) + metadatos.get("tiempo", 0)
        puntuacion_media = round(total_aciertos / total_tests, 2)

        # Aprobados / suspendidos
        aprobados = data.get("tests_aprobados", 0)
        suspendidos = data.get("tests_suspendidos", 0)
        if resultado == "aprobado":
            aprobados += 1
        else:
            suspendidos += 1

        # Actualizar historial
        historial = data.get("historial_tests", [])
        historial.append({
            "aciertos": aciertos,
            "fallos": fallos,
            "blancos": blancos,
            "puntuacion_final": puntuacion,
            "tipo": metadatos.get("tipo", "personalizado"),
            "temas": metadatos.get("temas", []),
            "tiempo": metadatos.get("tiempo", 0),
            "resultado": resultado,
            "fecha": datetime.utcnow().isoformat()
        })
        if len(historial) > 50:
            historial = historial[-50:]

        doc_user.update({
            "tests_realizados": total_tests,
            "total_aciertos": total_aciertos,
            "total_fallos": total_fallos,
            "tests_aprobados": aprobados,
            "tests_suspendidos": suspendidos,
            "temas_test": temas_test,
            "tiempo_total": tiempo_total,
            "puntuacion_media_test": puntuacion_media,
            "ultimo_test": historial[-1],
            "historial_tests": historial,
            "ultima_actividad": datetime.utcnow().isoformat()
        })

    elif tipo == "esquema":
        esquema_ref = doc_user.collection("esquemas").document()
        esquema_ref.set({
            "fecha": datetime.utcnow().isoformat(),
            "temas": metadatos.get("temas", []),
            "contenido": contenido
        })

        doc = doc_user.get()
        if not doc.exists:
            doc_user.set({})
            doc = doc_user.get()
        data = doc.to_dict()

        total_esquemas = data.get("esquemas_realizados", 0) + 1
        temas_esquema = list(set(data.get("temas_esquemas", []) + metadatos.get("temas", [])))

        doc_user.update({
            "esquemas_realizados": total_esquemas,
            "temas_esquemas": temas_esquema,
            "ultima_actividad": datetime.utcnow().isoformat()
        })
