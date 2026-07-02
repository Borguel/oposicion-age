import random
import os
import json
from openai import OpenAI
from utils import obtener_subbloques_individuales, contar_tokens
from validador_preguntas import validar_pregunta

openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generar_test_avanzado(temas, db, num_preguntas=5):
    print("🔍 función generar_test_avanzado() llamada")
    print(f"🧪 Temas recibidos: {temas}")

    try:
        subbloques = obtener_subbloques_individuales(db, temas)
        if not subbloques:
            print("⚠️ No se encontraron subbloques.")
            return {"test": [], "advertencia": "No se encontraron subbloques válidos."}

        print(f"📚 Subbloques encontrados: {len(subbloques)}")
        random.shuffle(subbloques)

        preguntas_generadas = []
        usados = set()
        errores = []

        instrucciones = (
            "Actúas como un generador profesional de preguntas tipo test, especializado en el Cuerpo General Administrativo del Estado (AGE). "
            "Tu objetivo es crear preguntas similares a las de exámenes oficiales de oposición, a partir del contenido proporcionado. "
            "Sigue estrictamente estas normas:\n\n"
            "1. Las preguntas deben ser claras, completas, bien formuladas y redactadas en un estilo técnico-formal.\n"
            "2. NO uses expresiones como 'según el texto', 'de acuerdo con lo anterior', 'en el contenido proporcionado'.\n"
            "3. Sustituye todas las siglas por su forma completa.\n"
            "4. Si el contenido no es suficiente, omítelo. No inventes datos.\n"
            "5. Las opciones incorrectas deben ser creíbles.\n"
            "6. Prioriza variedad temática.\n"
            "7. Redacta en un español técnico y preciso.\n\n"
            "Formato JSON:\n"
            "{\"pregunta\": \"...\", \"opciones\": {\"A\": \"...\", \"B\": \"...\", \"C\": \"...\", \"D\": \"...\"}, \"respuesta_correcta\": \"...\", \"explicacion\": \"...\"}"
        )

        while subbloques and len(preguntas_generadas) < num_preguntas:
            sub = subbloques.pop(0)
            etiqueta = sub.get("etiqueta", "")
            if etiqueta in usados:
                continue
            usados.add(etiqueta)

            contenido = sub.get("texto", "")
            if contar_tokens(contenido) > 3000:
                contenido = contenido[:4000]

            prompt = f"{instrucciones}\n\nContenido:\n{contenido}"

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
                else:
                    errores.append({"etiqueta": etiqueta, "motivo": "No pasó validación"})

            except json.JSONDecodeError as je:
                errores.append({"etiqueta": etiqueta, "motivo": f"JSON inválido: {je}"})
            except Exception as e:
                errores.append({"etiqueta": etiqueta, "motivo": f"Error GPT: {e}"})

        resultado_final = {
            "test": preguntas_generadas,
            "subbloques_utilizados": list(usados),
            "errores": errores
        }

        if len(preguntas_generadas) < num_preguntas:
            resultado_final["advertencia"] = f"Solo se generaron {len(preguntas_generadas)} de {num_preguntas} preguntas."

        print(f"🎯 Preguntas generadas: {len(preguntas_generadas)}")
        return resultado_final

    except Exception as error:
        print(f"🔥 Error inesperado en generar_test_avanzado: {error}")
        return {"test": [], "error": str(error)}

