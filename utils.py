import re

def obtener_contexto_por_temas(db, temas):
    """
    Recupera el texto completo de los subtemas relacionados con los temas indicados.

    Args:
        db: Cliente de Firestore.
        temas (list): Lista de IDs de documentos principales (temas) en la colección 'temario'.

    Returns:
        str: Texto concatenado de todos los subtemas de los temas indicados.
    """
    contexto = ""
    for tema in temas:
        tema_doc = db.collection("temario").document(tema)
        subtemas = tema_doc.collection("subtemas").stream()
        for sub in subtemas:
            contenido = sub.to_dict().get("contenido", "")
            contexto += f"\n{sub.id}:\n{contenido}\n"
    return contexto
