"""Generador de tarjetas de memoria (flashcards) a partir de un PDF subido
por el usuario, con arquitectura generar -> verificar -> reintentar (mismo
principio que generador_preguntas_verificado.py usa para Test
Personalizado, adaptado a un array de tarjetas en vez de un test):

  1. El texto se trocea en fragmentos (ver deepseek_utils._trocear_en_parrafos)
     y las tarjetas se reparten y generan por fragmento, en paralelo -- sin
     necesitar una fusión con IA como resumen/esquema, porque cada
     fragmento es un tramo de texto no solapado (basta con concatenar y
     deduplicar el resultado).
  2. Cada tarjeta candidata se verifica con una SEGUNDA llamada
     independiente, que recibe el mismo fragmento de origen y comprueba la
     respuesta contra él, no contra sí misma.
  3. Si la verificación falla (o la tarjeta resulta duplicada de otra ya
     aceptada), se descarta POR COMPLETO -- nunca se corrige/parchea -- y
     se pide una de recambio sobre el mismo fragmento evitando su tema,
     hasta MAX_INTENTOS_POR_TARJETA veces. Si se agotan, esa tarjeta se
     pierde para ese hueco.
  4. Si al terminar la fase anterior siguen faltando tarjetas (por huecos
     perdidos en el paso 3, o porque algún fragmento devolvió menos
     candidatas de las pedidas en su generación inicial), se rellenan
     ciclando entre los fragmentos disponibles, con la misma verificación
     sin relajar -- solo si ni así se completa el número pedido se avisa
     al final en vez de entregarse sin validar.
"""
import itertools
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from deepseek_utils import call_deepseek_api, _trocear_en_parrafos
from validador_preguntas import FRASES_PROHIBIDAS, contiene_referencia_meta

logger = logging.getLogger(__name__)

MAX_INTENTOS_POR_TARJETA = 3
_MAX_WORKERS_GENERACION = 4
_MAX_WORKERS_VERIFICACION = 6


def _normalizar(texto):
    return re.sub(r"\s+", " ", str(texto or "").strip().lower())


# Longitud mínima de la respuesta normalizada para entrar en la comparación
# de contención/solapamiento de abajo (05/08/2026, mismo valor y mismo
# motivo que _LONGITUD_MINIMA_CONTENCION en test_generator.py: por debajo
# de esto una coincidencia de texto es demasiado corta para ser una señal
# fiable de que dos tarjetas tratan el mismo hecho -- daría falsos
# positivos con respuestas cortas tipo "Sí." o "El Consejo.").
_LONGITUD_MINIMA_CONTENCION_TARJETA = 25
# Umbral de solapamiento de palabras (índice de Jaccard) para considerar dos
# respuestas el mismo hecho reformulado -- mismo valor 0.5 ya probado con
# datos reales en test_generator.py._UMBRAL_SOLAPAMIENTO_RESPUESTA (separa
# con margen amplio una reformulación del mismo hecho, 0.5-0.9, de dos
# hechos legítimamente distintos, que dan como mucho ~0.2).
_UMBRAL_SOLAPAMIENTO_TARJETA = 0.5


def _solapamiento_palabras(texto_a, texto_b):
    """Proporción de Jaccard entre las palabras de dos textos (intersección
    entre unión) -- ver _UMBRAL_SOLAPAMIENTO_TARJETA."""
    palabras_a = set(re.findall(r"\w+", texto_a))
    palabras_b = set(re.findall(r"\w+", texto_b))
    if not palabras_a or not palabras_b:
        return 0.0
    return len(palabras_a & palabras_b) / len(palabras_a | palabras_b)


def _es_semanticamente_duplicada(tarjeta, tarjetas_existentes):
    """Red de seguridad SEMÁNTICA adicional al dedup por texto exacto de
    _normalizar (05/08/2026, bug real reportado por el usuario: comparando
    un banco de 100 tarjetas generadas contra su PDF de origen, ~40-50 eran
    reformulaciones del mismo puñado de hechos -- p.ej. 10 tarjetas
    distintas preguntando, cada una con otras palabras, qué mecanismos de
    ayuda financiera creó la UE. El dedup por _normalizar solo caza el
    texto IDÉNTICO de la pregunta, así que ninguna de esas reformulaciones
    se detectaba entre sí).

    Mismo enfoque que _es_duplicado_por_contencion en test_generator.py
    (deliberadamente simplificado: sin el filtro de "mismo artículo citado"
    de ahí, porque las tarjetas no siempre citan un número de artículo y
    exigirlo aquí solo perdería recall) -- compara la RESPUESTA normalizada
    de la tarjeta candidata contra la de cada tarjeta ya aceptada, por
    CONTENCIÓN (una es un fragmento literal de la otra) o por SOLAPAMIENTO
    DE PALABRAS (mismo hecho con las palabras reordenadas o alguna
    distinta). No compara el enunciado de la pregunta -- dos preguntas
    pueden abordar el mismo hecho desde ángulos de redacción muy distintos,
    pero si la respuesta correcta es esencialmente la misma, es la misma
    tarjeta en la práctica."""
    respuesta = _normalizar(tarjeta.get("respuesta", ""))
    if len(respuesta) < _LONGITUD_MINIMA_CONTENCION_TARJETA:
        return False
    for otra in tarjetas_existentes:
        otra_respuesta = _normalizar(otra.get("respuesta", ""))
        if len(otra_respuesta) < _LONGITUD_MINIMA_CONTENCION_TARJETA:
            continue
        if respuesta in otra_respuesta or otra_respuesta in respuesta:
            return True
        if _solapamiento_palabras(respuesta, otra_respuesta) >= _UMBRAL_SOLAPAMIENTO_TARJETA:
            return True
    return False


# 12/08/2026: NO se reutiliza el 10 de test_generator.py._LONGITUD_MINIMA_
# DEDUP_RESPUESTA a propósito -- ahí "respuesta" es el texto de una opción
# de test (corta por naturaleza, "15 días", "El Congreso"), pero aquí
# "respuesta" es el texto LIBRE completo de una tarjeta, mucho más largo en
# general -- con 10 caracteres, dos tarjetas sobre hechos DISTINTOS que
# coinciden en una respuesta corta genérica ("Sí.", "El Rey.") se marcarían
# como duplicadas (bug real visto en un test de este archivo: dos tarjetas
# de relleno legítimas y distintas compartían la misma respuesta corta de
# prueba). Se reutiliza el mismo umbral y el mismo razonamiento que
# _LONGITUD_MINIMA_CONTENCION_TARJETA, ya calibrado para este campo.
_LONGITUD_MINIMA_DEDUP_RESPUESTA_TARJETA = _LONGITUD_MINIMA_CONTENCION_TARJETA

_PATRON_ARTICULO_BASE = re.compile(r"art[íi]culo\s+(\d+)", re.IGNORECASE)

_NUMEROS_EN_PALABRAS = {
    "un": "1", "uno": "1", "una": "1", "dos": "2", "tres": "3", "cuatro": "4",
    "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9", "diez": "10",
}
_DENOMINADORES_EN_PALABRAS = {
    "tercio": "3", "cuarto": "4", "quinto": "5", "sexto": "6", "septimo": "7",
    "octavo": "8", "noveno": "9", "decimo": "10",
}
_DENOMINADORES_ORDINAL_FEMENINO = {
    "segunda": "2", "tercera": "3", "cuarta": "4", "quinta": "5", "sexta": "6",
    "septima": "7", "octava": "8", "novena": "9", "decima": "10",
}
# _PATRON_CIFRA/_PATRON_PRINCIPIO_JURIDICO/_normalizar_cifra (12/08/2026,
# porte de test_generator.py._claves_dedup, ver el comentario largo de
# _claves_dedup más abajo): copia literal, sin adaptación -- son regex de
# reconocimiento de cifras/principios jurídicos en español, no dependen de
# la forma concreta de una pregunta ni de una tarjeta.
_PATRON_CIFRA = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:d[íi]as?\s+h[áa]biles?|d[íi]as?\s+naturales?|d[íi]as?|"
    r"meses?|mes\b|a[ñn]os?|tercios?|cuartos?|%|por\s*ciento)"
    r"|\d+\s*/\s*\d+"
    r"|(?:un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+"
    r"(?:tercios?|cuartos?|quintos?|sextos?|s[ée]ptimos?|octavos?|novenos?|d[ée]cimos?)"
    r"|(?:un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+"
    r"(?:segunda|tercera|cuarta|quinta|sexta|s[ée]ptima|octava|novena|d[ée]cima)s?\s+partes?"
    r"|mayor[íi]a\s+(?:absoluta|simple|cualificada|relativa)",
    re.IGNORECASE,
)
_PATRON_PRINCIPIO_JURIDICO = re.compile(
    r"principio\s+de\s+legalidad"
    r"|principio\s+de\s+jerarqu[íi]a\s+normativa"
    r"|principio\s+de\s+publicidad(?:\s+de\s+las\s+normas)?"
    r"|principio\s+de\s+irretroactividad"
    r"|principio\s+de\s+seguridad\s+jur[íi]dica"
    r"|principio\s+de\s+responsabilidad"
    r"|interdicci[óo]n\s+de\s+la\s+arbitrariedad",
    re.IGNORECASE,
)


def _normalizar_cifra(cifra):
    """Reduce una cifra encontrada por _PATRON_CIFRA a una forma canónica
    para que "dos tercios", "2/3" y "2 tercios" -- la misma fracción
    escrita de tres formas distintas -- produzcan la MISMA clave de dedup
    en vez de tres claves distintas que no se reconocen entre sí. Las
    cifras que no son una fracción (p.ej. "15 días hábiles", "mayoría
    absoluta") se devuelven tal cual, ya normalizadas en espacios por
    _normalizar aguas arriba."""
    coincide_barra = re.fullmatch(r"(\d+)\s*/\s*(\d+)", cifra)
    if coincide_barra:
        return f"{coincide_barra.group(1)}/{coincide_barra.group(2)}"
    coincide_fraccion = re.fullmatch(
        r"(\d+|[a-záéíóúñ]+)\s+(tercios?|cuartos?|quintos?|sextos?|s[ée]ptimos?|octavos?|novenos?|d[ée]cimos?)",
        cifra,
    )
    if coincide_fraccion:
        numerador = _NUMEROS_EN_PALABRAS.get(coincide_fraccion.group(1), coincide_fraccion.group(1))
        denominador_singular = re.sub(r"s$", "", coincide_fraccion.group(2)).replace("é", "e")
        denominador = _DENOMINADORES_EN_PALABRAS.get(denominador_singular)
        if denominador:
            return f"{numerador}/{denominador}"
    coincide_parte = re.fullmatch(
        r"(\d+|[a-záéíóúñ]+)\s+(segunda|tercera|cuarta|quinta|sexta|s[ée]ptima|octava|novena|d[ée]cima)s?\s+partes?",
        cifra,
    )
    if coincide_parte:
        numerador = _NUMEROS_EN_PALABRAS.get(coincide_parte.group(1), coincide_parte.group(1))
        denominador_singular = coincide_parte.group(2).replace("é", "e")
        denominador = _DENOMINADORES_ORDINAL_FEMENINO.get(denominador_singular)
        if denominador:
            return f"{numerador}/{denominador}"
    coincide_porcentaje = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(?:%|por\s*ciento)", cifra)
    if coincide_porcentaje:
        return f"{coincide_porcentaje.group(1)}%"
    return cifra


def _articulos_citados(tarjeta):
    """Números base de artículo citados en la PREGUNTA (anverso) -- o, si
    la pregunta no cita ninguno, en la RESPUESTA (reverso) como respaldo.
    Adaptado de _articulos_citados en test_generator.py (enunciado/
    explicación) a la forma de una tarjeta: el anverso es la analogía del
    enunciado, y el reverso -- que suele citar el artículo, ver el punto
    "Precisión normativa" del prompt de generación -- es la analogía de la
    explicación como respaldo. NO se usa la unión de ambos campos, por el
    mismo motivo que allí: la pregunta es la fuente fiable de qué artículo
    trata la tarjeta cuando lo cita; la respuesta solo se consulta como
    respaldo cuando la pregunta no cita ninguno."""
    articulos_pregunta = set(_PATRON_ARTICULO_BASE.findall(tarjeta.get("pregunta", "")))
    if articulos_pregunta:
        return articulos_pregunta
    return set(_PATRON_ARTICULO_BASE.findall(tarjeta.get("respuesta", "")))


def _conceptos_juridicos_citados(tarjeta):
    texto = f"{tarjeta.get('pregunta', '')} {_normalizar(tarjeta.get('respuesta', ''))}".lower()
    return set(_PATRON_PRINCIPIO_JURIDICO.findall(texto))


def _claves_dedup(tarjeta):
    """Claves de deduplicación de una tarjeta candidata/aceptada -- porte de
    _claves_dedup en test_generator.py a la forma {pregunta, respuesta} de
    una tarjeta (aquí "respuesta" ya es el texto directo, no una letra que
    mirar en un diccionario de opciones). Complementa, no sustituye, a
    _es_semanticamente_duplicada: esa red no exige artículo citado a
    propósito (para no perder recall en tarjetas sin cita normativa), esta
    caza el caso de alta precisión -- mismo artículo Y mismo dato concreto
    (cifra o principio jurídico con nombre propio) -- aunque la redacción
    sea completamente distinta y no llegue al umbral de solapamiento de
    palabras de la respuesta.

    'p:' texto exacto de la pregunta, 'r:' texto exacto de la respuesta (si
    es lo bastante larga para ser una señal fiable), 'd:' artículo base +
    conjunto de cifras citadas en la respuesta, 'c:' artículo base +
    principios jurídicos con nombre propio citados."""
    claves = set()
    clave_pregunta = _normalizar(tarjeta.get("pregunta", ""))
    if clave_pregunta:
        claves.add(f"p:{clave_pregunta}")
    clave_respuesta = _normalizar(tarjeta.get("respuesta", ""))
    if len(clave_respuesta) >= _LONGITUD_MINIMA_DEDUP_RESPUESTA_TARJETA:
        claves.add(f"r:{clave_respuesta}")
    articulos = sorted(_articulos_citados(tarjeta))
    cifras = sorted({_normalizar_cifra(c) for c in _PATRON_CIFRA.findall(clave_respuesta)})
    if articulos and cifras:
        claves.add(f"d:{'|'.join(articulos)}:{'|'.join(cifras)}")
    conceptos = sorted(_conceptos_juridicos_citados(tarjeta))
    if articulos and conceptos:
        claves.add(f"c:{'|'.join(articulos)}:{'|'.join(conceptos)}")
    return claves


def _parsear_tarjetas(texto_bruto):
    """Extrae la lista de tarjetas candidatas de la respuesta cruda de
    DeepSeek. Con response_format_json=True el modo JSON nativo de la API
    (igual que el de OpenAI, en el que se basa) garantiza JSON
    sintácticamente válido pero NO un array top-level -- por eso el prompt
    pide envolverlo en {"tarjetas": [...]}. Por si el modelo ignora el
    envoltorio y devuelve un array suelto, se acepta también esa forma."""
    if not texto_bruto:
        return []
    try:
        datos = json.loads(texto_bruto)
    except json.JSONDecodeError:
        return []
    if isinstance(datos, dict) and isinstance(datos.get("tarjetas"), list):
        return datos["tarjetas"]
    if isinstance(datos, list):
        return datos
    return []


def _repartir_cupos(n_fragmentos, num_tarjetas):
    """Reparte num_tarjetas entre n_fragmentos lo más equitativamente
    posible -- los primeros fragmentos se llevan una tarjeta extra cuando
    no divide exacto (y, si num_tarjetas < n_fragmentos, solo los primeros
    fragmentos reciben cupo, el resto queda a 0 y no genera ninguna
    llamada)."""
    base = num_tarjetas // n_fragmentos
    resto = num_tarjetas % n_fragmentos
    return [base + (1 if i < resto else 0) for i in range(n_fragmentos)]


def _prompt_con_exclusion(system, tarjetas_a_evitar):
    """Añade al prompt de generación la lista de tarjetas que NO debe
    repetir -- ya aceptadas en rondas ANTERIORES de una misma generación
    adaptativa de banco (ver generar_banco_tarjetas_adaptativo). Mismo
    principio que _prompt_con_exclusion en test_generator.py para Test
    desde PDF: sin esto, cada ronda parte de cero y puede converger en las
    mismas tarjetas que una ronda anterior ya generó sobre el mismo
    fragmento."""
    tarjetas_a_evitar = [t for t in (tarjetas_a_evitar or []) if t]
    if not tarjetas_a_evitar:
        return system
    listado = "; ".join(tarjetas_a_evitar[:60])
    return system + (
        f"\n\nNo repitas ninguna de estas tarjetas, ya generadas en una ronda anterior: {listado}. "
        f"Aborda un aspecto distinto del fragmento."
    )


def _prompt_generacion(fragmento, cupo, evitar=None):
    system = (
        "Eres un experto en metodologías de estudio para oposiciones en España. Tu tarea es crear "
        "tarjetas de memoria (flashcards) de alta calidad a partir de un fragmento de documento "
        "normativo o temario. Cada tarjeta debe cumplir lo siguiente:\n"
        "1. **Formato**: una pregunta clara y específica en el anverso; una respuesta concisa, precisa y completa en el reverso.\n"
        "2. **Tipos de tarjetas**: combina diferentes formatos:\n"
        "   - Definiciones: \"¿Qué es...?\"\n"
        "   - Enumeraciones: \"¿Cuáles son los principios de...?\", \"¿Qué plazos establece la ley para...?\"\n"
        "   - Comparaciones: \"¿Cuál es la diferencia entre X e Y?\"\n"
        "   - Funciones/competencias: \"¿A quién corresponde...?\", \"¿Qué órgano es competente para...?\"\n"
        "   - Supuestos prácticos breves: \"Si un funcionario hace X, ¿qué tipo de falta comete?\"\n"
        "   - Excepciones o límites: \"¿En qué casos NO se aplica...?\"\n"
        "3. **Profundidad, no repetición**: evita generar varias tarjetas del mismo artículo. En su lugar, extrae los conceptos clave y formula preguntas distintas.\n"
        "4. **Precisión normativa**: si el texto menciona leyes, artículos, reales decretos, etc., inclúyelos en la respuesta, pero no como copia literal.\n"
        "5. **Evita**: preguntas vagas, respuestas largas, frases incompletas o contenido redundante.\n"
        "6. **Fidelidad al fragmento**: basa cada tarjeta ÚNICAMENTE en el fragmento proporcionado. No "
        "completes huecos con conocimiento propio ni inventes datos, cifras, fechas o artículos que no "
        "aparezcan en el texto.\n"
        "7. **Autonomía de la tarjeta**: quien repasa la tarjeta más adelante NO tiene el documento "
        "delante, solo la pregunta -- así que nunca remitas a él. Prohibido \"según el texto\", "
        "\"según el documento\", \"en el fragmento proporcionado\", \"lo que has subido\", \"lo "
        "mencionado\"/\"lo anterior\" ni similares. Afirma cada dato directamente, como si fuera "
        "conocimiento general de la materia.\n"
        f"Genera EXACTAMENTE {cupo} tarjeta{'s' if cupo != 1 else ''} (ni más ni menos)."
        + (f" No repitas esta pregunta, ya descartada: {evitar!r}. Aborda un aspecto distinto del fragmento." if evitar else "")
        + "\nDevuelve ÚNICAMENTE un JSON con esta forma exacta, sin bloques de código ni texto adicional:\n"
        '{"tarjetas": [{"pregunta": "...", "respuesta": "..."}]}'
    )
    user = f"Fragmento del documento para crear tarjetas de memoria:\n{fragmento}"
    return system, user


def _prompt_verificacion(tarjeta, fragmento):
    system = (
        "Eres un verificador independiente. Te llega una tarjeta de memoria (pregunta + respuesta) YA "
        "REDACTADA por otro proceso, y el ÚNICO fragmento de documento del que debería haber salido. No "
        "des por hecho que es correcta: comprueba la respuesta contra el fragmento palabra por palabra, "
        "como si la vieras por primera vez.\n\n"
        "Marca la tarjeta como inválida si detectas CUALQUIERA de estos problemas:\n"
        "1. La respuesta no está respaldada por el fragmento proporcionado (dato inventado o extrapolado).\n"
        "2. La respuesta es incompleta, ambigua o podría inducir a error en un examen real.\n"
        "3. La pregunta no tiene una única respuesta clara según el fragmento.\n"
        "4. Cualquier cifra, plazo, fecha, artículo o nombre citado no coincide EXACTAMENTE con el fragmento.\n\n"
        "Devuelve ÚNICAMENTE un JSON con esta forma exacta, sin texto adicional:\n"
        '{"valido": true, "problemas": []}\n'
        "Si encuentras algún problema, \"valido\" debe ser false y \"problemas\" debe listar cada motivo."
    )
    user = f"FRAGMENTO:\n{fragmento}\n\nTARJETA A VERIFICAR:\n{json.dumps(tarjeta, ensure_ascii=False)}"
    return system, user


def _generar_candidatas_fragmento(fragmento, cupo, on_usage, tarjetas_a_evitar=None):
    if cupo <= 0:
        return []
    system, user = _prompt_generacion(fragmento, cupo)
    system = _prompt_con_exclusion(system, tarjetas_a_evitar)
    generado = call_deepseek_api(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.3,
        max_tokens=min(8000, 200 + cupo * 220),
        response_format_json=True,
        on_usage=on_usage,
        # stream=True (02/08/2026, arreglo real de producción: este archivo
        # se había quedado sin el fix de streaming que ya tenía
        # generador_preguntas_verificado.py -- un despiste, no una
        # decisión). Sin streaming, cualquier llamada que tarda más de ~30s
        # en generar muere con "Error de conexión: no se pudo conectar a
        # DeepSeek API" -- ver el comentario largo en
        # deepseek_utils._leer_respuesta_en_streaming.
        stream=True,
    )
    candidatas = []
    for c in _parsear_tarjetas(generado):
        if isinstance(c, dict) and c.get("pregunta") and c.get("respuesta"):
            candidatas.append({"pregunta": str(c["pregunta"]).strip(), "respuesta": str(c["respuesta"]).strip()})
    # Recorte al cupo pedido (12/08/2026, bug real: el modelo a veces
    # devuelve más tarjetas de las pedidas en "cupo" -- sin este recorte,
    # todas pasaban a verificación igualmente, gastando llamadas de más sin
    # ningún beneficio.
    return candidatas[:cupo]


def _verificar_tarjeta(tarjeta, fragmento, on_usage):
    system, user = _prompt_verificacion(tarjeta, fragmento)
    raw = call_deepseek_api(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        # Mismo margen que test_generator.py._verificar_pregunta (ver su
        # comentario): con 400 tokens, deepseek-v4-flash puede truncar la
        # respuesta si detalla varios problemas en "problemas", y un JSON
        # cortado se trata como tarjeta inválida aunque no lo fuera,
        # disparando una regeneración de más. No tiene coste extra si no
        # hace falta (se cobra por tokens generados, no por el tope). Subido
        # a 8000 (12/08/2026, igual que test_generator.py._verificar_pregunta):
        # con thinking_enabled=True el razonamiento interno cuenta contra
        # este mismo tope, así que 4000 dejaba menos margen real para el
        # JSON de salida en verificaciones con varios problemas detallados
        # que en test_generator.py, pese a ser una tarea equivalente.
        max_tokens=8000,
        response_format_json=True,
        on_usage=on_usage,
        # thinking_enabled=True (02/08/2026): call_deepseek_api desactiva el
        # razonamiento interno de deepseek-v4-flash por defecto (ver
        # deepseek_utils.py) porque en el Test Personalizado se vio que ese
        # razonamiento dominaba tiempo y tokens sin aportar nada en la
        # GENERACIÓN. Esta es una VERIFICACIÓN -- misma decisión que en
        # test_generator.py._verificar_pregunta: se mantiene el margen de
        # deliberación encendido a propósito para no perder precisión.
        thinking_enabled=True,
        # stream=True: ver el comentario en _generar_candidatas_fragmento --
        # mismo arreglo real de producción (este archivo se había quedado
        # sin streaming, y con thinking_enabled=True esta verificación
        # puede tardar bastante, condenándola a morir por conexión con
        # cierta frecuencia sin este fix).
        stream=True,
    )
    if not raw:
        return False
    try:
        return json.loads(raw).get("valido") is True
    except json.JSONDecodeError:
        return False


def _contiene_frase_prohibida(tarjeta):
    """Filtro determinista (no depende de que la IA de verificación lo
    detecte): igual que validador_preguntas.validar_pregunta hace para el
    Test Personalizado, comprueba localmente antes de gastar una llamada de
    verificación en una tarjeta que se va a descartar de todos modos."""
    texto = (tarjeta["pregunta"] + " " + tarjeta["respuesta"]).lower()
    # contiene_referencia_meta (03/08/2026): complementa FRASES_PROHIBIDAS
    # con patrones tipo "conforme al contenido"/"el documento establece que"
    # -- ver el comentario largo junto a PATRON_REFERENCIA_META en
    # validador_preguntas.py.
    return any(frase in texto for frase in FRASES_PROHIBIDAS) or contiene_referencia_meta(texto)


def _regenerar_una_tarjeta(fragmento, pregunta_descartada, on_usage):
    system, user = _prompt_generacion(fragmento, 1, evitar=pregunta_descartada)
    generado = call_deepseek_api(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.5,
        max_tokens=500,
        response_format_json=True,
        on_usage=on_usage,
        # stream=True: ver el comentario en _generar_candidatas_fragmento.
        stream=True,
    )
    for c in _parsear_tarjetas(generado):
        if isinstance(c, dict) and c.get("pregunta") and c.get("respuesta"):
            return {"pregunta": str(c["pregunta"]).strip(), "respuesta": str(c["respuesta"]).strip()}
    return None


def _asegurar_tarjeta_valida(candidata, fragmento, dedup_lock, claves_vistas, tarjetas_aceptadas, on_usage,
                              max_intentos=MAX_INTENTOS_POR_TARJETA):
    """tarjetas_aceptadas: lista compartida (protegida por dedup_lock) de
    las tarjetas ya aceptadas -- tanto de rondas anteriores del banco
    (sembrada por el llamante, ver tarjetas_previas en
    generar_tarjetas_verificadas) como las que otros hilos de ESTA misma
    llamada vayan aceptando mientras tanto. Se usa para
    _es_semanticamente_duplicada además del dedup por claves_vistas
    (_claves_dedup: texto exacto de pregunta/respuesta, o mismo artículo +
    misma cifra/principio jurídico citados, ver el comentario largo junto a
    _claves_dedup) -- unificar ambos en la misma lista compartida hace que
    una sola comprobación cubra a la vez duplicados dentro de la ronda,
    entre fragmentos en paralelo, y entre rondas del banco."""
    tarjeta = candidata
    intentos_restantes = max_intentos
    while intentos_restantes > 0:
        claves = _claves_dedup(tarjeta)
        with dedup_lock:
            es_duplicada = (not claves or (claves & claves_vistas)
                             or _es_semanticamente_duplicada(tarjeta, tarjetas_aceptadas))
        if (not es_duplicada and not _contiene_frase_prohibida(tarjeta)
                and _verificar_tarjeta(tarjeta, fragmento, on_usage)):
            with dedup_lock:
                if (claves & claves_vistas) or _es_semanticamente_duplicada(tarjeta, tarjetas_aceptadas):
                    es_duplicada = True  # otro hilo aceptó lo mismo (o algo semánticamente igual) mientras se verificaba esta
                else:
                    claves_vistas.update(claves)
                    tarjetas_aceptadas.append(tarjeta)
                    return tarjeta
        intentos_restantes -= 1
        if intentos_restantes <= 0:
            return None
        tarjeta = _regenerar_una_tarjeta(fragmento, tarjeta["pregunta"], on_usage)
        if not tarjeta:
            return None
    return None


def generar_tarjetas_verificadas(texto, num_tarjetas, on_usage=None, on_progreso=None,
                                  tarjetas_a_evitar=None, tarjetas_previas=None):
    """Genera hasta num_tarjetas tarjetas de memoria verificadas a partir de
    texto (ya extraído de un PDF). on_usage, si se pasa, recibe el usage de
    cada llamada a DeepSeek (ver AcumuladorTokens en coste_ia.py) -- esta
    función corre siempre dentro de ThreadPoolExecutor, sin flask.g
    disponible.

    on_progreso(evento), si se pasa, se llama con {"completadas": i,
    "total": n_candidatas} a medida que cada tarjeta candidata termina de
    verificarse (aceptada o descartada) -- pensado para retransmitir
    progreso real por SSE en vez de mensajes rotativos cosméticos (ver
    /generar-tarjetas-desde-pdf en blueprints/pdf_ia.py). Si la candidata
    fue ACEPTADA, el evento incluye además "tarjeta" con su contenido
    (mismo patrón que generador_preguntas_verificado.py/test_generator.py
    para Test Personalizado y Test desde PDF), para que el llamante pueda
    dejar empezar a repasar tarjetas ya listas sin esperar a que termine
    todo el documento.

    tarjetas_a_evitar/tarjetas_previas (03/08/2026, banco adaptativo, ver
    generar_banco_tarjetas_adaptativo; tarjetas_previas añadido 05/08/2026,
    ver _es_semanticamente_duplicada): permiten encadenar varias llamadas a
    esta función sobre el MISMO documento sin que cada una parta de cero --
    tarjetas_a_evitar se añade al prompt de generación (aviso "no repitas
    esto"), y tarjetas_previas siembra claves_vistas/tarjetas_aceptadas
    (_claves_dedup: texto exacto de pregunta/respuesta, o mismo artículo +
    misma cifra/principio jurídico citados; y contención/solapamiento de la
    respuesta) para que el dedup interno de ESTA llamada ya sepa qué se aceptó en
    rondas anteriores, no solo dentro de sí misma. A diferencia del antiguo
    claves_iniciales (solo el texto normalizado de la pregunta),
    tarjetas_previas son las tarjetas completas -- hace falta la respuesta
    para la comprobación semántica.

    Devuelve {"tarjetas": [...], "descartadas": int, "advertencia": str
    opcional si se generaron menos tarjetas de las pedidas}."""
    fragmentos = _trocear_en_parrafos(texto)
    cupos = _repartir_cupos(len(fragmentos), num_tarjetas)

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS_GENERACION, len(fragmentos))) as executor:
        futuros_generacion = [
            executor.submit(_generar_candidatas_fragmento, fragmento, cupo, on_usage, tarjetas_a_evitar)
            for cupo, fragmento in zip(cupos, fragmentos)
        ]
        candidatas_por_fragmento = [
            (fragmento, futuro.result())
            for fragmento, futuro in zip(fragmentos, futuros_generacion)
        ]

    pares_candidata_fragmento = [
        (candidata, fragmento)
        for fragmento, candidatas in candidatas_por_fragmento
        for candidata in candidatas
    ]
    if not pares_candidata_fragmento:
        return {
            "tarjetas": [], "descartadas": 0,
            "advertencia": "La IA no generó ninguna tarjeta a partir del documento.",
        }

    tarjetas_previas = list(tarjetas_previas or [])
    dedup_lock = threading.Lock()
    claves_vistas = {clave for t in tarjetas_previas for clave in _claves_dedup(t)}
    tarjetas_aceptadas = list(tarjetas_previas)
    tarjetas = []
    descartadas = 0
    total_candidatas = len(pares_candidata_fragmento)
    verificadas = 0

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS_VERIFICACION, len(pares_candidata_fragmento))) as executor:
        futuros = [
            executor.submit(_asegurar_tarjeta_valida, candidata, fragmento, dedup_lock, claves_vistas,
                             tarjetas_aceptadas, on_usage)
            for candidata, fragmento in pares_candidata_fragmento
        ]
        for futuro in as_completed(futuros):
            resultado = futuro.result()
            if resultado:
                tarjetas.append(resultado)
            else:
                descartadas += 1
            verificadas += 1
            if on_progreso:
                # "tarjeta" solo si resultado (aceptada) -- mismo patrón que
                # generador_preguntas_verificado.py/test_generator.py: el
                # llamante (ver /generar-tarjetas-desde-pdf en
                # blueprints/pdf_ia.py) usa esto para mandar un evento SSE
                # aparte por cada tarjeta aceptada, así el frontend puede
                # dejar ver/repasar las tarjetas ya listas sin esperar a que
                # termine todo el documento.
                evento = {"completadas": verificadas, "total": total_candidatas}
                if resultado:
                    evento["tarjeta"] = resultado
                on_progreso(evento)

    # Relleno: si tras la fase normal siguen faltando tarjetas -- ya sea
    # porque algún fragmento devolvió menos candidatas de las pedidas en su
    # generación inicial, o porque alguna se descartó tras agotar sus
    # MAX_INTENTOS_POR_TARJETA -- se da una oportunidad más por cada hueco,
    # ciclando entre los fragmentos disponibles (mismo patrón que el
    # "relleno" de generador_preguntas_verificado.py para Test
    # Personalizado). Nunca se relaja la verificación: cada intento pasa
    # por el mismo verificador independiente y el mismo dedup por
    # claves_vistas; si sigue sin conseguirse, se cuenta como descartada
    # igual que hoy.
    #
    # EN PARALELO (antes era un "for" secuencial, con el comentario "no
    # compensa un ThreadPoolExecutor para lo que normalmente son 1-4
    # tarjetas de hueco"): con un documento corto/difícil que necesite
    # muchos huecos, cada uno con hasta MAX_INTENTOS_POR_TARJETA rondas de
    # generación+verificación, rellenarlos uno detrás de otro puede sumar
    # varios minutos solo en esta fase -- el mismo problema real que ya se
    # detectó y arregló para Generar Test desde PDF (ver
    # test_generator.py). Al ser huecos independientes entre sí,
    # paralelizarlos no cambia la verificación ni el resultado final, solo
    # el tiempo. "verificadas"/"tarjetas"/"descartadas" se protegen con un
    # lock (antes eran seguros por ser secuencial); dedup_lock ya protegía
    # claves_vistas incluso en la fase anterior, así que _asegurar_tarjeta_valida
    # sigue siendo segura sin cambios.
    if len(tarjetas) < num_tarjetas and fragmentos:
        faltan = num_tarjetas - len(tarjetas)
        ciclo_fragmentos = itertools.cycle(fragmentos)
        # A cada hueco se le asignan varios fragmentos candidatos (no solo
        # uno) -- bug real reportado en un documento extenso: pedir 10
        # tarjetas y recibir solo 7, porque un hueco que caía en un
        # fragmento ya "exprimido" (sus datos distintos ya se habían
        # convertido en tarjetas antes) agotaba sus MAX_INTENTOS_POR_TARJETA
        # intentos siempre sobre ESE MISMO fragmento y se daba por perdido,
        # aunque el documento tuviera de sobra contenido sin usar en OTROS
        # fragmentos. Ahora, si el primer fragmento no da una tarjeta
        # válida, se prueba con el siguiente de la lista antes de rendirse.
        _FRAGMENTOS_POR_HUECO = min(3, len(fragmentos))
        listas_fragmentos_huecos = [
            [next(ciclo_fragmentos) for _ in range(_FRAGMENTOS_POR_HUECO)]
            for _ in range(faltan)
        ]
        lock_relleno = threading.Lock()

        def _rellenar_un_hueco(fragmentos_candidatos):
            nonlocal verificadas, descartadas
            resultado = None
            for fragmento in fragmentos_candidatos:
                candidatas = _generar_candidatas_fragmento(fragmento, 1, on_usage)
                resultado = (
                    _asegurar_tarjeta_valida(candidatas[0], fragmento, dedup_lock, claves_vistas,
                                              tarjetas_aceptadas, on_usage)
                    if candidatas else None
                )
                if resultado:
                    break
            with lock_relleno:
                verificadas += 1
                if resultado:
                    tarjetas.append(resultado)
                else:
                    descartadas += 1
                valor = verificadas
            if on_progreso:
                evento = {"completadas": valor, "total": total_candidatas}
                if resultado:
                    evento["tarjeta"] = resultado
                on_progreso(evento)

        with ThreadPoolExecutor(max_workers=min(10, faltan)) as executor:
            list(executor.map(_rellenar_un_hueco, listas_fragmentos_huecos))

    resultado_final = {"tarjetas": tarjetas, "descartadas": descartadas}
    if len(tarjetas) < num_tarjetas:
        resultado_final["advertencia"] = (
            f"Se generaron {len(tarjetas)} de {num_tarjetas} tarjetas -- el resto no llegó a superar la "
            "verificación de contenido tras varios intentos y se descartó en vez de entregarse sin validar."
        )
    return resultado_final


# Tope del "banco" de tarjetas de un documento (03/08/2026, decisión
# explícita del usuario): en vez de pedir un número fijo de una vez (100
# preguntas fijas, sin importar de qué dé el documento), se genera en
# RONDAS sucesivas hasta agotar el contenido distinto del documento -- 100
# es solo el TECHO de seguridad, nunca el objetivo a forzar. Ver el
# comentario largo de generar_banco_tarjetas_adaptativo.
TOPE_BANCO_TARJETAS = 100
# 40 (03/08/2026, subido de 20 -- optimización de tiempo, mismo motivo que
# test_generator.py._TAMANO_RONDA_BANCO): la generación aquí reparte cupo
# entre TODOS los fragmentos del documento en cada ronda (ver
# _repartir_cupos), así que el NÚMERO de llamadas de generación de una
# ronda depende del número de fragmentos, no del tamaño de la ronda -- una
# ronda más grande no pide más llamadas, solo un cupo mayor por fragmento
# en las mismas llamadas. Menos rondas para llegar al mismo tope (100/40 ~
# 3 en vez de 100/20 = 5) significa muchas menos llamadas de generación
# TOTALES sin subir la concurrencia pico (_MAX_WORKERS_GENERACION/
# _MAX_WORKERS_VERIFICACION no cambian).
_TAMANO_RONDA_BANCO = 40
# Si una ronda rinde menos de este porcentaje de lo pedido en tarjetas
# NUEVAS (no duplicadas de rondas anteriores), se considera que el
# documento ya no da más contenido distinto y se para -- seguir insistiendo
# solo generaría relleno de peor calidad para forzar una cuota arbitraria.
_UMBRAL_RENDIMIENTO_MINIMO_BANCO = 0.25


def generar_banco_tarjetas_adaptativo(texto, tope=TOPE_BANCO_TARJETAS, tamano_ronda=_TAMANO_RONDA_BANCO,
                                       on_usage=None, on_progreso=None, evento_parada=None):
    """Genera el máximo de tarjetas distintas que el documento realmente dé
    de sí, en rondas sucesivas de generar_tarjetas_verificadas, hasta:
    (a) llegar a 'tope' (techo de seguridad, nunca objetivo forzado),
    (b) que una ronda entera rinda por debajo de
        _UMBRAL_RENDIMIENTO_MINIMO_BANCO en tarjetas NUEVAS (señal de que
        el documento ya no tiene más contenido distinto que dar), o
    (c) agotar un número máximo de rondas (cinturón de seguridad para no
        disparar el gasto en un documento raro que rinda poco ronda tras
        ronda sin llegar nunca a 0).

    Cada ronda usa tarjetas_a_evitar/tarjetas_previas (ver
    generar_tarjetas_verificadas) para que no repita lo ya aceptado en
    rondas anteriores -- sin esto, cada ronda fragmentaría el MISMO
    documento de la MISMA forma y regeneraría tarjetas muy parecidas a las
    ya aceptadas, con un rendimiento decreciente artificial que pararía la
    generación demasiado pronto. Pasar las tarjetas completas (no solo sus
    claves) es lo que permite que generar_tarjetas_verificadas aplique
    _es_semanticamente_duplicada también CONTRA rondas anteriores, no solo
    dentro de la ronda actual (05/08/2026, ver el comentario largo de esa
    función) -- de rebote, esto hace que el freno de
    _UMBRAL_RENDIMIENTO_MINIMO_BANCO de abajo sea fiable: antes, una ronda
    podía contarse como "buen rendimiento" aunque sus tarjetas "nuevas"
    fueran en realidad reformulaciones de hechos ya cubiertos (el dedup
    entre rondas de aquí abajo solo comparaba texto EXACTO de la pregunta),
    así que el banco seguía generando rondas hasta el tope aunque el
    documento ya no diera contenido distinto.

    on_progreso(evento), si se pasa, se llama con {"completadas": N,
    "objetivo": tope, "tarjeta": t} por cada tarjeta NUEVA aceptada
    (después del dedup entre rondas) -- no se reenvían los eventos brutos
    de cada ronda individual, que incluirían candidatas luego descartadas
    por duplicar una ronda anterior.

    evento_parada (10/08/2026, threading.Event opcional, ver
    generacion_control.py): si se pasa y está marcado, no se lanza ninguna
    ronda nueva -- se devuelve lo acumulado hasta ese momento. No cancela
    la ronda YA en marcha (no es seguro interrumpir una petición HTTP a
    mitad), solo evita empezar otra.

    Devuelve la lista de tarjetas aceptadas (sin envoltorio, a diferencia
    de generar_tarjetas_verificadas: aquí no hay un "num_tarjetas pedido"
    único al que comparar para una advertencia de faltantes)."""
    acumuladas = []
    claves_acumuladas = set()
    evitar_acumulado = []
    max_rondas = max(3, (tope // tamano_ronda) + 2)
    ronda = 0
    while len(acumuladas) < tope and ronda < max_rondas and not (evento_parada and evento_parada.is_set()):
        objetivo_ronda = min(tamano_ronda, tope - len(acumuladas))
        resultado_ronda = generar_tarjetas_verificadas(
            texto, objetivo_ronda, on_usage=on_usage,
            tarjetas_a_evitar=evitar_acumulado, tarjetas_previas=acumuladas,
        )
        ronda += 1
        nuevas = []
        for tarjeta in resultado_ronda.get("tarjetas", []):
            # Un lote/fragmento puede ignorar el "EXACTAMENTE N" pedido y
            # devolver de más (mismo bug ya visto y arreglado en
            # generar_preguntas_ia_en_lotes) -- aquí se corta al llegar al
            # tope para no aceptar más de la cuenta.
            if len(acumuladas) >= tope:
                break
            claves = _claves_dedup(tarjeta)
            # Red de seguridad adicional (debería ser redundante: generar_
            # tarjetas_verificadas ya deduplicó esta tarjeta contra
            # tarjetas_previas=acumuladas antes de aceptarla) -- se
            # mantiene por si acaso, es una comprobación gratis.
            if not claves or (claves & claves_acumuladas) or _es_semanticamente_duplicada(tarjeta, acumuladas):
                continue
            claves_acumuladas.update(claves)
            acumuladas.append(tarjeta)
            nuevas.append(tarjeta)
            if on_progreso:
                on_progreso({"completadas": len(acumuladas), "objetivo": tope, "tarjeta": tarjeta})
        evitar_acumulado.extend(t.get("pregunta", "") for t in nuevas)
        if not nuevas or len(nuevas) / objetivo_ronda < _UMBRAL_RENDIMIENTO_MINIMO_BANCO:
            break
    return acumuladas
