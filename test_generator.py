import os
import random
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generar_test_avanzado(temas, db, num_preguntas=5):
    contexto = ""

    for tema_id in temas:
        subtemas = db.collection("temario").document(tema_id).collection("subtemas").stream()
        for sub in subtemas:
            datos = sub.to_dict()
            contexto += f"\n\n{sub.id}: {datos.get('contenido', '')}"

    if not contexto:
        return "No se encontró contenido relevante para los temas seleccionados."

    prompt = f"""
Actúa como generador experto de preguntas tipo test para oposiciones administrativas. Usa el contenido siguiente para redactar {num_preguntas} preguntas. Cada pregunta debe incluir:

- Enunciado claro.
- 4 opciones: A, B, C, D.
- Indica cuál es la opción correcta.
- Una explicación breve tras la respuesta correcta.

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

    return respuesta.choices[0].message.content.strip()


def generar_simulacro(db, num_preguntas=30):
    temas = [doc.id for doc in db.collection("temario").stream()]
    temas_seleccionados = random.sample(temas, min(len(temas), 5))
    return generar_test_avanzado(temas_seleccionados, db, num_preguntas)
