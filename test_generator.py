import random
from openai import OpenAI
from utils import obtener_subbloques_individuales, contar_tokens
from validador_preguntas import es_pregunta_valida

openai = OpenAI()

# ✔️ Ruta para generar test avanzado
def generar_test_avanzado(db, temas: list, num_preguntas: int):
    print("\n\U0001f4cb Generando test avanzado...")
    print(f"Temas recibidos: {temas}")
    print(f"Número de preguntas solicitadas: {num_preguntas}")

    # ✅ Obtener subbloques con límite de tokens
    subbloques = obtener_subbloques_individuales(db, temas)
    print(f"Subbloques encontrados: {len(subbloques)}")

    if not subbloques:
        print("\u274c No se encontraron subbloques.")
        return {"test": []}

    # ✅ Construir el contexto
    contexto = ""
    for sub in subbloques:
        fragmento = f"[{sub['etiqueta']}]:\n{sub['titulo']}\n{sub['texto']}\n"
        if contar_tokens(contexto + fragmento) > 3000:
            break
        contexto += fragmento

    print(f"\u2705 Tokens totales del contexto: {contar_tokens(contexto)}")

    if not contexto.strip():
        print("\u274c Contexto vacío tras filtrar por tokens.")
        return {"test": []}

    # ✅ Prompt para generar preguntas
    prompt = f"""
Eres un experto en oposiciones de la Administración General del Estado. Genera {num_preguntas} preguntas tipo test basadas en el siguiente texto. Cada pregunta debe tener 4 opciones (A, B, C, D), una correcta y una explicación clara. El formato debe ser:

{{
  "pregunta": "...",
  "opciones": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
  "respuesta_correcta": "A",
  "explicacion": "..."
}}

Texto:
{contexto}
"""

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=2000
        )
        contenido = response.choices[0].message.content
        print("\u2705 Respuesta generada por GPT-3.5-Turbo")

    except Exception as e:
        print(f"\u274c Error al llamar a OpenAI: {e}")
        return {"test": []}

    # ✅ Convertir texto a JSON
    try:
        import json
        preguntas = json.loads(contenido)
        print(f"\u2705 Preguntas generadas: {len(preguntas)}")
    except Exception as e:
        print(f"\u274c Error al convertir la respuesta en JSON: {e}")
        return {"test": []}

    # ✅ Validar preguntas
    preguntas_validas = [p for p in preguntas if es_pregunta_valida(p)]
    print(f"\u2705 Preguntas válidas: {len(preguntas_validas)}")

    if not preguntas_validas:
        print("\u274c Ninguna pregunta pasó la validación")
        return {"test": []}

    seleccionadas = random.sample(preguntas_validas, min(num_preguntas, len(preguntas_validas)))
    return {"test": seleccionadas}