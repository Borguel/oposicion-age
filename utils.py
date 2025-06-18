
import os
import tiktoken
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

enc = tiktoken.encoding_for_model("gpt-3.5-turbo")

def contar_tokens(texto):
    return len(enc.encode(texto))

def obtener_contexto_por_temas(db, temas):
    contexto = ""
    for tema_id in temas:
        tema_ref = db.collection("temario").document(tema_id)
        bloques = tema_ref.collection("bloques").stream()

        for bloque in bloques:
            bloque_ref = bloque.reference
            subbloques = bloque_ref.collection("subbloques").stream()

            for sub in subbloques:
                sub_id = sub.id
                sub_ref = sub.reference
                datos = sub.to_dict()
                contenido = datos.get("texto", "")

                necesita_corregir = (
                    len(contenido.strip()) < 200 or 
                    "..." in contenido or 
                    contar_tokens(contenido) < 100
                )

                if necesita_corregir:
                    prompt = f"""Este subbloque parece incompleto. Complétalo de forma coherente para su uso en oposiciones.

Título del subbloque: {sub_id}
Contenido parcial:
{contenido}

Contenido completo generado:"""

                    respuesta = client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": "Eres un redactor experto en legislación y oposiciones."},
                            {"role": "user", "content": prompt}
                        ],
                        max_tokens=1000,
                        temperature=0.5
                    )

                    texto_corregido = respuesta.choices[0].message.content.strip()

                    if contar_tokens(texto_corregido) <= 3000:
                        sub_ref.update({"texto": texto_corregido})
                        contenido = texto_corregido
                    else:
                        print(f"⚠️ Subbloque {sub_id} supera los 3000 tokens. No se ha guardado.")

                contexto += f"\n{sub_id}:\n{contenido}\n"
    return contexto
