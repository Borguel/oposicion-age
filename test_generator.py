from utils import obtener_subbloques_individuales
from validador_preguntas import es_pregunta_valida
import openai
import os

openai.api_key = os.getenv("OPENAI_API_KEY")

def generar_test_avanzado(db, temas, num_preguntas=10):
    subbloques = obtener_subbloques_individuales(db, temas)
    contexto = ""
    for sub in subbloques:
        contexto += f"[{sub['etiqueta']}]\n{sub['titulo']}\n{sub['texto']}\n\n"

    if not contexto:
        return []

    prompt = f"""Eres un experto en oposiciones. Genera {num_preguntas} preguntas tipo test con 4 opciones (A, B, C, D), una correcta y una explicación. Usa este contexto legal:
{contexto}"""

    try:
        respuesta = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        texto_generado = respuesta.choices[0].message.content.strip()
    except Exception as e:
        print("❌ Error con OpenAI:", e)
        return []

    preguntas = []
    bloques = texto_generado.split("\n\n")
    for bloque in bloques:
        if es_pregunta_valida(bloque):
            preguntas.append(bloque)

    return preguntas

