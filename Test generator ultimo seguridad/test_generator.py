import random
from utils import obtener_contexto_por_temas
from validador_preguntas import validar_pregunta
from openai import OpenAI
import os
from collections import defaultdict

openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generar_test_avanzado(temas, db, num_preguntas=5):
    contexto_completo = obtener_contexto_por_temas(db, temas, token_limit=3000)
    if not contexto_completo:
        return {"test": []}

    # Separar fragmentos por subbloque usando el prefijo [bloque-tema - subbloque]
    fragmentos = contexto_completo.strip().split("\n[")
    subbloques = {}

    for frag in fragmentos:
        if not frag.strip():
            continue
        if frag.startswith("["):
            etiqueta, texto = frag.split("\n", 1)
        else:
            etiqueta = "[" + frag.split("\n", 1)[0]
            texto = frag[len(etiqueta) + 1:]
        subbloques[etiqueta.strip("[]")] = texto.strip()

    subbloques_items = list(subbloques.items())
    random.shuffle(subbloques_items)

    preguntas_generadas = []
    intentos = 0
    max_intentos = num_preguntas * 3
    preguntas_por_subbloque = defaultdict(int)

    instrucciones = (
        "Actúas como un generador profesional de preguntas tipo test, especializado en el Cuerpo General Administrativo del Estado (AGE). "
        "Tu objetivo es crear preguntas similares a las de exámenes oficiales de oposición, a partir del contenido proporcionado. "
        "Sigue estrictamente estas normas:\n\n"
        "1. Las preguntas deben ser claras, completas, bien formuladas y redactadas en un estilo técnico-formal, como en los exámenes oficiales.\n"
        "2. NO uses expresiones como 'según el texto', 'de acuerdo con lo anterior', 'en el contenido proporcionado', ni ninguna mención al origen del texto.\n"
        "3. Sustituye todas las siglas (por ejemplo, 'CE') por su forma completa ('Constitución Española'), aunque en el texto aparezcan abreviadas.\n"
        "4. Si el contenido no es suficiente para formular una pregunta profesional, omítelo. No inventes datos, no rellenes con lógica ni contexto externo.\n"
        "5. Las opciones incorrectas deben ser verosímiles y creíbles, sin ser obviamente falsas ni incoherentes.\n"
        "6. Prioriza extraer preguntas desde subbloques distintos para asegurar variedad temática en cada test.\n"
        "7. Redacta en un español neutro, técnico y preciso, evitando coloquialismos.\n\n"
        "Formato de salida (JSON):\n"
        "{\n"
        "  \"pregunta\": \"...\",\n"
        "  \"opciones\": {\"A\": \"...\", \"B\": \"...\", \"C\": \"...\", \"D\": \"...\"},\n"
        "  \"respuesta_correcta\": \"...\",\n"
        "  \"explicacion\": \"...\"\n"
        "}"
    )

    for etiqueta, contenido in subbloques_items:
        if len(preguntas_generadas) >= num_preguntas or intentos >= max_intentos:
            break
        if preguntas_por_subbloque[etiqueta] >= 2:
            continue  # máximo 2 por subbloque

        prompt = f"{instrucciones}\n\nContenido:\n{contenido}"

        try:
            respuesta = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4
            )
            resultado = respuesta.choices[0].message.content.strip()
            pregunta = eval(resultado) if resultado.startswith("{") else None

            if validar_pregunta(pregunta):
                preguntas_generadas.append(pregunta)
                preguntas_por_subbloque[etiqueta] += 1
            else:
                print(f"❌ Pregunta inválida de [{etiqueta}]: {resultado}")
        except Exception as e:
            print(f"⚠️ Error generando pregunta para [{etiqueta}]: {e}")
        intentos += 1

    return {"test": preguntas_generadas}

