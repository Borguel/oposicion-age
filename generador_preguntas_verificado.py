"""Generador de preguntas de Test Personalizado con arquitectura generar ->
verificar -> reintentar, pensado para minimizar alucinaciones jurídicas.

Sustituye al generador anterior (generar_test_avanzado en test_generator.py,
ya retirado): aquí,

  1. La norma/tema/artículo NUNCA los "decide" el modelo: se eligen en
     Python a partir de contenido REAL ya cargado en Firestore
     (obtener_subbloques_individuales), extrayendo el artículo exacto del
     texto verbatim con una regex -- lo único que decide la IA es cómo
     redactar la pregunta a partir de ESE fragmento y qué tipo de pregunta
     construir (memoria literal, comprensión, aplicación práctica, trampa,
     distinción entre artículos similares).
  2. Cada pregunta se genera con una llamada, y se verifica con una SEGUNDA
     llamada independiente (no reutiliza el razonamiento de la primera),
     que recibe el mismo texto legal real y comprueba la pregunta contra
     él, no contra sí misma.
  3. Si la verificación falla, la pregunta se descarta POR COMPLETO (nunca
     se corrige/parchea) y se reintenta desde cero -- nueva elección de
     artículo, nuevo tipo de pregunta, nueva generación, nueva
     verificación -- hasta MAX_INTENTOS_POR_PREGUNTA veces. Si se agotan,
     ese hueco NO se da por perdido todavía: se le da una oportunidad más
     en otro tema con contenido disponible (ver el relleno al final de
     generar_test_verificado) -- con temario de sobra, que a un hueco
     concreto le toque mala suerte con sus intentos no debería traducirse
     en menos preguntas de las pedidas. Solo si también esa oportunidad
     falla se pierde de verdad (se avisa al final).
"""
import itertools
import json
import logging
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from deepseek_utils import call_deepseek_api
from utils import (
    obtener_subbloques_individuales, repartir_cupos_por_tema,
    repartir_cupos_por_tema_realista, calcular_pesos_reales_por_bloque,
    barajar_opciones_pregunta, limpiar_cache_preguntas_banco_ia,
)
from validador_preguntas import validar_pregunta
from oposiciones import OPOSICIONES, OPOSICION_POR_DEFECTO
from banco_preguntas_ia import guardar_pregunta_generada
from errores_generacion import registrar_error_generacion

logger = logging.getLogger(__name__)

# Bajado de 4 a 2 (02/08/2026, con datos reales de producción): los huecos
# corren en PARALELO, así que el tiempo total del test lo marca el más
# LENTO de todos -- un único hueco atascado en un tema/ancla propenso a
# repetición podía encadenar 4 intentos exteriores, cada uno con su propio
# reintento interno de truncamiento (ver _REINTENTOS_TRUNCAMIENTO en
# deepseek_utils.py), y llevarse más de 4 minutos ÉL SOLO mientras los
# otros 9 huecos ya llevaban rato terminados -- ese caso real (test de 10
# preguntas, ~4:20 total) es justo lo que se vio en producción. Bajar esto
# a 2 corta el tope de tiempo que un hueco puede monopolizar en la mitad,
# y es seguro hacerlo AHORA porque el relleno final (ver
# MAX_RONDAS_RELLENO más abajo) ya no es una única pasada sino un bucle
# que sigue intentando hasta completar el número pedido -- un hueco que
# se rinde antes no significa menos preguntas, solo que ese hueco concreto
# cede el turno antes a una ancla/tipo de pregunta distinto (en el propio
# tema o, en el relleno, en otro) que tiene más probabilidad real de
# terminar limpio que seguir insistiendo en la misma combinación
# problemática.
MAX_INTENTOS_POR_PREGUNTA = 2

# Tope de RONDAS de relleno (ver el final de generar_test_verificado): una
# única pasada de relleno dejaba el test corto de verdad en producción
# (02/08/2026: pedir 10 devolvía 8, pedir 20 devolvía 18) cuando algún
# hueco de relleno tenía a su vez mala suerte -- exactamente el mismo
# riesgo que ya se acepta para el primer hueco, solo que sin una segunda
# oportunidad. Repetir el relleno hasta completar el número pedido (o
# agotar las rondas) es la única forma de sostener "nunca menos preguntas
# de las pedidas" frente a mala suerte repetida, no solo puntual. Acotado
# (no un bucle infinito) porque un tema realmente sin más contenido
# disponible no va a "tener suerte" a la ronda 10 -- si tras
# MAX_RONDAS_RELLENO rondas sigue faltando, es que de verdad no hay más
# que ofrecer, y toca avisar en vez de reintentar para siempre.
MAX_RONDAS_RELLENO = 3

# Cuántas preguntas se piden en UNA sola llamada de GENERACIÓN (02/08/2026,
# con datos reales de producción): antes cada pregunta era su propia
# llamada de generación + su propia llamada de verificación (2 llamadas por
# hueco) -- con solo _MAX_LLAMADAS_SIMULTANEAS_DEEPSEEK=8 huecos de
# conexión reales (ver deepseek_utils.py), un test de 10 preguntas (~20
# llamadas, más reintentos) tardaba hasta 4-5 minutos, casi todo esperando
# turno en la cola del semáforo. Agrupar la GENERACIÓN (nunca la
# verificación, que sigue siendo una llamada independiente por pregunta
# contra SU PROPIO texto legal -- eso es lo que da la garantía de
# precisión jurídica y no se toca) en lotes de 4 reduce las llamadas de
# generación a una cuarta parte sin perder diversidad de temario: cada
# hueco del lote sigue viniendo de un tema DISTINTO (el reparto ya evita
# repetir tema mientras haya temas de sobra) y ancla a SU PROPIO texto
# legal, nunca mezclado con los demás del lote (regla explícita en
# _prompt_generacion_lote_normativo, y "pregunta_num" en la respuesta para
# emparejar cada pregunta con su texto sin ambigüedad -- ver
# _generar_candidatos_lote).
#
# Solo se agrupan huecos de temas NORMATIVOS (con artículo real, ver
# _tema_es_normativo): los descriptivos (ofimática/informática) siguen
# yendo uno a uno por _generar_pregunta_verificada, para no mezclar dos
# formatos de contenido distintos en el mismo prompt de lote. El tipo
# "distincion_articulos" (necesita 2 textos por pregunta) tampoco se
# agrupa, por el mismo motivo de simplicidad -- sigue disponible por la
# vía individual (y por el relleno, que también va uno a uno: es la vía
# fiable de respaldo, no tiene que ser la rápida).
TAMANO_LOTE_GENERACION = 4

# Subido de 6 a 10 (25/07/2026) y a 15 (26/07/2026): deepseek-v4-flash es
# barato por token, así que más llamadas en paralelo reduce el tiempo total
# de generación sin encarecerla apenas -- el cuello de botella es la
# LATENCIA de cada llamada (ver el log "DeepSeek respondió en Xs" en
# deepseek_utils.py, media de ~12.5s con 10 hilos), no el coste. Subida
# incremental (no un salto grande) para poder comparar esa misma media
# antes/después: si se mantiene parecida, DeepSeek todavía tiene margen y
# se puede seguir subiendo; si empieza a subir (o aparecen errores de
# conexión/429), es que ya se está saturando su capacidad por cuenta y
# subir más empeora las cosas en vez de ayudar.
_MAX_WORKERS = 15

# REVERTIDO a deepseek-v4-flash (25/07/2026): se probó deepseek-v4-pro
# (razonamiento) porque flash descartaba el 74% de las preguntas candidatas
# por no seguir las reglas estrictas de este módulo -- pero en producción
# deepseek-v4-pro dio fallos de conexión reales y persistentes
# ("Error de conexión: no se pudo conectar a DeepSeek API" repetido durante
# minutos, incluso en un intento limpio tras esperar), probablemente por ser
# un modelo recién lanzado bajo mucha demanda tras la migración forzosa del
# 24/07/2026. Un fallo de conexión deja el test sin NINGUNA pregunta, peor
# que el descarte alto de flash (que al menos entrega algunas) -- se
# vuelve a flash mientras se decide una solución de fondo (más reintentos,
# otro proveedor de IA, etc.).
_MODELO = "deepseek-v4-flash"

# Mismo patrón que cargar_temario_boe.py usa al trocear el temario en
# subbloques -- nunca corta un artículo a mitad -- para poder recuperar en
# tiempo de lectura el texto exacto de UN artículo dentro de un subbloque
# (que puede agrupar varios artículos consecutivos de la misma norma).
_PATRON_ARTICULO = re.compile(r"Art[íi]culo\s+(\d+)\s*(?:bis|ter)?\.")

_DESCRIPCION_TIPO_PREGUNTA = {
    "memoria_literal": (
        "Pregunta de memoria literal: exige recordar con precisión un dato concreto del artículo "
        "(un plazo, una cifra, un porcentaje, el nombre exacto de un órgano...)."
    ),
    "comprension": (
        "Pregunta de comprensión: exige entender el sentido de la norma, no solo memorizar un dato suelto."
    ),
    "aplicacion_practica": (
        "Pregunta de aplicación práctica: plantea un supuesto concreto y pregunta qué dice la norma "
        "para ese caso."
    ),
    "pregunta_trampa": (
        "Pregunta trampa típica de examen oficial: los distractores deben ser muy parecidos a la "
        "respuesta correcta, cambiando un único dato (un plazo, un sujeto, un órgano) para poner a "
        "prueba la atención al detalle."
    ),
    "distincion_articulos": (
        "Pregunta que distingue entre dos artículos similares o relacionados: la respuesta correcta y "
        "al menos un distractor deben basarse en el matiz que diferencia ambos artículos."
    ),
}

# Variante para temario NO normativo (informática, ofimática, temas técnicos o
# descriptivos): el mismo repertorio de tipos de pregunta, pero descrito sin
# lenguaje jurídico -- si no, el generador y el verificador exigen artículos,
# plazos y "lenguaje de la norma" que no existen en este contenido, y acaban
# descartando la mayoría de preguntas válidas.
_DESCRIPCION_TIPO_PREGUNTA_DESCRIPTIVO = {
    "memoria_literal": (
        "Pregunta de memoria literal: exige recordar con precisión un dato concreto del contenido "
        "(un nombre, una función, un atajo de teclado, un valor, una característica...)."
    ),
    "comprension": (
        "Pregunta de comprensión: exige entender cómo funciona o para qué sirve algo, no solo "
        "memorizar un dato suelto."
    ),
    "aplicacion_practica": (
        "Pregunta de aplicación práctica: plantea una situación concreta y pregunta qué haría o qué "
        "ocurre según el contenido."
    ),
    "pregunta_trampa": (
        "Pregunta trampa típica de examen: los distractores deben ser muy parecidos a la respuesta "
        "correcta, cambiando un único dato (un nombre, un valor, una función) para poner a prueba la "
        "atención al detalle."
    ),
    "distincion_articulos": (
        "Pregunta que distingue entre dos conceptos o apartados relacionados: la respuesta correcta y "
        "al menos un distractor deben basarse en el matiz que los diferencia."
    ),
}


def _es_normativo(anclas):
    """True si el contenido base es normativo (se detectó al menos un
    'Artículo N.'). En ese caso se usan los prompts jurídicos; si no (temas
    descriptivos como ofimática), los prompts descriptivos."""
    return any(ancla.get("articulo") for ancla in anclas)


def _tema_es_normativo(subbloques_tema):
    """Mismo criterio que _es_normativo, pero sobre los subbloques CRUDOS de
    un tema (antes de elegir ancla) -- para decidir si sus huecos pueden
    agruparse en un lote de generación (ver TAMANO_LOTE_GENERACION, solo
    temas normativos) o deben ir por la vía individual."""
    return any(_PATRON_ARTICULO.search(sub["texto"]) for sub in subbloques_tema)


def _extraer_articulos(texto):
    """Trocea el texto verbatim de un subbloque en fragmentos por artículo
    real. Si no se detecta ningún "Artículo N." (algunas normas cortas no
    los numeran así), degrada devolviendo el texto completo como único
    fragmento sin número de artículo -- nunca falla."""
    coincidencias = list(_PATRON_ARTICULO.finditer(texto))
    if not coincidencias:
        return [{"articulo": None, "texto": texto.strip()}]

    fragmentos = []
    for idx, m in enumerate(coincidencias):
        inicio = m.start()
        fin = coincidencias[idx + 1].start() if idx + 1 < len(coincidencias) else len(texto)
        fragmentos.append({"articulo": f"Artículo {m.group(1)}", "texto": texto[inicio:fin].strip()})
    return fragmentos


def _elegir_tipo_pregunta():
    return random.choice(list(_DESCRIPCION_TIPO_PREGUNTA.keys()))


def _elegir_ancla_legal(subbloques_tema, subbloques_ya_usados, necesita_dos):
    """Elige 1 (o 2, para 'distincion_articulos') fragmento(s) de artículo
    real sobre los que construir la pregunta, a partir de subbloques YA
    cargados en Firestore -- nunca inventados. subbloques_ya_usados es un
    snapshot (no se muta aquí) de etiquetas de subbloque ya usadas en este
    test, para variar el contenido en vez de repetir siempre el mismo."""
    if not subbloques_tema:
        return None

    disponibles = [s for s in subbloques_tema if s["etiqueta"] not in subbloques_ya_usados]
    if not disponibles:
        disponibles = list(subbloques_tema)  # copia -- nunca mutar la lista compartida
    random.shuffle(disponibles)

    anclas = []
    for sub in disponibles:
        articulos = _extraer_articulos(sub["texto"])
        random.shuffle(articulos)
        for art in articulos:
            anclas.append({
                "norma": sub["titulo"],
                "articulo": art["articulo"],
                "texto_legal": art["texto"],
                "etiqueta_subbloque": sub["etiqueta"],
            })
        if len(anclas) >= (2 if necesita_dos else 1):
            break

    if not anclas:
        return None
    if necesita_dos:
        if len(anclas) < 2:
            return [anclas[0]]  # no había dos artículos distintos -- degrada a uno solo
        return random.sample(anclas, 2)
    return [anclas[0]]


def _bloques_texto_legal(anclas):
    partes = []
    for i, ancla in enumerate(anclas, start=1):
        etiqueta_articulo = ancla["articulo"] or "(norma sin numeración de artículo)"
        partes.append(f"TEXTO LEGAL {i} -- {ancla['norma']}, {etiqueta_articulo}:\n{ancla['texto_legal']}")
    return "\n\n".join(partes)


def _bloques_contenido(anclas):
    partes = []
    for i, ancla in enumerate(anclas, start=1):
        partes.append(f"CONTENIDO {i} -- {ancla['norma']}:\n{ancla['texto_legal']}")
    return "\n\n".join(partes)


def _prompt_generacion(anclas, tipo_pregunta, oposicion):
    """Elige el prompt de generación según el tipo de contenido: jurídico si
    el tema es normativo (tiene artículos), descriptivo en caso contrario."""
    if _es_normativo(anclas):
        return _prompt_generacion_normativo(anclas, tipo_pregunta, oposicion)
    return _prompt_generacion_descriptivo(anclas, tipo_pregunta, oposicion)


def _prompt_generacion_normativo(anclas, tipo_pregunta, oposicion):
    nombre_oposicion = OPOSICIONES.get(oposicion, OPOSICIONES[OPOSICION_POR_DEFECTO])["nombre"]
    descripcion_tipo = _DESCRIPCION_TIPO_PREGUNTA[tipo_pregunta]
    contenido = _bloques_texto_legal(anclas)

    system = (
        f"Eres un generador profesional de preguntas tipo test para la oposición al {nombre_oposicion}, "
        "con el nivel de exigencia de las mejores academias de preparación (MAD, Adams, CEF). La "
        "precisión jurídica es la prioridad ABSOLUTA, por encima de cualquier otra consideración.\n\n"
        "REGLAS INQUEBRANTABLES:\n"
        "1. La pregunta, las 4 opciones y la explicación deben basarse EXCLUSIVAMENTE en el texto legal "
        "de más abajo. No completes huecos con conocimiento propio ni añadas matices que no estén en "
        "ese texto.\n"
        "2. Cualquier plazo, edad, mayoría, porcentaje, órgano, competencia, cuantía, requisito o fecha "
        "que menciones debe copiarse EXACTAMENTE del texto legal -- nunca aproximarlo ni simplificarlo.\n"
        "3. Debe existir una única respuesta correcta, completa y verificable en el texto. Las otras "
        "tres deben parecer reales, con dificultad de examen oficial, cada una con un único error "
        "jurídico claro (un dato cambiado, un plazo distinto, un órgano equivocado) -- nunca absurdas, "
        "nunca mezclando una afirmación verdadera con una falsa. Ninguna puede defenderse como "
        "parcialmente correcta.\n"
        "4. La explicación debe repasar TODAS las opciones, una por línea y en orden, con este formato "
        "exacto: \"A) es correcta/incorrecta porque... B) es correcta/incorrecta porque... C) ... D) "
        "...\", citando el artículo en la línea de la respuesta correcta, usando la terminología oficial "
        "de la norma (no sinónimos) y limitándose al contenido normativo: nunca inventar doctrina ni "
        "interpretar la ley. Cada línea debe ser UNA sola frase breve (máximo 25-30 palabras) que vaya "
        "directa al motivo -- nunca repitas el enunciado de la pregunta ni el texto de las demás "
        "opciones, ni añadas relleno o contexto que no aporte nada nuevo.\n"
        "5. Si la pregunta o la explicación citan un número de artículo (\"el artículo 52.1\", \"según "
        "el art. 24\"...), esa misma frase debe decir TAMBIÉN el nombre de la norma a la que pertenece, "
        "copiado tal cual aparece en TEXTO LEGAL más abajo (p. ej. \"el artículo 52.1 de la Ley 29/1998, "
        "reguladora de la Jurisdicción Contencioso-Administrativa\", o \"el artículo 24 de la "
        "Constitución Española\") -- un artículo mencionado sin decir de qué norma es deja a quien "
        "estudia sin poder ubicarlo ni repasarlo, y no es válido.\n"
        "6. Nunca abrevies el nombre de la norma con siglas (CE, TREBEP, LPAC, LRJSP, LOTC, LOPJ, LGP, "
        "LJCA...) ni con \"art.\" en vez de \"artículo\" -- los exámenes oficiales de esta oposición "
        "escriben el nombre completo cada vez que citan una norma, nunca una sigla. Escribe siempre el "
        "nombre entero tal como aparece en TEXTO LEGAL (p. ej. \"Constitución Española\", nunca \"CE\"; "
        "\"Ley 39/2015, del Procedimiento Administrativo Común de las Administraciones Públicas\", nunca "
        "\"LPAC\"). Esto incluye también el tipo de norma delante del número: nunca \"LO 3/2007\" ni "
        "\"RD 203/2021\", sino \"Ley Orgánica 3/2007, de 22 de marzo, para la igualdad efectiva de "
        "mujeres y hombres\" o \"Real Decreto 203/2021\" enteros, tal como aparecen en TEXTO LEGAL.\n"
        f"7. Tipo de pregunta a construir: {descripcion_tipo}\n\n"
        "Antes de responder, comprueba internamente: ¿existe una única respuesta correcta? ¿podría "
        "defenderse otra opción como correcta? ¿todos los datos coinciden EXACTAMENTE con el texto "
        "legal? Si tienes cualquier duda, ajusta la pregunta antes de responder.\n\n"
        "Devuelve ÚNICAMENTE un JSON con esta forma exacta, sin bloques de código ni texto adicional:\n"
        '{"norma": "...", "articulo": "...", "tipo_pregunta": "...", "pregunta": "...", '
        '"opciones": {"A": "...", "B": "...", "C": "...", "D": "..."}, "respuesta_correcta": "A", '
        '"explicacion": "..."}'
        # Nota: se pedía también "referencia_legal" hasta ahora, pero ese
        # campo no lo lee ni lo usa nadie (ni el frontend, ni
        # validador_preguntas.py, ni la propia verificación posterior) --
        # la exigencia real de citar artículo+norma ya vive dentro de
        # "explicacion" (reglas 4 y 5 de arriba). Quitarlo del esquema
        # ahorra tokens de salida (y por tanto tiempo, ver el log "DeepSeek
        # respondió en Xs... tokens_salida=..." en deepseek_utils.py) sin
        # tocar la calidad de la explicación real que sí se muestra.
    )
    user = f"{contenido}\n\nGenera la pregunta a partir de este texto legal."
    return system, user


def _prompt_generacion_lote_normativo(especificaciones, oposicion):
    """Variante en LOTE de _prompt_generacion_normativo (ver
    TAMANO_LOTE_GENERACION): pide varias preguntas INDEPENDIENTES en una
    sola llamada, cada una marcada "PREGUNTA N" y anclada a su propio
    "TEXTO LEGAL N". especificaciones: lista de {"anclas": [ancla],
    "tipo_pregunta": str} -- una sola ancla cada una (el lote no soporta
    'distincion_articulos', que necesita dos)."""
    nombre_oposicion = OPOSICIONES.get(oposicion, OPOSICIONES[OPOSICION_POR_DEFECTO])["nombre"]
    n = len(especificaciones)

    bloques = []
    for i, espec in enumerate(especificaciones, start=1):
        ancla = espec["anclas"][0]
        etiqueta_articulo = ancla["articulo"] or "(norma sin numeración de artículo)"
        descripcion_tipo = _DESCRIPCION_TIPO_PREGUNTA[espec["tipo_pregunta"]]
        bloques.append(
            f"PREGUNTA {i} -- tipo: {descripcion_tipo}\n"
            f"TEXTO LEGAL {i} -- {ancla['norma']}, {etiqueta_articulo}:\n{ancla['texto_legal']}"
        )
    contenido = "\n\n".join(bloques)

    system = (
        f"Eres un generador profesional de preguntas tipo test para la oposición al {nombre_oposicion}, "
        "con el nivel de exigencia de las mejores academias de preparación (MAD, Adams, CEF). La "
        "precisión jurídica es la prioridad ABSOLUTA, por encima de cualquier otra consideración. Se te "
        f"piden {n} preguntas INDEPENDIENTES en esta misma llamada, cada una marcada \"PREGUNTA N\" y "
        "anclada a su propio \"TEXTO LEGAL N\".\n\n"
        "REGLAS INQUEBRANTABLES (se aplican a CADA pregunta por separado):\n"
        "1. La pregunta N, sus 4 opciones y su explicación deben basarse EXCLUSIVAMENTE en el TEXTO "
        "LEGAL N correspondiente -- NUNCA en el texto legal de otra pregunta del lote, aunque traten "
        "materias parecidas. Cada pregunta es un ejercicio jurídico independiente; no completes huecos "
        "con conocimiento propio ni mezcles datos entre textos distintos.\n"
        "2. Cualquier plazo, edad, mayoría, porcentaje, órgano, competencia, cuantía, requisito o fecha "
        "que menciones debe copiarse EXACTAMENTE de su propio texto legal -- nunca aproximarlo ni "
        "simplificarlo.\n"
        "3. Debe existir una única respuesta correcta, completa y verificable en su propio texto. Las "
        "otras tres deben parecer reales, con dificultad de examen oficial, cada una con un único error "
        "jurídico claro -- nunca absurdas, ninguna defendible como parcialmente correcta.\n"
        "4. La explicación debe repasar TODAS las opciones, una por línea y en orden, con este formato "
        "exacto: \"A) es correcta/incorrecta porque... B) ... C) ... D) ...\", citando el artículo en la "
        "línea de la respuesta correcta, usando la terminología oficial de SU norma (no sinónimos) y "
        "limitándose al contenido de su propio texto legal: nunca inventar doctrina ni interpretar la "
        "ley. Cada línea debe ser UNA sola frase breve (máximo 25-30 palabras) que vaya directa al "
        "motivo.\n"
        "5. Si la pregunta o la explicación citan un número de artículo, esa misma frase debe decir "
        "TAMBIÉN el nombre de la norma a la que pertenece, copiado tal cual aparece en su TEXTO LEGAL.\n"
        "6. Nunca abrevies el nombre de la norma con siglas (CE, TREBEP, LPAC, LRJSP, LOTC, LOPJ, LGP, "
        "LJCA...) ni con \"art.\" en vez de \"artículo\" -- escribe siempre el nombre entero tal como "
        "aparece en su TEXTO LEGAL, incluido el tipo de norma delante del número (nunca \"LO 3/2007\", "
        "sino \"Ley Orgánica 3/2007...\" entera).\n\n"
        "Antes de responder, comprueba internamente PARA CADA PREGUNTA: ¿existe una única respuesta "
        "correcta? ¿todos los datos coinciden EXACTAMENTE con SU PROPIO texto legal, sin mezclar con los "
        "demás del lote? Si tienes cualquier duda, ajusta esa pregunta antes de responder.\n\n"
        f"Devuelve ÚNICAMENTE un JSON con esta forma exacta, con exactamente {n} elementos en "
        "\"preguntas\" (uno por cada TEXTO LEGAL numerado), sin bloques de código ni texto adicional. "
        "\"pregunta_num\" debe coincidir SIEMPRE con el número de su propio TEXTO LEGAL -- es lo único "
        "que permite emparejar cada pregunta con el texto correcto, así que nunca lo omitas ni lo "
        "repitas entre preguntas distintas:\n"
        '{"preguntas": [{"pregunta_num": 1, "norma": "...", "articulo": "...", "tipo_pregunta": "...", '
        '"pregunta": "...", "opciones": {"A": "...", "B": "...", "C": "...", "D": "..."}, '
        '"respuesta_correcta": "A", "explicacion": "..."}, ...]}'
    )
    user = f"{contenido}\n\nGenera las {n} preguntas pedidas, cada una a partir de SU PROPIO texto legal numerado."
    return system, user


def _prompt_generacion_descriptivo(anclas, tipo_pregunta, oposicion):
    nombre_oposicion = OPOSICIONES.get(oposicion, OPOSICIONES[OPOSICION_POR_DEFECTO])["nombre"]
    descripcion_tipo = _DESCRIPCION_TIPO_PREGUNTA_DESCRIPTIVO[tipo_pregunta]
    contenido = _bloques_contenido(anclas)

    system = (
        f"Eres un generador profesional de preguntas tipo test para la oposición al {nombre_oposicion}, "
        "sobre contenido técnico y descriptivo del temario (por ejemplo informática básica y ofimática), "
        "con el nivel de exigencia de las mejores academias. La fidelidad al contenido proporcionado es "
        "la prioridad ABSOLUTA.\n\n"
        "REGLAS INQUEBRANTABLES:\n"
        "1. La pregunta, las 4 opciones y la explicación deben basarse EXCLUSIVAMENTE en el contenido de "
        "más abajo. No completes huecos con conocimiento propio ni añadas datos que no estén en él.\n"
        "2. Cualquier dato concreto (un nombre, una función, un atajo de teclado, un menú, un valor, una "
        "característica, un paso) debe copiarse EXACTAMENTE del contenido -- nunca aproximarlo ni "
        "inventarlo.\n"
        "3. Debe existir una única respuesta correcta, completa y verificable en el contenido. Las otras "
        "tres deben parecer plausibles, con dificultad de examen oficial, cada una con un único error "
        "claro (un dato cambiado) -- nunca absurdas, ninguna defendible como parcialmente correcta.\n"
        "4. La explicación debe repasar TODAS las opciones, una por línea y en orden, con este formato "
        "exacto: \"A) es correcta/incorrecta porque... B) es correcta/incorrecta porque... C) ... D) "
        "...\", limitándose al contenido proporcionado. Cada línea debe ser UNA sola frase breve "
        "(máximo 25-30 palabras) que vaya directa al motivo -- nunca repitas el enunciado de la "
        "pregunta ni el texto de las demás opciones, ni añadas relleno o contexto que no aporte nada "
        "nuevo.\n"
        "5. Afirma cada dato DIRECTAMENTE. NO uses muletillas como \"según el contenido\", \"según el "
        "texto\", \"en el contenido proporcionado\", \"tal como se indica\", \"de acuerdo con el "
        "contenido\" ni similares -- están prohibidas y harían que la pregunta se descarte. Esto "
        "incluye también remitir a \"lo "
        "mencionado\" o \"lo anterior\" (p. ej. \"¿qué tienen en común los X mencionados en el "
        "contenido?\"): quien responde el test NUNCA ve el contenido de origen, solo la pregunta -- "
        "nombra tú mismo, explícitamente, de qué elementos concretos hablas (p. ej. \"¿qué tienen en "
        "común la escala de gestión y la escala auxiliar?\", nunca \"los mencionados en el contenido\").\n"
        f"6. Tipo de pregunta a construir: {descripcion_tipo}\n\n"
        "Antes de responder, comprueba internamente: ¿existe una única respuesta correcta? ¿podría "
        "defenderse otra opción? ¿todos los datos coinciden EXACTAMENTE con el contenido? Si tienes "
        "cualquier duda, ajusta la pregunta antes de responder.\n\n"
        "Devuelve ÚNICAMENTE un JSON con esta forma exacta, sin bloques de código ni texto adicional:\n"
        '{"tema": "...", "tipo_pregunta": "...", "pregunta": "...", '
        '"opciones": {"A": "...", "B": "...", "C": "...", "D": "..."}, "respuesta_correcta": "A", '
        '"explicacion": "..."}'
    )
    user = f"{contenido}\n\nGenera la pregunta a partir de este contenido."
    return system, user


def _prompt_verificacion(pregunta_candidata, anclas):
    """Elige el prompt de verificación acorde al tipo de contenido, igual que
    _prompt_generacion."""
    if _es_normativo(anclas):
        return _prompt_verificacion_normativo(pregunta_candidata, anclas)
    return _prompt_verificacion_descriptivo(pregunta_candidata, anclas)


def _prompt_verificacion_normativo(pregunta_candidata, anclas):
    contenido = _bloques_texto_legal(anclas)
    system = (
        "Eres un verificador jurídico independiente. Te llega una pregunta tipo test YA REDACTADA por "
        "otro proceso, y el ÚNICO texto legal real del que debería haber salido. No des por hecho que "
        "la pregunta es correcta solo porque cita el artículo: comprueba cada afirmación contra el "
        "texto legal palabra por palabra, como si la vieras por primera vez y no supieras nada más.\n\n"
        "Marca la pregunta como inválida si detectas CUALQUIERA de estos problemas:\n"
        "1. El artículo citado no existe en el texto legal proporcionado.\n"
        "2. El contenido de la pregunta no coincide con lo que dice ese texto.\n"
        "3. La respuesta marcada como correcta no es completamente correcta según el texto.\n"
        "4. Alguna de las otras tres opciones podría considerarse también correcta o parcialmente "
        "correcta -- ninguna debe ser defendible.\n"
        "5. La explicación no repasa las 4 opciones en el formato \"A) ... B) ... C) ... D) ...\", no "
        "coincide exactamente con la respuesta correcta, o no cita el artículo en la opción correcta.\n"
        "6. Cualquier plazo, cifra, porcentaje, edad, mayoría, órgano competente, competencia "
        "atribuida, cuantía, requisito o fecha no coincide EXACTAMENTE con el texto legal.\n"
        "7. Se mezcla contenido de distintos artículos como si fuera uno solo.\n"
        "8. Existe alguna contradicción interna entre la pregunta, las opciones y la explicación.\n"
        "9. El lenguaje jurídico usado no es el que emplea la propia norma.\n"
        "10. Hay cualquier dato o afirmación que no puedas verificar literalmente en el texto legal "
        "proporcionado (posible alucinación).\n"
        "11. Un tribunal de oposición podría razonablemente considerar correcta una opción distinta a "
        "la marcada.\n"
        "12. La pregunta o la explicación mencionan un número de artículo (\"el artículo 52.1\"...) sin "
        "decir en la misma frase de qué norma es -- toda mención a un artículo debe ir acompañada del "
        "nombre de la norma (el que aparece en TEXTO LEGAL), para que quien lo lea sepa sin ambigüedad "
        "de qué ley se habla.\n"
        "13. Se usa una sigla o abreviatura para nombrar la norma (\"CE\", \"TREBEP\", \"LPAC\", "
        "\"LRJSP\", \"LOTC\", \"art.\" en vez de \"artículo\"...) en vez del nombre completo tal como "
        "aparece en TEXTO LEGAL -- los exámenes oficiales de esta oposición nunca abrevian. Esto incluye "
        "también abreviar el tipo de norma delante de su número (\"LO 3/2007\", \"RD 203/2021\"...) en vez "
        "de escribirlo entero (\"Ley Orgánica 3/2007\", \"Real Decreto 203/2021\").\n\n"
        "Devuelve ÚNICAMENTE un JSON con esta forma exacta, sin texto adicional:\n"
        '{"valido": true, "problemas": []}\n'
        "Si encuentras algún problema, \"valido\" debe ser false y \"problemas\" debe listar cada motivo "
        "-- cada elemento de \"problemas\" debe ser UNA sola frase breve (máximo 20-25 palabras), no un "
        "párrafo explicativo."
    )
    user = f"{contenido}\n\nPREGUNTA A VERIFICAR:\n{json.dumps(pregunta_candidata, ensure_ascii=False)}"
    return system, user


def _prompt_verificacion_descriptivo(pregunta_candidata, anclas):
    contenido = _bloques_contenido(anclas)
    system = (
        "Eres un verificador independiente. Te llega una pregunta tipo test YA REDACTADA por otro "
        "proceso, y el ÚNICO contenido real del que debería haber salido. No des por hecho que la "
        "pregunta es correcta: comprueba cada afirmación contra el contenido, como si lo vieras por "
        "primera vez y no supieras nada más. Se trata de temario técnico/descriptivo (informática, "
        "ofimática...), NO de una norma legal: no exijas artículos, plazos ni terminología de leyes.\n\n"
        "Marca la pregunta como inválida si detectas CUALQUIERA de estos problemas:\n"
        "1. El contenido de la pregunta no coincide con lo que dice el texto proporcionado.\n"
        "2. La respuesta marcada como correcta no es completamente correcta según ese contenido.\n"
        "3. Alguna de las otras tres opciones podría considerarse también correcta o parcialmente "
        "correcta -- ninguna debe ser defendible.\n"
        "4. La explicación no repasa las 4 opciones en el formato \"A) ... B) ... C) ... D) ...\", o no "
        "coincide exactamente con la respuesta marcada como correcta.\n"
        "5. Cualquier dato concreto (nombre, función, atajo, menú, valor, característica, paso) no "
        "coincide con el contenido.\n"
        "6. Se mezcla información de partes distintas del contenido de forma que resulte incorrecta.\n"
        "7. Existe alguna contradicción interna entre la pregunta, las opciones y la explicación.\n"
        "8. Hay cualquier dato o afirmación que no puedas verificar en el contenido proporcionado "
        "(posible invención).\n"
        "9. La pregunta o la explicación remiten a \"el contenido\", \"el texto\", \"el documento\" o "
        "\"lo mencionado/anterior\" en vez de nombrar directamente de qué elementos concretos habla "
        "(p. ej. \"¿qué tienen en común los X mencionados en el contenido?\") -- quien responde el test "
        "nunca ve el material de origen, así que una pregunta así queda sin sentido para quien la lee.\n\n"
        "Devuelve ÚNICAMENTE un JSON con esta forma exacta, sin texto adicional:\n"
        '{"valido": true, "problemas": []}\n'
        "Si encuentras algún problema, \"valido\" debe ser false y \"problemas\" debe listar cada motivo "
        "-- cada elemento de \"problemas\" debe ser UNA sola frase breve (máximo 20-25 palabras), no un "
        "párrafo explicativo."
    )
    user = f"{contenido}\n\nPREGUNTA A VERIFICAR:\n{json.dumps(pregunta_candidata, ensure_ascii=False)}"
    return system, user


def _verificar_y_aceptar_pregunta(pregunta_candidata, anclas, tema_id, tipo_pregunta,
                                   preguntas_ya_aceptadas, lock, on_usage, db,
                                   contexto_intento, intento_numero):
    """Toma una pregunta YA GENERADA y sus anclas, la verifica con una
    llamada independiente contra ESE mismo texto legal, y la acepta o la
    descarta -- código compartido entre generar una en una
    (_generar_pregunta_verificada) y generar en lote
    (_generar_lote_preguntas_verificadas), para no duplicar la validación
    estructural, la deduplicación, la llamada de verificación y el
    registro de errores en dos sitios. Devuelve la pregunta aceptada (con
    las opciones ya barajadas) o None si se descarta por cualquier motivo
    -- nunca lanza salvo que la propia llamada a DeepSeek falle de un modo
    que el llamante deba tratar como "intento fallido, reintentar"."""
    if not validar_pregunta(pregunta_candidata):
        return None
    if pregunta_candidata.get("respuesta_correcta") not in ("A", "B", "C", "D"):
        return None

    clave_dedup = re.sub(r"\s+", " ", str(pregunta_candidata.get("pregunta", "")).strip().lower())
    with lock:
        ya_existe = clave_dedup in preguntas_ya_aceptadas
    if ya_existe:
        return None  # demasiado parecida a una ya aceptada -- se descarta y se reintenta

    system_ver, user_ver = _prompt_verificacion(pregunta_candidata, anclas)
    verificacion_raw = call_deepseek_api(
        messages=[{"role": "system", "content": system_ver}, {"role": "user", "content": user_ver}],
        temperature=0.0,
        # max_tokens=4000 (subido de 2000 a 3000, y de 3000 a 4000, ambos
        # el 02/08/2026): se vio en producción truncamiento real también
        # aquí, primero con tokens_salida == 2000 y luego, tras la primera
        # subida, con tokens_salida == 3000 de nuevo (cuando el
        # verificador encuentra varios problemas en una pregunta,
        # "problemas" puede alargarse bastante).
        max_tokens=4000,
        contexto=f"tema={tema_id} tipo=verificacion {contexto_intento}",
        stream=True,  # ver el comentario largo sobre streaming en la generación
        # frequency_penalty=0.4: mismo motivo que en la generación.
        # Especialmente importante aquí -- con temperature=0.0
        # (determinista) se vio en producción el mismo input truncarse dos
        # veces SEGUIDAS en el mismo punto exacto (4000/4000 tokens): sin
        # este freno a la repetición, un reintento en temperatura 0 tiene
        # muchas más papeletas de reproducir el mismo bucle en vez de
        # romperlo.
        frequency_penalty=0.4,
        response_format_json=True,
        on_usage=on_usage,
        model=_MODELO,
    )
    if not verificacion_raw:
        return None
    try:
        verificacion = json.loads(verificacion_raw)
    except json.JSONDecodeError:
        return None

    if verificacion.get("valido") is not True:
        # inválida: se descarta ENTERA, nunca se corrige -- siguiente
        # intento desde cero. Efecto secundario no bloqueante: deja
        # constancia en errores_generacion para el loop de mejora de
        # calidad (ver errores_generacion.py) -- un fallo aquí nunca debe
        # frenar la generación.
        if db is not None:
            problemas = verificacion.get("problemas")
            registrar_error_generacion(
                db, tema_id=tema_id, fuente="auto_verificacion",
                pregunta_texto=str(pregunta_candidata.get("pregunta", "")),
                detalle="; ".join(str(p) for p in problemas) if isinstance(problemas, list) else "",
                intento_numero=intento_numero,
            )
        return None

    with lock:
        if clave_dedup in preguntas_ya_aceptadas:
            return None  # otro hilo aceptó lo mismo mientras se verificaba esta
        preguntas_ya_aceptadas.add(clave_dedup)
    pregunta_candidata["tema_id"] = tema_id
    pregunta_candidata.setdefault("tipo_pregunta", tipo_pregunta)
    return barajar_opciones_pregunta(pregunta_candidata)


def _generar_pregunta_verificada(subbloques_tema, tema_id, oposicion, subbloques_ya_usados,
                                  preguntas_ya_aceptadas, lock, on_usage=None, db=None,
                                  max_intentos=MAX_INTENTOS_POR_PREGUNTA):
    for _intento in range(max_intentos):
        try:
            tipo_pregunta = _elegir_tipo_pregunta()
            with lock:
                usados_snapshot = set(subbloques_ya_usados)
            anclas = _elegir_ancla_legal(subbloques_tema, usados_snapshot, tipo_pregunta == "distincion_articulos")
            if not anclas:
                return None  # este tema no tiene contenido real disponible, no tiene sentido reintentar

            with lock:
                for ancla in anclas:
                    subbloques_ya_usados.add(ancla["etiqueta_subbloque"])

            system_gen, user_gen = _prompt_generacion(anclas, tipo_pregunta, oposicion)
            generado = call_deepseek_api(
                messages=[{"role": "system", "content": system_gen}, {"role": "user", "content": user_gen}],
                temperature=0.5,
                contexto=f"tema={tema_id} tipo=generacion intento={_intento + 1}",
                # max_tokens=5000 (subido de 3000 el 02/08/2026, con datos
                # reales de producción, no a ciegas): con 3000, la inmensa
                # mayoría de las llamadas de generación truncaban a mitad del
                # JSON (finish_reason == "length" con tokens_salida == 3000
                # una y otra vez en el log "DeepSeek respondió en Xs..." de
                # deepseek_utils.py) -- y no era un caso raro, sino casi
                # sistemático: incluso las respuestas BUENAS (finish_reason
                # == "stop", nunca truncadas) ya consumían hasta ~2950
                # tokens con este mismo prompt, así que 3000 apenas dejaba
                # margen real. El reintento por truncamiento (ver
                # call_deepseek_api) ayuda ante un corte puntual, pero
                # reintentar con el MISMO límite no arregla un corte
                # sistemático -- solo dobla o triplica la latencia de ese
                # hueco sin conseguir nada. 5000 da margen de sobra sobre
                # esos ~2950 sin tocar el prompt (que ya pide explícitamente
                # explicaciones breves, máximo 25-30 palabras por opción) --
                # así no se sacrifica calidad para ganar velocidad. Si con
                # datos reales se ve que finish_reason == "length" ha
                # desaparecido del todo, se puede volver a ajustar a la baja.
                max_tokens=5000,
                # stream=True NO es para mostrar la pregunta poco a poco (aquí
                # se espera igualmente al JSON completo antes de validarlo):
                # es lo que evita que una generación larga muera con "Error de
                # conexión". Con stream=false no viaja ningún byte mientras el
                # modelo genera, y en producción (02/08/2026) TODA llamada que
                # pasaba de ~30s se cortaba desde el otro lado -- justo las de
                # este prompt, que a los ~110-130 tokens/s de deepseek-v4-flash
                # cruzan ese muro en cuanto pasan de ~3300 tokens de salida.
                # Ver _leer_respuesta_en_streaming en deepseek_utils.py.
                stream=True,
                # frequency_penalty=0.4 (02/08/2026, con datos reales): se
                # veían truncamientos que no eran por falta de margen --
                # subir max_tokens de 3000 a 5000 solo desplazó el mismo
                # patrón más arriba en vez de arreglarlo, la firma de una
                # generación que se repite en vez de terminar sola. Esto
                # penaliza repetir tokens ya usados, el antídoto estándar
                # contra ese bucle. Ver el comentario largo en
                # deepseek_utils.call_deepseek_api.
                frequency_penalty=0.4,
                response_format_json=True,
                on_usage=on_usage,
                model=_MODELO,
            )
            if not generado:
                continue
            try:
                pregunta_candidata = json.loads(generado)
            except json.JSONDecodeError:
                continue

            resultado = _verificar_y_aceptar_pregunta(
                pregunta_candidata, anclas, tema_id, tipo_pregunta,
                preguntas_ya_aceptadas, lock, on_usage, db,
                contexto_intento=f"intento={_intento + 1}", intento_numero=_intento + 1,
            )
            if resultado is None:
                continue
        except Exception:
            # Una forma de respuesta de DeepSeek que ningún "continue" de
            # arriba contemplaba (p. ej. un campo con un tipo inesperado) no
            # debe perder este hueco entero a la primera -- cuenta como un
            # intento fallido más y se reintenta desde cero, igual que una
            # pregunta que no supera la verificación.
            logger.exception("Intento fallido generando una pregunta (tema %s), se reintenta", tema_id)
            continue
        return resultado

    # Se agotaron los max_intentos sin conseguir una pregunta válida para
    # este hueco (truncamientos persistentes, fallos de conexión repetidos,
    # o descartes reales de verificación) -- nunca debe pasar en silencio:
    # sin este log, un test incompleto no dejaba NINGÚN rastro de qué tema
    # concreto se quedó sin cubrir (los descartes individuales, por sí
    # solos, no distinguen "mala suerte puntual" de "este tema falló
    # sistemáticamente"). El hueco todavía puede recuperarse en el relleno
    # de generar_test_verificado, en otro tema.
    logger.warning(
        "No se pudo generar una pregunta válida para el tema %s tras %d intentos -- hueco perdido "
        "(puede recuperarse en el relleno)", tema_id, max_intentos,
    )
    return None


def _generar_candidatos_lote(especificaciones, oposicion, on_usage, contexto_lote):
    """Hace UNA llamada de generación para varias preguntas a la vez (ver
    TAMANO_LOTE_GENERACION). especificaciones: lista de {"anclas": [ancla],
    "tipo_pregunta": str}. Devuelve una lista del MISMO tamaño y en el
    MISMO orden que especificaciones, con la pregunta candidata (dict) en
    cada posición o None si esa posición no llegó bien formada -- nunca
    lanza, un lote parcialmente roto no debe tirar el resto."""
    n = len(especificaciones)
    system_gen, user_gen = _prompt_generacion_lote_normativo(especificaciones, oposicion)
    generado = call_deepseek_api(
        messages=[{"role": "system", "content": system_gen}, {"role": "user", "content": user_gen}],
        temperature=0.5,
        contexto=f"{contexto_lote} tipo=generacion_lote n={n}",
        # max_tokens escalado con el tamaño del lote: cada pregunta
        # individual necesita hasta 5000 (ver _generar_pregunta_verificada);
        # aquí se reserva algo menos por pregunta porque las reglas del
        # sistema NO se repiten n veces, pero se deja margen real para no
        # reintroducir el mismo truncamiento sistemático ya diagnosticado
        # con datos reales en la llamada individual.
        max_tokens=min(4200 * n, 20000),
        stream=True,
        frequency_penalty=0.4,
        response_format_json=True,
        on_usage=on_usage,
        model=_MODELO,
    )
    if not generado:
        return [None] * n
    try:
        cuerpo = json.loads(generado)
    except json.JSONDecodeError:
        return [None] * n
    items = cuerpo.get("preguntas")
    if not isinstance(items, list):
        return [None] * n

    # Empareja por "pregunta_num" (1-based), NUNCA por posición cruda: si
    # el modelo se salta o repite un índice, es mejor perder esa pregunta
    # concreta que anclarla por error al texto legal de OTRA -- eso
    # aprobaría en la verificación posterior una pregunta comparada contra
    # el texto EQUIVOCADO, justo el tipo de fallo silencioso que este
    # generador entero está diseñado para evitar.
    por_indice = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        num = item.get("pregunta_num")
        if isinstance(num, int) and 1 <= num <= n and num not in por_indice:
            por_indice[num] = item
    return [por_indice.get(i + 1) for i in range(n)]


def _generar_lote_preguntas_verificadas(huecos_lote, subbloques_por_tema, oposicion,
                                         subbloques_ya_usados, preguntas_ya_aceptadas, lock,
                                         on_usage=None, db=None):
    """Genera hasta len(huecos_lote) preguntas con UNA llamada de generación
    (ver TAMANO_LOTE_GENERACION), cada una anclada a un tema distinto de
    huecos_lote, y las verifica cada una POR SEPARADO (misma llamada y
    misma lógica que el camino de una en una, vía
    _verificar_y_aceptar_pregunta -- la garantía de precisión jurídica no
    cambia). Devuelve una lista del MISMO tamaño y en el MISMO orden que
    huecos_lote: la pregunta aceptada (dict) o None si ese hueco concreto
    no salió adelante en ESTE intento -- None no es un fallo definitivo,
    el llamante (generar_test_verificado) ya sabe recuperar huecos así en
    el relleno final (que va uno a uno, la vía fiable de respaldo)."""
    especificaciones = [None] * len(huecos_lote)
    for i, tema_id in enumerate(huecos_lote):
        tipo_pregunta = random.choice([t for t in _DESCRIPCION_TIPO_PREGUNTA if t != "distincion_articulos"])
        with lock:
            usados_snapshot = set(subbloques_ya_usados)
        anclas = _elegir_ancla_legal(subbloques_por_tema[tema_id], usados_snapshot, necesita_dos=False)
        if not anclas:
            continue  # este tema no tiene contenido real disponible -- hueco perdido en este intento
        with lock:
            for ancla in anclas:
                subbloques_ya_usados.add(ancla["etiqueta_subbloque"])
        especificaciones[i] = {"anclas": anclas, "tipo_pregunta": tipo_pregunta}

    indices_validos = [i for i, e in enumerate(especificaciones) if e is not None]
    resultados = [None] * len(huecos_lote)
    if not indices_validos:
        return resultados

    candidatos = _generar_candidatos_lote(
        [especificaciones[i] for i in indices_validos], oposicion, on_usage,
        contexto_lote=f"lote_temas={[huecos_lote[i] for i in indices_validos]}",
    )

    def _verificar_item(pos, i):
        pregunta_candidata = candidatos[pos]
        if not pregunta_candidata:
            return None
        tema_id = huecos_lote[i]
        espec = especificaciones[i]
        try:
            return _verificar_y_aceptar_pregunta(
                pregunta_candidata, espec["anclas"], tema_id, espec["tipo_pregunta"],
                preguntas_ya_aceptadas, lock, on_usage, db,
                contexto_intento="lote", intento_numero=1,
            )
        except Exception:
            logger.exception("Fallo inesperado verificando una pregunta del lote (tema %s)", tema_id)
            return None

    # Las verificaciones corren EN PARALELO entre sí, no una detrás de otra:
    # agrupar la generación en una sola llamada y luego verificar secuencial
    # solo movería el cuello de botella de sitio -- N verificaciones
    # seguidas en el mismo hilo tardarían tanto como las N llamadas de
    # generación que se acaban de ahorrar agrupándolas.
    with ThreadPoolExecutor(max_workers=len(indices_validos)) as executor:
        futuros = {executor.submit(_verificar_item, pos, i): i for pos, i in enumerate(indices_validos)}
        for futuro in futuros:
            resultados[futuros[futuro]] = futuro.result()
    return resultados


def generar_test_verificado(db, temas, num_preguntas, coleccion="Temario AGE",
                             oposicion=OPOSICION_POR_DEFECTO, on_progreso=None,
                             modo_reparto="equitativo", uid=None):
    """Genera hasta num_preguntas preguntas verificadas, repartidas entre
    'temas' según modo_reparto: "equitativo" (por defecto, cuota igual
    para cada tema) o "realista" (más preguntas de los bloques que
    históricamente más caen en los exámenes oficiales ya cargados, ver
    utils.calcular_pesos_reales_por_bloque -- si la oposición no tiene
    ninguno cargado, cae de vuelta a un reparto igual entre bloques),
    ejecutando el pipeline generar->verificar->reintentar de cada pregunta
    en paralelo (una pregunta con problemas no bloquea a las demás).

    on_progreso(evento), si se pasa, se llama cada vez que un hueco de
    pregunta termina (con éxito o descartado), con
    {"completadas": i, "total": n, "aceptadas": len(preguntas_hasta_ahora),
    "pregunta": <dict de la pregunta aceptada, o None si se descartó>}
    -- pensado para retransmitir progreso real (no cosmético) por SSE, y
    para que el llamante pueda ir entregando preguntas ya aceptadas antes
    de que termine todo el test (ver /generar-test-avanzado).
    """
    temas_unicos = list(dict.fromkeys(t for t in temas if t))
    if not temas_unicos:
        return {"test": [], "descartadas": 0, "advertencia": "No se ha seleccionado ningún tema."}

    # En PARALELO (antes secuencial: un round-trip a Firestore por cada
    # tema elegido, uno detrás de otro) -- con 20+ temas seleccionados
    # (habitual: el usuario elige varios bloques enteros aunque solo pida
    # 10 preguntas) esto solo sumaba ~10-12s de espera ANTES de que
    # arrancara siquiera la primera llamada a DeepSeek, visto en
    # producción el 02/08/2026 comparando el timestamp de "Petición
    # recibida" con el de "Reparto de preguntas por tema". Cada llamada a
    # obtener_subbloques_individuales es independiente (un tema, sin
    # estado compartido), así que paralelizarla es seguro.
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(temas_unicos))) as executor:
        subbloques_por_tema = dict(zip(
            temas_unicos,
            executor.map(lambda tid: obtener_subbloques_individuales(db, [tid], coleccion=coleccion), temas_unicos),
        ))
    temas_con_contenido = [tid for tid in temas_unicos if subbloques_por_tema[tid]]
    if not temas_con_contenido:
        return {"test": [], "descartadas": 0,
                "advertencia": "No se encontraron subbloques válidos para los temas elegidos."}

    if modo_reparto == "realista":
        pesos_por_bloque = calcular_pesos_reales_por_bloque(db, oposicion)
        cupos = repartir_cupos_por_tema_realista(temas_con_contenido, num_preguntas, pesos_por_bloque)
    else:
        cupos = repartir_cupos_por_tema(temas_con_contenido, num_preguntas)
    # Los temas con cupo 0 (reparto equitativo con más temas que preguntas
    # pedidas, p. ej. 40 temas para 20 preguntas) NO generan ningún hueco
    # más abajo, así que nunca disparan ninguna llamada a DeepSeek para
    # ellos -- se deja constancia aquí de qué le tocó a cada tema para
    # poder comprobarlo en los logs, en vez de tener que inferirlo contando
    # llamadas.
    logger.info("Reparto de preguntas por tema (modo=%s, %d preguntas / %d temas): %s",
                modo_reparto, num_preguntas, len(temas_con_contenido), cupos)
    huecos = [tid for tid, cupo in cupos.items() for _ in range(cupo)]
    total = len(huecos)
    if total == 0:
        return {"test": [], "descartadas": 0}
    # Se baraja el orden de ENVÍO (no el resultado final) para que las
    # preguntas que van llegando primero por el streaming ya salgan
    # mezcladas por tema, en vez de agrupadas -- así el frontend puede
    # empezar el test con las primeras que lleguen sin tener que esperar
    # a barajar el conjunto completo al final.
    random.shuffle(huecos)

    subbloques_ya_usados = set()
    preguntas_ya_aceptadas = set()
    lock = threading.Lock()
    preguntas = []
    descartadas = 0
    completadas = 0
    # Cuántas preguntas se aceptaron REALMENTE por tema (incluyendo las del
    # relleno más abajo) -- se compara con 'cupos' (lo asignado) al final,
    # para poder ver en los logs si el déficit se concentra en unos pocos
    # temas concretos en vez de repartirse por igual.
    generadas_por_tema = {tid: 0 for tid in temas_con_contenido}

    # Acumulador de tokens seguro entre hilos: los workers hacen las llamadas
    # a DeepSeek (donde no hay contexto de petición) y suman aquí; al acabar,
    # se vuelca al contador de coste del usuario de la petición.
    from coste_ia import AcumuladorTokens
    acumulador_tokens = AcumuladorTokens()

    # Se agrupan los huecos NORMATIVOS en lotes de generación (ver
    # TAMANO_LOTE_GENERACION) -- los descriptivos (ofimática/informática,
    # sin "Artículo N.") siguen yendo uno a uno, para no mezclar dos
    # formatos de contenido en el mismo prompt de lote. es_normativo se
    # calcula una vez por tema (constante para todos sus huecos).
    es_normativo_por_tema = {tid: _tema_es_normativo(subbloques_por_tema[tid]) for tid in temas_con_contenido}
    huecos_normativos = [tid for tid in huecos if es_normativo_por_tema[tid]]
    huecos_individuales = [tid for tid in huecos if not es_normativo_por_tema[tid]]
    lotes = [
        huecos_normativos[i:i + TAMANO_LOTE_GENERACION]
        for i in range(0, len(huecos_normativos), TAMANO_LOTE_GENERACION)
    ]

    def _tarea_individual(tid):
        # Envuelto en una lista de 1: así el consumidor de más abajo
        # itera SIEMPRE una lista de resultados, sea la tarea un lote de
        # varias preguntas o una sola -- misma forma, mismo código.
        return [_generar_pregunta_verificada(
            subbloques_por_tema[tid], tid, oposicion,
            subbloques_ya_usados, preguntas_ya_aceptadas, lock, acumulador_tokens.add, db,
        )]

    def _tarea_lote(lote):
        try:
            return _generar_lote_preguntas_verificadas(
                lote, subbloques_por_tema, oposicion,
                subbloques_ya_usados, preguntas_ya_aceptadas, lock, acumulador_tokens.add, db,
            )
        except Exception:
            # Un fallo inesperado en TODO el lote (no en una pregunta
            # suelta dentro de él -- eso ya lo captura
            # _generar_lote_preguntas_verificadas internamente) no debe
            # perder la cuenta de cuántos huecos traía este lote: se
            # devuelven todos como fallidos, cada uno recuperable en el
            # relleno final, igual que un hueco individual que agota sus
            # intentos.
            logger.exception("Fallo inesperado generando un lote de preguntas del test personalizado")
            return [None] * len(lote)

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(lotes) + len(huecos_individuales))) as executor:
        futuros = (
            [executor.submit(_tarea_lote, lote) for lote in lotes]
            + [executor.submit(_tarea_individual, tid) for tid in huecos_individuales]
        )
        for futuro in as_completed(futuros):
            try:
                resultados = futuro.result()
            except Exception:
                # Un fallo inesperado aquí ya no debería pasar (_tarea_lote
                # y _tarea_individual capturan por dentro), pero por si
                # acaso: mejor una pregunta descartada de más que tirar
                # todo lo que los demás hilos ya llevan aceptado.
                logger.exception("Fallo inesperado generando preguntas del test personalizado")
                resultados = [None]
            for resultado in resultados:
                completadas += 1
                if resultado:
                    preguntas.append(resultado)
                    generadas_por_tema[resultado["tema_id"]] = generadas_por_tema.get(resultado["tema_id"], 0) + 1
                    # Se acumula aparte, por oposición, un banco de preguntas ya
                    # verificadas (ver banco_preguntas_ia.py) -- Tu Tutor lo
                    # consulta (utils.buscar_pregunta_banco_ia) para dar la
                    # respuesta ya corregida en vez de razonarla de nuevo cuando
                    # el usuario le pega una de estas preguntas.
                    guardar_pregunta_generada(db, oposicion, resultado)
                    # Invalida en este proceso la caché de Tu Tutor sobre el
                    # banco de IA -- si no, buscar_pregunta_banco_ia podía tardar
                    # hasta 30 min (TTL) en ver esta misma pregunta recién
                    # generada (bug real visto en producción).
                    limpiar_cache_preguntas_banco_ia(oposicion)
                else:
                    descartadas += 1
                if on_progreso:
                    on_progreso({
                        "completadas": completadas, "total": total, "aceptadas": len(preguntas),
                        "pregunta": resultado,
                    })

    # Relleno: si algún hueco agotó sus MAX_INTENTOS_POR_PREGUNTA honestamente
    # (nunca se relaja la verificación para llegar al número pedido), se le da
    # otra oportunidad por cada uno que falte, en OTRO tema con contenido
    # disponible (rotando entre los elegidos) -- para que "hay temario de
    # sobra" no se traduzca en menos preguntas de las pedidas solo porque a
    # un hueco concreto le tocó mala suerte con sus intentos. Ver
    # MAX_RONDAS_RELLENO arriba: esto se repite en bucle (acotado) mientras
    # sigan faltando preguntas, no una única pasada -- una sola pasada podía
    # a su vez tener mala suerte y dejar el test corto de verdad.
    #
    # EN PARALELO (antes era un "for" secuencial, con el mismo razonamiento
    # de "no merece la pena otro ThreadPoolExecutor para 1-2 preguntas" que
    # resultó no aguantar en la práctica): con varios huecos, cada uno hasta
    # MAX_INTENTOS_POR_PREGUNTA rondas de generación+verificación (~15-20s
    # por llamada a DeepSeek), rellenarlos uno detrás de otro podía sumar
    # minutos SOLO en esta fase -- el mismo cuello de botella real ya
    # detectado y corregido en test_generator.py (generar_preguntas_ia_en_lotes)
    # para /generar-test-desde-pdf. Se reutiliza exactamente el mismo patrón
    # que ya usa el bucle principal de arriba (ThreadPoolExecutor +
    # as_completed): _generar_pregunta_verificada ya recibe y usa 'lock' para
    # proteger 'subbloques_ya_usados'/'preguntas_ya_aceptadas', así que no
    # hace falta ningún lock nuevo -- solo las mutaciones de 'preguntas'/
    # 'descartadas'/'completadas' y la llamada a on_progreso, que se hacen
    # aquí en el hilo principal según van llegando los resultados (as_completed),
    # nunca dentro de los hilos del pool.
    rondas_relleno = 0
    while len(preguntas) < num_preguntas and temas_con_contenido and rondas_relleno < MAX_RONDAS_RELLENO:
        rondas_relleno += 1
        faltan = num_preguntas - len(preguntas)
        ciclo_temas = itertools.cycle(temas_con_contenido)
        tids_relleno = [next(ciclo_temas) for _ in range(faltan)]
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, faltan)) as executor:
            futuros = [
                executor.submit(
                    _generar_pregunta_verificada, subbloques_por_tema[tid], tid, oposicion,
                    subbloques_ya_usados, preguntas_ya_aceptadas, lock, acumulador_tokens.add, db,
                )
                for tid in tids_relleno
            ]
            for futuro in as_completed(futuros):
                try:
                    resultado = futuro.result()
                except Exception:
                    logger.exception("Fallo inesperado en el relleno de un hueco del test personalizado")
                    resultado = None
                completadas += 1
                if resultado:
                    preguntas.append(resultado)
                    generadas_por_tema[resultado["tema_id"]] = generadas_por_tema.get(resultado["tema_id"], 0) + 1
                    guardar_pregunta_generada(db, oposicion, resultado)
                    limpiar_cache_preguntas_banco_ia(oposicion)
                else:
                    descartadas += 1
                if on_progreso:
                    on_progreso({
                        "completadas": completadas, "total": total, "aceptadas": len(preguntas),
                        "pregunta": resultado,
                    })
        if len(preguntas) < num_preguntas:
            logger.warning(
                "Relleno ronda %d/%d: siguen faltando %d/%d preguntas tras esta ronda (temas: %s)",
                rondas_relleno, MAX_RONDAS_RELLENO, num_preguntas - len(preguntas), num_preguntas, temas_unicos,
            )

    # Con uid (Test Personalizado): la generación corre en un hilo de fondo
    # desligado de la petición, así que se vuelca DIRECTO a Firestore. Sin uid
    # (llamadas dentro del propio hilo de la petición): se vuelca a flask.g y
    # el teardown_request lo guarda.
    if uid:
        acumulador_tokens.volcar_directo(db, uid)
    else:
        acumulador_tokens.volcar_a_peticion()
    resultado_final = {"test": preguntas, "descartadas": descartadas}
    if len(preguntas) < num_preguntas:
        resultado_final["advertencia"] = (
            f"Se generaron {len(preguntas)} de {num_preguntas} preguntas -- el resto no llegó a superar "
            f"la verificación de calidad tras varios intentos (incluyendo {MAX_RONDAS_RELLENO} rondas de "
            "relleno en otros temas) y se descartó en vez de entregarse sin validar."
        )
    # Sin este log, un test que entrega menos preguntas de las pedidas no
    # deja NINGÚN rastro en los logs (los descartes por no superar la
    # verificación no son un error, así que no pasan por logger.exception) --
    # visto en producción: sin esta línea no había forma de saber, a partir
    # de los logs de Render, si una tasa de descarte alta era el motivo real
    # de una generación lenta o incompleta. Nivel WARNING (no INFO) cuando
    # falta alguna: nunca debe poder pasar desapercibido en los logs que un
    # test se entregó incompleto.
    nivel_log = logger.warning if len(preguntas) < num_preguntas else logger.info
    nivel_log(
        "Test personalizado generado: %s/%s aceptadas, %s descartadas (temas: %s, asignadas vs "
        "generadas por tema: %s)",
        len(preguntas), num_preguntas, descartadas, temas_unicos,
        {tid: {"asignadas": cupos.get(tid, 0), "generadas": generadas_por_tema.get(tid, 0)} for tid in temas_con_contenido},
    )
    return resultado_final
