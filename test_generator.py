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
    max_intentos = num_preguntas * 2  # para reintentar si alguna pregunta falla

    instrucciones = (
        "Genera preguntas tipo test a partir del siguiente contenido. "
        "Cada pregunta debe tener:
"
        "- Un enunciado claro
"
        "- 4 opciones: A, B, C, D
"
        "- La respuesta correcta
"
        "- Una explicación breve basada en el contenido

"
        "Formato JSON:
"
        "{
"
        "  "pregunta": "...",
"
        "  "opciones": {"A": "...", "B": "...", "C": "...", "D": "..."},
"
        "  "respuesta_correcta": "A",
"
        "  "explicacion": "..."
"
        "}
"
        "Genera solo una pregunta por respuesta.
"
    )

    while len(preguntas_generadas) < num_preguntas and intentos < max_intentos:
        intentos += 1
        prompt = f"{instrucciones}

Contenido:
{contexto[:3000]}"

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
                print(f"❌ Pregunta descartada por formato inválido:
{contenido}\n")

        except Exception as e:
            print(f"⚠️ Error al generar pregunta: {e}")

    return {"test": preguntas_generadas}