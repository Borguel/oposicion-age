
import openai
from utils import obtener_contenido_relevante
import os

openai.api_key = os.getenv("OPENAI_API_KEY")

def responder_chat(mensaje_usuario, temas, db):
    contexto = obtener_contenido_relevante(temas, db)

    prompt = f"""Eres un asistente experto en oposiciones. Utiliza el siguiente contenido del temario para responder con claridad y precisión a la pregunta del usuario.

CONTENIDO DEL TEMARIO:
{contexto}

PREGUNTA DEL USUARIO:
{mensaje_usuario}
"""

    respuesta = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Eres un asistente experto en oposiciones."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=800
    )

    return respuesta.choices[0].message["content"].strip()
