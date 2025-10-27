import os
import requests
import json

def call_deepseek_api(messages, max_tokens=1500, temperature=0.7):
    """
    Función mejorada para llamar a la API de DeepSeek con mejor manejo de errores
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
        return None
        
    except requests.exceptions.ConnectionError:
        print("❌ Error de conexión: No se pudo conectar a DeepSeek API")
        return None
        
    except requests.exceptions.HTTPError as e:
        print(f"❌ Error HTTP {response.status_code}: {e}")
        if response.status_code == 401:
            print("   → Verifica que tu API key de DeepSeek sea válida")
        elif response.status_code == 429:
            print("   → Límite de tasa excedido, espera un momento")
        elif response.status_code >= 500:
            print("   → Error del servidor de DeepSeek, intenta más tarde")
        return None
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error en la petición a DeepSeek: {str(e)}")
        return None
        
    except KeyError as e:
        print(f"❌ Error en la estructura de la respuesta: {e}")
        print(f"   Respuesta completa: {data}")
        return None
        
    except Exception as e:
        print(f"❌ Error inesperado en DeepSeek API: {str(e)}")
        return None

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