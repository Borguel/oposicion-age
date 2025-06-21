import tiktoken
import random

def contar_tokens(texto, modelo="gpt-3.5-turbo"):
    try:
        encoding = tiktoken.encoding_for_model(modelo)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(texto))

def obtener_contexto_por_temas(db, temas, token_limit=3000, limite=None):
    token_total = 0
    resultado = []
    subbloques_global = {}

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
            if not contenido:
                print(f"⚠️ Subbloque vacío: {sub_id}")
                continue

            clave = f"{bloque_id}-{tema_id}-{sub_id}"
            subbloques_global[clave] = contenido

    # Mezclar para obtener diversidad
    claves = list(subbloques_global.keys())
    random.shuffle(claves)

    for clave in claves:
        fragmento = f"\n{clave}:\n{subbloques_global[clave]}\n"
        tokens = contar_tokens(fragmento)
        if token_total + tokens > token_limit:
            break
        resultado.append(fragmento)
        token_total += tokens

    return "\n".join(resultado)