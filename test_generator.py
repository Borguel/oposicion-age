import random
import os
import json
from collections import defaultdict
from openai import OpenAI
from utils import obtener_subbloques_individuales, contar_tokens
from validador_preguntas import validar_pregunta

openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generar_test_avanzado(temas, db, num_preguntas=5):
    subbloques = obtener_subbloques_individuales(db, temas)
    if not subbloques:
        print("⚠️ No se encontraron subbloques.")
        return {"test": []}

    random.shuffle(subbloques)

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

    for sub in subbloques:
        if len(preguntas_generadas) >= num_preguntas or intentos >= max_intentos:
            break

        etiqueta = sub.get("etiqueta", "")
        contenido = sub.get("texto", "")
        if preguntas_por_subbloque[etiqueta] >= 2:
            continue

        prompt = f"{instrucciones}\n\nContenido:\n{contenido}"

        try:
            print(f"\n📤 Enviando prompt a OpenAI (subbloque: {etiqueta}, tokens: {contar_tokens(prompt)}):\n{prompt[:300]}...\n")

            respuesta = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4
            )
            generado = respuesta.choices[0].message.content.strip()
            print(f"📩 Respuesta de OpenAI (subbloque: {etiqueta}):\n{generado}\n")

            try:
                generado_json = json.loads(generado)
                if validar_pregunta(generado_json):
                    preguntas_generadas.append(generado_json)
                    preguntas_por_subbloque[etiqueta] += 1
                    print(f"✅ Pregunta válida añadida del subbloque {etiqueta}")
                else:
                    print(f"⚠️ Pregunta inválida según el validador del subbloque {etiqueta}")
            except json.JSONDecodeError as je:
                print(f"❌ Error JSON en subbloque {etiqueta}: {je}")

        except Exception as e:
            print(f"❌ Error general con subbloque {etiqueta}: {e}")

        intentos += 1

    print(f"\n🎯 Total de preguntas generadas: {len(preguntas_generadas)}")
    return {"test": preguntas_generadas}


