import re
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from deepseek_utils import call_deepseek_api

MAX_INTENTOS_POR_PREGUNTA_PDF = 3
_MAX_WORKERS_VERIFICACION_LOTE = 6


def _prompt_verificacion(pregunta_candidata, texto_fuente):
    system = (
        "Eres un verificador independiente. Te llega una pregunta tipo test YA REDACTADA por otro "
        "proceso, y el ÚNICO documento del que debería haber salido. No des por hecho que es correcta "
        "solo porque parece bien escrita: comprueba cada afirmación contra el documento, como si lo "
        "vieras por primera vez y no supieras nada más.\n\n"
        "Marca la pregunta como inválida si detectas CUALQUIERA de estos problemas:\n"
        "1. El contenido de la pregunta no coincide con lo que dice el documento.\n"
        "2. La respuesta marcada como correcta no es completamente correcta según el documento.\n"
        "3. Alguna de las otras tres opciones podría considerarse también correcta o parcialmente "
        "correcta -- ninguna debe ser defendible.\n"
        "4. La explicación no repasa las 4 opciones en el formato \"A) ... B) ... C) ... D) ...\", o no "
        "coincide exactamente con la respuesta marcada como correcta.\n"
        "5. Cualquier plazo, cifra, porcentaje, artículo, órgano competente o fecha no coincide "
        "EXACTAMENTE con el documento.\n"
        "6. Hay cualquier dato o afirmación que no puedas verificar literalmente en el documento "
        "proporcionado (posible alucinación).\n\n"
        "Devuelve ÚNICAMENTE un JSON con esta forma exacta, sin texto adicional:\n"
        '{"valido": true, "problemas": []}\n'
        "Si encuentras algún problema, \"valido\" debe ser false y \"problemas\" debe listar cada motivo."
    )
    user = f"DOCUMENTO:\n{texto_fuente}\n\nPREGUNTA A VERIFICAR:\n{json.dumps(pregunta_candidata, ensure_ascii=False)}"
    return system, user


def _verificar_pregunta(pregunta, texto_fuente, on_usage):
    system, user = _prompt_verificacion(pregunta, texto_fuente)
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


def _prompt_con_exclusion(prompt, preguntas_a_evitar):
    """Añade al prompt de generación la lista de preguntas que NO debe
    repetir (ya generadas antes, descartadas por verificación, o ya
    aceptadas en este mismo lote), avisando de que reformular el mismo dato
    con otras palabras también cuenta como repetir -- así se ataca
    directamente el caso real observado: un documento corto con pocos datos
    verificables acaba generando varias preguntas sobre el MISMO hecho
    (p. ej. la misma duración de mandato) con enunciados distintos, que la
    comprobación por texto exacto no detecta."""
    preguntas_a_evitar = [p for p in (preguntas_a_evitar or []) if p]
    if not preguntas_a_evitar:
        return prompt
    listado = "\n".join(f"- {p}" for p in preguntas_a_evitar[:40])
    return prompt + (
        f"\n\nEstas preguntas ya existen (generadas antes a partir de este mismo documento, o ya "
        f"aceptadas en esta misma tanda) -- NO generes ninguna que repita su mismo dato o hecho "
        f"concreto, aunque la redactes con otras palabras distintas:\n{listado}\n"
        f"Aborda aspectos del documento no cubiertos por esas preguntas."
    )


def _pedir_una_pregunta_de_recambio(construir_prompt, preguntas_a_evitar, on_usage):
    """Pide UNA pregunta de recambio para sustituir a una que no superó la
    verificación (o que resultó ser un duplicado semántico de otra ya
    aceptada), evitando repetir el tema de todas las indicadas -- nunca se
    "corrige" la pregunta descartada, se pide una completamente nueva."""
    prompt = _prompt_con_exclusion(construir_prompt(1), preguntas_a_evitar)
    generado = call_deepseek_api(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
        max_tokens=600,
        on_usage=on_usage,
    )
    if not generado:
        return None
    inicio = generado.find("[")
    fin = generado.rfind("]") + 1
    if inicio == -1 or fin <= inicio:
        return None
    try:
        candidatas = json.loads(generado[inicio:fin])
    except json.JSONDecodeError:
        return None
    return candidatas[0] if candidatas else None


def _asegurar_pregunta_valida(pregunta_candidata, construir_prompt, texto_fuente, on_usage,
                               preguntas_a_evitar=None, max_intentos=MAX_INTENTOS_POR_PREGUNTA_PDF):
    """Verifica una pregunta candidata contra el documento de origen y, si
    no supera la verificación, la descarta POR COMPLETO y pide una de
    recambio evitando su tema (y los de 'preguntas_a_evitar', si se pasan),
    hasta max_intentos veces -- mismo principio que
    generador_preguntas_verificado.py aplica al temario oficial."""
    pregunta = pregunta_candidata
    evitar = list(preguntas_a_evitar or [])
    intentos_restantes = max_intentos
    while intentos_restantes > 0:
        if _verificar_pregunta(pregunta, texto_fuente, on_usage):
            return pregunta
        intentos_restantes -= 1
        if intentos_restantes <= 0:
            return None
        evitar.append(pregunta.get("pregunta", ""))
        pregunta = _pedir_una_pregunta_de_recambio(construir_prompt, evitar, on_usage)
        if not pregunta:
            return None
    return None


def _prompt_deteccion_duplicados(preguntas):
    listado = "\n".join(
        f"{i}. Pregunta: {p.get('pregunta', '')} | Respuesta correcta: "
        f"{(p.get('opciones') or {}).get(p.get('respuesta_correcta', ''), '')}"
        for i, p in enumerate(preguntas)
    )
    system = (
        "Eres un revisor de calidad de tests para oposiciones. Te llega una lista numerada de "
        "preguntas ya generadas y verificadas a partir de un mismo documento. El documento puede "
        "ser corto o tener pocos datos concretos, y a veces varias preguntas acaban preguntando "
        "por el MISMO hecho o dato exacto (la misma ley, el mismo plazo, la misma cifra, el mismo "
        "cargo...) aunque estén redactadas con palabras distintas -- eso cuenta como duplicado y "
        "hay que detectarlo, aunque el enunciado no sea idéntico.\n\n"
        "Para cada grupo de preguntas que traten el mismo hecho concreto, conserva SOLO la de "
        "menor número y marca como duplicadas todas las demás del mismo grupo.\n\n"
        "Devuelve ÚNICAMENTE un JSON con esta forma exacta, sin texto adicional:\n"
        '{"duplicados": [<números de las preguntas duplicadas a eliminar>]}\n'
        "Si ninguna pregunta se repite, devuelve {\"duplicados\": []}."
    )
    user = f"PREGUNTAS:\n{listado}"
    return system, user


def _detectar_indices_duplicados(preguntas, on_usage):
    """Detecta, dentro de una lista de preguntas ya verificadas
    individualmente contra el documento, cuáles preguntan por el mismo dato
    concreto que otra anterior de la lista -- la deduplicación por texto
    exacto de generar_preguntas_ia_en_lotes no detecta esto porque cada
    pregunta puede estar redactada de forma distinta aunque verse sobre el
    mismo hecho (caso real: un documento corto generando 4 variantes de la
    pregunta sobre la misma duración de mandato)."""
    if len(preguntas) < 2:
        return set()
    system, user = _prompt_deteccion_duplicados(preguntas)
    raw = call_deepseek_api(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        max_tokens=300,
        response_format_json=True,
        on_usage=on_usage,
    )
    if not raw:
        return set()
    try:
        indices = json.loads(raw).get("duplicados") or []
    except (json.JSONDecodeError, AttributeError, TypeError):
        return set()
    return {i for i in indices if isinstance(i, int) and 0 <= i < len(preguntas)}


def _pedir_y_verificar_recambio(construir_prompt, texto_fuente, preguntas_a_evitar, on_usage):
    candidata = _pedir_una_pregunta_de_recambio(construir_prompt, preguntas_a_evitar, on_usage)
    if not candidata:
        return None
    return _asegurar_pregunta_valida(candidata, construir_prompt, texto_fuente, on_usage, preguntas_a_evitar)


def _reemplazar_duplicadas(preguntas, indices_duplicados, construir_prompt, texto_fuente,
                            preguntas_a_evitar, on_usage):
    """Quita las preguntas marcadas como duplicado semántico y pide, EN
    PARALELO, una de recambio por cada una eliminada -- mismo mecanismo de
    recambio que ya usa _asegurar_pregunta_valida para las que no superan la
    verificación, aquí reutilizado para las que sí la superan pero repiten
    el dato de otra. Si no se consigue recambio para alguna, simplemente se
    queda con menos preguntas (igual que ya ocurre hoy cuando un lote no
    llega al número pedido)."""
    conservadas = [p for i, p in enumerate(preguntas) if i not in indices_duplicados]
    evitar = list(preguntas_a_evitar or []) + [p.get("pregunta", "") for p in conservadas]
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS_VERIFICACION_LOTE, len(indices_duplicados))) as executor:
        futuros = [
            executor.submit(_pedir_y_verificar_recambio, construir_prompt, texto_fuente, evitar, on_usage)
            for _ in indices_duplicados
        ]
        for futuro in as_completed(futuros):
            candidata = futuro.result()
            if candidata:
                conservadas.append(candidata)
    return conservadas


def generar_preguntas_ia_en_lotes(construir_prompt, num_preguntas, texto_fuente=None, tamano_lote=15,
                                   temperature=0.4, on_progreso=None, on_usage=None,
                                   preguntas_a_evitar=None):
    """Genera 'num_preguntas' preguntas pidiéndolas a DeepSeek en varios lotes
    en paralelo (ThreadPoolExecutor). Si se pasa texto_fuente, cada
    candidata se verifica además con una segunda llamada independiente
    antes de aceptarla (mismo principio que generador_preguntas_verificado.py
    usa para el temario oficial, aquí adaptado a un documento libre subido
    por el usuario en vez de un artículo anclado en Firestore).

    texto_fuente es el documento completo (ya truncado por el llamante)
    contra el que se verifica cada pregunta candidata -- distinto de
    construir_prompt(n), que además incluye las instrucciones de
    generación. Si no se pasa (None), NO se verifica ninguna pregunta y se
    conserva el comportamiento en el que ninguna pregunta se basa en un
    documento concreto contra el que verificar (por ejemplo, si algún día
    se añade un generador basado solo en el conocimiento general del
    modelo, sin PDF ni temario anclado).

    on_progreso(evento), si se pasa, se llama cada vez que UNA PREGUNTA
    individual termina de verificarse (con éxito o descarte definitivo,
    tras agotar sus reintentos de recambio si hiciera falta), con
    {"completadas": i, "total": num_preguntas} -- mismo grano que
    generador_preguntas_verificado.py usa para el temario oficial (por
    pregunta, no por lote), para que el progreso retransmitido por SSE se
    sienta igual de vivo en /generar-test-desde-pdf (blueprints/pdf_ia.py)
    que en el test personalizado, en vez de dar un único salto al final
    cuando el lote entero (hasta 15 preguntas) termina de golpe. Con lotes
    que devuelven menos candidatas de las pedidas (fallo parcial de
    DeepSeek), "completadas" puede quedarse por debajo de "total" al
    acabar -- el llamante ya remata la barra al 100% con el evento "fin".

    on_usage, si se pasa, recibe el usage de cada llamada a DeepSeek (de
    generación Y de verificación) -- esta función corre siempre dentro de
    un ThreadPoolExecutor (y normalmente además dentro de un
    threading.Thread de fondo para el streaming SSE), donde flask.g no
    está disponible, así que sin on_usage el coste de estas llamadas se
    pierde en silencio (ver AcumuladorTokens en coste_ia.py).

    /generar-test-desde-pdf antes pedía todo el test de golpe con
    max_tokens=min(4000, 300*num_preguntas): a partir de ~13-14 preguntas ese
    tope de 4000 tokens ya se queda corto para el JSON completo
    (pregunta+opciones+explicación ronda 400-600 tokens cada una), y la
    respuesta se corta a medio JSON. Pedir lotes de como mucho 'tamano_lote'
    preguntas mantiene cada llamada individual muy por debajo del límite,
    sea cual sea el total pedido.

    construir_prompt(n) debe devolver el prompt completo pidiendo EXACTAMENTE
    n preguntas, en el mismo formato de array JSON que ya usa esa ruta.

    preguntas_a_evitar (opcional): textos de preguntas ya generadas en
    ocasiones ANTERIORES para este mismo documento (p. ej. al pulsar
    "generar más" desde la biblioteca de "Mis documentos") -- se incluyen
    como exclusión en cada lote para que la IA no vuelva a preguntar por los
    mismos datos ya cubiertos, además de usarse como base para la
    deduplicación semántica de más abajo.

    Devuelve (preguntas, errores): preguntas ya verificadas y deduplicadas,
    tanto por texto de pregunta normalizado (pedir el mismo tema en varios
    lotes en paralelo puede repetir alguna con el mismo enunciado) como por
    significado (si texto_fuente no es None: varias preguntas pueden acabar
    versando sobre el mismo dato concreto del documento aunque estén
    redactadas de forma distinta -- típico en documentos cortos con pocos
    datos verificables, ver _detectar_indices_duplicados). errores es una
    lista de motivos de fallo por lote (vacía si todo fue bien) para poder
    avisar si faltan preguntas respecto a las pedidas.
    """
    lotes = []
    restante = num_preguntas
    while restante > 0:
        n = min(tamano_lote, restante)
        lotes.append(n)
        restante -= n

    # Contador compartido entre TODOS los hilos (los de cada lote y, dentro
    # de cada uno, los de verificación de cada candidata): un lock evita que
    # dos hilos incrementen a la vez y pisen el número que se manda por SSE.
    completadas_preguntas = 0
    lock_progreso = threading.Lock()

    def _reportar_avance_pregunta():
        nonlocal completadas_preguntas
        if not on_progreso:
            return
        with lock_progreso:
            completadas_preguntas += 1
            valor = completadas_preguntas
        on_progreso({"completadas": valor, "total": num_preguntas})

    def _pedir_lote_verificado(n):
        prompt = _prompt_con_exclusion(construir_prompt(n), preguntas_a_evitar)
        generado = call_deepseek_api(
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=min(4000, 300 * n),
            on_usage=on_usage
        )
        if not generado:
            return [], f"Sin respuesta de DeepSeek para un lote de {n} preguntas"
        inicio = generado.find("[")
        fin = generado.rfind("]") + 1
        if inicio == -1 or fin <= inicio:
            return [], "No se encontró un array JSON en la respuesta de un lote"
        try:
            candidatas = json.loads(generado[inicio:fin])
        except json.JSONDecodeError as je:
            return [], f"JSON inválido en un lote: {je}"
        if not candidatas:
            return [], None
        if texto_fuente is None:
            # Sin documento contra el que verificar: se acepta la candidata
            # tal cual, igual que antes de añadir la verificación.
            for _ in candidatas:
                _reportar_avance_pregunta()
            return candidatas, None

        # Se verifica cada candidata del lote EN PARALELO -- en serie
        # multiplicaría por hasta 'tamano_lote' el tiempo de este lote, y
        # una pregunta con problemas no debe frenar a las demás. Se reporta
        # el avance por 'as_completed' (una por una, según van resolviéndose,
        # con éxito o descarte) en vez de esperar a que TODAS terminen --
        # así el progreso real llega pregunta a pregunta, no lote a lote.
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS_VERIFICACION_LOTE, len(candidatas))) as executor:
            futuros = [
                executor.submit(_asegurar_pregunta_valida, candidata, construir_prompt, texto_fuente, on_usage)
                for candidata in candidatas
            ]
            verificadas = []
            for futuro in as_completed(futuros):
                verificadas.append(futuro.result())
                _reportar_avance_pregunta()
        aceptadas = [p for p in verificadas if p]
        if not aceptadas:
            # Generación OK (hubo candidatas), pero NINGUNA superó la
            # verificación de precisión -- normalmente indica que el
            # documento no tiene suficiente contenido distinto para tantas
            # preguntas, no un fallo técnico de DeepSeek. Se distingue este
            # motivo (con un prefijo reconocible) de los "return" de arriba
            # (sin respuesta / JSON inválido en la generación), para poder
            # dar un mensaje honesto en vez de "error técnico" cuando
            # ninguna pregunta llega a generarse en ningún lote (ver
            # blueprints/pdf_ia.py).
            return [], f"Ninguna de las {len(candidatas)} preguntas candidatas de un lote superó la verificación de calidad"
        return aceptadas, None

    preguntas = []
    errores = []
    with ThreadPoolExecutor(max_workers=min(5, len(lotes))) as executor:
        futuros = [executor.submit(_pedir_lote_verificado, n) for n in lotes]
        for futuro in as_completed(futuros):
            lote_preguntas, error = futuro.result()
            if error:
                errores.append(error)
            else:
                preguntas.extend(lote_preguntas)

    vistas = set()
    preguntas_unicas = []
    for p in preguntas:
        clave = re.sub(r"\s+", " ", str(p.get("pregunta", "")).strip().lower())
        if clave and clave not in vistas:
            vistas.add(clave)
            preguntas_unicas.append(p)

    if texto_fuente is not None and len(preguntas_unicas) > 1:
        indices_duplicados = _detectar_indices_duplicados(preguntas_unicas, on_usage)
        if indices_duplicados:
            preguntas_unicas = _reemplazar_duplicadas(
                preguntas_unicas, indices_duplicados, construir_prompt, texto_fuente,
                preguntas_a_evitar, on_usage,
            )

    return preguntas_unicas, errores
