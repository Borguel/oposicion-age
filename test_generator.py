from utils import obtener_subbloques_individuales
from validador_preguntas import validar_pregunta
from openai import OpenAI
import os
import random

openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generar_test_avanzado(db, temas, num_preguntas=10):
    subbloques = obtener_subbloques_individuales(db, temas)
    contexto = ""
    for sub in subbloques:
        contexto += f"[{sub['etiqueta']}]\n{sub['titulo']}\n{sub['texto']}\n\n"

    prompt = f"""Eres un experto en preparar tests de oposiciones.

Con el siguiente contenido legal y normativo, genera {num_preguntas} preguntas tipo test con 4 opciones (A, B, C, D). Marca la opción correcta y añade una breve explicación de la respuesta.

Formato:
{{
  "pregunta": "...",
  "opciones": {{
    "A": "...",
    "B": "...",
    "C": "...",
    "D": "..."
  }},
  "respuesta_correcta": "A",
  "explicacion": "..."
}}

CONTEXTO:
{contexto}
"""

    respuesta = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )

    try:
        contenido = respuesta.choices[0].message.content
        preguntas_generadas = eval(contenido)
        if isinstance(preguntas_generadas, dict):
            preguntas_generadas = [preguntas_generadas]
        preguntas_filtradas = [p for p in preguntas_generadas if validar_pregunta(p)]
        return preguntas_filtradas
    except Exception as e:
        print("Error procesando preguntas:", e)
        return []