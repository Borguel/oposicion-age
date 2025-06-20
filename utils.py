import tiktoken
import random

def contar_tokens(texto, modelo="gpt-3.5-turbo"):
    try:
        encoding = tiktoken.encoding_for_model(modelo)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(texto))

def obtener_contexto_por_temas(db, temas, token_limit=3000, limite=None):
    contexto = ""
    subbloques_total = []

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
            contenido = data.get("texto", "")
            titulo = data.get("titulo", "")

            if not contenido or not contenido.strip():
                print(f"⚠️ Subbloque vacío o solo espacios: {sub_id}")
                continue

            if len(contenido.strip()) < 100:
                print(f"⚠️ Subbloque demasiado corto (omitido): {sub_id}")
                continue

            fragmento = f"{titulo.strip()}\n{contenido.strip()}"
            subbloques_total.append(fragmento)

    if not subbloques_total:
        print("❌ No se encontraron subbloques válidos.")
        return ""

    # Mezclar aleatoriamente y recortar por tokens
    random.shuffle(subbloques_total)
    token_total = 0
    resultado = []

    for fragmento in subbloques_total:
        tokens = contar_tokens(fragmento)
        if token_total + tokens > token_limit:
            break
        resultado.append(fragmento)
        token_total += tokens

    contexto = "\n\n".join(resultado)
    print(f"✅ Contexto generado con {token_total} tokens y {len(resultado)} fragmentos.")
    return contexto

