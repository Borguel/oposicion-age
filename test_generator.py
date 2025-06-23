from utils import obtener_subbloques_individuales
from validador_preguntas import es_pregunta_valida
from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generar_test_avanzado(temas, db, num_preguntas=5):
    print(f"🧪 Generando test con temas: {temas} | Num: {num_preguntas}")
    
    subbloques = obtener_subbloques_individuales(db, temas, limite_total_tokens=3000)
    print(f"📚 Subbloques extraídos: {len(subbloques)}")

    if not subbloques:
        print("⚠️ No se encontraron subbloques con contenido válido.")
        return {"test": []}

    contexto = ""
    for bloque in subbloques:
        contexto += f"{bloque['titulo']}\n{bloque['texto']}\n\n"

    prompt = f"""
    A partir del siguiente contenido, genera {num_preguntas} preguntas tipo test con 4 opciones (A, B, C, D) y una única correcta. Formato JSON:
    {{
      "pregunta": "...",
      "opciones": {{
        "A": "...",
        "B": "...",
        "C": "...",
        "D": "..."
      }},
      "respuesta_correcta": "A",
      "explicacion": "..."
    }}

    CONTENIDO:
    {contexto}
    """

    print("📤 Enviando prompt a OpenAI...")
    respuesta = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    contenido = respuesta.choices[0].message.content.strip()
    print(f"📥 Respuesta de OpenAI:\n{contenido[:500]}...")  # solo primeros caracteres

    try:
        import json
        preguntas_generadas = json.loads(contenido)
        if not isinstance(preguntas_generadas, list):
            preguntas_generadas = [preguntas_generadas]
        preguntas_validas = [p for p in preguntas_generadas if es_pregunta_valida(p)]
        print(f"✅ Preguntas válidas generadas: {len(preguntas_validas)}")
        return {"test": preguntas_validas}
    except Exception as e:
        print(f"❌ Error al interpretar la respuesta: {e}")
        return {"test": []}
