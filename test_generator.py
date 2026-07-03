import random
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from deepseek_utils import call_deepseek_api
from utils import obtener_subbloques_individuales, contar_tokens
from validador_preguntas import validar_pregunta

INSTRUCCIONES = (
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


def _generar_pregunta_desde_subbloque(sub):
    etiqueta = sub.get("etiqueta", "")
    contenido = sub.get("texto", "")
    if contar_tokens(contenido) > 3000:
        contenido = contenido[:4000]

    prompt = f"{INSTRUCCIONES}\n\nContenido:\n{contenido}"

    messages = [{"role": "user", "content": prompt}]

    try:
        generado = call_deepseek_api(messages, max_tokens=800, temperature=0.4)
        if not generado:
            return {"etiqueta": etiqueta, "error": "Sin respuesta de DeepSeek"}

        generado_json = json.loads(generado)

        if validar_pregunta(generado_json):
            return {"etiqueta": etiqueta, "pregunta": generado_json}
        return {"etiqueta": etiqueta, "error": "No pasó validación"}

    except json.JSONDecodeError as je:
        return {"etiqueta": etiqueta, "error": f"JSON inválido: {je}"}
    except Exception as e:
        return {"etiqueta": etiqueta, "error": f"Error DeepSeek: {e}"}


def generar_test_avanzado(temas, db, num_preguntas=5, coleccion="Temario AGE"):
    print("🔍 función generar_test_avanzado() llamada")
    print(f"🧪 Temas recibidos: {temas}")

    try:
        subbloques = obtener_subbloques_individuales(db, temas, coleccion=coleccion)
        if not subbloques:
            print("⚠️ No se encontraron subbloques.")
            return {"test": [], "advertencia": "No se encontraron subbloques válidos."}

        print(f"📚 Subbloques encontrados: {len(subbloques)}")
        random.shuffle(subbloques)

        # Pedimos de más (hasta el doble) para compensar preguntas que no pasen
        # la validación, y lanzamos todas las llamadas a la IA en paralelo en
        # vez de una detrás de otra, para que tarde segundos y no minutos.
        candidatos = subbloques[:max(num_preguntas * 2, num_preguntas)]

        preguntas_generadas = []
        usados = []
        errores = []

        with ThreadPoolExecutor(max_workers=min(10, len(candidatos))) as executor:
            futuros = [executor.submit(_generar_pregunta_desde_subbloque, sub) for sub in candidatos]
            for futuro in as_completed(futuros):
                resultado = futuro.result()
                if "pregunta" in resultado:
                    if len(preguntas_generadas) < num_preguntas:
                        preguntas_generadas.append(resultado["pregunta"])
                        usados.append(resultado["etiqueta"])
                else:
                    errores.append({"etiqueta": resultado["etiqueta"], "motivo": resultado["error"]})

        resultado_final = {
            "test": preguntas_generadas,
            "subbloques_utilizados": usados,
            "errores": errores
        }

        if len(preguntas_generadas) < num_preguntas:
            resultado_final["advertencia"] = f"Solo se generaron {len(preguntas_generadas)} de {num_preguntas} preguntas."

        print(f"🎯 Preguntas generadas: {len(preguntas_generadas)}")
        return resultado_final

    except Exception as error:
        print(f"🔥 Error inesperado en generar_test_avanzado: {error}")
        return {"test": [], "error": str(error)}

