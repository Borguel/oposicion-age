import re
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from deepseek_utils import call_deepseek_api

MAX_INTENTOS_POR_PREGUNTA_PDF = 3
_MAX_WORKERS_VERIFICACION_LOTE = 6

# Umbral de longitud para usar el texto de la respuesta correcta como
# clave adicional de deduplicación (ver _claves_dedup): por debajo de
# este tamaño no se usa, para no dar falsos positivos con cifras o
# respuestas muy cortas (p.ej. "3%", "20 días") que varias preguntas
# LEGÍTIMAMENTE distintas pueden compartir por casualidad -- ni con las
# opciones de relleno tipo "1"/"2"/"3"/"4" que usan los tests. Las
# respuestas que SÍ se repiten en la práctica cuando el documento tiene
# un dato muy citable ("6 años, no renovable.", "A mediados de octubre
# de cada año.") están muy por encima de este umbral.
_LONGITUD_MINIMA_DEDUP_RESPUESTA = 10


def _normalizar(texto):
    return re.sub(r"\s+", " ", str(texto or "").strip().lower())


def _claves_dedup(pregunta):
    """Claves de deduplicación de una pregunta ya aceptada: siempre el
    texto de la pregunta normalizado, y ADEMÁS el texto de la respuesta
    correcta normalizado si es lo bastante largo (ver
    _LONGITUD_MINIMA_DEDUP_RESPUESTA). Dos preguntas con el ENUNCIADO
    reformulado de forma completamente distinta pero que citan el mismo
    dato con la misma respuesta correcta se detectan así como duplicadas
    aunque el texto de la pregunta no coincida en nada -- bug real: la
    misma pregunta sobre la duración de un mandato, repetida 4 veces con
    4 redacciones distintas, escapaba al dedup anterior (que solo
    comparaba el texto de la pregunta)."""
    claves = set()
    clave_pregunta = _normalizar(pregunta.get("pregunta", ""))
    if clave_pregunta:
        claves.add(f"p:{clave_pregunta}")
    opciones = pregunta.get("opciones") or {}
    letra_respuesta = str(pregunta.get("respuesta_correcta", "")).upper()
    clave_respuesta = _normalizar(opciones.get(letra_respuesta, ""))
    if len(clave_respuesta) >= _LONGITUD_MINIMA_DEDUP_RESPUESTA:
        claves.add(f"r:{clave_respuesta}")
    return claves


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
        "proporcionado (posible alucinación).\n"
        "7. La pregunta o la explicación citan un número de artículo sin decir en la misma frase de qué "
        "ley o norma es (tal como aparece en el documento) -- un artículo mencionado sin decir de qué "
        "norma es deja a quien lo lee sin poder ubicarlo.\n"
        "8. La pregunta o la explicación remiten a \"el documento\", \"el contenido\", \"el texto\" o "
        "\"lo mencionado/anterior\" en vez de nombrar directamente de qué elementos concretos habla -- "
        "quien responde el test nunca ve el documento de origen, solo la pregunta, así que una remisión "
        "de ese tipo la deja sin sentido.\n"
        "9. Se usa una sigla o abreviatura (\"CE\", \"TREBEP\", \"LPAC\", \"art.\" en vez de "
        "\"artículo\"...) para nombrar una ley o norma en vez de su nombre completo tal como aparece en "
        "el documento -- los exámenes oficiales de esta oposición nunca abrevian. Esto incluye también "
        "abreviar el tipo de norma delante de su número (\"LO 3/2007\", \"RD 203/2021\"...) en vez de "
        "escribirlo entero (\"Ley Orgánica 3/2007\", \"Real Decreto 203/2021\").\n\n"
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


def _fragmentos_por_lote(texto_fuente, n_lotes):
    """Devuelve una lista de n_lotes fragmentos del documento, uno por lote,
    para que cada llamada de generación en paralelo se apoye en una parte
    DISTINTA del documento en vez de que todos los lotes reciban el mismo
    texto completo. Sin esto, varios lotes independientes (no se ven entre
    sí, corren en paralelo) tienden a convertir el mismo hecho más citable
    del documento en varias preguntas con enunciados distintos -- el dedup
    de generar_preguntas_ia_en_lotes solo detecta coincidencia de texto
    normalizado, no reformulaciones de la misma información (bug real:
    "duración del mandato del Presidente..." repetida en 8 de 20 preguntas
    de un mismo test).

    Con documentos cortos, un solo lote, o sin texto_fuente, dividir no
    compensa (puede dejar algún fragmento sin contenido suficiente para
    generar preguntas de calidad): se devuelve None en cada posición, y el
    llamante entonces usa el documento completo tal cual (sin pasar
    'fragmento' a construir_prompt, para no romper compatibilidad con
    construir_prompt(n) de un solo argumento)."""
    if not texto_fuente or n_lotes <= 1 or len(texto_fuente) < n_lotes * 400:
        return [None] * n_lotes
    longitud_objetivo = len(texto_fuente) // n_lotes
    fragmentos = []
    resto = texto_fuente
    for _ in range(n_lotes - 1):
        corte = min(longitud_objetivo, len(resto))
        salto = resto.find("\n\n", corte)
        if salto == -1:
            salto = resto.find("\n", corte)
        if salto == -1:
            salto = corte
        fragmentos.append(resto[:salto])
        resto = resto[salto:]
    fragmentos.append(resto)
    return fragmentos


def _prompt_con_exclusion(prompt, preguntas_a_evitar):
    """Añade al prompt de generación la lista de preguntas que NO debe
    repetir -- ya generadas en tests ANTERIORES de este mismo documento
    (ver blueprints/pdf_ia.py, obtener_preguntas_previas en
    documentos_pdf.py). Sin esto, cada llamada a /generar-test-desde-pdf
    parte de cero: dentro de una misma generación _fragmentos_por_lote ya
    evita que los lotes converjan en el mismo dato, pero un usuario que
    pulsa "generar test" varias veces seguidas sobre el mismo documento de
    su biblioteca podía acabar recibiendo la misma pregunta (reformulada o
    no) en dos tests distintos, porque ninguno de los dos sabía de la
    existencia del otro."""
    preguntas_a_evitar = [p for p in (preguntas_a_evitar or []) if p]
    if not preguntas_a_evitar:
        return prompt
    listado = "; ".join(preguntas_a_evitar[:60])
    return prompt + (
        "\n\nEstas preguntas ya se hicieron en tests ANTERIORES de este mismo documento -- no "
        f"repitas ninguna, ni siquiera redactada con otras palabras: {listado}. Aborda aspectos "
        "del documento no cubiertos por esas preguntas."
    )


def _pedir_una_pregunta_de_recambio(construir_prompt, pregunta_descartada, on_usage):
    """Pide UNA pregunta de recambio para sustituir a una que no superó la
    verificación, evitando repetir su tema -- nunca se "corrige" la
    pregunta descartada, se pide una completamente nueva."""
    prompt = construir_prompt(1)
    if pregunta_descartada:
        prompt += (
            f"\n\nNo repitas esta pregunta, ya descartada por no superar una verificación de precisión: "
            f"{pregunta_descartada!r}. Aborda un aspecto distinto del documento."
        )
    generado = call_deepseek_api(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
        max_tokens=3000,
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
                               max_intentos=MAX_INTENTOS_POR_PREGUNTA_PDF):
    """Verifica una pregunta candidata contra el documento de origen y, si
    no supera la verificación, la descarta POR COMPLETO y pide una de
    recambio evitando su tema, hasta max_intentos veces -- mismo principio
    que generador_preguntas_verificado.py aplica al temario oficial."""
    pregunta = pregunta_candidata
    intentos_restantes = max_intentos
    while intentos_restantes > 0:
        if _verificar_pregunta(pregunta, texto_fuente, on_usage):
            return pregunta
        intentos_restantes -= 1
        if intentos_restantes <= 0:
            return None
        pregunta = _pedir_una_pregunta_de_recambio(construir_prompt, pregunta.get("pregunta", ""), on_usage)
        if not pregunta:
            return None
    return None


def generar_preguntas_ia_en_lotes(construir_prompt, num_preguntas, texto_fuente=None, tamano_lote=5,
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

    /generar-test-desde-pdf antes pedía todo el test de golpe; el primer
    intento de arreglarlo con lotes asumía ~400-600 tokens por pregunta
    (max_tokens=min(4000, 300*n)), pero la investigación de rendimiento de
    Test Personalizado (mismo modelo deepseek-v4-flash, mismo formato de
    pregunta+4 opciones+explicación con cita de artículo, verificable con
    el log "finish_reason=%s, tokens_salida=%s" de deepseek_utils.py) mostró
    que una sola pregunta de este tipo puede necesitar hasta 3000 tokens y
    que la media real ronda 1200-1350 -- ya se veía JSON truncado
    (finish_reason="length") con lotes de solo 10 preguntas, no a partir de
    13-14. Por eso 'tamano_lote' se quedó en 5 (no 15) y el presupuesto de
    tokens por pregunta subió a la par (ver _pedir_lote_verificado más
    abajo): con menos preguntas por lote y más margen por pregunta, un lote
    lleno deja holgura real aunque alguna pregunta salga más verbosa de lo
    normal, en vez de agotar el tope a mitad del JSON.

    construir_prompt(n) debe devolver el prompt completo pidiendo EXACTAMENTE
    n preguntas, en el mismo formato de array JSON que ya usa esa ruta.
    Opcionalmente puede aceptar un segundo argumento, construir_prompt(n,
    fragmento) -- si el documento es lo bastante largo y hay más de un
    lote, cada lote recibe un FRAGMENTO distinto del documento (ver
    _fragmentos_por_lote más abajo) para repartir la generación entre
    partes distintas en vez de que todos los lotes vean el documento
    completo y converjan en los mismos hechos más citables (bug real:
    la misma pregunta reformulada varias veces en un test de 20). Solo se
    llama con 2 argumentos cuando de verdad hay un fragmento que pasar;
    en caso contrario (documento corto, un solo lote, o sin texto_fuente)
    se llama como construir_prompt(n), igual que antes.

    preguntas_a_evitar (opcional): textos de preguntas de tests ANTERIORES
    de este mismo documento (ver documentos_pdf.obtener_preguntas_previas,
    llamado desde blueprints/pdf_ia.py cuando se reusa un documento de la
    biblioteca) -- se añaden como exclusión tanto en los lotes iniciales
    como en el relleno de huecos, para que "generar test" varias veces
    sobre el mismo documento no repita lo ya preguntado en una generación
    previa (_fragmentos_por_lote y el relleno de más abajo solo evitan
    duplicados DENTRO de una misma llamada).

    Devuelve (preguntas, errores): preguntas ya verificadas y deduplicadas
    por texto de pregunta normalizado (pedir el mismo tema en varios lotes
    en paralelo puede repetir alguna), errores es una lista de motivos de
    fallo por lote (vacía si todo fue bien) para poder avisar si faltan
    preguntas respecto a las pedidas.
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

    def _reportar_avance_pregunta(pregunta_aceptada=None):
        """pregunta_aceptada: si se pasa (una pregunta que YA ha superado
        la verificación, o que se acepta sin verificar por no haber
        texto_fuente), se incluye en el evento como "pregunta" -- el
        llamante (ver blueprints/pdf_ia.py) la manda como un evento SSE
        aparte para que el frontend pueda empezar el test en cuanto
        lleguen las primeras N, igual que ya hace Test Personalizado
        (generador_preguntas_verificado.py)."""
        nonlocal completadas_preguntas
        if not on_progreso:
            return
        with lock_progreso:
            completadas_preguntas += 1
            valor = completadas_preguntas
        evento = {"completadas": valor, "total": num_preguntas}
        if pregunta_aceptada:
            evento["pregunta"] = pregunta_aceptada
        on_progreso(evento)

    def _pedir_lote_verificado(n, fragmento=None):
        prompt = construir_prompt(n, fragmento) if fragmento is not None else construir_prompt(n)
        prompt = _prompt_con_exclusion(prompt, preguntas_a_evitar)
        generado = call_deepseek_api(
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=min(8000, 1500 * n),
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
            for candidata in candidatas:
                _reportar_avance_pregunta(candidata)
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
                resultado = futuro.result()
                verificadas.append(resultado)
                _reportar_avance_pregunta(resultado)
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

    fragmentos = _fragmentos_por_lote(texto_fuente, len(lotes))

    preguntas = []
    errores = []
    # max_workers=8 (no 15, como generador_preguntas_verificado.py): cada
    # lote de aquí dispara además hasta _MAX_WORKERS_VERIFICACION_LOTE
    # verificaciones propias en paralelo, así que 8 lotes a la vez ya
    # supone picos de hasta 48 llamadas simultáneas a DeepSeek -- subir
    # más sin evidencia de que la API lo soporta bien sería imprudente.
    # Sirve sobre todo para peticiones grandes (30-100 preguntas, varios
    # lotes): con num_preguntas pequeño ya cabían todos los lotes en una
    # sola tanda incluso con el límite anterior de 5.
    with ThreadPoolExecutor(max_workers=min(8, len(lotes))) as executor:
        futuros = [
            executor.submit(_pedir_lote_verificado, n, fragmentos[i])
            for i, n in enumerate(lotes)
        ]
        for futuro in as_completed(futuros):
            lote_preguntas, error = futuro.result()
            if error:
                errores.append(error)
            else:
                preguntas.extend(lote_preguntas)

    vistas = set()
    preguntas_unicas = []
    for p in preguntas:
        claves = _claves_dedup(p)
        if claves and not (claves & vistas):
            vistas.update(claves)
            preguntas_unicas.append(p)

    # Relleno: si tras los lotes normales (con verificación y reintento por
    # pregunta ya agotados) sigue faltando alguna respecto a num_preguntas
    # -- por descartes que agotaron sus intentos, o por deduplicar entre
    # lotes en paralelo -- se da un hueco más por cada una que falte, con
    # el mismo principio que ya usan generador_preguntas_verificado.py y
    # tarjetas_generator.py para no dejar "pedí N, me dieron menos" como
    # respuesta por defecto. Cada hueco lleva su propio presupuesto
    # completo de reintentos dentro de _asegurar_pregunta_valida (genera
    # un candidato + hasta max_intentos-1 recambios si la verificación
    # falla), así que un hueco de relleno recibe el mismo presupuesto que
    # un hueco normal, no un múltiplo. Nunca relaja la verificación.
    #
    # EN PARALELO (antes era un "for" secuencial): con varios huecos, cada
    # uno tardando hasta 3 rondas de generación+verificación (~15-20s por
    # llamada a DeepSeek), rellenarlos uno detrás de otro podía sumar
    # 1-3 minutos SOLO en esta fase (bug real reportado: 16 preguntas
    # tardando 5-6 minutos) -- el cuello de botella dominante no eran los
    # lotes (ya paralelos) sino este relleno puramente secuencial. Al
    # tratarse de huecos independientes entre sí, paralelizarlos no
    # cambia en nada la verificación ni el resultado final, solo el
    # tiempo. Se protege con un lock el check-then-add sobre 'vistas' /
    # 'preguntas_unicas' (antes era seguro por ser secuencial; en
    # paralelo, dos hilos podrían aceptar el mismo tema a la vez sin él).
    faltan = num_preguntas - len(preguntas_unicas)
    if faltan > 0:
        lock_relleno = threading.Lock()

        def construir_prompt_evitando_repetidas(n):
            # Envuelve construir_prompt con un aviso de qué temas/datos ya
            # están cubiertos por el resto del test (snapshot de
            # preguntas_unicas en el momento de la llamada, incluyendo lo
            # que otros huecos de relleno ya hayan ido aceptando) -- sin
            # esto, un hueco podía regenerar a ciegas el mismo dato
            # sobreexplotado del documento una y otra vez hasta agotar sus
            # intentos, sin llegar nunca a rellenarse de verdad (bug real:
            # "pedí 10, recibí 9" con el hueco perdido siendo justo el que
            # intentaba repetir un hecho ya cubierto 3 veces en el resto
            # del test).
            with lock_relleno:
                cubiertas = [
                    f"{p.get('pregunta', '')} (respuesta: "
                    f"{(p.get('opciones') or {}).get(str(p.get('respuesta_correcta', '')).upper(), '')})"
                    for p in preguntas_unicas
                ]
            prompt = construir_prompt(n)
            if cubiertas:
                prompt += (
                    "\n\nNo repitas ninguno de estos temas/datos, ya cubiertos por otras preguntas de este "
                    f"mismo test: {'; '.join(cubiertas)}. Aborda un aspecto distinto del documento."
                )
            # También se evitan aquí las de tests ANTERIORES del mismo
            # documento (ver preguntas_a_evitar más arriba) -- un hueco de
            # relleno es, igual que un lote normal, una oportunidad más de
            # acabar repitiendo lo ya preguntado en una generación previa.
            return _prompt_con_exclusion(prompt, preguntas_a_evitar)

        def _rellenar_un_hueco(_indice):
            candidata = _pedir_una_pregunta_de_recambio(construir_prompt_evitando_repetidas, None, on_usage)
            pregunta = (
                _asegurar_pregunta_valida(candidata, construir_prompt_evitando_repetidas, texto_fuente, on_usage)
                if candidata and texto_fuente is not None else candidata
            )
            aceptada = None
            if pregunta:
                claves = _claves_dedup(pregunta)
                with lock_relleno:
                    if claves and not (claves & vistas):
                        vistas.update(claves)
                        preguntas_unicas.append(pregunta)
                        aceptada = pregunta
            # Solo se incluye en el evento si de verdad se aceptó (no si
            # era un duplicado que se descarta) -- el "pregunta" del
            # evento SSE representa una pregunta genuinamente nueva del
            # test final, no un intento cualquiera.
            _reportar_avance_pregunta(aceptada)

        with ThreadPoolExecutor(max_workers=min(10, faltan)) as executor:
            list(executor.map(_rellenar_un_hueco, range(faltan)))

    faltan_final = num_preguntas - len(preguntas_unicas)
    if faltan_final > 0:
        errores.append(f"No se pudieron generar {faltan_final} pregunta(s) adicionales tras varios intentos de relleno")

    return preguntas_unicas, errores
