import os
import random
import re
from openai import OpenAI
from dotenv import load_dotenv
from utils import obtener_contexto_por_temas

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def parsear_preguntas(texto):
    preguntas = []
    bloques = texto.strip().split("**")
    for bloque in bloques:
        bloque = bloque.strip()
        if not bloque:
            continue

        pregunta_match = re.search(r"(Pregunta\s*\d*:?\s*)?(.*?)\n", bloque)
        if not pregunta_match:
            continue

        pregunta_texto = pregunta_match.group(2).strip()
        opciones_match = re.findall(r"([A-D])\)\s*(.*?)\s*(?=(?:[A-D]\)|Respuesta correcta|Explicación|$))", bloque, re.DOTALL)

        if len(opciones_match) != 4:
            continue

        opciones = {letra: texto.strip() for letra, texto in opciones_match}

        respuesta_match = re.search(r"Respuesta correcta[:\-]?\s*([A-D])", bloque)
        respuesta = respuesta_match.group(1) if respuesta_match else "No indicada"

        explicacion_match = re.search(r"Explicaci[oó]n[:\-]?\s*(.*)", bloque, re.DOTALL)
        explicacion = explicacion_match.group(1).strip() if explicacion_match else "Explicación no disponible"

        preguntas.append({
            "pregunta": pregunta_texto,
            "opciones": opciones,
            "respuesta_correcta": respuesta,
            "explicacion": explicacion
        })

    print(f"GPT generó {len(preguntas)} preguntas")
    return preguntas

def generar_test_avanzado(temas, db, num_preguntas=5):
    contexto = obtener_contexto_por_temas(db, temas)
    if not contexto:
        print("⚠️ Contexto vacío. No se puede generar test.")
        return {"test": []}

    prompt = f"""
Eres un generador experto en preguntas tipo test para oposiciones. A partir del contenido siguiente, redacta {num_preguntas} preguntas. Para cada pregunta, incluye obligatoriamente:

- El enunciado completo.
- Opciones en formato:
  A) ...
  B) ...
  C) ...
  D) ...
- Una línea con: Respuesta correcta: X (donde X es la letra correcta)
- Una línea con: Explicación detallada y clara de por qué esa es la respuesta correcta

Contenido base:
{contexto}

Comienza ahora:
"""

    respuesta = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Eres un experto generador de preguntas de oposición con explicaciones detalladas."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=1800,
        temperature=0.5
    )

    texto_generado = respuesta.choices[0].message.content.strip()
    print("GPT generó:\n", texto_generado)
    preguntas_formateadas = parsear_preguntas(texto_generado)

    return {"test": preguntas_formateadas}

def generar_simulacro(db, num_preguntas=30):
    temas = [doc.id for doc in db.collection("temario").stream()]
    temas_seleccionados = random.sample(temas, min(len(temas), 5))
    return generar_test_avanzado(temas_seleccionados, db, num_preguntas)

