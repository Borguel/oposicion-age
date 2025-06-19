from validador_preguntas import detectar_repeticiones, filtrar_preguntas_repetidas

def generar_test_avanzado(temas, db, num_preguntas=5, max_repeticiones=2):
    contexto = obtener_contexto_por_temas(db, temas)
    if not contexto:
        print("⚠️ Contexto vacío. No se puede generar test.")
        return {"test": []}

    # Lógica de límite dinámico según tabla preferida
    if num_preguntas <= 5:
        limite_tema = 1
    elif num_preguntas <= 10:
        limite_tema = 1
    elif num_preguntas <= 20:
        limite_tema = 2
    elif num_preguntas <= 50:
        limite_tema = 3
    else:
        limite_tema = 5

    prompt = f"""
Eres un generador experto en preguntas tipo test para oposiciones del Estado. A partir del contenido siguiente, redacta {num_preguntas} preguntas con estilo profesional, como las utilizadas en exámenes oficiales. Para cada pregunta:

- Usa redacción clara, formal y precisa.
- Si se menciona un artículo, incluye el nombre completo de la norma a la que pertenece (por ejemplo, "de la Constitución Española", "de la Ley Orgánica 6/1985, del Poder Judicial", etc.).
- Opciones tipo test en formato:
  A) ...
  B) ...
  C) ...
  D) ...
- Una línea con: Respuesta correcta: X
- Una línea con: Explicación clara, concisa y con referencia a la norma si procede.

⚠️ Importante: evita incluir más de {limite_tema} preguntas basadas en el mismo párrafo o idea concreta del texto.

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

    # Validación de repeticiones
    conceptos_repetidos = detectar_repeticiones(preguntas_formateadas, max_repeticiones)
    if conceptos_repetidos:
        print(f"🟠 Se detectaron conceptos repetidos: {conceptos_repetidos}")
        preguntas_filtradas = filtrar_preguntas_repetidas(preguntas_formateadas, conceptos_repetidos)
        preguntas_faltantes = num_preguntas - len(preguntas_filtradas)

        if preguntas_faltantes > 0:
            print(f"🔁 Faltan {preguntas_faltantes} preguntas. Regenerando las necesarias...")
            prompt_regenerado = f"Redacta {preguntas_faltantes} preguntas adicionales con los mismos criterios que antes, evitando repetir los siguientes conceptos: {', '.join(conceptos_repetidos.keys())}\n\n{contexto}"

            nueva_respuesta = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Eres un experto redactor de preguntas de oposición."},
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