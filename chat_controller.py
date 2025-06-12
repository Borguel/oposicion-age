import os
from openai import OpenAI
from dotenv import load_dotenv
from utils import obtener_contexto_por_temas

load_dotenv()

print("CLAVE:", os.getenv("OPENAI_API_KEY"))

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def responder_chat(pregunta, db):
    contexto = obtener_contexto_por_temas(pregunta, db)
    if not contexto:
        contexto = "No se encontró información específica, responde con base en el temario general."

    prompt = f"""
Responde con claridad, precisión y tono profesional a la siguiente pregunta de un opositor basada en el contenido normativo del temario:

Contexto:
{contexto}

Pregunta:
{pregunta}
    """

    respuesta = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Eres un asistente experto en normativa administrativa española para opositores."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=700,
        temperature=0.4
    )

    return respuesta.choices[0].message.content.strip()
