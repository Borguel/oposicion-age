# ✅ test_generator.py mejorado

import openai
import os
from utils import obtener_contexto_por_temas
from validador_preguntas import detectar_repeticiones, filtrar_preguntas_repetidas

openai.api_key = os.getenv("OPENAI_API_KEY")
client = openai

def parsear_preguntas(texto):
    bloques = texto.split("\n\n")
    preguntas = []
    contador = 1

    for bloque in bloques:
        bloque = bloque.strip()
        if not bloque or "Respuesta correcta" not in bloque:
            continue

        lineas = bloque.split("\n")
        enunciado = ""
        opciones = {}
        correcta = ""
        explicacion = ""

        for i, linea in enumerate(lineas):
            l = linea.strip()

            if not enunciado and not l.startswith(("A)", "B)", "C)", "D)", "Respuesta", "Explicación")):
                enunciado = l
                continue

            if l.startswith("A)"):
                opciones["A"] = l.split("A)", 1)[-1].strip()
            elif l.startswith("B)"):
                opciones["B"] = l.split("B)", 1)[-1].strip()
            elif l.startswith("C)"):
                opciones["C"] = l.split("C)", 1)[-1].strip()
            elif l.startswith("D)"):
                opciones["D"] = l.split("D)", 1)[-1].strip()
            elif "Respuesta correcta" in l:
                correcta = l.split(":")[-1].strip()
            elif "Explicación" in l:
                explicacion = l.split(":", 1)[-1].strip()

        # Validaciones
        if not enunciado or len(opciones) < 4:
            print(f"❌ Pregunta descartada (incompleta o con opciones insuficientes): {bloque[:80]}")
            continue

        preguntas.append({
            "pregunta": enunciado.strip(),
            "opciones": opciones,
            "respuesta_correcta": correcta,
            "explicacion": explicacion
        })
        contador += 1

    return preguntas

def generar_test_avanzado(temas, db, num_preguntas=5, max_repeticiones=2):
    contexto = obtener_contexto_por_temas(db, temas, token_limit=3000, limite=5)
    if not contexto:
        print("⚠️ Contexto vacío. No se puede generar test.")
        return {"test": []}

    if num_preguntas <= 10:
        limite_tema = 1
    elif num_preguntas <= 20:
        limite_tema = 2
    elif num_preguntas <= 50:
        limite_tema = 3
    else:
        limite_tema = 5

    prompt = f"""
Eres un generador experto en preguntas tipo test para oposiciones del Estado. A partir del contenido siguiente, redacta {num_preguntas} preguntas con estilo profesional, variado y realista, como las que aparecen en exámenes oficiales. Puedes usar diferentes estructuras de redacción:

- Preguntas directas (Ej: ¿Qué órgano...?)
- Preguntas con introducción normativa (Ej: Según el artículo..., ¿quién...?)
- Enunciados incompletos (Ej: La Ley X establece que...)

Cada pregunta debe incluir:
- Enunciado claro y formal.
- Opciones A) B) C) D)
- Respuesta correcta: X
- Explicación clara con referencia legal si es posible (Ej: "Según el art. 14 de la CE...")

Evita incluir más de {limite_tema} preguntas basadas en el mismo fragmento.

Contenido base:
{contexto}

Comienza ahora:
"""

    respuesta = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Eres un experto redactor de preguntas de examen tipo test para oposiciones del Estado."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=1800,
        temperature=0.5
    )

    texto_generado = respuesta.choices[0].message.content.strip()
    preguntas_formateadas = parsear_preguntas(texto_generado)

    conceptos_repetidos = detectar_repeticiones(preguntas_formateadas, max_repeticiones)
    if conceptos_repetidos:
        preguntas_filtradas = filtrar_preguntas_repetidas(preguntas_formateadas, conceptos_repetidos)
        preguntas_faltantes = num_preguntas - len(preguntas_filtradas)

        if preguntas_faltantes > 0:
            prompt_regenerado = f"Redacta {preguntas_faltantes} preguntas adicionales con los mismos criterios, evitando repetir: {', '.join(conceptos_repetidos.keys())}\n\n{contexto}"

            nueva_respuesta = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Eres un redactor experto de oposiciones."},
                    {"role": "user", "content": prompt_regenerado}
                ],
                max_tokens=1800,
                temperature=0.5
            )

            nuevas_preguntas = parsear_preguntas(nueva_respuesta.choices[0].message.content.strip())
            preguntas_finales = preguntas_filtradas + nuevas_preguntas[:preguntas_faltantes]
        else:
            preguntas_finales = preguntas_filtradas
    else:
        preguntas_finales = preguntas_formateadas

    return {"test": preguntas_finales}
