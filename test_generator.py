import re
import json
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


def generar_preguntas_ia_en_lotes(construir_prompt, num_preguntas, texto_fuente=None, tamano_lote=15,
                                   temperature=0.4, on_progreso=None, on_usage=None):
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

    on_progreso(evento), si se pasa, se llama cada vez que un LOTE termina
    de generarse Y VERIFICARSE por completo (con éxito o error), con
    {"completadas": i, "total": n_lotes} -- pensado para retransmitir
    progreso real por SSE en vez de mensajes rotativos cosméticos (ver
    /generar-test-desde-pdf en blueprints/pdf_ia.py). El contrato no
    cambia por la verificación: "completadas" ahora significa "lotes ya
    verificados", que es justo el objetivo.

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

    def _pedir_lote_verificado(n):
        prompt = construir_prompt(n)
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
            return candidatas, None

        # Se verifica cada candidata del lote EN PARALELO -- en serie
        # multiplicaría por hasta 'tamano_lote' el tiempo de este lote, y
        # una pregunta con problemas no debe frenar a las demás.
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS_VERIFICACION_LOTE, len(candidatas))) as executor:
            futuros = [
                executor.submit(_asegurar_pregunta_valida, candidata, construir_prompt, texto_fuente, on_usage)
                for candidata in candidatas
            ]
            verificadas = [f.result() for f in futuros]
        return [p for p in verificadas if p], None

    preguntas = []
    errores = []
    completadas = 0
    with ThreadPoolExecutor(max_workers=min(5, len(lotes))) as executor:
        futuros = [executor.submit(_pedir_lote_verificado, n) for n in lotes]
        for futuro in as_completed(futuros):
            lote_preguntas, error = futuro.result()
            completadas += 1
            if error:
                errores.append(error)
            else:
                preguntas.extend(lote_preguntas)
            if on_progreso:
                on_progreso({"completadas": completadas, "total": len(lotes)})

    vistas = set()
    preguntas_unicas = []
    for p in preguntas:
        clave = re.sub(r"\s+", " ", str(p.get("pregunta", "")).strip().lower())
        if clave and clave not in vistas:
            vistas.add(clave)
            preguntas_unicas.append(p)

    return preguntas_unicas, errores
