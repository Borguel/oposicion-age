from utils import obtener_subbloques_individuales, contar_tokens
from validador_preguntas import validar_pregunta
import openai
import os

openai.api_key = os.getenv("OPENAI_API_KEY")

def generar_test_avanzado(db, temas, num_preguntas=10):
    subbloques = obtener_subbloques_individuales(db, temas)
    contexto = ""
    for sub in subbloques:
        contexto += f"[{sub['etiqueta']}]
{sub['titulo']}
{sub['texto']}

"

    prompt = f"""
Eres un experto creando tests de oposiciones. A partir del siguiente contenido:

{contexto}

Crea {num_preguntas} preguntas tipo test con 4 opciones (A, B, C, D), una correcta y una explicación. Devuélvelas en JSON así:
{{
  "pregunta": "...",
  "opciones": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
  "respuesta_correcta": "A",
  "explicacion": "..."
}}
"""

    respuesta = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    try:
        contenido = respuesta.choices[0].message.content
        preguntas = eval(contenido) if isinstance(contenido, str) else contenido
        return [p for p in preguntas if validar_pregunta(p)]
    except Exception:
        return []