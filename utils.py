
import tiktoken
import random

def contar_tokens(texto, modelo="gpt-3.5-turbo"):
    try:
        encoding = tiktoken.encoding_for_model(modelo)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(texto))

def obtener_contexto_equilibrado_por_temas(db, temas, token_limit=3000):
    tokens_por_tema = {}
    bloques_tema = {}

    for tema in temas:
        if "-" not in tema:
            print(f"❌ Formato incorrecto en '{tema}' (usa bloque_01-tema_02)")
            continue

        bloque_id, tema_id = tema.split("-", 1)
        subbloques = db.collection("Temario AGE").document(bloque_id).collection("temas").document(tema_id).collection("subbloques").stream()

        sub_contenido = []
        total_tokens = 0

        for sub in subbloques:
            data = sub.to_dict()
            texto = data.get("texto", "").strip()
            if texto:
                t = contar_tokens(texto)
                total_tokens += t
                sub_contenido.append((sub.id, texto, t))

        if sub_contenido:
            tokens_por_tema[tema] = total_tokens
            bloques_tema[tema] = sub_contenido

    total = sum(tokens_por_tema.values())
    if total == 0:
        return ""

    resultado = []
    tokens_total = 0

    for tema, bloques in bloques_tema.items():
        proporcion = tokens_por_tema[tema] / total
        tokens_asignados = int(token_limit * proporcion)

        random.shuffle(bloques)
        tokens_añadidos = 0
        for sub_id, texto, t in bloques:
            if tokens_añadidos + t > tokens_asignados:
                break
            resultado.append(f"\n{sub_id} ({tema}):\n{texto}\n")
            tokens_añadidos += t
            tokens_total += t

            if tokens_total >= token_limit:
                break

    random.shuffle(resultado)
    return "\n".join(resultado[:10])
