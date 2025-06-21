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
        "Eres un generador de tests de oposiciones para el Cuerpo General Administrativo del Estado (AGE). "
        "A partir del contenido proporcionado, genera preguntas tipo test con estas condiciones:\n"
        "- Formulación clara y completa, estilo examen oficial.\n"
        "- Nunca menciones expresiones como 'según el texto' o 'en el contenido anterior'.\n"
        "- 4 opciones (A, B, C, D), solo una es correcta.\n"
        "- Una explicación clara basada en el contenido.\n\n"
        "Formato JSON:\n"
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


    return {"test": preguntas_generadas}
