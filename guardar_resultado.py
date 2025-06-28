from datetime import datetime
from firebase_admin import firestore

def guardar_resultado_en_firestore(db, tipo, contenido, usuario_id="usuario_prueba", metadatos=None):
    """
    Guarda un test o un esquema dentro del documento del usuario en Firestore.
    Si es un test, calcula la puntuación, guarda en subcolección 'tests' y actualiza totales.
    Si es un esquema, guarda en subcolección 'esquemas' y actualiza totales.
    """
    metadatos = metadatos or {}
    doc_user = db.collection("usuarios").document(usuario_id)

    if tipo == "test":
        # Calcular resultados
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
            "preguntas": [
                {
                    "pregunta": p.get("pregunta"),
                    "respuesta_correcta": p.get("respuesta_correcta"),
                    "respuesta_usuario": respuestas[i] if i < len(respuestas) else None,
                    "opciones": p.get("opciones")
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
        tiempo_total = data.get("tiempo_total_dedicado_min", 0) + round(metadatos.get("tiempo", 0) / 60)
        puntuacion_media = round(total_aciertos / total_tests, 2)

        doc_user.update({
            "tests_realizados": total_tests,
            "total_aciertos": total_aciertos,
            "total_fallos": total_fallos,
            "temas_test": temas_test,
            "tiempo_total_dedicado_min": tiempo_total,
            "ultimo_test": {
                "aciertos": aciertos,
                "fallos": fallos,
                "blancos": blancos,
                "puntuacion_final": puntuacion,
                "tipo": metadatos.get("tipo", "personalizado"),
                "temas": metadatos.get("temas", []),
                "tiempo_min": round(metadatos.get("tiempo", 0) / 60),
                "fecha": datetime.utcnow().isoformat()
            },
            "ultima_actividad": datetime.utcnow().isoformat(),
            "puntuacion_media_test": puntuacion_media
        })

    elif tipo == "esquema":
        # Guardar en subcolección esquemas
        esquema_ref = doc_user.collection("esquemas").document()
        esquema_ref.set({
            "fecha": datetime.utcnow().isoformat(),
            "temas": metadatos.get("temas", []),
            "contenido": contenido
        })

        # Actualizar totales
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
