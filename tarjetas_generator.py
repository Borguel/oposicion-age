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

logger = logging.getLogger(__name__)

MAX_INTENTOS_POR_TARJETA = 3
_MAX_WORKERS_GENERACION = 4
_MAX_WORKERS_VERIFICACION = 6


def _normalizar(texto):
    return re.sub(r"\s+", " ", str(texto or "").strip().lower())


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


def _generar_candidatas_fragmento(fragmento, cupo, on_usage):
    if cupo <= 0:
        return []
    system, user = _prompt_generacion(fragmento, cupo)
    generado = call_deepseek_api(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.3,
        max_tokens=min(8000, 200 + cupo * 220),
        response_format_json=True,
        on_usage=on_usage,
    )
    candidatas = []
    for c in _parsear_tarjetas(generado):
        if isinstance(c, dict) and c.get("pregunta") and c.get("respuesta"):
            candidatas.append({"pregunta": str(c["pregunta"]).strip(), "respuesta": str(c["respuesta"]).strip()})
    return candidatas


def _verificar_tarjeta(tarjeta, fragmento, on_usage):
    system, user = _prompt_verificacion(tarjeta, fragmento)
    raw = call_deepseek_api(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        max_tokens=400,
        response_format_json=True,
        on_usage=on_usage,
    )
    if not raw:
        return False
    try:
        return json.loads(raw).get("valido") is True
    except json.JSONDecodeError:
        return False


def _regenerar_una_tarjeta(fragmento, pregunta_descartada, on_usage):
    system, user = _prompt_generacion(fragmento, 1, evitar=pregunta_descartada)
    generado = call_deepseek_api(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.5,
        max_tokens=500,
        response_format_json=True,
        on_usage=on_usage,
    )
    for c in _parsear_tarjetas(generado):
        if isinstance(c, dict) and c.get("pregunta") and c.get("respuesta"):
            return {"pregunta": str(c["pregunta"]).strip(), "respuesta": str(c["respuesta"]).strip()}
    return None


def _asegurar_tarjeta_valida(candidata, fragmento, dedup_lock, claves_vistas, on_usage,
                              max_intentos=MAX_INTENTOS_POR_TARJETA):
    tarjeta = candidata
    intentos_restantes = max_intentos
    while intentos_restantes > 0:
        clave = _normalizar(tarjeta["pregunta"])
        with dedup_lock:
            es_duplicada = clave in claves_vistas
        if not es_duplicada and _verificar_tarjeta(tarjeta, fragmento, on_usage):
            with dedup_lock:
                if clave in claves_vistas:
                    es_duplicada = True  # otro hilo aceptó lo mismo mientras se verificaba esta
                else:
                    claves_vistas.add(clave)
                    return tarjeta
        intentos_restantes -= 1
        if intentos_restantes <= 0:
            return None
        tarjeta = _regenerar_una_tarjeta(fragmento, tarjeta["pregunta"], on_usage)
        if not tarjeta:
            return None
    return None


def generar_tarjetas_verificadas(texto, num_tarjetas, on_usage=None, on_progreso=None):
    """Genera hasta num_tarjetas tarjetas de memoria verificadas a partir de
    texto (ya extraído de un PDF). on_usage, si se pasa, recibe el usage de
    cada llamada a DeepSeek (ver AcumuladorTokens en coste_ia.py) -- esta
    función corre siempre dentro de ThreadPoolExecutor, sin flask.g
    disponible.

    on_progreso(evento), si se pasa, se llama con {"completadas": i,
    "total": n_candidatas} a medida que cada tarjeta candidata termina de
    verificarse (aceptada o descartada) -- pensado para retransmitir
    progreso real por SSE en vez de mensajes rotativos cosméticos (ver
    /generar-tarjetas-desde-pdf en blueprints/pdf_ia.py).

    Devuelve {"tarjetas": [...], "descartadas": int, "advertencia": str
    opcional si se generaron menos tarjetas de las pedidas}."""
    fragmentos = _trocear_en_parrafos(texto)
    cupos = _repartir_cupos(len(fragmentos), num_tarjetas)

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS_GENERACION, len(fragmentos))) as executor:
        futuros_generacion = [
            executor.submit(_generar_candidatas_fragmento, fragmento, cupo, on_usage)
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

    dedup_lock = threading.Lock()
    claves_vistas = set()
    tarjetas = []
    descartadas = 0
    total_candidatas = len(pares_candidata_fragmento)
    verificadas = 0

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS_VERIFICACION, len(pares_candidata_fragmento))) as executor:
        futuros = [
            executor.submit(_asegurar_tarjeta_valida, candidata, fragmento, dedup_lock, claves_vistas, on_usage)
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
                on_progreso({"completadas": verificadas, "total": total_candidatas})

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
        fragmentos_huecos = [next(ciclo_fragmentos) for _ in range(faltan)]
        lock_relleno = threading.Lock()

        def _rellenar_un_hueco(fragmento):
            nonlocal verificadas, descartadas
            candidatas = _generar_candidatas_fragmento(fragmento, 1, on_usage)
            resultado = (
                _asegurar_tarjeta_valida(candidatas[0], fragmento, dedup_lock, claves_vistas, on_usage)
                if candidatas else None
            )
            with lock_relleno:
                verificadas += 1
                if resultado:
                    tarjetas.append(resultado)
                else:
                    descartadas += 1
                valor = verificadas
            if on_progreso:
                on_progreso({"completadas": valor, "total": total_candidatas})

        with ThreadPoolExecutor(max_workers=min(10, faltan)) as executor:
            list(executor.map(_rellenar_un_hueco, fragmentos_huecos))

    resultado_final = {"tarjetas": tarjetas, "descartadas": descartadas}
    if len(tarjetas) < num_tarjetas:
        resultado_final["advertencia"] = (
            f"Se generaron {len(tarjetas)} de {num_tarjetas} tarjetas -- el resto no llegó a superar la "
            "verificación de contenido tras varios intentos y se descartó en vez de entregarse sin validar."
        )
    return resultado_final
