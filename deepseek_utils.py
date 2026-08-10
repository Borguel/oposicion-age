import os
import re
import time
import logging
import threading
import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as _FuturesTimeoutError

logger = logging.getLogger(__name__)

# Backoff entre reintentos ante fallos TRANSITORIOS (timeout/conexión/5xx,
# y desde el 02/08/2026 también finish_reason=length) -- nunca ante errores
# 4xx (API key inválida, payload mal formado), que no se arreglan
# reintentando. Deliberadamente corto: estos reintentos protegen un simple
# parpadeo de red, no sustituyen a la lógica de negocio que decide si hay
# que reintentar por otros motivos (p. ej. una pregunta que no supera la
# verificación jurídica en generador_preguntas_verificado.py).
#
# NOTA (02/08/2026): se probó subir esto a 3 y bajar el semáforo de abajo
# a 6, con la hipótesis de que el problema era contención en la propia
# app -- con datos reales resultó ser un empeoramiento claro (más errores
# de conexión agrupados en ráfaga, tiempo total peor), así que se revirtió
# a los valores de siempre. La causa real de "Error de conexión: no se
# pudo conectar a DeepSeek API" / "Response ended prematurely" parece ser
# inestabilidad del lado de DeepSeek (o de la red hacia allí), no
# contención nuestra -- no se toca más este número a ciegas sin evidencia
# clara de que ayuda.
_REINTENTOS_TRANSITORIOS = 2
_ESPERA_ENTRE_REINTENTOS_SEGUNDOS = 1.5

# Reintentos ante finish_reason=length, DELIBERADAMENTE SEPARADOS de
# _REINTENTOS_TRANSITORIOS (02/08/2026, con datos reales de producción):
# un truncamiento no es un simple parpadeo de red -- cada reintento cuesta
# una generación ENTERA (hasta ~40s con max_tokens=5000), así que
# compartir presupuesto con timeout/conexión (barato de reintentar) es
# carísimo en la cola con peor suerte: se vio un hueco tardar más de 4
# minutos ÉL SOLO por encadenar reintentos de truncamiento dentro de
# varios intentos exteriores (ver MAX_INTENTOS_POR_PREGUNTA en
# generador_preguntas_verificado.py), y como los huecos corren en
# paralelo, el tiempo total del test lo marca el MÁS LENTO de todos -- un
# solo hueco atascado se lleva por delante el test entero por mucho que
# el resto ya hubiera terminado. Un único reintento (con la temperature
# ya subida, ver más abajo) es suficiente para darle una oportunidad real
# de escapar del bucle sin multiplicar el coste de un caso ya perdido --
# si tampoco funciona, es mejor ceder el turno cuanto antes al bucle
# EXTERIOR (que sí prueba con una ancla/tipo de pregunta distintos, un
# cambio real, no solo más temperatura) o al relleno final, que a un tema
# concreto le siga tocando mala suerte con el mismo prompt.
_REINTENTOS_TRUNCAMIENTO = 1

# Tope global de peticiones EN VUELO a DeepSeek en todo el proceso (app.py
# corre un único proceso -- ver --workers 1 en render.yaml, a propósito
# porque este semáforo y el rate-limiter de app.py son estado en memoria
# de un solo proceso -- así que un semáforo a nivel de módulo sí
# representa el límite real, no uno por worker). Sin esto, generar un
# test de 30 preguntas desde PDF puede disparar hasta ~48 llamadas en
# paralelo (8 lotes x 6 verificaciones cada uno, ver test_generator.py), y
# si en ese momento hay más herramientas u otros usuarios llamando a la
# vez, el conjunto parece saturar al proveedor.
#
# Empezó en 16, pero la misma firma de fallo (avisos de "Error de
# conexión" y tiempos de respuesta crecientes hasta ~94s -- 3 intentos de
# 30s cada uno) se ha seguido viendo en producción con ese tope, incluso
# DESPUÉS de pasar de "python app.py" a gunicorn (ver render.yaml): eso
# descarta que fuera un cuello de botella del servidor de aplicación y
# confirma que 16 llamadas a la vez ya basta para que la propia API de
# DeepSeek se sature bajo nuestra cuenta. Bajado a 8. Frenar aquí (el
# único punto por el que pasan TODAS las llamadas a la API, sea cual sea
# la herramienta que las dispare) es más simple y más fiable que ajustar
# cada ThreadPoolExecutor por separado uno a uno. Una llamada que no
# consigue hueco espera en cola (barato) en vez de sumarse a la
# sobrecarga real del proveedor.
#
# NOTA (02/08/2026): se probó bajar esto a 6 tras subir max_tokens de
# generación (respuestas más largas = cada hueco del semáforo ocupado más
# tiempo), con la hipótesis de que había contención propia -- con datos
# reales de producción resultó en MÁS errores de conexión, agrupados en
# ráfaga, y un tiempo total peor. Revertido a 8. Todo apunta a que "Error
# de conexión: no se pudo conectar a DeepSeek API" / "Response ended
# prematurely" es inestabilidad del lado de DeepSeek (o de la red hacia
# allí) más que contención nuestra -- no bajar este número otra vez sin
# evidencia clara de que ayuda de verdad, no solo en teoría.
_MAX_LLAMADAS_SIMULTANEAS_DEEPSEEK = 8
_semaforo_deepseek = threading.Semaphore(_MAX_LLAMADAS_SIMULTANEAS_DEEPSEEK)

# Timeout de una llamada NO streaming: la respuesta entera tiene que llegar
# dentro de este margen, porque con stream=false no se recibe ni un byte
# hasta que el modelo ha terminado de generar.
_TIMEOUT_RESPUESTA_COMPLETA = 30

# Timeout de una llamada en STREAMING, como (conexión, lectura). El de
# lectura NO es el tope de la respuesta entera, sino el máximo ENTRE dos
# fragmentos consecutivos: una vez el modelo empieza a emitir, los
# fragmentos llegan cada pocos milisegundos, así que en la práctica este
# margen solo aplica al tiempo hasta el PRIMER fragmento. Por eso una
# respuesta en streaming puede tardar 60s en total sin problema, mientras
# que la misma respuesta sin streaming moriría a los ~30s (ver
# _leer_respuesta_en_streaming).
_TIMEOUT_STREAMING = (10, 60)

_URL_DEEPSEEK = "https://api.deepseek.com/chat/completions"


def _leer_respuesta_completa(headers, payload, timeout):
    """Llamada clásica (stream=false): se espera a la respuesta entera y se
    devuelve (contenido, finish_reason, usage). contenido es None -- y ya
    queda logueado aquí -- si la respuesta no trae 'choices', un fallo de
    forma que no se arregla reintentando."""
    response = requests.post(_URL_DEEPSEEK, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()  # Lanza excepción para códigos HTTP 4xx/5xx
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        logger.error("Respuesta inesperada de DeepSeek API: %s", data)
        return None, None, data.get("usage")
    return choices[0]["message"]["content"], choices[0].get("finish_reason"), data.get("usage")


def _leer_respuesta_en_streaming(headers, payload, timeout):
    """Misma llamada pero con stream=true, consumiendo el SSE entero aquí
    dentro y devolviendo (contenido, finish_reason, usage) EXACTAMENTE con
    la misma forma que _leer_respuesta_completa -- quien llama no nota la
    diferencia, solo recibe el texto completo igual que antes.

    El motivo no es mostrar la respuesta poco a poco (aquí no se cede nada
    al llamante hasta tener el texto entero), sino que la conexión no se
    quede muda: con stream=false no viaja NINGÚN byte entre la petición y
    la respuesta terminada, y en producción (02/08/2026) se comprobó que
    toda llamada que tardaba más de ~30s en generar moría con "Error de
    conexión: no se pudo conectar a DeepSeek API" / "Response ended
    prematurely" -- cortada desde el otro lado, no por nuestro timeout (un
    timeout nuestro se registraría como Timeout, y ese mensaje no aparecía
    nunca en los logs). La correlación era total: ninguna respuesta
    completada por debajo de 30s falló, y ninguna por encima de 30s
    sobrevivió. Con deepseek-v4-flash generando a ~110-130 tokens/s, ese
    muro cae sobre los 3300-3900 tokens de salida, justo el tamaño de las
    preguntas más largas del test personalizado. En streaming los
    fragmentos van llegando continuamente desde el primer token, la
    conexión nunca parece inactiva, y una respuesta de 45s se completa sin
    problema."""
    partes = []
    finish_reason = None
    usage = None
    with requests.post(_URL_DEEPSEEK, headers=headers, json=payload, timeout=timeout, stream=True) as response:
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
            # El chunk final (con stream_options.include_usage) trae usage y
            # choices vacío -- de ahí que se lea antes de mirar choices.
            if data.get("usage"):
                usage = data["usage"]
            choices = data.get("choices") or []
            if not choices:
                continue
            fragmento = (choices[0].get("delta") or {}).get("content")
            if fragmento:
                partes.append(fragmento)
            # finish_reason llega en el último chunk con contenido: se
            # guarda para que el reintento por truncamiento ("length")
            # siga funcionando igual que sin streaming.
            if choices[0].get("finish_reason"):
                finish_reason = choices[0]["finish_reason"]
    return "".join(partes), finish_reason, usage


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


def call_deepseek_api(messages, max_tokens=1500, temperature=0.7, response_format_json=False, on_usage=None, model="deepseek-v4-flash", contexto=None, stream=False, frequency_penalty=None, max_reintentos_truncamiento=None, thinking_enabled=None):
    """
    Función mejorada para llamar a la API de DeepSeek con mejor manejo de errores.

    response_format_json=True activa el modo JSON nativo de la API
    (`response_format: {"type": "json_object"}`, soportado por DeepSeek pero
    no usado hasta ahora) -- reduce fallos de parseo cuando se espera JSON,
    frente a depender solo de instrucciones en el prompt.

    model por defecto "deepseek-v4-flash" (el usado en todo el resto de la
    app: generación de tests, resúmenes, esquemas...). "deepseek-v4-pro" es
    el modelo de razonamiento (más lento y caro, pero más capaz en preguntas
    de varios pasos) -- de momento solo lo usa Tu Tutor, de forma opcional
    (ver TUTOR_MODELO_IA en chat_controller.py). NOTA: hasta el 24/07/2026
    estos modelos se llamaban "deepseek-chat" y "deepseek-reasoner" -- esos
    dos nombres se retiraron ese día sin periodo de gracia (cualquier
    llamada con el nombre antiguo devuelve error). El antiguo
    "deepseek-reasoner" rechazaba con HTTP 400 el parámetro temperature; el
    "deepseek-v4-pro" actual sí lo admite con normalidad -- se mantiene la
    exclusión de abajo solo por si quedara algún sitio con el nombre
    retirado todavía configurado, nunca se activa con los nombres actuales.

    contexto (opcional): etiqueta libre (p. ej. "tema=bloque_01-tema_02
    tipo=generacion") que se añade a los logs de esta llamada concreta --
    solo para poder identificar en los logs de Render QUÉ tema/pregunta se
    vio afectado por una respuesta truncada o un fallo de conexión, sin
    tener que cruzar manualmente varias líneas de log por timestamp.

    Una respuesta con finish_reason == "length" (DeepSeek cortó la salida
    al llegar a max_tokens, casi siempre a mitad del JSON pedido) se trata
    igual que un fallo transitorio de red: se reintenta hasta
    _REINTENTOS_TRANSITORIOS veces con el mismo backoff, y si sigue
    truncando tras agotar los reintentos se devuelve None (nunca el JSON a
    medias) para que el llamante lo trate como un intento fallido más, en
    vez de que un json.loads() posterior falle en silencio sin dejar
    ningún rastro de que la causa real fue un límite de tokens.

    stream=True hace la llamada en streaming pero SIN cambiar en nada lo
    que recibe quien llama: el SSE se consume entero aquí dentro y se
    devuelve el mismo texto completo de siempre (ver
    _leer_respuesta_en_streaming). No es para pintar la respuesta poco a
    poco -- es la forma de que una respuesta que tarda más de ~30s en
    generarse no muera con "Error de conexión" por tener la conexión muda
    mientras el modelo piensa. Recomendado para cualquier llamada que
    pueda pasar de ~3000 tokens de salida; innecesario (y sin ventaja)
    para respuestas cortas.

    frequency_penalty (opcional, None por defecto = no se manda -- se
    respeta el valor por defecto de la propia API): penaliza repetir
    tokens ya usados, el antídoto estándar contra que el modelo entre en
    un bucle de repetición y no emita nunca su propio stop token. Datos
    reales de producción (02/08/2026): se veían llamadas -- incluso de
    VERIFICACIÓN, con temperature=0.0 -- que se truncaban al llegar
    EXACTAMENTE a max_tokens en dos intentos seguidos con el mismo input
    (4000/4000 ambas veces). Con temperature=0 eso es casi determinista:
    si de verdad necesitara más espacio, subir max_tokens lo arreglaría
    sin más -- pero subirlo de 3000 a 5000 solo desplazó el mismo patrón
    más arriba (ver la nota de max_tokens en
    generador_preguntas_verificado.py), la firma clásica de una
    generación que se repite en vez de terminar. Se recomienda para
    cualquier llamada de generación/verificación estructurada como esta.

    max_reintentos_truncamiento (opcional, None = usa _REINTENTOS_TRUNCAMIENTO):
    permite BAJAR el presupuesto de reintentos por truncamiento para una
    llamada concreta -- pensado para la generación EN LOTE (ver
    TAMANO_LOTE_GENERACION en generador_preguntas_verificado.py), donde
    max_tokens ya es varias veces mayor que en una llamada normal (varias
    preguntas a la vez) y un reintento cuesta proporcionalmente mucho más
    tiempo (datos reales, 02/08/2026: un lote de solo 2 preguntas tardó
    116s en total por truncar y reintentar una vez con max_tokens=8400).
    Con 0, un lote que trunca no reintenta él mismo -- cede el turno de
    inmediato al relleno final (rápido, en paralelo, con llamadas
    individuales normales) en vez de pagar un segundo intento gigante
    dentro del mismo lote.
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
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": stream
    }
    if stream:
        # Pide que el último chunk del stream incluya el consumo de tokens:
        # sin esto, una llamada en streaming no podría contabilizar coste.
        payload["stream_options"] = {"include_usage": True}
    if model != "deepseek-reasoner":
        payload["temperature"] = temperature
    # thinking (02/08/2026, con datos reales de producción):
    # "deepseek-v4-flash" -- el modelo que usa toda la generación de
    # tests -- viene con razonamiento interno (delta.reasoning_content)
    # activado por defecto en nivel "high", algo invisible hasta ahora
    # porque solo se leía delta.content. El diagnóstico temporal añadido
    # ese mismo día mostró que CADA llamada gastaba la mayoría de sus
    # tokens en ese razonamiento (p.ej. una verificación con
    # reasoning_content=7970 caracteres y content=33) y que el caso que
    # truncó a 8000/8000 lo hizo con reasoning_content=31511 caracteres y
    # content=0 -- se quedó sin presupuesto pensando, sin llegar a
    # escribir el JSON. Esto explicaba a la vez la lentitud general y los
    # truncamientos sistemáticos.
    #
    # Por defecto (thinking_enabled=None) se desactiva para cualquier
    # modelo que no sea explícitamente el de razonamiento
    # ("deepseek-v4-pro", usado a propósito por Tu Tutor, y el nombre
    # retirado "deepseek-reasoner"). PERO en generador_preguntas_verificado
    # la llamada de VERIFICACIÓN pasa thinking_enabled=True explícitamente
    # para mantenerlo encendido ahí: verificar es justo la tarea donde ese
    # "borrador" (cotejar fechas/artículos/datos contra el texto legal
    # antes de decidir) puede importar de verdad para no dejar pasar un
    # desfase o un dato inventado -- a diferencia de la generación, más
    # mecánica (redactar opciones a partir del texto ya dado), donde
    # desactivarlo no debería perder precisión y sí ahorra mucho tiempo.
    if thinking_enabled is None:
        desactivar_thinking = model not in ("deepseek-v4-pro", "deepseek-reasoner")
    else:
        desactivar_thinking = not thinking_enabled
    if desactivar_thinking:
        payload["thinking"] = {"type": "disabled"}
    if response_format_json:
        payload["response_format"] = {"type": "json_object"}
    if frequency_penalty is not None:
        payload["frequency_penalty"] = frequency_penalty

    # Cronómetro de TODA la llamada (incluidos los reintentos internos de
    # abajo): permite ver en los logs de Render cuánto tarda de verdad
    # DeepSeek en responder, para distinguir "el proveedor va lento" de "hay
    # algo nuestro atascado" sin tener que adivinar -- ver también el mismo
    # patrón en call_deepseek_api_stream.
    inicio = time.monotonic()
    sufijo_contexto = f" [{contexto}]" if contexto else ""

    intentos_restantes = _REINTENTOS_TRANSITORIOS
    intentos_truncamiento_restantes = (
        _REINTENTOS_TRUNCAMIENTO if max_reintentos_truncamiento is None else max_reintentos_truncamiento
    )
    while True:
        try:
            # Todo el consumo de la respuesta ocurre DENTRO del semáforo: en
            # streaming la llamada no termina al recibir las cabeceras, sino
            # al agotar el stream, así que soltar el hueco antes dejaría
            # muchas más llamadas realmente en vuelo que las permitidas.
            with _semaforo_deepseek:
                if stream:
                    contenido, finish_reason, usage = _leer_respuesta_en_streaming(
                        headers, payload, _TIMEOUT_STREAMING)
                else:
                    contenido, finish_reason, usage = _leer_respuesta_completa(
                        headers, payload, _TIMEOUT_RESPUESTA_COMPLETA)

            # Si nos pasan on_usage (llamadas dentro de hilos, que no ven
            # flask.g) se lo entregamos ahí; si no, se contabiliza contra la
            # petición actual como de costumbre.
            if on_usage is not None:
                try:
                    on_usage(usage)
                except Exception:
                    pass
            else:
                _registrar_coste(usage)

            # contenido None == respuesta sin 'choices' (ya logueada dentro
            # del lector): un fallo de forma, no se arregla reintentando.
            if contenido is None:
                return None

            # finish_reason/tokens_salida: para comprobar con datos reales
            # (no adivinando) si max_tokens se está quedando corto --
            # "length" significa que la respuesta se cortó antes de que
            # el modelo terminara por sí solo, candidato real a JSON
            # incompleto/descartado; "stop" significa que el modelo
            # terminó por su cuenta bien dentro del límite. modo= permite
            # confirmar de un vistazo en los logs si una llamada concreta
            # fue en streaming o no.
            logger.info(
                "DeepSeek respondió en %.2fs (modelo=%s, finish_reason=%s, tokens_salida=%s, modo=%s)%s",
                time.monotonic() - inicio, model, finish_reason,
                (usage or {}).get('completion_tokens'),
                "streaming" if stream else "completo", sufijo_contexto,
            )
            if finish_reason == "length":
                # Truncado a mitad de respuesta: nunca se devuelve el JSON a
                # medias (el llamante solo lo descartaría igual al fallar el
                # parseo, sin dejar rastro claro de por qué). Presupuesto de
                # reintentos PROPIO (_REINTENTOS_TRUNCAMIENTO, ver la
                # constante arriba) -- deliberadamente más corto que el de
                # timeout/conexión: cada reintento aquí cuesta una
                # generación entera (hasta ~40s), no un simple parpadeo.
                if intentos_truncamiento_restantes > 0:
                    intentos_truncamiento_restantes -= 1
                    # Sube la temperatura para EL REINTENTO (nunca la
                    # llamada original) en vez de repetir exactamente la
                    # misma petición: con temperature=0.0 (verificación)
                    # reintentar tal cual es casi inútil -- es
                    # determinista, así que reproduce el mismo bucle de
                    # repetición y vuelve a truncarse en el mismo punto
                    # (visto en producción el 02/08/2026: 4000/4000 tokens
                    # en dos intentos seguidos del mismo input). Subir la
                    # temperatura le da al reintento una probabilidad real
                    # de tomar un camino de generación distinto que sí
                    # termine solo. Tope 0.9 -- no hace falta más para
                    # romper un bucle, y una temperatura demasiado alta
                    # perjudicaría la precisión jurídica que exige este
                    # generador.
                    if model != "deepseek-reasoner":
                        payload["temperature"] = min(payload.get("temperature", temperature) + 0.3, 0.9)
                    logger.warning(
                        "DeepSeek truncó la respuesta (finish_reason=length, max_tokens=%s)%s -- "
                        "reintentando con temperature=%s (quedan %d intentos de truncamiento)",
                        max_tokens, sufijo_contexto, payload.get("temperature"), intentos_truncamiento_restantes,
                    )
                    time.sleep(_ESPERA_ENTRE_REINTENTOS_SEGUNDOS)
                    continue
                logger.warning(
                    "DeepSeek siguió truncando la respuesta tras agotar los reintentos "
                    "(finish_reason=length, max_tokens=%s)%s -- se descarta este intento",
                    max_tokens, sufijo_contexto,
                )
                return None
            return contenido

        except requests.exceptions.Timeout:
            logger.warning(
                "Timeout: la API de DeepSeek no respondió a tiempo (%s)%s",
                "streaming" if stream else "sin streaming, 30 segundos", sufijo_contexto,
            )
            transitorio = True

        except requests.exceptions.ConnectionError:
            logger.warning("Error de conexión: no se pudo conectar a DeepSeek API%s", sufijo_contexto)
            transitorio = True

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            cuerpo = e.response.text[:500] if e.response is not None else ""
            if status == 401:
                logger.error("Error HTTP 401 de DeepSeek: verifica que la API key sea válida (%s) -- %s%s", e, cuerpo, sufijo_contexto)
            elif status == 429:
                logger.warning("Error HTTP 429 de DeepSeek: límite de tasa excedido (%s) -- %s%s", e, cuerpo, sufijo_contexto)
            elif status is not None and status >= 500:
                logger.warning("Error HTTP %s del servidor de DeepSeek (%s) -- %s%s", status, e, cuerpo, sufijo_contexto)
            else:
                logger.error("Error HTTP %s de DeepSeek: %s -- %s%s", status, e, cuerpo, sufijo_contexto)
            transitorio = _es_error_transitorio(e)

        except requests.exceptions.RequestException as e:
            logger.warning("Error en la petición a DeepSeek: %s%s", e, sufijo_contexto)
            transitorio = _es_error_transitorio(e)

        except KeyError as e:
            logger.exception("Error en la estructura de la respuesta de DeepSeek: %s%s", e, sufijo_contexto)
            return None

        except Exception:
            logger.exception("Error inesperado en DeepSeek API%s", sufijo_contexto)
            return None

        if transitorio and intentos_restantes > 0:
            intentos_restantes -= 1
            time.sleep(_ESPERA_ENTRE_REINTENTOS_SEGUNDOS)
            continue
        logger.warning("DeepSeek falló tras %.2fs (modelo=%s)%s", time.monotonic() - inicio, model, sufijo_contexto)
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
            with _semaforo_deepseek:
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


def generar_con_continuacion(system_prompt, mensaje_usuario, max_tokens=4096, temperature=0.3, max_continuaciones=1, on_usage=None):
    """Genera texto largo (resúmenes/esquemas a partir de un PDF) sin
    arriesgarse a que se corte a mitad de frase -- o directamente a mitad
    del documento -- si el texto de origen es largo. Si DeepSeek corta la
    respuesta por haber alcanzado max_tokens (finish_reason == "length"), se
    le pide que continúe EXACTAMENTE donde lo dejó, hasta max_continuaciones
    veces, y se concatena todo. Antes se pedía una única llamada con
    max_tokens=2000 y, si el documento era largo, el resumen simplemente se
    quedaba a medias (p. ej. cortado en mitad del índice de artículos) sin
    ningún aviso.

    max_continuaciones=1 (bajado de 2 el 10/08/2026, a petición explícita del
    usuario: "no tiene que consumir muchas llamadas... calidad media, no
    alta"): con los max_tokens ya generosos por llamada (4096 general/8192
    legal, ver blueprints/pdf_ia.py) una sola continuación de margen basta
    para el caso normal -- permitir hasta 2 (3 peticiones HTTP en total)
    multiplicaba innecesariamente el peor caso de coste para un beneficio de
    calidad marginal.

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
            "model": "deepseek-v4-flash",
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


# Detección de texto legal (05/08/2026): resumen/esquema desde PDF (ver
# /resumir-pdf y /generar-esquema-desde-pdf en blueprints/pdf_ia.py) tratan
# todo el contenido igual -- para una ley, un "resumen narrativo" pierde
# justo lo que un opositor necesita (número de artículo, plazos,
# excepciones). Esta heurística es puramente por regex, SIN llamar a
# DeepSeek (gratis, instantánea): busca patrones típicos de texto legal
# español y decide con dos condiciones, no solo una, para evitar falsos
# positivos:
#   1. Densidad de coincidencias por cada 1.000 caracteres por encima de
#      _UMBRAL_DENSIDAD_LEGAL -- un conteo absoluto sin más se dispara
#      igual en un documento de 5 páginas que en uno de 50, así que se
#      normaliza por longitud.
#   2. Al menos _UMBRAL_TIPOS_DISTINTOS_LEGAL patrones DISTINTOS con
#      alguna coincidencia -- un temario "general" que cita de pasada UNA
#      ley concreta (p. ej. "la Ley 39/2015 regula...") no debería bastar
#      para activar el modo legal si es la única señal que aparece.
# Además, _UMBRAL_MATCHES_ABSOLUTOS pone un suelo absoluto: sin él, un
# extracto CORTO con un par de citas incidentales ("el artículo 14 de la
# Ley 39/2015...") dispara una densidad alta solo por tener pocos
# caracteres en el denominador, aunque en términos absolutos sean
# clarísimamente pocas menciones. Los tres umbrales se calibraron con un
# documento legal real de este mismo proyecto (Tema 3: fuentes del
# derecho -- CE, Código Civil, Ley 50/1997 -- 58 "artículo N", 39 "ley
# N/YYYY", 7 "real decreto" en 53.034 caracteres: densidad ~1,96/1000,
# 3 tipos) frente a texto narrativo general (densidad 0) y un extracto
# corto con solo 3 menciones incidentales (densidad ~5,4/1000 pero muy
# por debajo del suelo absoluto).
_PATRONES_TEXTO_LEGAL = (
    re.compile(r'\bart[íi]culo\s+\d+', re.IGNORECASE),
    re.compile(r'BOE-[AB]-\d{4}-\d+', re.IGNORECASE),
    re.compile(r'\bley\s+\d+/\d{4}', re.IGNORECASE),
    re.compile(r'real decreto', re.IGNORECASE),
    re.compile(r'disposici[óo]n\s+(final|adicional|transitoria)', re.IGNORECASE),
)
_UMBRAL_DENSIDAD_LEGAL = 1.2  # coincidencias por cada 1.000 caracteres
_UMBRAL_TIPOS_DISTINTOS_LEGAL = 2
_UMBRAL_MATCHES_ABSOLUTOS_LEGAL = 8


def detectar_texto_legal(texto):
    """True si 'texto' tiene pinta de ser una ley/reglamento/BOE (en cuyo
    caso resumen/esquema deberían generarse como mapa de artículos en vez
    de narrativa -- ver blueprints/pdf_ia.py). Puramente heurístico y sin
    coste: no llama a DeepSeek. Ver el comentario largo de arriba para el
    razonamiento de los tres umbrales."""
    texto = texto or ""
    if not texto.strip():
        return False
    total_matches = 0
    tipos_distintos = 0
    for patron in _PATRONES_TEXTO_LEGAL:
        n = len(patron.findall(texto))
        if n:
            tipos_distintos += 1
            total_matches += n
    if total_matches < _UMBRAL_MATCHES_ABSOLUTOS_LEGAL or tipos_distintos < _UMBRAL_TIPOS_DISTINTOS_LEGAL:
        return False
    densidad = total_matches / (len(texto) / 1000)
    return densidad >= _UMBRAL_DENSIDAD_LEGAL


# De 15000 a 90000 y de vuelta a 35000 (10/08/2026). El salto a 90000 (a
# petición del usuario: "que se genere más rápido, sin gastar demasiados
# tokens") buscaba que la mayoría de documentos cupieran en una sola
# llamada -- pero un caso real lo desmintió: un documento de ~17-20.000
# caracteres, MUY por debajo de 90000, tomó el camino de una sola llamada y
# aun así se cortó a media palabra (red de seguridad de "respuesta
# sospechosamente corta" incluida, ver más abajo). Eso confirma que incluso
# documentos bastante más pequeños que 90000 ya son demasiado ambiciosos
# para una única llamada fiable al 100% -- el umbral no estaba resolviendo
# el problema que decía resolver. 35000 es el punto intermedio real: sigue
# dejando la mayoría de documentos cortos/medios (hasta ~8-10 páginas) en
# una sola llamada (barato, rápido), pero documentos más largos escalan a
# 2, 3, N fragmentos en paralelo (hasta _MAX_LLAMADAS_SIMULTANEAS_DEEPSEEK
# a la vez) en vez de arriesgarse a una única llamada demasiado grande --
# reduce cuánto puede perderse si UNA llamada falla, y baja de verdad la
# frecuencia con la que se dispara el aviso de generación parcial (no lo
# sustituye: sigue siendo la red de seguridad para cuando aun así pase).
TAMANO_CHUNK_CARACTERES = 35000

# Umbral de la comprobación de tamaño de la fusión en
# generar_documento_largo_por_partes (10/08/2026, ver el comentario largo
# junto a su uso): por debajo de esta fracción del tamaño de entrada, un
# resultado de fusión se considera sospechoso y se reintenta en vez de
# aceptarse tal cual. 0.4 deja margen de sobra para el resumen/reequilibrado
# legítimo que algunos prompts de fusión piden entre secciones desiguales,
# muy por encima del colapso real observado (una fusión de ~4 fragmentos
# que se quedó en un solo apartado, <5% de la entrada).
_FRACCION_MINIMA_FUSION = 0.4

# Tope de tiempo total (10/08/2026, bug real: un usuario reportó una
# generación que se quedó "Generando..." durante más de 10 minutos sin
# terminar nunca). Antes, generar_documento_largo_por_partes podía
# encadenar hasta 4 rondas secuenciales (MAP inicial, reintento del MAP,
# fusión, reintento de la fusión), cada una con su propio margen de
# reintentos de red y continuación por truncamiento -- en el peor caso
# (poco probable pero real, sobre todo con un documento que le cuesta a la
# IA) esas rondas se sumaban sin ningún límite conjunto. Ahora se lleva la
# cuenta del tiempo transcurrido desde que arrancó esta función: si al
# empezar una ronda nueva (reintento del MAP, fusión, reintento de la
# fusión) ya no queda margen, esa ronda se salta directamente y se
# abandona la generación (mismo camino que cualquier otro fallo: no se
# guarda nada incompleto, se devuelve la cuota) en vez de seguir
# encadenando. No cancela una llamada YA en marcha (no es seguro
# interrumpir a mitad una petición HTTP), pero sí evita que seguir
# encadenando rondas dispare el tiempo total sin tope.
# Subido de 150 a 240 (10/08/2026, bug real: seguía dando "se agotó el
# tiempo máximo" con documentos de 7 fragmentos incluso tras juntar todos
# los workers en una sola tanda -- ver el comentario de max_workers más
# abajo). 150s no dejaba margen de verdad: una sola llamada de
# generar_con_continuacion, en el peor caso (timeout de 60s + 2 reintentos
# transitorios con su espera, multiplicado por hasta 3 rondas de
# continuación si el modelo sigue cortando por longitud) puede tardar
# varios minutos ella sola sin que eso sea ningún fallo -- es la política
# de reintento normal ante inestabilidad real de DeepSeek (ver el
# comentario de _MAX_LLAMADAS_SIMULTANEAS_DEEPSEEK). 240s deja margen de
# sobra por debajo de --timeout 300 del worker de gunicorn (ver
# render.yaml) para que el propio proceso HTTP no se vea interrumpido antes.
_TIEMPO_MAXIMO_GENERACION_SEGUNDOS = 240

# Igual que _FRACCION_MINIMA_FUSION pero para un fragmento INDIVIDUAL del
# MAP frente a SU PROPIO texto de entrada (10/08/2026, bug real: con un
# documento de 4 fragmentos de ~15.000 caracteres cada uno, el colapso no
# siempre pasaba en la fusión -- a veces el propio fragmento (p. ej. el
# último, el que contenía las disposiciones adicionales del final de la
# ley) ya venía degenerado del MAP, cubriendo solo su propio último
# apartado en vez de todo su contenido. La comprobación de la fusión no lo
# detectaba porque compara la fusión contra la SUMA de los parciales
# recibidos -- si un parcial YA era pequeño, la fusión podía "conservarlo
# fielmente" sin perder nada MÁS y aun así pasar esa comprobación, aunque
# le faltara casi todo el fragmento original. Más bajo que el de fusión
# porque un mapa de artículos SÍ condensa mucho un fragmento de entrada
# (es su función), no solo lo reorganiza como hace la fusión.
_FRACCION_MINIMA_MAP = 0.15

# Umbrales propios para el ESQUEMA (10/08/2026, bug real: un usuario reportó
# que el esquema fallaba sistemáticamente mientras el resumen del MISMO
# documento no). Un esquema es, por diseño de su propio prompt, un árbol de
# epígrafes en viñetas cortas -- no prosa -- así que, incluso completo y
# bien hecho, es mucho más compacto frente a su fuente que un resumen
# narrativo o que un mapa de artículos. Con los umbrales generales (0.15 /
# 0.4, calibrados pensando en prosa) un esquema correcto pero condensado se
# marcaba como "colapsado", se reintentaba y acababa abandonándose sin
# devolver nada. Más bajos que los generales pero no cero: siguen
# detectando el colapso real (una sola frase o apartado en vez del árbol
# completo, muy por debajo incluso de estos umbrales).
FRACCION_MINIMA_MAP_ESQUEMA = 0.08
FRACCION_MINIMA_FUSION_ESQUEMA = 0.2


# Separadores que _trocear_en_parrafos prueba en cascada, del más "natural"
# (mejor punto de corte) al más forzado.
_SEPARADORES_TROCEADO = ["\n\n", "\n", " "]


def _trocear_en_parrafos(texto, tamano=TAMANO_CHUNK_CARACTERES):
    """Trocea el texto en fragmentos de como mucho 'tamano' caracteres,
    cortando siempre en un punto "natural" -- salto de párrafo si el texto
    tiene, si no salto de línea, si no un espacio -- para no partir una
    idea a mitad de palabra si se puede evitar.

    Bug real (10/08/2026): pypdf's extract_text() a menudo NO deja ningún
    "\\n\\n" en el texto extraído (depende de cómo esté maquetado el PDF
    de origen -- comprobado con un BOE real: 0 dobles saltos en 51.000
    caracteres). Con solo "\\n\\n" como separador, texto.split("\\n\\n")
    devolvía UN SOLO "párrafo" con el documento entero, así que ni
    siquiera intentaba trocearlo por mucho que superara 'tamano' -- el
    documento completo se mandaba de una sola vez a la IA en un único
    prompt gigante, que la desbordaba y devolvía un resultado válido en
    formato pero catastróficamente incompleto (un resumen de 14 páginas
    reducido a un párrafo). Ahora, si el separador actual no aparece en el
    texto (o dividir por él deja algún trozo que sigue sin caber),
    se prueba con el siguiente separador de la cascada antes de rendirse."""
    return _trocear_recursivo(texto, tamano, _SEPARADORES_TROCEADO)


def _trocear_recursivo(texto, tamano, separadores):
    if len(texto) <= tamano:
        return [texto]
    if not separadores:
        # Sin separadores que valgan (ni siquiera un espacio en todo el
        # texto): último recurso, corte duro por número de caracteres, para
        # no dejar nunca un fragmento sin trocear por muy patológico que
        # sea el texto de entrada.
        return [texto[i:i + tamano] for i in range(0, len(texto), tamano)]

    separador, *resto = separadores
    piezas = texto.split(separador)
    if len(piezas) == 1:
        # Este separador no aparece en el texto -- prueba con el siguiente.
        return _trocear_recursivo(texto, tamano, resto)

    fragmentos = []
    actual = ""
    for pieza in piezas:
        candidato = f"{actual}{separador}{pieza}" if actual else pieza
        if actual and len(candidato) > tamano:
            fragmentos.append(actual)
            actual = pieza
        else:
            actual = candidato
    if actual:
        fragmentos.append(actual)

    # Cualquier fragmento que aún así siga superando 'tamano' (una sola
    # pieza, entre dos apariciones de este separador, ya demasiado larga
    # por sí sola) se retrocea con el siguiente separador de la cascada.
    resultado = []
    for fragmento in fragmentos:
        if len(fragmento) > tamano:
            resultado.extend(_trocear_recursivo(fragmento, tamano, resto))
        else:
            resultado.append(fragmento)
    return resultado


def generar_documento_largo_por_partes(
    system_prompt, texto, etiqueta_documento="Documento", max_tokens=4096,
    instrucciones_fusion_extra=None, on_usage=None, on_progreso=None,
    tamano_chunk=TAMANO_CHUNK_CARACTERES,
    fraccion_minima_map=_FRACCION_MINIMA_MAP,
    fraccion_minima_fusion=_FRACCION_MINIMA_FUSION,
    evento_parada=None,
):
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

    Devuelve None SOLO si no se pudo aprovechar NINGÚN fragmento (10/08/2026,
    bug real: antes, si fallaba UN SOLO fragmento incluso tras reintentar, se
    descartaba TODO el documento -- con un documento de varios fragmentos
    era habitual que el usuario se quedara sin nada una y otra vez aunque la
    mayoría se hubiera generado bien). Si sobrevivió al menos un fragmento,
    se devuelve el documento construido con lo que sí se generó bien
    (fundido si hay tiempo y la fusión sale bien, sin fundir si no) con un
    aviso "> **Aviso:** ..." antepuesto en Markdown -- visible para el
    usuario, no un fallo silencioso (eso fue el bug original de esta misma
    función).

    Con un documento que ya cabe en un único prompt (la inmensa mayoría desde
    que TAMANO_CHUNK_CARACTERES subió a 90000): una sola llamada a
    generar_con_continuacion, sin fusión -- pero con el mismo criterio de
    "¿es sospechosamente corta frente a lo que se le pidió cubrir?" que un
    fragmento del MAP, reintento incluido, para no dejar pasar en silencio
    una llamada que se rindió antes de tiempo.

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
    mensajes rotativos cosméticos que tenían antes.

    tamano_chunk (10/08/2026, bug real): tamaño de fragmento a usar en vez
    del TAMANO_CHUNK_CARACTERES por defecto -- para el mapa de artículos de
    texto legal, que exige cubrir CADA artículo sin omitir ninguno (un
    listón mucho más exigente que el resumen narrativo), un fragmento de
    15.000 caracteres puede traer varias decenas de artículos, y ni
    siquiera con más max_tokens el modelo los cubría todos de forma fiable
    (visto en producción: fallaba una y otra vez con el mismo documento,
    incluso tras reintentar). Fragmentos más pequeños bajan de verdad la
    exigencia por llamada, en vez de solo darle más presupuesto de salida
    para la misma tarea.

    fraccion_minima_map / fraccion_minima_fusion (10/08/2026, bug real): los
    umbrales de _FRACCION_MINIMA_MAP/_FRACCION_MINIMA_FUSION por defecto se
    calibraron pensando en un resumen NARRATIVO, que se queda cerca del
    tamaño del texto de origen. Un ESQUEMA (árbol de epígrafes en viñetas,
    sin prosa) es, por diseño de su propio prompt, mucho más compacto que su
    fuente incluso estando completo y bien hecho -- con el umbral por
    defecto, un esquema correcto pero condensado se podía marcar como
    "colapsado", reintentar y acabar abandonándose (visto en producción: el
    esquema fallaba mientras el resumen del mismo documento no). Estos dos
    parámetros permiten que cada llamante pase un umbral más bajo y
    realista para su propio formato de salida, en vez de forzar el mismo
    listón a todos los documentos por igual.

    evento_parada (10/08/2026, threading.Event opcional, ver
    generacion_control.py): si se pasa y está marcado, se trata igual que
    agotar el tiempo máximo -- se deja de lanzar RONDAS nuevas (reintento,
    fusión, reintento de la fusión) y se devuelve lo que ya hubiera
    disponible, con aviso si es parcial. No cancela ninguna llamada YA en
    marcha (no es seguro interrumpir una petición HTTP a mitad), solo evita
    lanzar más."""
    limite_tiempo = time.monotonic() + _TIEMPO_MAXIMO_GENERACION_SEGUNDOS

    def _debe_abandonar():
        return time.monotonic() >= limite_tiempo or bool(evento_parada and evento_parada.is_set())

    fragmentos = _trocear_en_parrafos(texto, tamano=tamano_chunk)
    if len(fragmentos) == 1:
        # Bug real (10/08/2026): al subir TAMANO_CHUNK_CARACTERES a 90000,
        # este camino de una sola llamada pasó de ser un caso raro a ser el
        # habitual -- y, a diferencia del camino de varios fragmentos, no
        # tenía NINGUNA comprobación de que la respuesta cubriera de verdad
        # el documento. Visto en producción: una llamada que se cortaba a
        # mitad de palabra, muy por debajo de max_tokens, sin marcar
        # finish_reason=length (así que generar_con_continuacion no lo
        # trata como truncado) -- el mismo "el modelo se rinde antes de
        # tiempo" que ya se detectaba en el MAP y en la fusión, pero que
        # aquí pasaba sin ningún control. Mismo criterio que un fragmento
        # del MAP: si el resultado es sospechosamente corto frente a la
        # entrada, se reintenta una vez; si sigue igual, se devuelve con
        # aviso visible en vez de un documento silenciosamente incompleto.
        def _intento_unico():
            return generar_con_continuacion(system_prompt, f"{etiqueta_documento}:\n{texto}", max_tokens=max_tokens, on_usage=on_usage)

        def _sospechoso(r):
            return not r or len(r) < len(texto) * fraccion_minima_map

        # Evento de progreso AL EMPEZAR, no solo al terminar (10/08/2026, bug
        # real: sin esto, on_progreso solo se llamaba una vez al final, así
        # que progreso_resumen/progreso_esquema en Firestore no reflejaba
        # "generando" hasta que YA había terminado -- inútil como señal de
        # que sigue vivo mientras el usuario espera, ver el comentario largo
        # en blueprints/pdf_ia.py sobre el sondeo del frontend).
        if on_progreso:
            on_progreso({"completadas": 0, "total": 1, "fase": "generando"})
        resultado = _intento_unico()
        if _sospechoso(resultado):
            logger.warning(
                "generar_documento_largo_por_partes: la única llamada (documento sin trocear) "
                "devolvió %s caracteres frente a los %d de entrada -- reintentando una vez.",
                len(resultado) if resultado else 0, len(texto),
            )
            resultado = _intento_unico()
            if not resultado:
                logger.warning(
                    "generar_documento_largo_por_partes: la única llamada sigue fallando tras "
                    "reintentar -- se abandona."
                )
                return None
            if _sospechoso(resultado):
                logger.warning(
                    "generar_documento_largo_por_partes: la única llamada sigue devolviendo muy "
                    "poco contenido tras reintentar -- se devuelve con aviso en vez de un "
                    "documento silenciosamente incompleto."
                )
                resultado = (
                    "> **Aviso:** no se ha podido generar este documento por completo por un "
                    "problema temporal con la IA. Pulsa «Regenerar» para intentarlo de nuevo.\n\n"
                ) + resultado
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
    # Ronda inicial acotada al tiempo máximo (10/08/2026, bug real: con esta
    # ronda sin límite, el tiempo total podía superar los _TIEMPO_MAXIMO_...
    # 150s pactados -- en producción se vieron 221s porque el límite solo se
    # comprobaba en el reintento y en la fusión, nunca aquí). No se usa
    # "with ThreadPoolExecutor(...) as executor" a propósito: su __exit__
    # llama a shutdown(wait=True) incondicionalmente y bloquearía hasta que
    # TODAS las llamadas en curso terminen, anulando el propio timeout de
    # as_completed. En su lugar se crea el executor a mano y se cierra con
    # shutdown(wait=False): los fragmentos que no respondieron a tiempo
    # siguen su llamada HTTP en segundo plano (no es seguro cancelar una
    # petición de requests ya en vuelo) pero la función no espera por ellos.
    # max_workers = _MAX_LLAMADAS_SIMULTANEAS_DEEPSEEK, no un tope fijo más
    # bajo (10/08/2026, bug real: con un tope de 4, un documento legal de 7
    # fragmentos -- nada raro con tamano_chunk=8000 -- se partía en 2 tandas
    # secuenciales de 4+3, duplicando el tiempo de pared necesario sin
    # ninguna ventaja real: el semáforo global _semaforo_deepseek ya limita
    # la concurrencia total hacia DeepSeek de toda la app a la vez, así que
    # restringir TAMBIÉN el executor de un único documento por debajo de
    # ese límite solo servía para forzar tandas innecesarias y hacer más
    # fácil agotar _TIEMPO_MAXIMO_GENERACION_SEGUNDOS).
    # Evento de progreso AL EMPEZAR (10/08/2026, mismo motivo que en la rama
    # de un solo fragmento, ver el comentario ahí): sin esto, el primer
    # evento de progreso no llega hasta que el primer fragmento termina, que
    # puede tardar bastante -- el usuario no ve ninguna señal de que la
    # generación arrancó de verdad hasta ese momento.
    if on_progreso:
        on_progreso({"completadas": 0, "total": len(fragmentos), "fase": "generando"})
    executor_inicial = ThreadPoolExecutor(max_workers=min(_MAX_LLAMADAS_SIMULTANEAS_DEEPSEEK, len(fragmentos)))
    futuro_a_indice = {executor_inicial.submit(_generar_parcial, item): item[0] for item in enumerate(fragmentos)}
    try:
        restante_inicial = max(limite_tiempo - time.monotonic(), 0)
        for futuro in as_completed(futuro_a_indice, timeout=restante_inicial):
            indice = futuro_a_indice[futuro]
            parciales_por_indice[indice] = futuro.result()
            completadas += 1
            if on_progreso:
                on_progreso({"completadas": completadas, "total": len(fragmentos), "fase": "generando"})
    except _FuturesTimeoutError:
        logger.warning(
            "generar_documento_largo_por_partes: se agotó el tiempo máximo (%ds) durante la "
            "primera ronda -- %d de %d fragmentos no respondieron a tiempo y se tratan como "
            "fallidos, sin esperar a que esas llamadas terminen en segundo plano.",
            _TIEMPO_MAXIMO_GENERACION_SEGUNDOS, len(fragmentos) - completadas, len(fragmentos),
        )
    finally:
        executor_inicial.shutdown(wait=False)

    def _fragmento_sospechoso(indice):
        """True si el parcial de ese índice es None, o si es sospechosamente
        corto respecto al fragmento de ENTRADA que se le pidió procesar --
        ver _FRACCION_MINIMA_MAP. Cubre tanto "la llamada falló" como "la
        llamada 'tuvo éxito' pero el modelo se rindió y solo cubrió una
        fracción mínima de su propio fragmento", que es indistinguible de
        un éxito real si solo se mira si hay o no resultado."""
        parcial = parciales_por_indice.get(indice)
        if not parcial:
            return True
        return len(parcial) < len(fragmentos[indice]) * fraccion_minima_map

    # Reintento de fragmentos fallidos o sospechosos (10/08/2026, bug real
    # reportado por un usuario: un resumen de 14 páginas se guardó con un
    # solo párrafo, el de la última "Disposición adicional"). Antes, un
    # fallo transitorio de red hacia DeepSeek (ver el comentario largo de
    # _REINTENTOS_TRANSITORIOS más arriba -- ocurre de verdad, no es
    # hipotético) en algún fragmento del MAP bastaba para que ese trozo del
    # documento desapareciera del resultado sin ningún aviso -- y si solo
    # sobrevivía uno, ANTES se devolvía tal cual como si fuera el documento
    # completo (ver más abajo), pasando la validación de formato porque sí
    # traía un encabezado "# " válido. Un reintento (mismo fragmento, misma
    # llamada) antes de rendirse del todo con ese trozo reduce la
    # probabilidad de que un simple parpadeo de red -- o que el modelo se
    # rinda con un fragmento concreto -- se lleve por delante contenido real.
    indices_fallidos = [i for i in range(len(fragmentos)) if _fragmento_sospechoso(i)]
    if indices_fallidos and not _debe_abandonar():
        # Mismo motivo que en la ronda inicial: no usar "with executor" porque
        # su shutdown(wait=True) implícito bloquearía sin límite si algún
        # reintento no responde a tiempo, anulando el timeout de as_completed.
        executor_reintento = ThreadPoolExecutor(max_workers=min(_MAX_LLAMADAS_SIMULTANEAS_DEEPSEEK, len(indices_fallidos)))
        futuro_a_indice = {
            executor_reintento.submit(_generar_parcial, (i, fragmentos[i])): i for i in indices_fallidos
        }
        try:
            restante_reintento = max(limite_tiempo - time.monotonic(), 0)
            for futuro in as_completed(futuro_a_indice, timeout=restante_reintento):
                indice = futuro_a_indice[futuro]
                parciales_por_indice[indice] = futuro.result()
        except _FuturesTimeoutError:
            logger.warning(
                "generar_documento_largo_por_partes: se agotó el tiempo máximo (%ds) durante el "
                "reintento -- algún fragmento no respondió a tiempo y sigue sospechoso.",
                _TIEMPO_MAXIMO_GENERACION_SEGUNDOS,
            )
        finally:
            executor_reintento.shutdown(wait=False)
    elif indices_fallidos:
        logger.warning(
            "generar_documento_largo_por_partes: se agotó el tiempo máximo (%ds) o se pidió "
            "detener la generación antes de poder reintentar %d fragmento(s) -- se abandona sin "
            "reintentar.",
            _TIEMPO_MAXIMO_GENERACION_SEGUNDOS, len(indices_fallidos),
        )

    # Degradación con aviso, no todo o nada (10/08/2026, bug real: incluso
    # tras el reintento, era habitual que 3-4 de 7 fragmentos de un
    # documento largo no llegaran a tiempo -- con la política anterior
    # ("si falta CUALQUIERA, se descarta TODO") eso significaba tirar
    # fragmentos ya generados y pagados, y el usuario se quedaba sin nada
    # una y otra vez pase lo que pase. Ahora solo se rinde del todo si NO
    # sobrevivió NINGÚN fragmento; si sobrevivió al menos uno, se construye
    # el documento con lo que sí se generó bien y se antepone un aviso
    # visible (no un fallo silencioso -- eso fue el bug original de esta
    # misma función) de que faltan secciones y hay que regenerar.
    indices_disponibles = [i for i in range(len(fragmentos)) if not _fragmento_sospechoso(i)]
    n_fallidos = len(fragmentos) - len(indices_disponibles)
    if not indices_disponibles:
        logger.warning(
            "generar_documento_largo_por_partes: los %d fragmentos fallaron o siguen sospechosos "
            "ni siquiera tras reintentar -- no hay nada aprovechable, se abandona.",
            len(fragmentos),
        )
        return None

    advertencia_parcial = ""
    if n_fallidos:
        logger.warning(
            "generar_documento_largo_por_partes: %d de %d fragmentos no se generaron bien ni "
            "siquiera tras reintentar -- se continúa con los %d restantes en vez de descartar todo "
            "el documento.",
            n_fallidos, len(fragmentos), len(indices_disponibles),
        )
        # Sin emoji (10/08/2026, bug real): las fuentes estándar de jsPDF
        # (helvetica) no tienen esos glifos -- un emoji aquí se veía como
        # caracteres sueltos ilegibles en el PDF descargado, y además
        # descuadraba el cálculo de ancho de splitTextToSize, cortando el
        # texto del aviso a mitad de palabra en vez de ajustarlo al recuadro.
        advertencia_parcial = (
            f"> **Aviso:** no se ha podido generar {n_fallidos} de {len(fragmentos)} "
            "secciones de este documento por un problema temporal con la IA. Pulsa «Regenerar» "
            "para completarlas.\n\n"
        )
    parciales = [parciales_por_indice[i] for i in indices_disponibles]

    # Con un único fragmento aprovechable no hay nada que fusionar de
    # verdad -- usarlo tal cual en vez de gastar una llamada más a fundir
    # "un solo trozo consigo mismo".
    if len(parciales) == 1:
        return advertencia_parcial + parciales[0]

    bloque_parciales = "\n\n---\n\n".join(parciales)

    if _debe_abandonar():
        logger.warning(
            "generar_documento_largo_por_partes: se agotó el tiempo máximo (%ds) o se pidió "
            "detener la generación antes de llegar a la fusión -- se devuelven los %d "
            "fragmentos sin fundir en vez de nada.",
            _TIEMPO_MAXIMO_GENERACION_SEGUNDOS, len(parciales),
        )
        return advertencia_parcial + bloque_parciales

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
    fusionado = generar_con_continuacion(prompt_fusion, bloque_parciales, max_tokens=max_tokens, on_usage=on_usage)

    # Comprobación de tamaño de la fusión (10/08/2026, bug real: con los
    # fragmentos ya generados y válidos por separado, la llamada de fusión a
    # veces "colapsaba" -- el modelo respondía con solo una fracción mínima
    # del contenido (p. ej. un único apartado del último fragmento) y
    # paraba de forma NATURAL (finish_reason distinto de "length", así que
    # generar_con_continuacion no lo detecta como truncado) en vez de
    # fusionar de verdad los fragmentos recibidos. Como el resultado sí
    # tenía un encabezado Markdown válido, pasaba la validación de formato
    # de _parece_documento_generado_valido sin levantar sospecha -- así es
    # como un usuario real acabó con un "resumen" de 14 páginas reducido a
    # un solo párrafo. Un resultado de fusión drásticamente más corto que
    # la suma de lo que se le pidió fusionar es una señal barata y fiable
    # de que se perdió contenido real, sin tener que comparar dato por
    # dato -- se reintenta una vez antes de renunciar A LA FUSIÓN (no al
    # documento entero: si la fusión sigue colapsando, se devuelven los
    # parciales sin fundir en vez de nada -- misma filosofía que arriba).
    if fusionado and len(fusionado) < len(bloque_parciales) * fraccion_minima_fusion:
        if _debe_abandonar():
            logger.warning(
                "generar_documento_largo_por_partes: la fusión colapsó y se agotó el tiempo "
                "máximo (%ds) o se pidió detener la generación antes de poder reintentarla -- "
                "se devuelven los fragmentos sin fundir en vez de nada.",
                _TIEMPO_MAXIMO_GENERACION_SEGUNDOS,
            )
            return advertencia_parcial + bloque_parciales
        logger.warning(
            "generar_documento_largo_por_partes: la fusión de %d fragmentos devolvió solo %d "
            "caracteres frente a los %d de entrada -- reintentando una vez.",
            len(parciales), len(fusionado), len(bloque_parciales),
        )
        fusionado = generar_con_continuacion(prompt_fusion, bloque_parciales, max_tokens=max_tokens, on_usage=on_usage)
        if fusionado and len(fusionado) < len(bloque_parciales) * fraccion_minima_fusion:
            logger.warning(
                "generar_documento_largo_por_partes: la fusión sigue devolviendo muy poco "
                "contenido tras reintentar -- se devuelven los fragmentos sin fundir en vez de nada."
            )
            return advertencia_parcial + bloque_parciales
    if not fusionado:
        # generar_con_continuacion devolvió None (fallo de red/HTTP en la
        # propia llamada de fusión, no colapso de contenido) -- mismo
        # motivo: los parciales YA generados siguen siendo aprovechables.
        logger.warning(
            "generar_documento_largo_por_partes: la llamada de fusión falló -- se devuelven los "
            "fragmentos sin fundir en vez de nada."
        )
        return advertencia_parcial + bloque_parciales
    return advertencia_parcial + fusionado


# Versión en streaming de call_deepseek_api: en vez de devolver el texto
# completo de una vez, va cediendo (yield) cada fragmento tal y como lo manda
# DeepSeek (protocolo SSE, "data: {...}" por línea, terminado en "data:
# [DONE]"), para poder mostrarlo en el frontend con efecto de escritura en
# vez de esperar a que termine toda la respuesta.
def call_deepseek_api_stream(messages, max_tokens=1500, temperature=0.7, model="deepseek-v4-flash"):
    """model por defecto "deepseek-v4-flash" (ver call_deepseek_api). Con
    "deepseek-v4-pro" (el modelo de razonamiento) emite primero tokens de
    razonamiento internos (campo `delta.reasoning_content`, no
    `delta.content`) antes de la respuesta final -- como abajo solo se cede
    `delta.content`, esos tokens de razonamiento quedan descartados
    automáticamente (nunca llegan al frontend), pero sí se facturan: puede
    haber un silencio inicial más largo antes de que empiece a aparecer
    texto."""
    api_key = os.getenv("DEEPSEEK_API_KEY")

    if not api_key:
        logger.error("No hay API key de DeepSeek configurada")
        return

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
        # Pide que el último chunk del stream incluya el consumo de tokens,
        # para poder contabilizar el coste también en las respuestas en
        # streaming (Tu Tutor, test personalizado).
        "stream_options": {"include_usage": True},
    }
    if model != "deepseek-reasoner":
        payload["temperature"] = temperature

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
    except requests.exceptions.HTTPError as e:
        cuerpo = e.response.text[:500] if e.response is not None else ""
        logger.warning("Error en streaming de DeepSeek: %s -- %s", e, cuerpo)
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