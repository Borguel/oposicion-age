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
     ese hueco se pierde (se avisa al final) en vez de bloquear el resto
     del test para siempre.
"""
import json
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from deepseek_utils import call_deepseek_api
from utils import obtener_subbloques_individuales, repartir_cupos_por_tema, barajar_opciones_pregunta
from validador_preguntas import validar_pregunta
from oposiciones import OPOSICIONES, OPOSICION_POR_DEFECTO

MAX_INTENTOS_POR_PREGUNTA = 4
_MAX_WORKERS = 6

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


def _prompt_generacion(anclas, tipo_pregunta, oposicion):
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
        f"5. Tipo de pregunta a construir: {descripcion_tipo}\n\n"
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


def _prompt_verificacion(pregunta_candidata, anclas):
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
        "la marcada.\n\n"
        "Devuelve ÚNICAMENTE un JSON con esta forma exacta, sin texto adicional:\n"
        '{"valido": true, "problemas": []}\n'
        "Si encuentras algún problema, \"valido\" debe ser false y \"problemas\" debe listar cada motivo."
    )
    user = f"{contenido}\n\nPREGUNTA A VERIFICAR:\n{json.dumps(pregunta_candidata, ensure_ascii=False)}"
    return system, user


def _generar_pregunta_verificada(subbloques_tema, tema_id, oposicion, subbloques_ya_usados,
                                  preguntas_ya_aceptadas, lock, max_intentos=MAX_INTENTOS_POR_PREGUNTA):
    for _intento in range(max_intentos):
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
            max_tokens=1000,
            response_format_json=True,
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
            max_tokens=400,
            response_format_json=True,
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
        return barajar_opciones_pregunta(pregunta_candidata)

    return None


def generar_test_verificado(db, temas, num_preguntas, coleccion="Temario AGE",
                             oposicion=OPOSICION_POR_DEFECTO, on_progreso=None):
    """Genera hasta num_preguntas preguntas verificadas, repartidas en cuota
    equitativa entre 'temas' (igual criterio que el generador anterior),
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

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, total)) as executor:
        futuros = [
            executor.submit(
                _generar_pregunta_verificada, subbloques_por_tema[tid], tid, oposicion,
                subbloques_ya_usados, preguntas_ya_aceptadas, lock
            )
            for tid in huecos
        ]
        for futuro in as_completed(futuros):
            resultado = futuro.result()
            completadas += 1
            if resultado:
                preguntas.append(resultado)
            else:
                descartadas += 1
            if on_progreso:
                on_progreso({
                    "completadas": completadas, "total": total, "aceptadas": len(preguntas),
                    "pregunta": resultado,
                })

    resultado_final = {"test": preguntas, "descartadas": descartadas}
    if len(preguntas) < num_preguntas:
        resultado_final["advertencia"] = (
            f"Se generaron {len(preguntas)} de {num_preguntas} preguntas -- el resto no llegó a superar "
            "la verificación jurídica tras varios intentos y se descartó en vez de entregarse sin validar."
        )
    return resultado_final
