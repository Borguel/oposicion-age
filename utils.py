import tiktoken
from typing import List, Dict

# ✅ Cuenta los tokens de un texto
def contar_tokens(texto: str, modelo="gpt-3.5-turbo") -> int:
    try:
        encoding = tiktoken.encoding_for_model(modelo)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(texto))

# ✅ Agrupa subbloques por tema para prompts largos (estructura anterior, por si la usas aún)
def agrupar_subbloques_por_tema(db, temas: List[str], limite_tokens=3000) -> Dict[str, List[List[dict]]]:
    resultado = {}
    for tema_completo in temas:
        if "-" not in tema_completo:
            continue
        bloque_id, tema_id = tema_completo.split("-", 1)
        subbloques_ref = db.collection("Temario AGE").document(bloque_id).collection("temas").document(tema_id).collection("subbloques").stream()
        grupo_actual = []
        total_tokens = 0
        todos_grupos = []

        for sub in subbloques_ref:
            datos = sub.to_dict()
            if not datos:
                continue
            texto = datos.get("texto", "").strip()
            titulo = datos.get("titulo", "")
            etiqueta = f"{bloque_id}-{tema_id}-{sub.id}"
            tokens = contar_tokens(texto)

            if tokens > limite_tokens:
                todos_grupos.append([{"etiqueta": etiqueta, "titulo": titulo, "texto": texto}])
                continue

            if total_tokens + tokens > limite_tokens:
                todos_grupos.append(grupo_actual)
                grupo_actual = []
                total_tokens = 0

            grupo_actual.append({"etiqueta": etiqueta, "titulo": titulo, "texto": texto})
            total_tokens += tokens

        if grupo_actual:
            todos_grupos.append(grupo_actual)
        resultado[tema_completo] = todos_grupos
    return resultado

# ✅ Obtiene el contexto completo de varios temas para usarlo en respuestas IA
def obtener_contexto_por_temas(db, temas, token_limit=3000):
    contexto_total = ""
    usados = set()

    bloques = db.collection("Temario AGE").list_documents()

    for bloque_doc in bloques:
        temas_ref = bloque_doc.collection("temas")
        for tema in temas:
            tema_doc = temas_ref.document(tema).get()
            if not tema_doc.exists:
                continue
            subbloques_ref = temas_ref.document(tema).collection("subbloques")
            subbloques = subbloques_ref.stream()

            for sub in subbloques:
                sub_id = f"{bloque_doc.id}-{tema}-{sub.id}"
                if sub_id in usados:
                    continue
                usados.add(sub_id)

                texto = sub.to_dict().get("texto", "")
                titulo = sub.to_dict().get("titulo", "")
                fragmento = f"[{sub_id}]\n{titulo}\n{texto.strip()}\n"
                if contar_tokens(contexto_total + fragmento) > token_limit:
                    return contexto_total.strip()
                contexto_total += fragmento

    return contexto_total.strip()

# ✅ NUEVA: Extrae todos los subbloques de todos los temas sin límite de tokens acumulados
def obtener_subbloques_individuales(db, temas: List[str]) -> List[dict]:
    subbloques_utilizados = []

    for tema_completo in temas:
        if "-" not in tema_completo:
            continue

        bloque_id, tema_id = tema_completo.split("-", 1)
        temas_ref = db.collection("Temario AGE").document(bloque_id).collection("temas")
        subbloques_ref = temas_ref.document(tema_id).collection("subbloques").stream()

        for sub in subbloques_ref:
            datos = sub.to_dict()
            if not datos:
                continue
            texto = datos.get("texto", "").strip()
            if len(texto.split()) < 30:
                continue
            if contar_tokens(texto) > 3000:
                texto = texto[:4000]  # recorte de seguridad

            subbloques_utilizados.append({
                "etiqueta": f"{bloque_id}-{tema_id}-{sub.id}",
                "titulo": datos.get("titulo", ""),
                "texto": texto
            })

    return subbloques_utilizados


    return contexto_total.strip()

