import random
from utils import obtener_contexto_por_temas
from validador_preguntas import validar_pregunta
from openai import OpenAI
import os

openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generar_test_avanzado(temas, db, num_preguntas=5):
    contexto = obtener_contexto_por_temas(db, temas, token_limit=3000)
    if not contexto:
        print("⚠️ No se encontró contenido relevante en Firestore.")
        return {"test": []}

    preguntas_generadas = []
    intentos = 0
    max_intentos = num_preguntas * 3  # más margen por si falla alguna

    instrucciones = (
        "Genera una pregunta tipo test a partir del siguiente contenido extraído de un temario de oposiciones. "
        "La pregunta debe tener:\n"
        "- Un enunciado claro (basado en el contenido)\n"
        "- 4 opciones (A, B, C, D)\n"
        "- Indicar la opción correcta\n"
        "- Una explicación breve con base en el texto\n\n"
        "Devuélvelo en formato JSON así:\n"
        "{\n"
        "  \"pregunta\": \"...\",\n"
        "  \"opciones\": {\"A\": \"...\", \"B\": \"...\", \"C\": \"...\", \"D\": \"...\"},\n"
        "  \"respuesta_correcta\": \"A\",\n"
        "  \"explicacion\": \"...\"\n"
        "}\n"
        "Genera solo una pregunta por respuesta."
    )

    while len(preguntas_generadas) < num_preguntas and intentos < max_intentos:
        intentos += 1
        prompt = f"{instrucciones}\n\nContenido:\n{contexto}"

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
                print("❌ Pregunta descartada. Formato inválido o incompleto.")
                print(contenido)

        except Exception as e:
            print(f"⚠️ Error al generar pregunta: {e}")

    return {"test": preguntas_generadas}
