import random
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from deepseek_utils import call_deepseek_api
from utils import obtener_subbloques_individuales, contar_tokens
from validador_preguntas import validar_pregunta
from oposiciones import OPOSICIONES, OPOSICION_POR_DEFECTO


def _instrucciones(oposicion):
    nombre = OPOSICIONES.get(oposicion, OPOSICIONES[OPOSICION_POR_DEFECTO])["nombre"]
    return (
        f"Actúas como un generador profesional de preguntas tipo test, especializado en la oposición "
        f"al {nombre}. "
        "Tu objetivo es crear preguntas similares a las de exámenes oficiales de oposición, a partir del contenido proporcionado. "
        "Sigue estrictamente estas normas:\n\n"
        "1. Las preguntas deben ser claras, completas, bien formuladas y redactadas en un estilo técnico-formal.\n"
        "2. NO uses expresiones como 'según el texto', 'de acuerdo con lo anterior', 'en el contenido proporcionado'.\n"
        "3. Sustituye todas las siglas por su forma completa.\n"
        "4. Si el contenido no es suficiente, omítelo. No inventes datos.\n"
        "5. Las opciones incorrectas deben ser creíbles.\n"
        "6. Prioriza variedad temática.\n"
        "7. Redacta en un español técnico y preciso.\n"
        "8. La explicación debe ser breve (2-3 frases como máximo).\n\n"
        "Formato JSON:\n"
        "{\"pregunta\": \"...\", \"opciones\": {\"A\": \"...\", \"B\": \"...\", \"C\": \"...\", \"D\": \"...\"}, \"respuesta_correcta\": \"...\", \"explicacion\": \"...\"}\n"
        "Devuelve ÚNICAMENTE ese JSON: sin bloques de código, sin backticks (```), sin ningún texto antes o después."
    )


def _generar_pregunta_desde_subbloque(sub, oposicion=OPOSICION_POR_DEFECTO):
    etiqueta = sub.get("etiqueta", "")
    contenido = sub.get("texto", "")
    if contar_tokens(contenido) > 3000:
        contenido = contenido[:4000]

    prompt = f"{_instrucciones(oposicion)}\n\nContenido:\n{contenido}"

    messages = [{"role": "user", "content": prompt}]

    try:
        generado = call_deepseek_api(messages, max_tokens=1100, temperature=0.4)
        if not generado:
            return {"etiqueta": etiqueta, "error": "Sin respuesta de DeepSeek"}

        # DeepSeek a veces envuelve el JSON en un bloque de código markdown
        # (```json ... ```) pese a que se le pide que no lo haga; en vez de
        # descartar la pregunta por eso, se extrae el objeto {...} tal y como
        # ya se hace en las demás rutas de generación (app.py).
        inicio = generado.find("{")
        fin = generado.rfind("}") + 1
        if inicio == -1 or fin <= inicio:
            return {"etiqueta": etiqueta, "error": "No se encontró un objeto JSON en la respuesta"}
        generado_json = json.loads(generado[inicio:fin])

        if validar_pregunta(generado_json):
            # El id de tema tal y como lo expone /temas-disponibles es
            # "bloque-tema" (sin el subbloque); se deriva de la etiqueta para
            # que cada pregunta sepa de qué tema salió realmente, en vez de
            # que el frontend tenga que adivinarlo/asignarlo al azar.
            partes = etiqueta.split("-")
            if len(partes) >= 2:
                generado_json["tema_id"] = "-".join(partes[:2])
            return {"etiqueta": etiqueta, "pregunta": generado_json}
        return {"etiqueta": etiqueta, "error": "No pasó validación"}

    except json.JSONDecodeError as je:
        return {"etiqueta": etiqueta, "error": f"JSON inválido: {je}"}
    except Exception as e:
        return {"etiqueta": etiqueta, "error": f"Error DeepSeek: {e}"}


def generar_test_avanzado(temas, db, num_preguntas=5, coleccion="Temario AGE", oposicion=OPOSICION_POR_DEFECTO):
    print("🔍 función generar_test_avanzado() llamada")
    print(f"🧪 Temas recibidos: {temas}")

    try:
        subbloques = obtener_subbloques_individuales(db, temas, coleccion=coleccion)
        if not subbloques:
            print("⚠️ No se encontraron subbloques.")
            return {"test": [], "advertencia": "No se encontraron subbloques válidos."}

        print(f"📚 Subbloques encontrados: {len(subbloques)}")
        random.shuffle(subbloques)

        preguntas_generadas = []
        usados = []
        errores = []
        indice = 0

        # Se pide de más (el doble de lo que falta) para compensar preguntas
        # que no pasen la validación o fallen al generarse. Si aun así no se
        # llega al número pedido, se sigue intentando con más subbloques sin
        # usar -- en vez de rendirse tras el primer lote -- hasta agotarlos.
        while len(preguntas_generadas) < num_preguntas and indice < len(subbloques):
            faltan = num_preguntas - len(preguntas_generadas)
            lote = subbloques[indice: indice + max(faltan * 2, faltan)]
            indice += len(lote)

            with ThreadPoolExecutor(max_workers=min(10, len(lote))) as executor:
                futuros = [executor.submit(_generar_pregunta_desde_subbloque, sub, oposicion) for sub in lote]
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
            resultado_final["advertencia"] = f"Solo se generaron {len(preguntas_generadas)} de {num_preguntas} preguntas (no había suficiente contenido válido en los temas elegidos)."

        print(f"🎯 Preguntas generadas: {len(preguntas_generadas)}")
        return resultado_final

    except Exception as error:
        print(f"🔥 Error inesperado en generar_test_avanzado: {error}")
        return {"test": [], "error": str(error)}
