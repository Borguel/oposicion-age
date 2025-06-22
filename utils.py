import firebase_admin
from firebase_admin import credentials, firestore
import os
import tiktoken

# Inicializar Firebase solo si no se ha hecho ya
if not firebase_admin._apps:
    cred = credentials.Certificate("clave-firebase.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()

def contar_tokens(texto, modelo="gpt-3.5-turbo"):
    try:
        encoding = tiktoken.encoding_for_model(modelo)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(texto))


def obtener_contexto_por_temas(db, temas, token_limit=3000):
    contexto_total = ""
    usados = set()

    for tema in temas:
        bloques = db.collection("Temario AGE").list_documents()
        for bloque_doc in bloques:
            temas_ref = bloque_doc.collection("temas")
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