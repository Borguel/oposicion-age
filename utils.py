
# ✅ utils.py corregido y definitivo

import re
import random
import tiktoken
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI()

def contar_tokens(texto, modelo="gpt-3.5-turbo"):
    try:
        codificador = tiktoken.encoding_for_model(modelo)
    except KeyError:
        codificador = tiktoken.get_encoding("cl100k_base")
    return len(codificador.encode(texto))

def obtener_contexto_por_temas(db, temas, token_limit=3000, limite=None):
    contexto = ""
    subbloques_total = []

    for tema_id in temas[:limite] if limite else temas:
        bloques = db.collection("temario").document(tema_id).collection("bloques").stream()
        for bloque in bloques:
            subbloques = db.collection("temario").document(tema_id)\
                            .collection("bloques").document(bloque.id)\
                            .collection("subbloques").stream()

            for sub in subbloques:
                data = sub.to_dict()
                sub_id = sub.id
                sub_ref = sub.reference
                contenido = data.get("texto", "").strip()

                if not contenido:
                    print(f"⚠️ Subbloque vacío: {sub_id}")
                    continue

                necesita_corregir = (
                    len(contenido) < 200 or
                    "..." in contenido or
                    contar_tokens(contenido) < 100
                )

                if necesita_corregir:
                    prompt = f"""Este subbloque parece incompleto. Complétalo manteniendo fidelidad legal al contenido y estilo jurídico-administrativo:

Texto original:
\"\"\"{contenido}\"\"\"

Texto corregido:"""

                    try:
                        respuesta = client.chat.completions.create(
                            model="gpt-3.5-turbo",
                            messages=[
                                {"role": "system", "content": "Eres un redactor legal experto en oposiciones."},
                                {"role": "user", "content": prompt}
                            ],
                            max_tokens=700,
                            temperature=0.5
                        )
                        texto_corregido = respuesta.choices[0].message.content.strip()
                        sub_ref.update({"texto": texto_corregido})
                        contenido = texto_corregido
                    except Exception as e:
                        print(f"❌ Error al completar subbloque {sub_id}: {e}")
                        continue

                subbloques_total.append(f"\n{sub_id}:\n{contenido}\n")

    random.shuffle(subbloques_total)
    token_total = 0
    resultado = []

    for fragmento in subbloques_total:
        tokens = contar_tokens(fragmento)
        if token_total + tokens > token_limit:
            break
        resultado.append(fragmento)
        token_total += tokens

    contexto = "\n".join(resultado)
    return contexto
