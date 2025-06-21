import tiktoken
import random

def contar_tokens(texto, modelo="gpt-3.5-turbo"):
    try:
        encoding = tiktoken.encoding_for_model(modelo)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(texto))

def obtener_contexto_por_temas(db, temas, token_limit=3000, limite=None):
    subbloques_por_tema = []

    for tema in temas[:limite] if limite else temas:
        if "-" in tema:
            bloque_id, tema_id = tema.split("-", 1)
        else:
            print(f"❌ Formato incorrecto en '{tema}'. Usa bloque_01-tema_02")
            continue

        subbloques = db.collection("Temario AGE").document(bloque_id) \
                       .collection("temas").document(tema_id) \
                       .collection("subbloques").stream()

        for sub in subbloques:
            data = sub.to_dict()
            sub_id = sub.id
            contenido = data.get("texto", "").strip()
            if contenido:
                # Guardamos también el tema para identificar de dónde viene
                subbloques_por_tema.append((tema, sub_id, contenido))

    # Mezclamos todos los subbloques de todos los temas
    random.shuffle(subbloques_por_tema)

    resultado = []
    token_total = 0

    for tema, sub_id, contenido in subbloques_por_tema:
        fragmento = f"\n[{tema} - {sub_id}]\n{contenido}\n"
        tokens = contar_tokens(fragmento)
        if token_total + tokens > token_limit:
            break
        resultado.append(fragmento)
        token_total += tokens

    return "\n".join(resultado)