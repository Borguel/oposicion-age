import os
import time
import logging
import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Backoff entre reintentos ante fallos TRANSITORIOS (timeout/conexión/5xx) --
# nunca ante errores 4xx (API key inválida, payload mal formado), que no se
# arreglan reintentando. Deliberadamente corto: estos reintentos protegen un
# simple parpadeo de red, no sustituyen a la lógica de negocio que decide si
# hay que reintentar por otros motivos (p. ej. una pregunta que no supera la
# verificación jurídica en generador_preguntas_verificado.py).
_REINTENTOS_TRANSITORIOS = 2
_ESPERA_ENTRE_REINTENTOS_SEGUNDOS = 1.5


def _registrar_coste(usage):
    """Contabiliza el consumo de tokens de una respuesta de DeepSeek en el
    acumulador de la petición actual (best-effort; ver coste_ia.py). Nunca
    debe romper la llamada principal."""
    try:
        from coste_ia import acumular_usage
        acumular_usage(usage)
    except Exception:
        pass


def _es_error_transitorio(exc):
    """Decide si un fallo llamando a DeepSeek merece un reintento
    automático: timeouts y errores de conexión (un simple parpadeo de
    red) y errores 5xx del propio servidor de DeepSeek -- nunca 4xx (API
    key inválida, payload mal formado), que no se arreglan reintentando.
    Se comparte entre call_deepseek_api, generar_con_continuacion y
    call_deepseek_api_stream para no repetir este criterio tres veces."""
    if isinstance(exc, requests.exceptions.Timeout):
        return True
    if isinstance(exc, requests.exceptions.ConnectionError):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        return status is not None and status >= 500
    if isinstance(exc, requests.exceptions.RequestException):
        return True
    return False


def call_deepseek_api(messages, max_tokens=1500, temperature=0.7, response_format_json=False, on_usage=None):
    """
    Función mejorada para llamar a la API de DeepSeek con mejor manejo de errores.

    response_format_json=True activa el modo JSON nativo de la API
    (`response_format: {"type": "json_object"}`, soportado por DeepSeek pero
    no usado hasta ahora) -- reduce fallos de parseo cuando se espera JSON,
    frente a depender solo de instrucciones en el prompt.
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")

    if not api_key:
        logger.error("No hay API key de DeepSeek configurada")
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
        try:
            response = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers=headers,
                json=payload,
                timeout=30  # 30 segundos de timeout
            )

            response.raise_for_status()  # Lanza excepción para códigos HTTP 4xx/5xx

            data = response.json()
            # Si nos pasan on_usage (llamadas dentro de hilos, que no ven
            # flask.g) se lo entregamos ahí; si no, se contabiliza contra la
            # petición actual como de costumbre.
            if on_usage is not None:
                try:
                    on_usage(data.get("usage"))
                except Exception:
                    pass
            else:
                _registrar_coste(data.get("usage"))

            # Verificar que la respuesta tiene la estructura esperada
            if 'choices' in data and len(data['choices']) > 0:
                return data['choices'][0]['message']['content']
            else:
                logger.error("Respuesta inesperada de DeepSeek API: %s", data)
                return None

        except requests.exceptions.Timeout:
            logger.warning("Timeout: la API de DeepSeek no respondió en 30 segundos")
            transitorio = True

        except requests.exceptions.ConnectionError:
            logger.warning("Error de conexión: no se pudo conectar a DeepSeek API")
            transitorio = True

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status == 401:
                logger.error("Error HTTP 401 de DeepSeek: verifica que la API key sea válida (%s)", e)
            elif status == 429:
                logger.warning("Error HTTP 429 de DeepSeek: límite de tasa excedido (%s)", e)
            elif status is not None and status >= 500:
                logger.warning("Error HTTP %s del servidor de DeepSeek (%s)", status, e)
            else:
                logger.error("Error HTTP %s de DeepSeek: %s", status, e)
            transitorio = _es_error_transitorio(e)

        except requests.exceptions.RequestException as e:
            logger.warning("Error en la petición a DeepSeek: %s", e)
            transitorio = _es_error_transitorio(e)

        except KeyError as e:
            logger.exception("Error en la estructura de la respuesta de DeepSeek: %s", e)
            return None

        except Exception:
            logger.exception("Error inesperado en DeepSeek API")
            return None

        if transitorio and intentos_restantes > 0:
            intentos_restantes -= 1
            time.sleep(_ESPERA_ENTRE_REINTENTOS_SEGUNDOS)
            continue
        return None

def _post_deepseek_con_reintentos(headers, payload, timeout, stream=False):
    """POST a DeepSeek con el mismo criterio de reintento transitorio que
    call_deepseek_api (ver _es_error_transitorio), para que
    generar_con_continuacion y call_deepseek_api_stream no se queden sin
    reintentos ante un simple parpadeo de red solo por no reutilizar
    call_deepseek_api (que no encaja aquí: ésta devuelve solo el texto
    final, sin finish_reason, y el streaming es un generador -- formas
    incompatibles con estas dos funciones). Reintenta tanto errores de
    transporte como respuestas 5xx del servidor; nunca deja pasar un 4xx
    sin reintentar, porque eso no se arregla reintentando."""
    intentos_restantes = _REINTENTOS_TRANSITORIOS
    while True:
        try:
            response = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers=headers, json=payload, timeout=timeout, stream=stream,
            )
        except requests.exceptions.RequestException as e:
            if _es_error_transitorio(e) and intentos_restantes > 0:
                intentos_restantes -= 1
                time.sleep(_ESPERA_ENTRE_REINTENTOS_SEGUNDOS)
                continue
            raise
        if response.status_code >= 500 and intentos_restantes > 0:
            intentos_restantes -= 1
            time.sleep(_ESPERA_ENTRE_REINTENTOS_SEGUNDOS)
            continue
        return response


def generar_con_continuacion(system_prompt, mensaje_usuario, max_tokens=4096, temperature=0.3, max_continuaciones=2, on_usage=None):
    """Genera texto largo (resúmenes/esquemas a partir de un PDF) sin
    arriesgarse a que se corte a mitad de frase -- o directamente a mitad
    del documento -- si el texto de origen es largo. Si DeepSeek corta la
    respuesta por haber alcanzado max_tokens (finish_reason == "length"), se
    le pide que continúe EXACTAMENTE donde lo dejó, hasta max_continuaciones
    veces, y se concatena todo. Antes se pedía una única llamada con
    max_tokens=2000 y, si el documento era largo, el resumen simplemente se
    quedaba a medias (p. ej. cortado en mitad del índice de artículos) sin
    ningún aviso.

    on_usage, igual que en call_deepseek_api: si se pasa (llamadas hechas
    desde un hilo de trabajo que no ve flask.g, p. ej. dentro del
    ThreadPoolExecutor de generar_documento_largo_por_partes), se le entrega
    el usage de cada llamada en vez de contabilizarlo contra la petición
    actual.

    Devuelve el texto completo, o None si la primera llamada falla."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": mensaje_usuario},
    ]
    texto_completo = ""
    for _ in range(max_continuaciones + 1):
        payload = {
            "model": "deepseek-chat",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            response = _post_deepseek_con_reintentos(headers, payload, timeout=60)
        except requests.exceptions.RequestException as e:
            logger.warning("Error de red generando continuación con DeepSeek: %s", e)
            break
        if response.status_code != 200:
            logger.warning("DeepSeek devolvió %s generando continuación", response.status_code)
            break
        cuerpo = response.json() or {}
        if on_usage is not None:
            try:
                on_usage(cuerpo.get("usage"))
            except Exception:
                pass
        else:
            _registrar_coste(cuerpo.get("usage"))
        choices = cuerpo.get("choices") or []
        if not choices:
            logger.warning("DeepSeek no devolvió 'choices' generando continuación")
            break
        fragmento = choices[0].get("message", {}).get("content") or ""
        texto_completo += fragmento
        if choices[0].get("finish_reason") != "length":
            break
        messages.append({"role": "assistant", "content": fragmento})
        messages.append({
            "role": "user",
            "content": "Continúa exactamente donde lo dejaste, sin repetir nada de lo ya escrito y sin añadir ninguna introducción ni recordatorio de lo anterior."
        })
    return texto_completo or None


TAMANO_CHUNK_CARACTERES = 15000


def _trocear_en_parrafos(texto, tamano=TAMANO_CHUNK_CARACTERES):
    """Trocea el texto en fragmentos de como mucho 'tamano' caracteres,
    cortando siempre en un salto de párrafo (nunca a mitad de frase) para no
    partir una idea entre dos fragmentos si se puede evitar. Si un único
    párrafo ya supera 'tamano' se deja tal cual como su propio fragmento en
    vez de partirlo a la fuerza -- generar_con_continuacion ya sabe pedir
    continuaciones si un fragmento resulta más largo de lo esperado."""
    if len(texto) <= tamano:
        return [texto]
    parrafos = texto.split("\n\n")
    fragmentos = []
    actual = ""
    for parrafo in parrafos:
        if actual and len(actual) + len(parrafo) + 2 > tamano:
            fragmentos.append(actual)
            actual = parrafo
        else:
            actual = f"{actual}\n\n{parrafo}" if actual else parrafo
    if actual:
        fragmentos.append(actual)
    return fragmentos


def generar_documento_largo_por_partes(system_prompt, texto, etiqueta_documento="Documento", max_tokens=4096, instrucciones_fusion_extra=None, on_usage=None, on_progreso=None):
    """Para documentos largos, en vez de meter todo el texto de golpe en un
    único prompt (peor calidad: el modelo tiene que abarcar decenas de
    miles de palabras a la vez, y es más fácil que se pierda o mezcle
    secciones), se resume/esquematiza por partes:

    1. MAP: el texto se trocea en fragmentos (ver _trocear_en_parrafos) y
       cada uno se resume/esquematiza por separado, en paralelo, con el
       mismo formato pedido en system_prompt.
    2. REDUCE: los resultados parciales se funden en una llamada final en
       un único documento coherente, sin secciones duplicadas ni solapadas
       entre fragmentos.

    Con un documento que ya cabe en un único prompt (la inmensa mayoría),
    se comporta exactamente igual que antes: una sola llamada a
    generar_con_continuacion, sin trocear ni fusionar nada.

    instrucciones_fusion_extra permite añadir, solo al paso de fusión, un
    aviso adicional específico del tipo de documento (p. ej. el esquema
    necesita que se detecte y fusione un mismo epígrafe tratado a distinta
    profundidad en fragmentos distintos, algo que la instrucción genérica de
    "sin secciones duplicadas" no cubre por sí sola porque el texto de esas
    dos versiones no es literalmente idéntico).

    on_usage, si se pasa, recibe el usage de cada llamada (MAP y fusión)
    para contabilizar coste desde fuera de flask.g -- ver AcumuladorTokens
    en coste_ia.py. Imprescindible cuando el documento se trocea, porque el
    paso MAP corre en un ThreadPoolExecutor sin contexto de petición.

    on_progreso(evento), si se pasa, se llama con {"completadas": i,
    "total": n_fragmentos, "fase": "generando"|"fusionando"} a medida que
    cada fragmento del MAP termina, y una última vez al empezar la fusión --
    pensado para retransmitir progreso real por SSE (ver /resumir-documento,
    /generar-esquema-desde-pdf en blueprints/pdf_ia.py) en vez de los
    mensajes rotativos cosméticos que tenían antes."""
    fragmentos = _trocear_en_parrafos(texto)
    if len(fragmentos) == 1:
        resultado = generar_con_continuacion(system_prompt, f"{etiqueta_documento}:\n{texto}", max_tokens=max_tokens, on_usage=on_usage)
        if on_progreso:
            on_progreso({"completadas": 1, "total": 1, "fase": "generando"})
        return resultado

    def _generar_parcial(indice_fragmento):
        indice, fragmento = indice_fragmento
        mensaje = (
            f"Este es el FRAGMENTO {indice + 1} de {len(fragmentos)} de un documento más largo -- "
            "NO es el documento completo, así que no asumas que faltan secciones anteriores o "
            "posteriores ni lo indiques en tu respuesta. Aplica el formato pedido solo al "
            f"contenido de este fragmento.\n\n{etiqueta_documento} (fragmento {indice + 1}/{len(fragmentos)}):\n{fragmento}"
        )
        # on_usage es obligatorio aquí (no el _registrar_coste por defecto):
        # este closure corre dentro del ThreadPoolExecutor de abajo, en un
        # hilo de trabajo sin flask.g, así que sin on_usage el coste de
        # TODAS las llamadas del MAP se perdería en silencio.
        return generar_con_continuacion(system_prompt, mensaje, max_tokens=max_tokens, on_usage=on_usage)

    parciales_por_indice = {}
    completadas = 0
    with ThreadPoolExecutor(max_workers=min(4, len(fragmentos))) as executor:
        futuro_a_indice = {executor.submit(_generar_parcial, item): item[0] for item in enumerate(fragmentos)}
        for futuro in as_completed(futuro_a_indice):
            indice = futuro_a_indice[futuro]
            parciales_por_indice[indice] = futuro.result()
            completadas += 1
            if on_progreso:
                on_progreso({"completadas": completadas, "total": len(fragmentos), "fase": "generando"})
    parciales = [parciales_por_indice[i] for i in range(len(fragmentos)) if parciales_por_indice.get(i)]
    if not parciales:
        return None
    if len(parciales) == 1:
        return parciales[0]

    if on_progreso:
        on_progreso({"completadas": len(fragmentos), "total": len(fragmentos), "fase": "fusionando"})
    prompt_fusion = (
        f"{system_prompt}\n\n"
        "A continuación tienes varios resultados YA generados a partir de distintos fragmentos "
        "consecutivos del MISMO documento (separados por '---'). Fusiónalos en un único resultado "
        "coherente, sin secciones duplicadas ni solapadas, respetando el orden original y el mismo "
        "formato indicado arriba. No añadas ningún comentario sobre la fusión en sí ni menciones "
        "que procede de varios fragmentos. No introduzcas en el resultado fusionado ningún dato, "
        "cifra, fecha o afirmación que no estuviera ya presente en alguno de los fragmentos "
        "parciales que se te dan a continuación -- fusionar no significa completar ni enriquecer, "
        "solo combinar y reorganizar lo ya generado."
        + (f"\n\n{instrucciones_fusion_extra}" if instrucciones_fusion_extra else "")
    )
    bloque_parciales = "\n\n---\n\n".join(parciales)
    return generar_con_continuacion(prompt_fusion, bloque_parciales, max_tokens=max_tokens, on_usage=on_usage)


# Versión en streaming de call_deepseek_api: en vez de devolver el texto
# completo de una vez, va cediendo (yield) cada fragmento tal y como lo manda
# DeepSeek (protocolo SSE, "data: {...}" por línea, terminado en "data:
# [DONE]"), para poder mostrarlo en el frontend con efecto de escritura en
# vez de esperar a que termine toda la respuesta.
def call_deepseek_api_stream(messages, max_tokens=1500, temperature=0.7):
    api_key = os.getenv("DEEPSEEK_API_KEY")

    if not api_key:
        logger.error("No hay API key de DeepSeek configurada")
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
        "stream": True,
        # Pide que el último chunk del stream incluya el consumo de tokens,
        # para poder contabilizar el coste también en las respuestas en
        # streaming (Tu Tutor, test personalizado).
        "stream_options": {"include_usage": True},
    }

    try:
        # Solo se reintenta la CONEXIÓN inicial (antes de que se haya
        # cedido ya algún fragmento al llamante) -- reintentar a mitad de
        # un stream que el frontend ya está pintando no sería seguro.
        with _post_deepseek_con_reintentos(headers, payload, timeout=60, stream=True) as response:
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
                # El chunk final (con include_usage) trae usage y choices
                # vacío: se contabiliza y no se cede nada.
                if data.get("usage"):
                    _registrar_coste(data.get("usage"))
                choices = data.get("choices") or []
                if not choices:
                    continue
                fragmento = (choices[0].get("delta") or {}).get("content")
                if fragmento:
                    yield fragmento
    except requests.exceptions.Timeout:
        logger.warning("Timeout: la API de DeepSeek no respondió a tiempo (streaming)")
    except requests.exceptions.ConnectionError:
        logger.warning("Error de conexión: no se pudo conectar a DeepSeek API (streaming)")
    except requests.exceptions.RequestException as e:
        logger.warning("Error en streaming de DeepSeek: %s", e)

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
        logger.error("Tipo de contenido no soportado: %s", tipo_contenido)
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
            logger.warning("La IA no devolvió un JSON válido para tipo_contenido=%s", tipo_contenido)
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