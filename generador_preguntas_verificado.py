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

logger = logging.getLogger(__name__)

MAX_INTENTOS_POR_PREGUNTA = 4
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
        "interpretar la ley.\n"
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
        '"explicacion": "...", "referencia_legal": "..."}'
    )
    user = f"{contenido}\n\nGenera la pregunta a partir de este texto legal."
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
        "...\", limitándose al contenido proporcionado.\n"
        "5. Afirma cada dato DIRECTAMENTE. NO uses muletillas como \"según el contenido\", \"según el "
        "texto\", \"en el contenido proporcionado\", \"tal como se indica\" ni similares -- están "
        "prohibidas y harían que la pregunta se descarte. Esto incluye también remitir a \"lo "
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
        "Si encuentras algún problema, \"valido\" debe ser false y \"problemas\" debe listar cada motivo."
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
        "Si encuentras algún problema, \"valido\" debe ser false y \"problemas\" debe listar cada motivo."
    )
    user = f"{contenido}\n\nPREGUNTA A VERIFICAR:\n{json.dumps(pregunta_candidata, ensure_ascii=False)}"
    return system, user


def _generar_pregunta_verificada(subbloques_tema, tema_id, oposicion, subbloques_ya_usados,
                                  preguntas_ya_aceptadas, lock, on_usage=None,
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
                # max_tokens=1000: valor normal para _MODELO = deepseek-v4-flash
                # (no es un modelo de razonamiento, así que no necesita el
                # margen extra para "pensar" antes de responder). Se llegó a
                # subir a 3000 al probar deepseek-v4-pro (que sí razona y
                # consume tokens en ello antes del JSON final) pero se
                # revierte aquí al volver a flash -- ver el log "DeepSeek
                # respondió en Xs (... finish_reason=...)" en
                # deepseek_utils.py para comprobar con datos reales si
                # finish_reason == "length" alguna vez (señal de que este
                # tope se ha quedado corto) antes de volver a subirlo.
                max_tokens=1000,
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
            if not validar_pregunta(pregunta_candidata):
                continue
            if pregunta_candidata.get("respuesta_correcta") not in ("A", "B", "C", "D"):
                continue

            clave_dedup = re.sub(r"\s+", " ", str(pregunta_candidata.get("pregunta", "")).strip().lower())
            with lock:
                ya_existe = clave_dedup in preguntas_ya_aceptadas
            if ya_existe:
                continue  # demasiado parecida a una ya aceptada -- se descarta y se reintenta

            system_ver, user_ver = _prompt_verificacion(pregunta_candidata, anclas)
            verificacion_raw = call_deepseek_api(
                messages=[{"role": "system", "content": system_ver}, {"role": "user", "content": user_ver}],
                temperature=0.0,
                max_tokens=400,  # ver comentario de max_tokens en la llamada de generación de arriba
                response_format_json=True,
                on_usage=on_usage,
                model=_MODELO,
            )
            if not verificacion_raw:
                continue
            try:
                verificacion = json.loads(verificacion_raw)
            except json.JSONDecodeError:
                continue

            if verificacion.get("valido") is not True:
                continue  # inválida: se descarta ENTERA, nunca se corrige -- siguiente intento desde cero

            with lock:
                if clave_dedup in preguntas_ya_aceptadas:
                    continue  # otro hilo aceptó lo mismo mientras se verificaba esta
                preguntas_ya_aceptadas.add(clave_dedup)
            pregunta_candidata["tema_id"] = tema_id
            pregunta_candidata.setdefault("tipo_pregunta", tipo_pregunta)
        except Exception:
            # Una forma de respuesta de DeepSeek que ningún "continue" de
            # arriba contemplaba (p. ej. un campo con un tipo inesperado) no
            # debe perder este hueco entero a la primera -- cuenta como un
            # intento fallido más y se reintenta desde cero, igual que una
            # pregunta que no supera la verificación.
            logger.exception("Intento fallido generando una pregunta (tema %s), se reintenta", tema_id)
            continue
        return barajar_opciones_pregunta(pregunta_candidata)

    return None


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

    subbloques_por_tema = {
        tid: obtener_subbloques_individuales(db, [tid], coleccion=coleccion)
        for tid in temas_unicos
    }
    temas_con_contenido = [tid for tid in temas_unicos if subbloques_por_tema[tid]]
    if not temas_con_contenido:
        return {"test": [], "descartadas": 0,
                "advertencia": "No se encontraron subbloques válidos para los temas elegidos."}

    if modo_reparto == "realista":
        pesos_por_bloque = calcular_pesos_reales_por_bloque(db, oposicion)
        cupos = repartir_cupos_por_tema_realista(temas_con_contenido, num_preguntas, pesos_por_bloque)
    else:
        cupos = repartir_cupos_por_tema(temas_con_contenido, num_preguntas)
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

    # Acumulador de tokens seguro entre hilos: los workers hacen las llamadas
    # a DeepSeek (donde no hay contexto de petición) y suman aquí; al acabar,
    # se vuelca al contador de coste del usuario de la petición.
    from coste_ia import AcumuladorTokens
    acumulador_tokens = AcumuladorTokens()

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, total)) as executor:
        futuros = [
            executor.submit(
                _generar_pregunta_verificada, subbloques_por_tema[tid], tid, oposicion,
                subbloques_ya_usados, preguntas_ya_aceptadas, lock, acumulador_tokens.add
            )
            for tid in huecos
        ]
        for futuro in as_completed(futuros):
            try:
                resultado = futuro.result()
            except Exception:
                # Un fallo inesperado en UN hueco (p. ej. una forma de
                # respuesta de DeepSeek que ningún "continue" contemplaba)
                # no debe tirar todas las preguntas ya aceptadas por los
                # demás hilos -- se trata como una pregunta descartada más,
                # igual que si no hubiera superado la verificación.
                logger.exception("Fallo inesperado generando una pregunta del test personalizado")
                resultado = None
            completadas += 1
            if resultado:
                preguntas.append(resultado)
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
    # una oportunidad más por cada uno que falte, en OTRO tema con contenido
    # disponible (rotando entre los elegidos) -- para que "hay temario de
    # sobra" no se traduzca en menos preguntas de las pedidas solo porque a
    # un hueco concreto le tocó mala suerte con sus intentos. Secuencial (no
    # merece la pena otro ThreadPoolExecutor para lo que normalmente es 1-2
    # preguntas). SÍ llama a on_progreso igual que el bucle principal: cada
    # intento aquí puede suponer dos llamadas a DeepSeek de hasta 30s cada
    # una, y con varios huecos por rellenar esta fase puede tardar bastante
    # -- sin ningún evento durante todo ese tramo, quien consume el streaming
    # SSE (ver /generar-test-avanzado) se queda sin ninguna señal de que
    # sigue en marcha, tiempo de silencio real que un cliente o proxy
    # intermedio puede llegar a interpretar como conexión muerta.
    if len(preguntas) < num_preguntas and temas_con_contenido:
        faltan = num_preguntas - len(preguntas)
        ciclo_temas = itertools.cycle(temas_con_contenido)
        for _ in range(faltan):
            tid = next(ciclo_temas)
            try:
                resultado = _generar_pregunta_verificada(
                    subbloques_por_tema[tid], tid, oposicion,
                    subbloques_ya_usados, preguntas_ya_aceptadas, lock, acumulador_tokens.add,
                )
            except Exception:
                logger.exception("Fallo inesperado en el relleno de un hueco del test personalizado")
                resultado = None
            completadas += 1
            if resultado:
                preguntas.append(resultado)
                guardar_pregunta_generada(db, oposicion, resultado)
                limpiar_cache_preguntas_banco_ia(oposicion)
            else:
                descartadas += 1
            if on_progreso:
                on_progreso({
                    "completadas": completadas, "total": total, "aceptadas": len(preguntas),
                    "pregunta": resultado,
                })

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
            "la verificación de calidad tras varios intentos (incluyendo un intento de relleno en otro "
            "tema) y se descartó en vez de entregarse sin validar."
        )
    # Sin este log, un test que entrega menos preguntas de las pedidas no
    # deja NINGÚN rastro en los logs (los descartes por no superar la
    # verificación no son un error, así que no pasan por logger.exception) --
    # visto en producción: sin esta línea no había forma de saber, a partir
    # de los logs de Render, si una tasa de descarte alta era el motivo real
    # de una generación lenta o incompleta.
    logger.info(
        "Test personalizado generado: %s/%s aceptadas, %s descartadas (temas: %s)",
        len(preguntas), num_preguntas, descartadas, temas_unicos,
    )
    return resultado_final
