
from utils import obtener_subbloques_individuales
from validador_preguntas import es_pregunta_valida
import openai
import os

openai.api_key = os.getenv("OPENAI_API_KEY")

def generar_test_avanzado(db, temas, num_preguntas=10):
    subbloques = obtener_subbloques_individuales(db, temas)
    contexto = ""
    for sub in subbloques:
        contexto += f"""[{sub['etiqueta']}]
{sub['titulo']}
{sub['texto']}

"""

    if not contexto:
        return []

    prompt = f"""
Eres un experto en oposiciones. Genera {num_preguntas} preguntas tipo test con 4 opciones (A, B, C, D) y una correcta.
Incluye también una breve explicación. Usa este contexto legal:
{contexto}
"""

    respuesta = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    texto_generado = respuesta.choices[0].message.content.strip()

    # Aquí podrías usar lógica más robusta
    preguntas = []  # 👈 Lógica para parsear preguntas, sustituir si tienes algo mejor

    for linea in texto_generado.split("\n\n"):
        if es_pregunta_valida(linea):
            preguntas.append(linea)

    return preguntas
