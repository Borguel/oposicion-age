# ✅ Versión fusionada: estructura original + reparto proporcional por tema

import random
import os
import json
from collections import defaultdict
from openai import OpenAI
from utils import obtener_contexto_por_temas, contar_tokens
from validador_preguntas import validar_pregunta

openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generar_test_avanzado(temas, db, num_preguntas=5):
    print("🔍 función generar_test_avanzado() llamada")
    print(f"🧪 Temas recibidos: {temas}")

    try:
        # Cargar el contexto completo por tema
        contexto_por_tema = {}
        total_tokens = 0

        for tema in temas:
            contexto = obtener_contexto_por_temas(db, [tema])
            tokens = contar_tokens(contexto)
            contexto_por_tema[tema] = {"texto": contexto, "tokens": tokens}
            total_tokens += tokens

        if total_tokens == 0:
            print("⚠️ No se ha encontrado contenido en los temas.")
            return {"test": []}

        # Calcular cuántas preguntas tocarían por tema proporcionalmente
        preguntas_por_tema = {}
        for tema, datos in contexto_por_tema.items():
            proporcion = datos["tokens"] / total_tokens
            preguntas_por_tema[tema] = max(1, round(proporcion * num_preguntas))

        # Ajustar para que la suma total no exceda
        ajuste = sum(preguntas_por_tema.values()) - num_preguntas
        while ajuste > 0:
            for tema in sorted(preguntas_por_tema, key=preguntas_por_tema.get, reverse=True):
                if preguntas_por_tema[tema] > 1:
                    preguntas_por_tema[tema] -= 1
                    ajuste -= 1
                    if ajuste == 0:
                        break

        print(f"📊 Distribución de preguntas por tema: {preguntas_por_tema}")

        preguntas_generadas = []

        instrucciones = (
            "Actúas como un generador profesional de preguntas tipo test, especializado en el Cuerpo General Administrativo del Estado (AGE). "
            "Tu objetivo es crear preguntas similares a las de exámenes oficiales de oposición, a partir del contenido proporcionado. "
            "Sigue estrictamente estas normas:

"
            "1. Las preguntas deben ser claras, completas, bien formuladas y redactadas en un estilo técnico-formal, como en los exámenes oficiales.
"
            "2. NO uses expresiones como 'según el texto', 'de acuerdo con lo anterior', 'en el contenido proporcionado', ni ninguna mención al origen del texto.
"
            "3. Sustituye todas las siglas (por ejemplo, 'CE') por su forma completa ('Constitución Española'), aunque en el texto aparezcan abreviadas.
"
            "4. Si el contenido no es suficiente para formular una pregunta profesional, omítelo. No inventes datos, no rellenes con lógica ni contexto externo.
"
            "5. Las opciones incorrectas deben ser verosímiles y creíbles, sin ser obviamente falsas ni incoherentes.
"
            "6. Redacta en un español neutro, técnico y preciso, evitando coloquialismos.

"
            "Formato de salida (JSON):
"
            "{
"
            "  "pregunta": "...",
"
            "  "opciones": {"A": "...", "B": "...", "C": "...", "D": "..."},
"
            "  "respuesta_correcta": "...",
"
            "  "explicacion": "..."
"
            "}"
        )

        for tema in temas:
            datos = contexto_por_tema[tema]
            for _ in range(preguntas_por_tema.get(tema, 0)):
                prompt = f"{instrucciones}

Contenido:
{datos['texto']}"

                try:
                    print(f"\n📤 Enviando prompt a OpenAI (tema: {tema}, tokens: {datos['tokens']})...\n")

                    respuesta = openai.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.4
                    )
                    generado = respuesta.choices[0].message.content.strip()
                    print(f"📩 Respuesta de OpenAI:\n{generado[:300]}...\n")

                    generado_json = json.loads(generado)
                    if validar_pregunta(generado_json):
                        preguntas_generadas.append(generado_json)
                        print(f"✅ Pregunta válida añadida del tema {tema}")
                    else:
                        print(f"⚠️ Pregunta inválida del tema {tema}")
                except Exception as e:
                    print(f"❌ Error generando pregunta para el tema {tema}: {e}")

        print(f"\n🎯 Total de preguntas generadas: {len(preguntas_generadas)}")
        return {"test": preguntas_generadas}

    except Exception as error:
        print(f"🔥 Error inesperado en generar_test_avanzado: {error}")
        return {"test": []}
