import tiktoken

def contar_tokens(texto, modelo="gpt-3.5-turbo"):
    encoding = tiktoken.encoding_for_model(modelo)
    return len(encoding.encode(texto))

def obtener_subbloques_individuales(db, temas, limite_total_tokens=3000):
    subbloques_utilizados = []
    total_tokens = 0

    for tema_completo in temas:
        if "-" not in tema_completo:
            continue
        bloque_id, tema_id = tema_completo.split("-", 1)

        temas_ref = db.collection("Temario AGE").document(bloque_id).collection("temas")
        tema_doc = temas_ref.document(tema_id).get()
        if not tema_doc.exists:
            continue

        subbloques = temas_ref.document(tema_id).collection("subbloques").stream()
        for sub in subbloques:
            datos = sub.to_dict()
            texto = datos.get("texto", "")
            titulo = datos.get("titulo", "")
            etiqueta = f"{bloque_id}-{tema_id}-{sub.id}"

            tokens = contar_tokens(texto)
            if total_tokens + tokens > limite_total_tokens:
                continue

            subbloques_utilizados.append({
                "etiqueta": etiqueta,
                "titulo": titulo,
                "texto": texto
            })
            total_tokens += tokens

    return subbloques_utilizados

def obtener_temas_disponibles(db):
    temas_disponibles = []
    bloques = db.collection("Temario AGE").list_documents()
    for bloque in bloques:
        temas_ref = bloque.collection("temas").stream()
        for tema in temas_ref:
            datos = tema.to_dict()
            if not datos:
                continue
            titulo = datos.get("titulo", "Sin título")
            temas_disponibles.append({
                "id": f"{bloque.id}-{tema.id}",
                "titulo": titulo
            })
    return temas_disponibles