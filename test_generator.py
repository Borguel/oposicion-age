
import random
import json
import os
from openai import OpenAI
from utils import agrupar_subbloques_por_tema
from validador_preguntas import validar_pregunta

openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generar_test_avanzado(temas, db, num_preguntas=5):
    print("🔍 generar_test_avanzado()")

    bloques_por_tema = agrupar_subbloques_por_tema(db, temas)
    preguntas_generadas = []
    preguntas_por_tema = max(1, num_preguntas // len(bloques_por_tema))
    preguntas_restantes = num_preguntas

    for tema, bloques in bloques_por_tema.items():
        print(f"📦 Tema: {tema}, grupos disponibles: {len(bloques)}")
        random.shuffle(bloques)
        preguntas_tema = 0
        for grupo in bloques:
            if preguntas_tema >= preguntas_por_tema:
                break
            prompt = crear_prompt(grupo)
            print(f"📌 Intentando generar pregunta {preguntas_tema + 1} para tema {tema}")
            print(f"🔤 Prompt tokens: {len(prompt)}")
            try:
                respuesta = openai.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.4
                )
                generado = respuesta.choices[0].message.content.strip()
                print(f"📤 Respuesta cruda:
{generado[:500]}")

                generado_json = json.loads(generado)
                if validar_pregunta(generado_json):
                    preguntas_generadas.append(generado_json)
                    preguntas_tema += 1
                    preguntas_restantes -= 1
                    print(f"✅ Pregunta válida añadida")
                    if preguntas_restantes <= 0:
                        break
                else:
                    print(f"⚠️ Pregunta inválida (no pasó validador)")
            except json.JSONDecodeError as je:
                print(f"❌ Error JSON: {je}")
            except Exception as e:
                print(f"❌ Error generando pregunta: {e}")
        if preguntas_restantes <= 0:
            break

    print(f"🎯 Total preguntas generadas: {len(preguntas_generadas)} / {num_preguntas}")
    return {"test": preguntas_generadas}

def crear_prompt(subbloques):
    instrucciones = """Actúas como un generador profesional de preguntas tipo test, especializado en el Cuerpo General Administrativo del Estado (AGE).
Tu objetivo es crear preguntas similares a las de exámenes oficiales de oposición, a partir del contenido proporcionado.
Sigue estrictamente estas normas:

1. Las preguntas deben ser claras, completas, bien formuladas y redactadas en un estilo técnico-formal, como en los exámenes oficiales.
2. NO uses expresiones como 'según el texto', 'de acuerdo con lo anterior', 'en el contenido proporcionado', ni ninguna mención al origen del texto.
3. Sustituye todas las siglas (por ejemplo, 'CE') por su forma completa ('Constitución Española'), aunque en el texto aparezcan abreviadas.
4. Si el contenido no es suficiente para formular una pregunta profesional, omítelo. No inventes datos, no rellenes con lógica ni contexto externo.
5. Las opciones incorrectas deben ser verosímiles y creíbles, sin ser obviamente falsas ni incoherentes.
6. Prioriza extraer preguntas desde subbloques distintos para asegurar variedad temática en cada test.
7. Redacta en un español neutro, técnico y preciso, evitando coloquialismos.

Formato de salida (JSON):
{
  "pregunta": "...",
  "opciones": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "respuesta_correcta": "...",
  "explicacion": "..."
}"""
    contenido = "\n\n".join(sub["texto"] for sub in subbloques)
    return instrucciones + f"\n\nContenido:\n{{contenido}}"
