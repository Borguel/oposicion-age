
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
        random.shuffle(bloques)
        preguntas_tema = 0
        for grupo in bloques:
            if preguntas_tema >= preguntas_por_tema:
                break
            prompt = crear_prompt(grupo)
            try:
                respuesta = openai.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.4
                )
                generado = respuesta.choices[0].message.content.strip()
                generado_json = json.loads(generado)
                if validar_pregunta(generado_json):
                    preguntas_generadas.append(generado_json)
                    preguntas_tema += 1
                    preguntas_restantes -= 1
                    if preguntas_restantes <= 0:
                        break
            except Exception as e:
                print(f"❌ Error generando pregunta: {e}")
        if preguntas_restantes <= 0:
            break

    print(f"✅ Preguntas generadas: {len(preguntas_generadas)} / {num_preguntas}")
    return {"test": preguntas_generadas}

def crear_prompt(subbloques):
    instrucciones = (
        "Actúas como un generador profesional de preguntas tipo test, especializado en oposiciones AGE. "
        "No uses expresiones como 'según el texto'. Sustituye siglas por su forma completa. "
        "Opciones verosímiles. Español técnico. Devuelve en JSON con los campos pregunta, opciones (A-D), respuesta_correcta y explicacion.

"
    )
    contenido = "\n\n".join(sub["texto"] for sub in subbloques)
    return instrucciones + f"Contenido:
{contenido}"
