import re
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from deepseek_utils import call_deepseek_api
from validador_preguntas import validar_pregunta

logger = logging.getLogger(__name__)

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

# Artículo citado en el enunciado (solo el número base, p.ej. "26" tanto
# para "artículo 26" como para "artículo 26.6" -- ver _claves_dedup) y
# cifras concretas ("15 días hábiles", "1 mes", "2 tercios"...) en la
# respuesta correcta -- ver el comentario largo en _claves_dedup sobre por
# qué hace falta esta clave adicional.
_PATRON_ARTICULO_BASE = re.compile(r"art[íi]culo\s+(\d+)", re.IGNORECASE)

# Fracciones en PALABRAS ("dos tercios", "tres quintos") y en cifras con
# barra ("2/3", "3/5") -- bug real, documento real (03/08/2026): 4
# preguntas sobre el art. 168 de la Constitución Española y la mayoría
# exigida ("dos tercios de cada Cámara") se colaron como 4 preguntas
# "distintas" en un test de 20 porque la respuesta correcta las expresaba
# de formas distintas ("dos tercios", "2/3") y ninguna contenía un dígito
# PEGADO a la unidad como exige el resto de _PATRON_CIFRA (que solo cazaba
# "15 días", "1 mes", nunca un número en palabras). Las mayorías
# cualificadas ("mayoría de tres quintos", "mayoría de dos tercios",
# "mayoría absoluta") son uno de los datos más citados en cualquier
# temario de oposición (procedimientos legislativos, reformas
# constitucionales y de estatutos, votaciones de órganos colegiados...),
# así que este hueco no es específico de un documento sino un patrón
# recurrente en este tipo de test.
_NUMEROS_EN_PALABRAS = {
    "un": "1", "uno": "1", "una": "1", "dos": "2", "tres": "3", "cuatro": "4",
    "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9", "diez": "10",
}
_DENOMINADORES_EN_PALABRAS = {
    "tercio": "3", "cuarto": "4", "quinto": "5", "sexto": "6", "septimo": "7",
    "octavo": "8", "noveno": "9", "decimo": "10",
}
# Fracciones como "adjetivo ordinal femenino + parte" ("una quinta parte",
# "dos quintas partes", "una décima parte") -- forma HABITUAL en español
# jurídico para expresar fracciones de un colectivo (quórums, iniciativas
# firmadas por una fracción de una Cámara...), y GRAMATICALMENTE DISTINTA
# de "un quinto"/"dos quintos" (que _DENOMINADORES_EN_PALABRAS ya cubre):
# aquí el numeral concuerda con "parte" (femenino), no con la fracción en
# sí. Bug real, documento real (03/08/2026): "la firma de 2 Grupos
# Parlamentarios o de una quinta parte de los miembros de la Cámara" (art.
# 146 del Reglamento del Congreso) se preguntó 2 veces con enunciados
# distintos ("¿qué se requiere para presentar...?" / "¿qué se exige para
# que los Grupos... puedan presentar...?") -- sin este patrón, "una quinta
# parte" no producía ninguna cifra reconocible.
_DENOMINADORES_ORDINAL_FEMENINO = {
    "segunda": "2", "tercera": "3", "cuarta": "4", "quinta": "5", "sexta": "6",
    "septima": "7", "octava": "8", "novena": "9", "decima": "10",
}
_PATRON_CIFRA = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:d[íi]as?\s+h[áa]biles?|d[íi]as?\s+naturales?|d[íi]as?|"
    r"meses?|mes\b|a[ñn]os?|tercios?|cuartos?|%|por\s*ciento)"
    r"|\d+\s*/\s*\d+"
    r"|(?:un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+"
    r"(?:tercios?|cuartos?|quintos?|sextos?|s[ée]ptimos?|octavos?|novenos?|d[ée]cimos?)"
    r"|(?:un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+"
    r"(?:segunda|tercera|cuarta|quinta|sexta|s[ée]ptima|octava|novena|d[ée]cima)s?\s+partes?"
    # Mayorías cualificadas SIN cifra explícita (bug real, documento real:
    # "mayoría absoluta" se preguntó 3 veces sobre el mismo dato con
    # enunciados distintos, ninguno con un número o fracción que la
    # regla de arriba pudiera cazar) -- tan citadas en cualquier temario
    # de oposición como las fracciones numéricas de más arriba.
    r"|mayor[íi]a\s+(?:absoluta|simple|cualificada|relativa)",
    re.IGNORECASE,
)

# Principios jurídicos con NOMBRE PROPIO del artículo 9.3 de la Constitución
# Española (legalidad, jerarquía normativa, publicidad de las normas,
# irretroactividad, seguridad jurídica, responsabilidad de los poderes
# públicos, interdicción de la arbitrariedad) -- bug real, documento real
# (03/08/2026): "¿qué principio implica que la ley no podrá aplicarse a
# casos anteriores...?" (respuesta: "El principio de irretroactividad de
# ciertas normas.") y "¿qué se establece en el artículo 9.3 respecto a las
# disposiciones sancionadoras no favorables?" (respuesta: "La Constitución
# garantiza SU IRRETROACTIVIDAD...") son la misma pregunta sobre el mismo
# principio, pero ninguna clave de _claves_dedup las detectaba: los textos
# no coinciden ni por completo ni por contención, y "irretroactividad" no
# es una cifra (_PATRON_CIFRA no aplica). El artículo 9.3 CE es de los
# artículos más preguntados en cualquier temario de oposición sobre
# Administración Pública española, así que este patrón concreto no es
# específico de un documento.
#
# Se busca SOLO en pregunta+RESPUESTA CORRECTA, nunca en la explicación
# completa ni en las opciones incorrectas (ver
# _conceptos_juridicos_citados) -- probado con datos reales y descartado:
# el campo "explicacion" repasa TODAS las opciones (A-D), así que una
# pregunta sobre "publicidad de las normas" con distractores que descartan
# "legalidad"/"jerarquía normativa"/"irretroactividad" menciona los CUATRO
# nombres en su propia explicación, y dos preguntas de un mismo test que
# comparten solo un distractor en común (nada raro con 7 principios
# posibles y varias preguntas sobre el mismo artículo) acababan
# fusionándose como si fueran la misma -- un falso positivo real,
# reproducido con las preguntas de este mismo documento. La pregunta y la
# respuesta CORRECTA, en cambio, casi nunca nombran un principio que no
# sea el que de verdad se está preguntando.
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


def _conceptos_juridicos_citados(pregunta):
    texto = f"{pregunta.get('pregunta', '')} {_respuesta_correcta_normalizada(pregunta)}".lower()
    return set(_PATRON_PRINCIPIO_JURIDICO.findall(texto))


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
    # Porcentajes en símbolo ("13%") y en palabras ("13 por ciento") -- bug
    # real, documento real (03/08/2026): una pregunta sobre el límite de
    # deuda pública de las Comunidades Autónomas ("El 13 por ciento del
    # Producto Interior Bruto nacional") y otra pregunta más amplia sobre
    # el mismo artículo, con el desglose completo por subsector escrito en
    # símbolo ("El 60% del PIB..., un 13% para el conjunto de las
    # Comunidades Autónomas..."), citan el MISMO dato (13% para CCAA) pero
    # ninguna clave de dedup las detectaba: "13 por ciento" y "13%" son
    # cadenas distintas para _PATRON_CIFRA, así que ni siquiera producían
    # la misma cifra dentro de la clave artículo+cifras.
    coincide_porcentaje = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(?:%|por\s*ciento)", cifra)
    if coincide_porcentaje:
        return f"{coincide_porcentaje.group(1)}%"
    return cifra


def _normalizar(texto):
    return re.sub(r"\s+", " ", str(texto or "").strip().lower())


def _articulos_citados(pregunta):
    """Números base de artículo citados en el ENUNCIADO -- o, si el
    enunciado no cita ninguno, en la EXPLICACIÓN como respaldo (bug real,
    documento real: "Según la Constitución Española de 1978, ¿qué mayoría
    se exige en el Senado para que...?" no citaba ningún artículo en el
    enunciado, solo en la explicación ("el artículo 167.2 de la
    Constitución Española establece..."), así que buscar solo en el
    enunciado dejaba esa pregunta sin artículo detectado -- y por tanto sin
    la clave artículo+cifras -- pese a ser, con otras dos preguntas del
    mismo test que sí lo citaban en el enunciado, la MISMA pregunta sobre
    la misma mayoría del mismo artículo repetida 3 veces.

    NO se usa la UNIÓN de enunciado+explicación (03/08/2026, bug real,
    documento real): dos preguntas casi idénticas sobre el artículo 167
    ("mayoría de tres quintos" para la reforma ordinaria) escaparon al
    dedup porque una de ellas, al descartar la opción "mayoría de dos
    tercios", explicaba de pasada que esa mayoría "se exige... en el
    procedimiento agravado del artículo 168" -- una simple referencia
    cruzada en un distractor, no el artículo de la pregunta. Con la unión,
    esa pregunta quedaba con articulos={'167','168'} mientras la otra (sin
    esa referencia cruzada) quedaba con articulos={'167'}: conjuntos
    distintos, clave d:167|168:3/5 frente a d:167:3/5, ninguna coincidía.
    El enunciado (¿"Según/Conforme al artículo N..."?) es la fuente fiable
    de qué artículo trata la pregunta; la explicación solo se consulta
    como respaldo cuando el enunciado no cita ninguno."""
    articulos_enunciado = set(_PATRON_ARTICULO_BASE.findall(pregunta.get("pregunta", "")))
    if articulos_enunciado:
        return articulos_enunciado
    return set(_PATRON_ARTICULO_BASE.findall(pregunta.get("explicacion", "")))


# Umbral para la contención de respuestas (ver _es_duplicado_por_contencion):
# más alto que _LONGITUD_MINIMA_DEDUP_RESPUESTA (10) a propósito, para no
# confundir dos preguntas legítimamente distintas del mismo artículo que
# comparten una respuesta corta y genérica por coincidencia (p.ej. "Mayoría
# absoluta.", 16 caracteres) con un duplicado real.
_LONGITUD_MINIMA_CONTENCION = 25

# Umbral de solapamiento de palabras (ver _solapamiento_palabras) para que
# dos respuestas correctas del mismo artículo se consideren el mismo hecho
# reformulado -- 0.5 separa con margen amplio los casos reales: el mismo
# hecho reformulado con las palabras reordenadas o una palabra distinta
# ("o"/"ni") da 0.58-0.92, mientras que dos hechos LEGÍTIMAMENTE distintos
# del mismo artículo (p.ej. el deber de resolver de los jueces frente a los
# requisitos de la costumbre, ambos del art. 1 del Código Civil) dan como
# mucho 0.18 -- probado con datos reales, ver el comentario largo de
# _es_duplicado_por_contencion.
_UMBRAL_SOLAPAMIENTO_RESPUESTA = 0.5


def _respuesta_correcta_normalizada(pregunta):
    opciones = pregunta.get("opciones") or {}
    letra = str(pregunta.get("respuesta_correcta", "")).upper()
    return _normalizar(opciones.get(letra, ""))


def _solapamiento_palabras(texto_a, texto_b):
    """Proporción de Jaccard entre las palabras de dos textos (intersección
    entre unión) -- ver _UMBRAL_SOLAPAMIENTO_RESPUESTA."""
    palabras_a = set(re.findall(r"\w+", texto_a))
    palabras_b = set(re.findall(r"\w+", texto_b))
    if not palabras_a or not palabras_b:
        return 0.0
    return len(palabras_a & palabras_b) / len(palabras_a | palabras_b)


def _es_duplicado_por_contencion(pregunta, candidatas_existentes):
    """Duplicado adicional (03/08/2026, bug real, documento real): dos
    preguntas sobre el MISMO artículo, una más amplia ("¿qué establece el
    artículo 8 sobre las Fuerzas Armadas?" -> composición Y misión) y otra
    más concreta ("¿cuál es la misión de las Fuerzas Armadas según el
    artículo 8?" -> solo la misión), cuya respuesta correcta de la concreta
    es un FRAGMENTO LITERAL de la respuesta de la amplia. Ninguna de las
    dos claves de _claves_dedup las detecta: el texto de la pregunta es
    distinto, el texto completo de la respuesta también (una es más larga
    que la otra), y sin cifras concretas tampoco se genera la clave
    artículo+cifras (ese hecho -- composición y misión de un órgano -- no
    es una cifra). Se compara aquí el artículo base citado junto con
    CONTENCIÓN de texto entre las respuestas correctas normalizadas, ya que
    _claves_dedup exige coincidencia casi literal y esto necesita detectar
    que una es un subconjunto de la otra.

    También se compara por SOLAPAMIENTO DE PALABRAS, no solo contención
    literal (03/08/2026, bug real, documento real): 3 preguntas sobre el
    mismo requisito del artículo 1.3 del Código Civil (que la costumbre
    "regirá en defecto de ley aplicable, siempre que resulte probada y no
    sea contraria a la moral o al orden público") se colaron juntas en un
    test de 20 porque cada una reformulaba la frase con las palabras en
    otro orden o con una palabra distinta ("o" en vez de "ni") -- ninguna
    era ni el texto exacto de otra (falla 'r:') ni un fragmento literal
    contiguo de otra (falla la contención de arriba, por el reordenamiento).
    El solapamiento de palabras (intersección/unión, sin importar el orden)
    sí detecta que son el mismo hecho.

    También se compara por CONTENCIÓN DE CIFRAS, no solo de texto (03/08/2026,
    bug real, documento real): una pregunta concreta sobre el límite de deuda
    de las Comunidades Autónomas ("El 13 por ciento del PIB nacional") y otra
    más amplia sobre el mismo artículo con el desglose completo por subsector
    ("El 60% del PIB..., un 13% para las Comunidades Autónomas...") citan el
    MISMO dato, pero ninguna de las comprobaciones de arriba lo detectaba: el
    texto completo no coincide ni por contención ni por solapamiento (la
    pregunta amplia tiene muchas más palabras propias -- 44%, 3%, Corporaciones
    Locales... -- que diluyen el solapamiento muy por debajo del umbral), y la
    clave "d:" de _claves_dedup exige que el CONJUNTO de cifras sea IDÉNTICO,
    no que uno esté contenido en el otro. Si el conjunto de cifras de una
    pregunta es subconjunto del de la otra (mismo artículo, ya comprobado
    arriba), es el mismo dato citado con distinto nivel de detalle."""
    articulos = _articulos_citados(pregunta)
    if not articulos:
        return False
    respuesta = _respuesta_correcta_normalizada(pregunta)
    if len(respuesta) < _LONGITUD_MINIMA_CONTENCION:
        return False
    cifras = {_normalizar_cifra(c) for c in _PATRON_CIFRA.findall(respuesta)}
    for otra in candidatas_existentes:
        if not (articulos & _articulos_citados(otra)):
            continue
        otra_respuesta = _respuesta_correcta_normalizada(otra)
        if len(otra_respuesta) < _LONGITUD_MINIMA_CONTENCION:
            continue
        if respuesta in otra_respuesta or otra_respuesta in respuesta:
            return True
        if _solapamiento_palabras(respuesta, otra_respuesta) >= _UMBRAL_SOLAPAMIENTO_RESPUESTA:
            return True
        cifras_otra = {_normalizar_cifra(c) for c in _PATRON_CIFRA.findall(otra_respuesta)}
        if cifras and cifras_otra and (cifras <= cifras_otra or cifras_otra <= cifras):
            return True
    return False


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
    comparaba el texto de la pregunta).

    Tercera clave (02/08/2026, bug real): "artículo citado + cifras
    concretas de la respuesta correcta" -- las dos claves de arriba
    exigen coincidencia de texto casi literal (la pregunta entera, o la
    respuesta entera), así que una reformulación MÁS AMPLIA del mismo
    hecho (p.ej. "¿cuál es el plazo?" -> "15 días hábiles" vs "¿cuál es
    el plazo y cuándo se reduce?" -> "15 días hábiles, reducible a 7 días
    hábiles...") se les escapa a ambas por igual. Visto en producción con
    un documento real: el art. 26.6 de una ley (plazo de audiencia
    pública, 15 días hábiles reducible a 7) generado 4 veces con 4
    redacciones distintas, 2 de ellas casi calcadas entre sí -- ninguna
    coincidía en texto exacto con otra. Aquí se compara el NÚMERO BASE
    del artículo citado (26 tanto para "artículo 26" como "artículo
    26.6" -- los lotes en paralelo no siempre citan el mismo nivel de
    detalle del mismo apartado) junto con el CONJUNTO de cifras de la
    respuesta correcta: mismo artículo base + mismas cifras es una
    combinación lo bastante específica para no confundir dos preguntas
    LEGÍTIMAMENTE distintas sobre el mismo artículo (p.ej. el plazo de
    audiencia pública frente al plazo de informes preceptivos, ambos del
    art. 26 pero con cifras distintas -- 15/7 días frente a 1 mes). Si no
    hay artículo citado o no hay cifras en la respuesta, esta clave
    simplemente no se genera (las dos de arriba siguen aplicando igual).

    El artículo se busca con _articulos_citados (enunciado Y explicación,
    ver su comentario) -- no todas las preguntas repiten el número de
    artículo en el propio enunciado, pero la explicación casi siempre lo
    cita."""
    claves = set()
    texto_pregunta = pregunta.get("pregunta", "")
    clave_pregunta = _normalizar(texto_pregunta)
    if clave_pregunta:
        claves.add(f"p:{clave_pregunta}")
    opciones = pregunta.get("opciones") or {}
    letra_respuesta = str(pregunta.get("respuesta_correcta", "")).upper()
    clave_respuesta = _normalizar(opciones.get(letra_respuesta, ""))
    if len(clave_respuesta) >= _LONGITUD_MINIMA_DEDUP_RESPUESTA:
        claves.add(f"r:{clave_respuesta}")
    articulos = sorted(_articulos_citados(pregunta))
    cifras = sorted({_normalizar_cifra(c) for c in _PATRON_CIFRA.findall(clave_respuesta)})
    if articulos and cifras:
        claves.add(f"d:{'|'.join(articulos)}:{'|'.join(cifras)}")
    # Cuarta clave (03/08/2026, bug real): igual que la de arriba pero para
    # principios jurídicos con nombre propio ("principio de irretroactividad",
    # "interdicción de la arbitrariedad"...) en vez de cifras -- ver el
    # comentario largo junto a _PATRON_PRINCIPIO_JURIDICO.
    conceptos = sorted(_conceptos_juridicos_citados(pregunta))
    if articulos and conceptos:
        claves.add(f"c:{'|'.join(articulos)}:{'|'.join(conceptos)}")
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
        # Bug real de producción: con 400 tokens, deepseek-v4-flash trunca
        # la respuesta (finish_reason="length") cuando la verificación
        # encuentra varios problemas y los detalla en "problemas" -- un JSON
        # cortado a mitad no parsea (json.loads falla más abajo), así que la
        # pregunta se trata como inválida AUNQUE la IA la hubiera dado por
        # buena, disparando una regeneración innecesaria. Eso multiplica las
        # llamadas totales (una verificación truncada cuenta como fallo, lo
        # que pide una pregunta de recambio Y su propia verificación) y deja
        # el test por debajo de lo pedido cuando se agotan los reintentos.
        # 2000 iguala el margen que generador_preguntas_verificado.py ya usa
        # para el mismo modelo y el mismo tipo de verificación, con la misma
        # razón documentada ahí: deepseek-v4-flash es más verboso de lo que
        # parece necesario. Subir max_tokens no encarece nada por sí solo
        # (DeepSeek cobra por los tokens que de verdad genera, no por el
        # tope): solo evita el corte cuando de verdad hacen falta más de 400.
        # Actualización: en producción, con el margen ya en 2000, todavía se
        # vieron un par de verificaciones con finish_reason="length" justo
        # en ese tope -- 2000 redujo muchísimo los cortes pero no los quitó
        # del todo. Subido a 4000 con el mismo razonamiento (sin coste si no
        # hace falta).
        # Segunda actualización (02/08/2026): con thinking_enabled=True ya
        # activo aquí (ver más abajo), en producción se vio esta
        # verificación truncar varias veces justo en tokens_salida=4000 --
        # mismo patrón, misma causa y mismo arreglo ya aplicado en
        # generador_preguntas_verificado.py: el razonamiento (que aquí
        # cuenta contra el mismo tope que el JSON de salida) necesita más
        # margen del que hacía falta antes de activarlo. Subido a 8000.
        max_tokens=8000,
        response_format_json=True,
        on_usage=on_usage,
        # thinking_enabled=True (02/08/2026): call_deepseek_api desactiva el
        # razonamiento interno de deepseek-v4-flash por defecto (ver el
        # comentario largo junto a payload["thinking"] en deepseek_utils.py)
        # porque en el Test Personalizado se vio que ese razonamiento
        # dominaba tiempo y tokens sin aportar nada en la GENERACIÓN. Pero
        # esto es una VERIFICACIÓN -- la misma decisión tomada ahí aplica
        # aquí igual: es la tarea que se juega la precisión, así que se
        # mantiene el margen de deliberación encendido a propósito.
        thinking_enabled=True,
        # stream=True (02/08/2026, arreglo real de producción: este archivo
        # se había quedado sin el fix de streaming que ya tenía
        # generador_preguntas_verificado.py desde el principio de la sesión
        # -- un despiste, no una decisión). Sin streaming no viaja NINGÚN
        # byte entre la petición y la respuesta terminada, y toda llamada
        # que tarda más de ~30s en generar muere con "Error de conexión: no
        # se pudo conectar a DeepSeek API" -- cortada desde el otro lado,
        # no por nuestro timeout. Con thinking_enabled=True esta
        # verificación puede tardar bastante (visto en el generador
        # principal: reasoning_content de hasta 20000+ caracteres, 40-50s),
        # así que sin streaming estaba condenada a morir con cierta
        # frecuencia -- exactamente lo que se vio en producción: varias
        # "Error de conexión" seguidos y un test de 20 preguntas que se
        # quedó en 18-19. Ver el comentario largo en
        # deepseek_utils._leer_respuesta_en_streaming.
        stream=True,
    )
    if not raw:
        return False
    try:
        return json.loads(raw).get("valido") is True
    except json.JSONDecodeError:
        return False


def _prompt_deduplicacion_final(preguntas):
    listado = "\n".join(
        f"{i}. PREGUNTA: {p.get('pregunta', '')}\n"
        f"   RESPUESTA CORRECTA: {(p.get('opciones') or {}).get(str(p.get('respuesta_correcta', '')).upper(), '')}"
        for i, p in enumerate(preguntas)
    )
    system = (
        "Eres un revisor de calidad de un test tipo oposición YA TERMINADO. Te llega la lista completa "
        "de preguntas ya aceptadas, numeradas. Tu única tarea es encontrar grupos de preguntas que "
        "pregunten por el MISMO dato o hecho concreto, aunque estén redactadas de forma muy distinta: "
        "con las palabras en otro orden, con una cifra en otro formato (\"13%\" y \"13 por ciento\"), "
        "citando el mismo dato desde un ángulo distinto (\"¿qué mayoría se exige en el Senado?\" y "
        "\"¿qué mayoría hace falta para que el Congreso apruebe...?\" si ambas apuntan al mismo requisito "
        "concreto), o una más amplia que ya incluye por completo el dato de otra más concreta.\n\n"
        "NO marques como duplicadas dos preguntas solo por tratar el mismo artículo, la misma ley o el "
        "mismo tema general si cada una pregunta por un dato, cifra, plazo u órgano DISTINTO dentro de "
        "ese artículo -- eso son preguntas legítimamente distintas, no duplicados, aunque tengan mucho "
        "vocabulario en común.\n\n"
        "Devuelve ÚNICAMENTE un JSON con esta forma exacta, sin texto adicional:\n"
        '{"grupos_duplicados": [[0, 3], [5, 7, 8]]}\n'
        "Cada lista interna son los números de las preguntas que preguntan por el mismo dato entre sí. "
        "Si no hay ningún grupo, devuelve exactamente {\"grupos_duplicados\": []}."
    )
    return system, listado


def _detectar_duplicados_finales(preguntas, on_usage=None):
    """Pasada final de deduplicación SEMÁNTICA sobre la lista YA ACEPTADA
    de un test completo (03/08/2026, decisión explícita del usuario tras
    varias rondas de bugs reales de duplicados en esta misma sesión: art.
    167 con una referencia cruzada a otro artículo en la explicación,
    "mayoría de tres quintos" repetida con las palabras reordenadas o una
    palabra distinta, el mismo dato citado en símbolo y en palabras...).
    Cada uno de esos bugs se corrigió por separado en _claves_dedup /
    _es_duplicado_por_contencion (comparaciones deterministas, gratis,
    rápidas -- se quedan como primera línea de defensa porque no cuestan
    nada), pero son heurísticas LÉXICAS: cada documento nuevo puede volver
    a encontrar una reformulación distinta que ninguna de ellas cubra
    todavía. En vez de seguir persiguiendo casos nuevos uno a uno, esta
    pasada añade una red de seguridad SEMÁNTICA: una única llamada extra,
    al final, que compara los enunciados y respuestas ya cortos de la
    lista final entre sí (sin el documento de origen, así que es rápida y
    barata) y no escala con el tamaño del documento ni con el número de
    lotes -- solo se paga UNA vez por test, no una vez por candidata.

    Devuelve el conjunto de ÍNDICES a eliminar (todos menos el primero de
    cada grupo duplicado que la IA identifique). Si la llamada falla o no
    devuelve JSON válido, se queda sin eliminar nada (falla abierta: mejor
    dejar un posible duplicado que perder preguntas buenas por un fallo de
    red)."""
    if len(preguntas) < 2:
        return set()
    system, user = _prompt_deduplicacion_final(preguntas)
    raw = call_deepseek_api(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        max_tokens=1500,
        response_format_json=True,
        on_usage=on_usage,
        stream=True,
    )
    if not raw:
        return set()
    try:
        datos = json.loads(raw)
    except json.JSONDecodeError:
        return set()
    # datos podría no ser un dict (p.ej. en tests que mockean
    # call_deepseek_api sin distinguir esta llamada de otras y devuelven
    # el array de generación por defecto) -- fallar abierto, sin
    # eliminar nada, igual que ante cualquier otra respuesta inesperada.
    if not isinstance(datos, dict):
        return set()
    grupos = datos.get("grupos_duplicados", [])
    indices_a_quitar = set()
    for grupo in grupos:
        if not isinstance(grupo, list):
            continue
        indices_validos = sorted({i for i in grupo if isinstance(i, int) and 0 <= i < len(preguntas)})
        if len(indices_validos) >= 2:
            indices_a_quitar.update(indices_validos[1:])
    return indices_a_quitar


# Marcador de bloque PRIMARIO -- artículo o disposición -- que nunca debe
# repartirse entre dos lotes (03/08/2026, ver el comentario largo en
# _fragmentos_por_lote sobre por qué el reparto por párrafo intercalado
# seguía dando duplicados en documentos legales). Anclado al INICIO DE
# LÍNEA (^, con re.MULTILINE): un encabezado real extraído de un PDF legal
# casi siempre empieza su propia línea ("Artículo 167.\n1. Los proyectos
# de reforma..."), mientras que una REFERENCIA a ese artículo dentro del
# texto de OTRO ("como establece el artículo 167 de la Constitución...")
# aparece a mitad de frase -- sin el ancla, esa referencia cruzada se
# confundiría con un encabezado nuevo y cortaría el bloque del artículo
# que sí lo contiene a mitad de frase.
_PATRON_MARCADOR_PRIMARIO = re.compile(
    r"^\s*(?:"
    r"art[íi]culo\s+\d+"
    r"|disposici[óo]n\s+(?:adicional|transitoria|final|derogatoria)"
    r"\s*(?:primera|segunda|tercera|cuarta|quinta|sexta|s[ée]ptima|octava|novena|d[ée]cima|[úu]nica|\d+\.?[ªa]?)?"
    r")",
    re.IGNORECASE | re.MULTILINE,
)
# Marcador de SECCIÓN (Título/Capítulo/Sección) -- no es un bloque en sí
# mismo, pero actúa como límite: si tras él viene directamente un
# Artículo, su propio "bloque" queda vacío (se descarta, ver
# _bloques_estructurales) y el título simplemente antecede al artículo
# como esperaría cualquiera; si en cambio agrupa texto SIN artículos
# numerados propios (p.ej. un título puramente introductorio), ese texto
# se trata como un bloque más, para que tampoco se reparta entre lotes.
_PATRON_MARCADOR_SECCION = re.compile(
    # "preliminar" además de números romanos/arábigos (03/08/2026, bug
    # real de esta misma sesión): la propia Constitución Española tiene un
    # "Título Preliminar" antes del Título I -- sin esta alternativa, ese
    # título quedaba sin reconocer como marcador y todo su contenido (más
    # lo que viniera antes) se trataba como prosa suelta.
    r"^\s*(?:T[ÍI]TULO|CAP[ÍI]TULO|SECCI[ÓO]N)\s+(?:[IVXLCDM]+|\d+|preliminar)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _bloques_estructurales(texto_fuente):
    """Divide texto_fuente en bloques anclados a sus marcadores
    estructurales (artículo, disposición, título/capítulo/sección) --
    cada bloque abarca desde su marcador hasta el siguiente marcador de
    CUALQUIER tipo (o fin de documento). Un apartado numerado dentro de un
    artículo ("1.", "2.", "a)"...) nunca se confunde con un marcador
    nuevo porque _PATRON_MARCADOR_PRIMARIO/_SECCION no matchean ese
    patrón -- se queda como texto normal dentro del bloque de su
    artículo/disposición padre.

    Devuelve (bloques, prosa_inicial): bloques es una lista de
    {"etiqueta": str, "tipo": "primario"|"seccion", "inicio": int,
    "texto": str} en el orden en que aparecen en el documento;
    prosa_inicial es el texto ANTES del primer marcador (portada,
    introducción...), que no pertenece a ningún bloque -- ver el
    comentario largo en _fragmentos_por_lote sobre por qué esa prosa
    suelta se reparte aparte, por párrafo, en vez de intentar agruparla.

    LIMITACIÓN CONOCIDA: si el documento cita el MISMO número de artículo
    en dos normas distintas sin un Título/Capítulo por medio que las
    separe (p.ej. "Artículo 5" de una ley y, más adelante, "Artículo 5" de
    otra ley distinta dentro del mismo PDF), cada aparición se trata como
    su propio bloque igualmente (esta función no intenta identificar a
    qué norma pertenece cada uno) -- caso raro, y no es nuevo: la propia
    clave de deduplicación de _claves_dedup ya tenía esta misma limitación
    (compara solo el número de artículo, nunca la norma)."""
    marcadores = sorted(
        [
            (m.start(), m.end(), "primario", re.sub(r"\s+", " ", m.group()).strip())
            for m in _PATRON_MARCADOR_PRIMARIO.finditer(texto_fuente)
        ] + [
            (m.start(), m.end(), "seccion", re.sub(r"\s+", " ", m.group()).strip())
            for m in _PATRON_MARCADOR_SECCION.finditer(texto_fuente)
        ],
        key=lambda marcador: marcador[0],
    )
    if not marcadores:
        return [], texto_fuente

    prosa_inicial = texto_fuente[:marcadores[0][0]]
    bloques = []
    for indice, (inicio, fin_marcador, tipo, etiqueta) in enumerate(marcadores):
        fin_bloque = marcadores[indice + 1][0] if indice + 1 < len(marcadores) else len(texto_fuente)
        if tipo == "seccion":
            # Solo cuenta como bloque si hay contenido DESPUÉS del propio
            # texto del marcador -- el caso normal (un Título seguido
            # directamente de su primer Artículo) no debe dejar un
            # "bloque" formado únicamente por el título repitiéndose a sí
            # mismo sin texto propio.
            if not texto_fuente[fin_marcador:fin_bloque].strip():
                continue
            etiqueta = f"{etiqueta} completo (sin artículos numerados)"
        contenido = texto_fuente[inicio:fin_bloque]
        if not contenido.strip():
            continue
        bloques.append({"etiqueta": etiqueta, "tipo": tipo, "inicio": inicio, "texto": contenido})
    return bloques, prosa_inicial


def _repartir_bloques_en_lotes(bloques, n_lotes):
    """Reparte 'bloques' (ver _bloques_estructurales) entre n_lotes listas,
    equilibrando el total de CARACTERES por lote -- no solo el número de
    bloques, que dejaría un lote con un único artículo larguísimo y otro
    con cinco artículos cortos como si fuera un reparto equilibrado. Bin
    packing voraz clásico: los bloques más grandes se colocan primero,
    cada uno en el lote que menos caracteres lleve acumulados hasta ese
    momento -- con al menos tantos bloques como lotes (única condición
    bajo la que se llama a esta función, ver _fragmentos_por_lote), los
    primeros n_lotes bloques colocados garantizan que ningún lote se quede
    vacío."""
    lotes = [[] for _ in range(n_lotes)]
    tamanos = [0] * n_lotes
    for bloque in sorted(bloques, key=lambda b: -len(b["texto"])):
        indice_lote = tamanos.index(min(tamanos))
        lotes[indice_lote].append(bloque)
        tamanos[indice_lote] += len(bloque["texto"])
    for lote in lotes:
        lote.sort(key=lambda b: b["inicio"])
    return lotes


def _prompt_esquema_documento(texto_fuente, n_bloques):
    return (
        "Eres un asistente que divide un documento en secciones temáticas para repartir su "
        f"contenido entre {n_bloques} grupos de trabajo -- cada grupo se encargará de una "
        "parte distinta, ningún grupo debe ver la misma sección que otro, para no duplicar "
        "trabajo entre ellos.\n\n"
        f"Divide el documento de abajo en EXACTAMENTE {n_bloques} secciones consecutivas, de "
        "tamaño lo más parecido posible entre sí, que cubran el documento COMPLETO de "
        "principio a fin sin solaparse ni dejar huecos. Elige los cortes en los límites "
        "temáticos más naturales del propio documento (un artículo, un apartado, un cambio de "
        "tema o epígrafe...), nunca a mitad de una frase o de una idea.\n\n"
        "Para cada sección, copia LITERALMENTE del documento (sin cambiar ni una letra, ni "
        "corregir tildes o mayúsculas) las primeras 6-10 palabras con las que empieza esa "
        "sección -- se usan para localizar el corte exacto en el texto original, así que deben "
        "coincidir carácter por carácter con el documento.\n\n"
        "Devuelve ÚNICAMENTE un JSON con esta forma exacta, sin texto adicional:\n"
        '[{"titulo": "resumen breve del tema de la sección", "inicio_literal": "primeras '
        'palabras exactas de la sección"}]\n\n'
        f"DOCUMENTO:\n{texto_fuente}"
    )


def _bloques_por_esquema_ia(texto_fuente, n_bloques, on_usage=None):
    """Segundo nivel de detección de estructura (03/08/2026, ver el
    comentario largo en _fragmentos_por_lote): _bloques_estructurales
    (basada en regex de artículo/disposición/título) solo funciona con
    texto LEGAL en bruto -- probada contra un documento real subido por un
    usuario (un temario narrativo tipo apunte, no la ley en sí, con los
    artículos citados dentro de la prosa: "el art. 9 CE señala que...")
    encontró un único "bloque", y ese uno era un falso positivo (un salto
    de línea del PDF que coincidía por casualidad con el patrón). Los
    usuarios suben documentos de cualquier formato, así que ninguna regex
    fija va a generalizar -- aquí se le pide a la propia IA que LEA el
    documento (funciona igual de bien sea cual sea su estructura, porque
    no depende de reconocer un patrón concreto) y devuelva dónde empieza
    cada sección temática.

    No se le pide un número de carácter o página (los modelos son malos
    calculando posiciones exactas) sino que COPIE LITERALMENTE las
    primeras palabras de cada sección -- se localizan buscando ese
    fragmento tal cual en el texto original, mucho más fiable que pedir
    un índice numérico.

    Devuelve una lista de bloques (mismo formato que _bloques_estructurales,
    con tipo="tema") o [] si la llamada falla, el JSON no es válido, o no
    se pudo localizar en el texto ni la mitad de los fragmentos que la IA
    dijo -- en cualquiera de esos casos el llamante (_fragmentos_por_lote)
    cae al reparto por párrafo de siempre, nunca se bloquea ni rompe la
    generación por esto."""
    if not texto_fuente or n_bloques <= 1:
        return []
    generado = call_deepseek_api(
        messages=[{"role": "user", "content": _prompt_esquema_documento(texto_fuente, n_bloques)}],
        temperature=0.0,
        # Respuesta corta (un título + unas palabras por sección, unas
        # pocas decenas de bloques como mucho) -- no hace falta más
        # margen que el que ya usa el resto de llamadas cortas de este
        # archivo.
        max_tokens=min(4000, 300 + 150 * n_bloques),
        response_format_json=True,
        on_usage=on_usage,
        # thinking_enabled=False (por defecto, ver deepseek_utils.py): es
        # una tarea de extracción mecánica (copiar texto tal cual, no
        # verificar precisión legal contra un documento), no la tarea
        # donde razonar aporta algo -- igual que la GENERACIÓN de
        # preguntas, a diferencia de su VERIFICACIÓN (ver
        # _verificar_pregunta).
        # stream=True: mismo motivo que el resto de llamadas de este
        # archivo -- el documento completo puede ser largo, sin streaming
        # una llamada de más de ~30s muere con "Error de conexión".
        stream=True,
    )
    if not generado:
        return []
    try:
        secciones = json.loads(generado)
    except json.JSONDecodeError:
        inicio_json = generado.find("[")
        fin_json = generado.rfind("]") + 1
        if inicio_json == -1 or fin_json <= inicio_json:
            return []
        try:
            secciones = json.loads(generado[inicio_json:fin_json])
        except json.JSONDecodeError:
            return []
    if not isinstance(secciones, list):
        return []

    posiciones = {}
    for seccion in secciones:
        if not isinstance(seccion, dict):
            continue
        inicio_literal = str(seccion.get("inicio_literal", "")).strip()
        if not inicio_literal:
            continue
        posicion = texto_fuente.find(inicio_literal)
        if posicion == -1:
            continue
        titulo = str(seccion.get("titulo", "")).strip() or inicio_literal[:40]
        posiciones[posicion] = titulo

    # Si no se pudo localizar ni la mitad de las secciones pedidas, el
    # esquema no es de fiar (demasiados fragmentos inventados o
    # reescritos por el modelo pese a la instrucción de copiarlos tal
    # cual) -- mejor caer al reparto por párrafo que repartir con cortes
    # a medias.
    if len(posiciones) < max(2, n_bloques // 2):
        return []

    posiciones_ordenadas = sorted(posiciones.items())
    bloques = []
    for indice, (inicio, titulo) in enumerate(posiciones_ordenadas):
        fin = posiciones_ordenadas[indice + 1][0] if indice + 1 < len(posiciones_ordenadas) else len(texto_fuente)
        contenido = texto_fuente[inicio:fin]
        if contenido.strip():
            bloques.append({"etiqueta": titulo, "tipo": "tema", "inicio": inicio, "texto": contenido})
    return bloques


def _fragmentos_por_lote(texto_fuente, n_lotes, on_usage=None):
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

    Reparto por BLOQUE ESTRUCTURAL COMPLETO, en DOS NIVELES (03/08/2026,
    bug real): el reparto anterior, intercalado por párrafo, evitaba que
    un lote se llevara un único tramo temático contiguo, pero un artículo
    largo (con varios párrafos) se ACABABA REPARTIENDO ENTRE VARIOS LOTES
    -- cada uno veía solo un trozo, pero cada uno veía LO BASTANTE del
    mismo artículo (p.ej. el dato más citable, "mayoría absoluta", "quinta
    parte de los miembros"...) como para generar, sin saber unos de otros,
    una pregunta sobre el mismo hecho con una redacción distinta --
    confirmado en producción con 3 preguntas sobre "qué mayoría exige el
    Senado" del art. 167 repartidas entre lotes distintos de un mismo
    test. Ahora un artículo, disposición, título/capítulo sin artículos
    propios, o sección temática (según el nivel, ver abajo) va ENTERO a un
    único lote, repartidos por _repartir_bloques_en_lotes para equilibrar
    caracteres totales -- dos lotes ya no pueden converger en el mismo
    bloque porque ninguno de los dos lo ve si no le tocó a él.

    Nivel 1 -- _bloques_estructurales (regex, gratis, sin llamada a la
    API): busca marcadores de artículo/disposición/título -- funciona bien
    con texto LEGAL en bruto (leyes, reglamentos), pero solo con eso.
    Nivel 2 -- _bloques_por_esquema_ia (una llamada a DeepSeek, ver su
    comentario largo): si el nivel 1 no encuentra suficientes bloques (bug
    real: probado contra un temario narrativo real -- un apunte de
    academia que EXPLICA la Constitución citando los artículos dentro de
    la prosa, "el art. 9 CE señala que...", nunca como encabezado propio
    -- el nivel 1 encontró un único bloque, y ese uno era un falso
    positivo), se le pide a la IA que lea el documento COMPLETO y proponga
    ella misma dónde cortarlo en secciones temáticas -- funciona sea cual
    sea el formato del documento, porque no depende de reconocer un patrón
    de texto fijo. Añade una única llamada corta (sin razonamiento
    profundo) antes de arrancar los lotes, no una por lote -- tiempo fijo
    y pequeño, no crece con el número de lotes ni con num_preguntas.

    Solo si NINGUNO de los dos niveles encuentra suficientes bloques (un
    documento demasiado corto, sin estructura reconocible NI accesible
    por lectura, o si la llamada a la IA del nivel 2 falla) se cae al
    reparto INTERCALADO por párrafo de siempre (02/08/2026, bug real): con
    el reparto contiguo anterior a ese arreglo (el lote 1 se llevaba
    literalmente el primer tramo del documento, el lote 2 el segundo...),
    si esa primera zona trataba un único tema, las primeras preguntas que
    ve el usuario con el arranque temprano (num_preguntas > 5, ver
    generar_preguntas_ia_en_lotes) podían salir TODAS de ese mismo tema --
    ni mejor ni peor que el comportamiento anterior a este cambio.

    Con documentos cortos, un solo lote, sin texto_fuente, o con pocos
    saltos de párrafo reales (menos del doble de n_lotes -- p.ej. texto
    extraído de un PDF en pocas líneas largas, sin dobles saltos), el
    reparto por párrafo dejaría lotes vacíos o casi vacíos: se cae al
    reparto contiguo de siempre (mejor que nada) o, si ni eso compensa
    (documento corto/un solo lote), se devuelve None en cada posición y el
    llamante usa el documento completo tal cual (sin pasar 'fragmento' a
    construir_prompt, para no romper compatibilidad con construir_prompt(n)
    de un solo argumento).

    on_usage: se pasa a la llamada del nivel 2, si hace falta -- sin esto
    el coste de esa llamada se perdería en silencio (ver AcumuladorTokens
    en coste_ia.py), igual que el resto de llamadas de este archivo."""
    if not texto_fuente or n_lotes <= 1 or len(texto_fuente) < n_lotes * 400:
        return [None] * n_lotes

    bloques, prosa_inicial = _bloques_estructurales(texto_fuente)
    if len(bloques) < n_lotes:
        bloques_ia = _bloques_por_esquema_ia(texto_fuente, n_lotes, on_usage)
        if len(bloques_ia) >= n_lotes:
            bloques, prosa_inicial = bloques_ia, ""

    if len(bloques) >= n_lotes:
        lotes_de_bloques = _repartir_bloques_en_lotes(bloques, n_lotes)
        parrafos_prosa = [p for p in prosa_inicial.split("\n\n") if p.strip()]
        fragmentos = []
        for indice, bloques_del_lote in enumerate(lotes_de_bloques):
            partes = list(parrafos_prosa[indice::n_lotes]) if parrafos_prosa else []
            partes.extend(bloque["texto"] for bloque in bloques_del_lote)
            fragmento = "\n\n".join(parte.strip() for parte in partes if parte.strip())
            fragmentos.append(fragmento)
            logger.info(
                "Lote %d: %s - %d caracteres",
                indice + 1,
                ", ".join(bloque["etiqueta"] for bloque in bloques_del_lote),
                len(fragmento),
            )
        if parrafos_prosa:
            logger.info(
                "Prosa suelta repartida por párrafo: %d bloques (portada/intro)",
                len(parrafos_prosa),
            )
        return fragmentos

    parrafos = [p for p in texto_fuente.split("\n\n") if p.strip()]
    if len(parrafos) >= n_lotes * 2:
        return ["\n\n".join(parrafos[i::n_lotes]) for i in range(n_lotes)]

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
        # 4500 (no 3000): en producción se vio un caso real con
        # finish_reason="length" justo en el tope de 3000 -- una única
        # pregunta con explicación detallada de las 4 opciones puede
        # necesitar más de eso puntualmente. Igual que en _verificar_pregunta,
        # subir el margen no cuesta nada si no hace falta.
        max_tokens=4500,
        on_usage=on_usage,
        # stream=True: ver el comentario largo en _verificar_pregunta --
        # mismo arreglo real de producción (este archivo se había quedado
        # sin streaming, provocando "Error de conexión" en llamadas largas).
        stream=True,
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
                               max_intentos=MAX_INTENTOS_POR_PREGUNTA_PDF, forzar_recambio=False):
    """Verifica una pregunta candidata contra el documento de origen y, si
    no supera la verificación, la descarta POR COMPLETO y pide una de
    recambio evitando su tema, hasta max_intentos veces -- mismo principio
    que generador_preguntas_verificado.py aplica al temario oficial.

    validar_pregunta (02/08/2026, bug real): este archivo nunca usaba el
    filtro local determinista que SÍ usan generador_preguntas_verificado.py
    y tarjetas_generator.py -- dependía solo del juicio de la IA
    verificadora para cazar frases como "según el contenido"/"el documento
    indica que..." (prohibidas explícitamente en el prompt de generación y
    en el de verificación, ver _prompt_verificacion), y esa verificación no
    las cazaba siempre: en un test real de 20 preguntas, 3 empezaban con
    "Según/De acuerdo con el contenido del tema..." y varias explicaciones
    decían "el documento indica/señala/establece que...". validar_pregunta
    las descarta de forma determinista (100% de aciertos, no depende de que
    el modelo verificador se acuerde de esta regla concreta entre las
    otras 8 que comprueba a la vez) y ANTES de gastar la llamada de
    verificación -- mismo ahorro que _contiene_frase_prohibida ya da en
    tarjetas_generator.py.

    forzar_recambio (03/08/2026, bug real de dedup entre lotes): si
    pregunta_candidata YA superó su propia verificación de precisión
    (individual, en otro lote) y el único motivo por el que llega aquí es
    ser un duplicado
    de otra pregunta ya aceptada (ver _intentar_aceptar en
    generar_preguntas_ia_en_lotes), no tiene sentido volver a verificarla
    tal cual -- su contenido no ha cambiado, así que pasaría otra vez y
    seguiría siendo el mismo duplicado, sin llegar nunca a pedir una
    pregunta distinta. Con forzar_recambio=True se salta la comprobación
    sobre pregunta_candidata y se pide directamente una de recambio, con el
    resto del presupuesto de intentos igual que si esa primera comprobación
    hubiera fallado."""
    pregunta = pregunta_candidata
    intentos_restantes = max_intentos
    if forzar_recambio:
        intentos_restantes -= 1
        pregunta = _pedir_una_pregunta_de_recambio(construir_prompt, pregunta.get("pregunta", ""), on_usage)
        if not pregunta or intentos_restantes <= 0:
            return None
    while intentos_restantes > 0:
        if validar_pregunta(pregunta) and _verificar_pregunta(pregunta, texto_fuente, on_usage):
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
    Cada candidata se verifica de forma INDIVIDUAL y en paralelo (ver
    _verificar_pregunta más abajo, mismo principio que
    generador_preguntas_verificado.py usa para el temario oficial), así
    que las que pasan van llegando una a una según van terminando, no todas
    de golpe -- progreso-conversador.js ya rellena huecos entre eventos
    reales para que la barra no se note a saltos.

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

    # vistas/preguntas_unicas/lock_dedup (03/08/2026, bug real): antes se
    # deduplicaba en UNA pasada final, después de que TODOS los lotes en
    # paralelo hubieran terminado (ver el bloque que hacía "for p in
    # preguntas: ..." tras el ThreadPoolExecutor de más abajo). El problema
    # es que _reportar_avance_pregunta (y con ella el evento SSE "pregunta"
    # que el frontend muestra de inmediato, ver blueprints/pdf_ia.py) se
    # dispara DENTRO de _pedir_lote_verificado, en cuanto una candidata
    # supera la verificación de SU PROPIO lote -- mucho antes de que la
    # pasada final de dedup tenga ocasión de descartarla. Dos lotes en
    # paralelo pueden generar, cada uno por su cuenta, una pregunta distinta
    # sobre el mismo hecho (no se ven entre sí mientras corren), y las dos se
    # enseñan al usuario antes de que el dedup tardío las detecte -- bug
    # real confirmado con un documento real: 3 preguntas casi idénticas
    # sobre el art. 26.6 (plazo de audiencia pública) de 3 lotes distintos,
    # las 3 mostradas en el test aunque _claves_dedup ya las identificaba
    # correctamente como la misma pregunta. generador_preguntas_verificado.py
    # (Test Personalizado) no tiene este problema porque su dedup
    # (preguntas_ya_aceptadas) se comprueba de forma ATÓMICA en el momento
    # de aceptar, bajo un lock, antes de reportar -- vistas/preguntas_unicas
    # se adelantan aquí (antes solo existían tras el ThreadPoolExecutor de
    # los lotes) para poder hacer exactamente lo mismo: _intentar_aceptar
    # comprueba-y-registra bajo lock_dedup ANTES de que el llamante decida
    # si reportar la pregunta por SSE.
    vistas = set()
    preguntas_unicas = []
    lock_dedup = threading.Lock()

    def _intentar_aceptar(pregunta):
        """Registra 'pregunta' (ya verificada) en preguntas_unicas si no es
        un duplicado de otra ya aceptada por CUALQUIER lote -- comprobación
        e inserción atómicas bajo lock_dedup, para que dos lotes en paralelo
        no puedan aceptar el mismo hecho a la vez. Devuelve True si se
        aceptó (el llamante debe reportarla por SSE) o False si ya había una
        equivalente (el llamante debe tratarla como descartada y, si puede,
        pedir una de recambio -- nunca reportarla).

        _es_duplicado_por_contencion se comprueba bajo el MISMO lock que
        _claves_dedup, no antes por separado: compara contra
        preguntas_unicas, que otro hilo podría estar mutando a la vez si no
        se protegiera aquí dentro."""
        claves = _claves_dedup(pregunta)
        with lock_dedup:
            if not claves or (claves & vistas) or _es_duplicado_por_contencion(pregunta, preguntas_unicas):
                return False
            vistas.update(claves)
            preguntas_unicas.append(pregunta)
        return True

    def _pedir_lote_verificado(n, fragmento=None):
        prompt = construir_prompt(n, fragmento) if fragmento is not None else construir_prompt(n)
        prompt = _prompt_con_exclusion(prompt, preguntas_a_evitar)
        generado = call_deepseek_api(
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=min(8000, 1500 * n),
            on_usage=on_usage,
            # stream=True: ver el comentario largo en _verificar_pregunta --
            # mismo arreglo real de producción (este archivo se había
            # quedado sin streaming, provocando "Error de conexión" en
            # llamadas largas -- más probable aún aquí, generando varias
            # preguntas de golpe con hasta 8000 tokens de margen).
            stream=True,
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
            # tal cual (nunca hay verificación con la que rechazarla), pero
            # SÍ pasa por el dedup atómico -- sin texto_fuente no hay forma
            # de pedir una de recambio (no hay nada contra lo que
            # verificarla), así que una duplicada simplemente no se cuenta
            # como aceptada ni se reporta por SSE.
            aceptadas = []
            for candidata in candidatas:
                if _intentar_aceptar(candidata):
                    aceptadas.append(candidata)
                    _reportar_avance_pregunta(candidata)
            return aceptadas, None

        # validar_pregunta ANTES de verificar (02/08/2026, bug real, mismo
        # motivo que en _asegurar_pregunta_valida): una candidata que ya
        # viola el filtro local determinista (frases como "según el
        # contenido"/"el documento indica que...", siglas sin desarrollar,
        # estructura incompleta) no necesita gastar una llamada de
        # verificación para saber que hace falta regenerarla -- se manda
        # directa al camino de recambio individual, que si acepta la
        # reemplaza por una limpia.
        #
        # 'pendientes' es una lista de (candidata, forzar_recambio):
        # filtro local fallido todavía no sabe si la candidata en sí es
        # válida, así que _asegurar_pregunta_valida la vuelve a intentar tal
        # cual antes de pedir recambio (forzar_recambio=False). Una
        # candidata que YA pasó su propia verificación individual (ver más
        # abajo) y falla después -- por no superarla, o por resultar
        # duplicada de otro lote -- va con forzar_recambio=True: repetir la
        # MISMA verificación que ya se hizo, o la MISMA candidata que ya se
        # sabe duplicada, no cambiaría el resultado.
        candidatas_ok_local = []
        pendientes = []
        for candidata in candidatas:
            if validar_pregunta(candidata):
                candidatas_ok_local.append(candidata)
            else:
                pendientes.append((candidata, False))

        # Verificación INDIVIDUAL en paralelo, una llamada por candidata --
        # NO en bloque (03/08/2026, bug real de producción, mismo principio
        # que generador_preguntas_verificado.py ya usa para el temario
        # oficial). La verificación en bloque anterior (_verificar_lote,
        # retirada) juzgaba las hasta 5 candidatas de un lote en UNA sola
        # llamada para ahorrar llamadas totales, pero con
        # thinking_enabled=True (necesario para no perder precisión, ver
        # _verificar_pregunta) el razonamiento interno del modelo escala
        # con cuántas candidatas hay que juzgar A LA VEZ, no con el número
        # de llamadas -- en producción, un lote de 5 agotó los 8000 tokens
        # SOLO PENSANDO, sin llegar a escribir el veredicto, obligando a un
        # reintento de 126s para una sola llamada. Verificando cada
        # candidata por separado, cada llamada solo tiene que razonar sobre
        # UNA pregunta -- mismo margen de 8000 tokens, mucho más difícil de
        # agotar -- y el dedup atómico (_intentar_aceptar) puede actuar en
        # cuanto CADA candidata individual termina, en vez de esperar a que
        # el lote entero de 5 resuelva su veredicto conjunto.
        # texto_fuente_lote: el FRAGMENTO de este lote si lo hay, no el
        # documento completo -- optimización de tiempo (03/08/2026, bug
        # real, documento real): la verificación individual de arriba
        # pasaba SIEMPRE texto_fuente (el documento COMPLETO, hasta
        # 300000+ caracteres en documentos grandes) a cada llamada de
        # verificación, aunque la candidata se hubiera generado
        # ÚNICAMENTE a partir de 'fragmento' -- el propio prompt de
        # generación se lo exige explícitamente ("Basa tus preguntas
        # ÚNICAMENTE en lo que aparece en este fragmento", ver
        # blueprints/pdf_ia.py). Verificar contra el documento entero
        # cuando basta con el fragmento multiplicaba sin necesidad el
        # contexto que el verificador (con thinking_enabled=True) tiene
        # que leer y razonar en cada llamada -- la causa más probable de
        # varias llamadas de más de 60s y un caso real de finish_reason
        # truncado (8000 tokens SOLO razonando) vistos en producción con
        # documentos de más de 300000 caracteres. Verificar contra el
        # fragmento es igual de riguroso (es la MISMA porción de texto de
        # la que la candidata debía salir) y mucho más rápido. Cuando no
        # hay fragmento (documento corto, sin fragmentar) se sigue usando
        # texto_fuente completo, como antes.
        texto_fuente_lote = fragmento if fragmento is not None else texto_fuente

        aceptadas = []
        if candidatas_ok_local:
            with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS_VERIFICACION_LOTE, len(candidatas_ok_local))) as executor:
                futuros = {
                    executor.submit(_verificar_pregunta, candidata, texto_fuente_lote, on_usage): candidata
                    for candidata in candidatas_ok_local
                }
                for futuro in as_completed(futuros):
                    candidata = futuros[futuro]
                    if not futuro.result():
                        pendientes.append((candidata, True))
                    elif _intentar_aceptar(candidata):
                        aceptadas.append(candidata)
                        _reportar_avance_pregunta(candidata)
                    else:
                        # Superó la verificación pero es un duplicado (mismo
                        # artículo + mismas cifras, o mismo texto) de una
                        # pregunta ya aceptada por OTRO lote en paralelo --
                        # ver el comentario largo junto a
                        # vistas/preguntas_unicas más arriba. Se manda a
                        # recambio en vez de descartarse sin más, para no
                        # perder el hueco.
                        pendientes.append((candidata, True))

        if pendientes:
            with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS_VERIFICACION_LOTE, len(pendientes))) as executor:
                futuros = [
                    executor.submit(_asegurar_pregunta_valida, candidata, construir_prompt, texto_fuente, on_usage,
                                     forzar_recambio=forzar)
                    for candidata, forzar in pendientes
                ]
                for futuro in as_completed(futuros):
                    resultado = futuro.result()
                    if resultado and _intentar_aceptar(resultado):
                        aceptadas.append(resultado)
                        _reportar_avance_pregunta(resultado)
                    else:
                        # Sin resultado (recambio agotó sus intentos) o
                        # resultado duplicado de otra ya aceptada mientras
                        # tanto: no se reporta como pregunta (no hay
                        # "pregunta" en el evento), pero SÍ cuenta como un
                        # hueco de progreso ya resuelto -- el relleno final
                        # (ver más abajo) se encarga de cubrir lo que falte.
                        _reportar_avance_pregunta(None)

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

    fragmentos = _fragmentos_por_lote(texto_fuente, len(lotes), on_usage)

    errores = []
    # max_workers=8 (no 15, como generador_preguntas_verificado.py): cada
    # lote de aquí dispara además hasta _MAX_WORKERS_VERIFICACION_LOTE
    # verificaciones propias en paralelo, así que 8 lotes a la vez ya
    # supone picos de hasta 48 llamadas simultáneas a DeepSeek -- subir
    # más sin evidencia de que la API lo soporta bien sería imprudente.
    # Sirve sobre todo para peticiones grandes (30-100 preguntas, varios
    # lotes): con num_preguntas pequeño ya cabían todos los lotes en una
    # sola tanda incluso con el límite anterior de 5.
    #
    # preguntas_unicas/vistas YA se rellenan dentro de _pedir_lote_verificado
    # (vía _intentar_aceptar, bajo lock_dedup) según cada lote va aceptando
    # candidatas -- no hace falta (ni sería correcto: ver el comentario
    # largo junto a _intentar_aceptar) una segunda pasada de dedup aquí
    # después de que todos los lotes terminen; el valor de retorno de
    # _pedir_lote_verificado solo se usa aquí para saber si hubo error.
    with ThreadPoolExecutor(max_workers=min(8, len(lotes))) as executor:
        futuros = [
            executor.submit(_pedir_lote_verificado, n, fragmentos[i])
            for i, n in enumerate(lotes)
        ]
        for futuro in as_completed(futuros):
            _, error = futuro.result()
            if error:
                errores.append(error)

    # Nunca se acepta más preguntas de las pedidas: un lote puede ignorar el
    # "EXACTAMENTE n" del prompt y devolver más candidatas de las
    # solicitadas -- bug real: pedir 20 preguntas y recibir 22, porque
    # ninguna comprobación recortaba el exceso antes de esto. Se recorta
    # aquí (tras deduplicar, no lote a lote) porque el exceso puede venir de
    # la SUMA de varios lotes, no necesariamente de uno solo que se pasara.
    if len(preguntas_unicas) > num_preguntas:
        preguntas_unicas = preguntas_unicas[:num_preguntas]

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
    # _MAX_RONDAS_RELLENO=2 (03/08/2026): antes, un hueco de relleno que
    # fallaba (verificación agotada, o duplicado de otro hueco que terminó
    # a la vez) se daba por perdido sin más -- un único intento por hueco,
    # pese a que cada intento YA lleva su propio presupuesto completo de
    # reintentos (ver _rellenar_un_hueco/_asegurar_pregunta_valida). El
    # dedup por artículo+cifras/mayoría/parte-fracción de más arriba ahora
    # detecta bastantes más duplicados reales que antes -- correcto, pero
    # también significa que el relleno se invoca más a menudo (un
    # duplicado detectado a tiempo dentro de un lote se manda a recambio
    # ahí mismo, pero uno que dos huecos de relleno aceptan A LA VEZ solo
    # se resuelve dejando UNO y perdiendo el otro). Una segunda ronda,
    # dirigida solo a los huecos que sigan faltando tras la primera, no
    # cuesta nada si no hace falta (si faltan=0 el bucle ni se ejecuta) y
    # evita que una colisión puntual entre dos huecos en paralelo se
    # traduzca directamente en "pedí 20, recibí 18".
    #
    # Subido de 2 a 3 (03/08/2026, decisión explícita del usuario, documento
    # real): con el dedup ya bastante más estricto tras varias rondas de
    # correcciones esta misma sesión (solapamiento de palabras, contención
    # de cifras...), un documento centrado en pocos artículos con un
    # conjunto de hechos citables limitado (aquí, arts. 166-169 y 9.3 de la
    # Constitución Española) puede agotar sus hechos distintos antes de
    # llegar a las N preguntas pedidas -- 2 rondas dejaron un test en 17/20
    # sin ningún duplicado real entre las 17 (el dedup funcionaba bien, solo
    # faltaba presupuesto de intentos). El usuario, informado del cambio de
    # tiempo que esto puede suponer en esos casos límite (una ronda más
    # solo se ejecuta si aún faltan preguntas), prefirió priorizar llegar a
    # las N pedidas sobre ahorrar esos segundos.
    # construir_prompt_evitando_repetidas y _rellenar_un_hueco se definen
    # UNA vez aquí fuera (antes solo existían dentro del "for" de rondas)
    # para poder reutilizarlas también en la pasada final de deduplicación
    # semántica de más abajo, que necesita el mismo mecanismo de "rellenar
    # un hueco concreto" pero fuera de esas rondas.
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
        # del test). Se lee bajo lock_dedup (el mismo lock que protege
        # las inserciones vía _intentar_aceptar) para que la foto de
        # "cubiertas" esté sincronizada con lo que de verdad hay
        # aceptado en cada momento, no con un lock distinto que ya no
        # protege las escrituras.
        with lock_dedup:
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
        # _intentar_aceptar (mismo helper que usan los lotes, ver más
        # arriba): comprueba-y-registra en 'vistas'/'preguntas_unicas'
        # bajo el mismo lock_dedup, así un hueco de relleno tampoco
        # puede aceptar por duplicado un hecho que otro hueco (u otro
        # lote que aún estuviera terminando) ya hubiera cubierto.
        aceptada = pregunta if pregunta and _intentar_aceptar(pregunta) else None
        # Solo se incluye en el evento si de verdad se aceptó (no si
        # era un duplicado que se descarta) -- el "pregunta" del
        # evento SSE representa una pregunta genuinamente nueva del
        # test final, no un intento cualquiera.
        _reportar_avance_pregunta(aceptada)

    def _rellenar_huecos(cantidad):
        if cantidad <= 0:
            return
        with ThreadPoolExecutor(max_workers=min(10, cantidad)) as executor:
            list(executor.map(_rellenar_un_hueco, range(cantidad)))

    _MAX_RONDAS_RELLENO = 3
    for _ronda_relleno in range(_MAX_RONDAS_RELLENO):
        faltan = num_preguntas - len(preguntas_unicas)
        if faltan <= 0:
            break
        _rellenar_huecos(faltan)

    # Pasada final de deduplicación SEMÁNTICA (03/08/2026, decisión
    # explícita del usuario tras varias rondas de bugs reales de
    # duplicados en esta misma sesión, cada uno una reformulación
    # distinta que ninguna heurística anterior cubría todavía -- ver el
    # comentario largo en _detectar_duplicados_finales). Una única
    # llamada extra, al final, sin el documento de origen (compara solo
    # los enunciados y respuestas ya cortos de la lista final entre sí),
    # así que no escala con el tamaño del documento ni con el número de
    # lotes -- se paga UNA vez por test, no una vez por candidata. Si
    # encuentra duplicados los quita y rellena el hueco resultante con
    # el MISMO mecanismo de arriba, pero solo UNA pasada más (no otras
    # _MAX_RONDAS_RELLENO completas): esto es una red de seguridad para
    # lo que las heurísticas deterministas no cazaron, no se espera que
    # dispare a menudo.
    if texto_fuente is not None and len(preguntas_unicas) > 1:
        indices_duplicados = _detectar_duplicados_finales(preguntas_unicas, on_usage)
        for indice in sorted(indices_duplicados, reverse=True):
            preguntas_unicas.pop(indice)
        if indices_duplicados:
            faltan = num_preguntas - len(preguntas_unicas)
            _rellenar_huecos(faltan)

    faltan_final = num_preguntas - len(preguntas_unicas)
    if faltan_final > 0:
        errores.append(f"No se pudieron generar {faltan_final} pregunta(s) adicionales tras varios intentos de relleno")

    return preguntas_unicas, errores


# Tope del "banco" de preguntas de un documento (03/08/2026, decisión
# explícita del usuario): en vez de pedir un número fijo de una vez (100
# preguntas fijas, sin importar de qué dé el documento), se genera en
# RONDAS sucesivas hasta agotar el contenido distinto del documento -- 100
# es solo el TECHO de seguridad, nunca el objetivo a forzar. Ver el
# comentario largo de generar_banco_preguntas_adaptativo.
TOPE_BANCO_PREGUNTAS = 100
_TAMANO_RONDA_BANCO = 20
# Si una ronda rinde menos de este porcentaje de lo pedido en preguntas
# NUEVAS (no duplicadas de rondas anteriores), se considera que el
# documento ya no da más contenido distinto y se para -- seguir insistiendo
# solo generaría relleno de peor calidad para forzar una cuota arbitraria
# (el mismo riesgo que ya vimos con num_preguntas fijo alto en documentos
# de contenido limitado: más relleno, más gasto, y en el peor caso
# preguntas de menor calidad para completar la cuota).
_UMBRAL_RENDIMIENTO_MINIMO_BANCO = 0.25


def generar_banco_preguntas_adaptativo(construir_prompt, texto_fuente, tope=TOPE_BANCO_PREGUNTAS,
                                        tamano_ronda=_TAMANO_RONDA_BANCO, on_usage=None, on_progreso=None,
                                        preguntas_a_evitar=None):
    """Genera el máximo de preguntas distintas que el documento realmente dé
    de sí, en rondas sucesivas de generar_preguntas_ia_en_lotes, hasta:
    (a) llegar a 'tope' (techo de seguridad, nunca objetivo forzado),
    (b) que una ronda entera rinda por debajo de
        _UMBRAL_RENDIMIENTO_MINIMO_BANCO en preguntas NUEVAS (señal de que
        el documento ya no tiene más contenido distinto que dar), o
    (c) agotar un número máximo de rondas (cinturón de seguridad para no
        disparar el gasto en un documento raro que rinda poco ronda tras
        ronda sin llegar nunca a 0).

    Cada ronda pide preguntas_a_evitar (acumulado de rondas anteriores,
    igual que ya se usa para evitar repetir tests ANTERIORES del mismo
    documento) -- sin esto, cada ronda fragmentaría el MISMO documento de
    la MISMA forma y regeneraría preguntas muy parecidas a las ya
    aceptadas, con un rendimiento decreciente artificial que pararía la
    generación demasiado pronto.

    generar_preguntas_ia_en_lotes ya deduplica DENTRO de cada ronda (claves
    léxicas + pasada semántica final), pero esa deduplicación es local a
    la llamada -- cada ronda crea su propio 'vistas'/'preguntas_unicas' sin
    memoria de rondas anteriores. Aquí se añade una comprobación adicional
    CRUZANDO rondas con las mismas funciones deterministas
    (_claves_dedup/_es_duplicado_por_contencion) contra todo lo ya
    acumulado, antes de aceptar cada pregunta de una ronda nueva.

    on_progreso(evento), si se pasa, se llama con {"completadas": N,
    "objetivo": tope, "pregunta": p} por cada pregunta NUEVA aceptada
    (después del dedup entre rondas) -- no se reenvían los eventos brutos
    de cada ronda individual, que incluirían candidatas luego descartadas
    por duplicar una ronda anterior.

    Devuelve la lista de preguntas aceptadas."""
    acumuladas = []
    claves_acumuladas = set()
    evitar_acumulado = list(preguntas_a_evitar or [])
    max_rondas = max(3, (tope // tamano_ronda) + 2)
    ronda = 0
    while len(acumuladas) < tope and ronda < max_rondas:
        objetivo_ronda = min(tamano_ronda, tope - len(acumuladas))
        preguntas_ronda, _errores_ronda = generar_preguntas_ia_en_lotes(
            construir_prompt, objetivo_ronda, texto_fuente,
            on_usage=on_usage, preguntas_a_evitar=evitar_acumulado,
        )
        ronda += 1
        nuevas = []
        for pregunta in preguntas_ronda:
            # Un lote puede ignorar el "EXACTAMENTE N" pedido y devolver de
            # más (mismo bug ya visto y arreglado en
            # generar_preguntas_ia_en_lotes) -- aquí se corta al llegar al
            # tope para no aceptar más de la cuenta.
            if len(acumuladas) >= tope:
                break
            claves = _claves_dedup(pregunta)
            if not claves or (claves & claves_acumuladas) or _es_duplicado_por_contencion(pregunta, acumuladas):
                continue
            claves_acumuladas.update(claves)
            acumuladas.append(pregunta)
            nuevas.append(pregunta)
            if on_progreso:
                on_progreso({"completadas": len(acumuladas), "objetivo": tope, "pregunta": pregunta})
        evitar_acumulado.extend(
            f"{p.get('pregunta', '')} (respuesta: "
            f"{(p.get('opciones') or {}).get(str(p.get('respuesta_correcta', '')).upper(), '')})"
            for p in nuevas
        )
        if not nuevas or len(nuevas) / objetivo_ronda < _UMBRAL_RENDIMIENTO_MINIMO_BANCO:
            break
    return acumuladas
