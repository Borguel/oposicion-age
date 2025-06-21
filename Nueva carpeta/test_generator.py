import random
from utils import obtener_contexto_por_temas
from validador_preguntas import validar_pregunta
from openai import OpenAI
import os

openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generar_test_avanzado(temas, db, num_preguntas=5):
    contexto = obtener_contexto_por_temas(db, temas, token_limit=3000)
    if not contexto:
        return {"test": []}

    preguntas_generadas = []
    intentos = 0
    max_intentos = num_preguntas * 2  # reintentos en caso de preguntas fallidas

    instrucciones = (
        "Eres un generador de preguntas tipo test para una oposición del Estado (Grupo C1 - Administración General del Estado). "
        "A partir del contenido que te doy, redacta preguntas realistas como las que aparecen en exámenes oficiales. "
        "Si el contenido es limitado, usa tu conocimiento general de derecho administrativo y constitucional para reforzar el contexto.\n\n"
        "Cada pregunta debe tener:\n"
        "- Un enunciado claro, sin decir 'según el contenido' ni referencias al texto.\n"
        "- 4 opciones: A, B, C, D\n"
        "- La respuesta correcta (una sola letra)\n"
        "- Una explicación breve, clara y objetiva, pero sin citar el texto literalmente.\n\n"
        "Devuelve una única pregunta en este formato JSON:\n"
        "{\n"
        "  \"pregunta\": \"...\",\n"
        "  \"opciones\": {\"A\": \"...\", \"B\": \"...\", \"C\": \"...\", \"D\": \"...\"},\n"
        "  \"respuesta_correcta\": \"A\",\n"
        "  \"explicacion\": \"...\"\n"
        "}"
    )

    while len(preguntas_generadas) < num_preguntas and intentos < max_intentos:
        intentos += 1
        prompt = f"{instrucciones}\n\nContenido:\n{contexto[:3000]}"

        try:
            respuesta = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )

            contenido = respuesta.choices[0].message.content.strip()

            pregunta = eval(contenido) if contenido.startswith("{") else None

            if validar_pregunta(pregunta):
                preguntas_generadas.append(pregunta)
            else:
                print(f"❌ Pregunta descartada por formato inválido:\n{contenido}\n")

        except Exception as e:
            print(f"⚠️ Error al generar pregunta: {e}")

    return {"test": preguntas_generadas}