import os
import time
import requests
import json

# Backoff entre reintentos ante fallos TRANSITORIOS (timeout/conexión/5xx) --
# nunca ante errores 4xx (API key inválida, payload mal formado), que no se
# arreglan reintentando. Deliberadamente corto: estos reintentos protegen un
# simple parpadeo de red, no sustituyen a la lógica de negocio que decide si
# hay que reintentar por otros motivos (p. ej. una pregunta que no supera la
# verificación jurídica en generador_preguntas_verificado.py).
_REINTENTOS_TRANSITORIOS = 2
_ESPERA_ENTRE_REINTENTOS_SEGUNDOS = 1.5


def call_deepseek_api(messages, max_tokens=1500, temperature=0.7, response_format_json=False):
    """
    Función mejorada para llamar a la API de DeepSeek con mejor manejo de errores.

    response_format_json=True activa el modo JSON nativo de la API
    (`response_format: {"type": "json_object"}`, soportado por DeepSeek pero
    no usado hasta ahora) -- reduce fallos de parseo cuando se espera JSON,
    frente a depender solo de instrucciones en el prompt.
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")

    if not api_key:
        print("❌ Error: No hay API key de DeepSeek configurada")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False
    }
    if response_format_json:
        payload["response_format"] = {"type": "json_object"}

    intentos_restantes = _REINTENTOS_TRANSITORIOS
    while True:
        transitorio = False
        try:
            response = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers=headers,
                json=payload,
                timeout=30  # 30 segundos de timeout
            )

            response.raise_for_status()  # Lanza excepción para códigos HTTP 4xx/5xx

            data = response.json()

            # Verificar que la respuesta tiene la estructura esperada
            if 'choices' in data and len(data['choices']) > 0:
                return data['choices'][0]['message']['content']
            else:
                print(f"❌ Respuesta inesperada de DeepSeek API: {data}")
                return None

        except requests.exceptions.Timeout:
            print("❌ Timeout: La API de DeepSeek no respondió en 30 segundos")
            transitorio = True

        except requests.exceptions.ConnectionError:
            print("❌ Error de conexión: No se pudo conectar a DeepSeek API")
            transitorio = True

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            print(f"❌ Error HTTP {status}: {e}")
            if status == 401:
                print("   → Verifica que tu API key de DeepSeek sea válida")
            elif status == 429:
                print("   → Límite de tasa excedido, espera un momento")
            elif status is not None and status >= 500:
                print("   → Error del servidor de DeepSeek, intenta más tarde")
            transitorio = status is not None and status >= 500

        except requests.exceptions.RequestException as e:
            print(f"❌ Error en la petición a DeepSeek: {str(e)}")
            transitorio = True

        except KeyError as e:
            print(f"❌ Error en la estructura de la respuesta: {e}")
            return None

        except Exception as e:
            print(f"❌ Error inesperado en DeepSeek API: {str(e)}")
            return None

        if transitorio and intentos_restantes > 0:
            intentos_restantes -= 1
            time.sleep(_ESPERA_ENTRE_REINTENTOS_SEGUNDOS)
            continue
        return None

# Versión en streaming de call_deepseek_api: en vez de devolver el texto
# completo de una vez, va cediendo (yield) cada fragmento tal y como lo manda
# DeepSeek (protocolo SSE, "data: {...}" por línea, terminado en "data:
# [DONE]"), para poder mostrarlo en el frontend con efecto de escritura en
# vez de esperar a que termine toda la respuesta.
def call_deepseek_api_stream(messages, max_tokens=1500, temperature=0.7):
    api_key = os.getenv("DEEPSEEK_API_KEY")

    if not api_key:
        print("❌ Error: No hay API key de DeepSeek configurada")
        return

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True
    }

    try:
        with requests.post(
            "https://api.deepseek.com/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
            stream=True
        ) as response:
            response.raise_for_status()
            for linea in response.iter_lines(decode_unicode=True):
                if not linea or not linea.startswith("data: "):
                    continue
                contenido_linea = linea[len("data: "):].strip()
                if contenido_linea == "[DONE]":
                    break
                try:
                    data = json.loads(contenido_linea)
                except json.JSONDecodeError:
                    continue
                choices = data.get("choices") or []
                if not choices:
                    continue
                fragmento = (choices[0].get("delta") or {}).get("content")
                if fragmento:
                    yield fragmento
    except requests.exceptions.Timeout:
        print("❌ Timeout: La API de DeepSeek no respondió a tiempo (streaming)")
    except requests.exceptions.ConnectionError:
        print("❌ Error de conexión: No se pudo conectar a DeepSeek API (streaming)")
    except requests.exceptions.RequestException as e:
        print(f"❌ Error en streaming de DeepSeek: {e}")

# Función adicional para generar contenido específico
def generar_contenido_desde_texto(texto, tipo_contenido, num_items=10):
    """
    Función genérica para generar diferentes tipos de contenido desde texto
    """
    prompts = {
        "resumen": "Eres un experto en oposiciones. Resume este documento en puntos clave, destacando conceptos fundamentales, leyes importantes y fechas relevantes. Usa viñetas claras y estructura organizada.",
        "esquema": "Eres un experto en oposiciones. Crea un esquema estructurado y organizado a partir del siguiente documento. Usa títulos, subtítulos y viñetas claras. El esquema debe ser útil para estudiar y repasar.",
        "test": f"Eres un generador experto de preguntas tipo test para oposiciones. Crea {num_items} preguntas claras con 4 opciones (A, B, C, D) y una única respuesta correcta. Incluye una explicación breve. Devuelve SOLO un array JSON válido.",
        "tarjetas": f"Eres un experto en crear tarjetas de memoria para estudiar. Crea {num_items} tarjetas con preguntas claras en el anverso y respuestas concisas en el reverso. Devuelve SOLO un array JSON válido."
    }
    
    if tipo_contenido not in prompts:
        print(f"❌ Tipo de contenido no soportado: {tipo_contenido}")
        return None
    
    system_prompt = prompts[tipo_contenido]
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Documento para procesar:\n\n{texto}"}
    ]
    
    # Ajustar parámetros según el tipo de contenido
    if tipo_contenido in ["test", "tarjetas"]:
        max_tokens = 3000
        temperature = 0.4
    else:
        max_tokens = 2000
        temperature = 0.3
    
    respuesta = call_deepseek_api(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature
    )
    
    if respuesta and tipo_contenido in ["test", "tarjetas"]:
        try:
            # Intentar parsear JSON para tests y tarjetas
            return json.loads(respuesta)
        except json.JSONDecodeError:
            print("❌ La IA no devolvió un JSON válido")
            return respuesta  # Devolver respuesta cruda como fallback
    
    return respuesta

# Función para verificar que la API key está configurada
def verificar_configuracion():
    """
    Verifica que la configuración de DeepSeek esté correcta
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    
    if not api_key:
        print("❌ ERROR CRÍTICO: DEEPSEEK_API_KEY no está configurada")
        print("   Por favor, añade DEEPSEEK_API_KEY a tu archivo .env")
        return False
    
    # Verificar formato básico de la API key (empieza con sk-)
    if not api_key.startswith('sk-'):
        print("⚠️  ADVERTENCIA: La API key no tiene el formato esperado (debería empezar con 'sk-')")
    
    print("✅ Configuración de DeepSeek verificada correctamente")
    return True

# Ejemplo de uso (para testing)
if __name__ == "__main__":
    # Verificar configuración al importar el módulo
    verificar_configuracion()
    
    # Ejemplo de prueba
    test_messages = [
        {"role": "system", "content": "Eres un asistente útil."},
        {"role": "user", "content": "Hola, ¿puedes saludarme?"}
    ]
    
    respuesta = call_deepseek_api(test_messages, max_tokens=50)
    if respuesta:
        print(f"✅ Test exitoso: {respuesta}")
    else:
        print("❌ Test fallido")