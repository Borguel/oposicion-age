import os
import random
import re
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def parsear_preguntas(texto):
    bloques = texto.strip().split("\n\n")
    preguntas = []
    actual = {}

    for bloque in bloques:
        if bloque.lower().startswith("pregunta") or bloque.startswith("**Pregunta"):
            if actual:
                preguntas.append(actual)
                actual = {}
            actual["pregunta"] = bloque.split(":", 1)[-1].strip()
        elif bloque.startswith("A)"):
            actual["opciones"] = {
                "A": bloque[3:].strip()
            }
        elif bloque.startswith("B)"):
            actual["opciones"]["B"] = bloque[3:].strip()
        elif bloque.startswith("C)"):
            actual["opciones"]["C"] = bloque[3:].strip()
        elif bloque.startswith("D)"):
            actual["opciones"]["D"] = bloque[3:].strip()
        elif "Respuesta correcta" in bloque:
            match = re.search(r"Respuesta correcta[:\-]?\s*([A-D])", bloque)
            if match:
                actual["respuesta_correcta"] = match.group(1)
        elif "Explicación" in bloque or "explicación" in bloque.lower():
            actual["explicacion"] = bloque.split(":", 1)[-1].strip()

    if actual:
        preguntas.append(actual)

    return preguntas


def generar_test_avanzado(temas, db, num_preguntas=5):
    contexto = ""

    for tema_id in temas:
        subtemas = db.collection("temario").document(tema_id).collection("subtemas").stream()
        for sub in subtemas:
            datos = sub.to_dict()
            contexto += f"\n\n{sub.id}: {datos.get('contenido', '')}"

    if not contexto:
        return {"test": []}

    prompt = f"""
Actúa como generador experto de preguntas tipo test para oposiciones administrativas. Usa el contenido siguiente para redactar {num_preguntas} preguntas. Cada pregunta debe incluir:

- Enunciado claro
- Opciones: A), B), C), D)
- Indica la opción correcta (Respuesta correcta: X)
- Explicación breve

Contenido de referencia:
{contexto}

Genera el test:
"""

    respuesta = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Eres un generador experto de preguntas de oposición con explicaciones."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=1500,
        temperature=0.6
    )

    texto_generado = respuesta.choices[0].message.content.strip()
    preguntas_formateadas = parsear_preguntas(texto_generado)

    return {"test": preguntas_formateadas}


def generar_simulacro(db, num_preguntas=30):
    temas = [doc.id for doc in db.collection("temario").stream()]
    temas_seleccionados = random.sample(temas, min(len(temas), 5))
    return generar_test_avanzado(temas_seleccionados, db, num_preguntas)
