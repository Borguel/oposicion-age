from datetime import datetime

def guardar_resultado_en_firestore(db, tipo, contenido, usuario_id="usuario_prueba", metadatos=None):
    """
    Guarda un resultado (test o esquema) en Firestore bajo la colección 'resultados'.

    Args:
        db: Cliente Firestore.
        tipo (str): 'test' o 'esquema'.
        contenido (dict): Contenido generado (preguntas, respuestas, explicación...).
        usuario_id (str): ID del usuario que generó el contenido.
        metadatos (dict): Información adicional como número de preguntas, aciertos, fallos, temas, etc.
    """
    doc_ref = db.collection("resultados").document()
    doc_ref.set({
        "tipo": tipo,
        "usuario_id": usuario_id,
        "contenido": contenido,
        "metadatos": metadatos or {},
        "fecha": datetime.utcnow().isoformat()
    })
