import tiktoken
from typing import List

def contar_tokens(texto: str, modelo="gpt-3.5-turbo") -> int:
    try:
        encoding = tiktoken.encoding_for_model(modelo)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(texto))

def obtener_subbloques_individuales(db, temas: List[str], limite_total_tokens=3000) -> List[dict]:
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

        subbloques_ref = temas_ref.document(tema_id).collection("subbloques").stream()

        for sub in subbloques_ref:
            datos = sub.to_dict()
            if not datos:
                continue
            texto = datos.get("texto", "")
            titulo = datos.get("titulo", "")
            etiqueta = f"{bloque_id}-{tema_id}-{sub.id}"

            tokens = contar_tokens(texto)
            if total_tokens + tokens > limite_total_tokens:
                return subbloques_utilizados

            subbloques_utilizados.append({
                "etiqueta": etiqueta,
                "titulo": titulo,
                "texto": texto
            })
            total_tokens += tokens

    return subbloques_utilizados

def obtener_temas_disponibles(db):
    temas_disponibles = []
    bloques = db.collection("Temario AGE").stream()
    for bloque in bloques:
        bloque_id = bloque.id
        temas_ref = db.collection("Temario AGE").document(bloque_id).collection("temas").stream()
        for tema in temas_ref:
            datos = tema.to_dict()
            if not datos:
                continue
            titulo = datos.get("titulo", "Sin título")
            temas_disponibles.append({
                "id": f"{bloque_id}-{tema.id}",
                "titulo": titulo
            })
    return temas_disponibles

