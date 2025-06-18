
import os
import tiktoken
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Usamos el codificador de tokens para gpt-3.5-turbo
enc = tiktoken.encoding_for_model("gpt-3.5-turbo")

def contar_tokens(texto):
    return len(enc.encode(texto))

def obtener_contexto_por_temas(db, temas):
    contexto = ""
    for tema in temas:
        tema_doc = db.collection("temario").document(tema)
        subtemas = tema_doc.collection("subtemas").stream()
        for sub in subtemas:
            sub_id = sub.id
            sub_ref = sub.reference
            datos = sub.to_dict()
            contenido = datos.get("contenido", "")

            necesita_corregir = (
                len(contenido.strip()) < 200 or 
                "..." in contenido or 
                contar_tokens(contenido) < 100
            )

            if necesita_corregir:
                prompt = f"""Este subtema parece incompleto. Rellena su contenido de forma coherente para usarlo en un test de oposiciones.

Título del subtema: {sub_id}
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

                # Verificamos que no supere los 3000 tokens antes de actualizar Firestore
                if contar_tokens(texto_corregido) <= 3000:
                    sub_ref.update({"contenido": texto_corregido})
                    contenido = texto_corregido
                else:
                    print(f"⚠️ Subtema {sub_id} generado supera los 3000 tokens y no se ha guardado.")

            contexto += f"\n{sub_id}:\n{contenido}\n"
    return contexto
