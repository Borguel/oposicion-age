
def obtener_subbloques_individuales(db, temas, token_limit=3000):
    from tiktoken import encoding_for_model, get_encoding
    modelo = "gpt-3.5-turbo"
    try:
        encoding = encoding_for_model(modelo)
    except KeyError:
        encoding = get_encoding("cl100k_base")

    def contar_tokens(texto):
        return len(encoding.encode(texto))

    subbloques = []
    for tema in temas:
        partes = tema.split(".")
        if len(partes) == 2:
            bloque_id, tema_id = partes
        else:
            continue

        ref = db.collection("Temario AGE").document(bloque_id).collection("temas").document(tema_id).collection("subbloques")
        docs = ref.stream()

        for doc in docs:
            data = doc.to_dict()
            texto = data.get("texto", "")
            if contar_tokens(texto) <= token_limit:
                subbloques.append({"id": doc.id, "texto": texto})

    return subbloques
