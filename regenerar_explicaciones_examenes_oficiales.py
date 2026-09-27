"""Regenera el campo `explicacion` de las preguntas de examenes oficiales
(AGE, AUXILIAR, GACE) que no repasan las 4 opciones -- solo justifican la
correcta, igual que hace ya Test Personalizado (generador_preguntas_
verificado.py, regla 4 de _prompt_generacion_normativo/_descriptivo):
"A) es correcta/incorrecta porque... B) ... C) ... D) ...".

Motivo: al cargar los examenes oficiales (cargar_examen_oficial_age.py y
sus gemelos de auxiliar/gace), la explicacion de cada pregunta se toma de
un fichero *_explicaciones.json curado a mano o, si falta, se genera con
`generar_explicacion()` (definida en cada uno de esos loaders) -- un
prompt mucho mas simple que solo pide justificar la opcion correcta,
nunca las otras 3. El resultado es una explicacion pobre frente a las de
Test Personalizado, que si desglosan las 4.

Por seguridad va en dos pasos, como el resto de scripts de datos de este
proyecto (ver reasignar_temas_examenes.py):
    python regenerar_explicaciones_examenes_oficiales.py              # solo AUDITA
    python regenerar_explicaciones_examenes_oficiales.py --aplicar    # regenera de verdad

Es idempotente: el criterio de "pendiente" (_tiene_formato_bueno) se
recalcula cada vez sobre el estado actual de Firestore, asi que volver a
lanzarlo tras una interrupcion o algun fallo puntual solo reintenta lo
que de verdad siga sin arreglar.

Ademas incluye un modo --verificar (tambien de dos pasos), pensado para
revisar la CALIDAD de las explicaciones ya regeneradas -- una segunda
pasada de autocritica (una IA revisa cada explicacion ya escrita
buscando afirmaciones demasiado tajantes o contradicciones) y, con
--aplicar, regenera solo las que fallen esa revision, esta vez con el
problema detectado como pista:
    python regenerar_explicaciones_examenes_oficiales.py --verificar
    python regenerar_explicaciones_examenes_oficiales.py --verificar --aplicar

Respaldo con texto legal real (cuando hay cobertura): las preguntas de
examenes oficiales ya tienen un `tema_id` (bloque_XX-tema_XX) asignado
por reasignar_temas_examenes.py, que apunta al mismo temario que usa
Test Personalizado como fuente real (subbloques con texto BOE, ver
utils.obtener_subbloques_individuales). Cuando ese tema_id resuelve a
contenido real, tanto la generacion como la verificacion lo usan como
"TEXTO LEGAL" de referencia (mismo espiritu que generador_preguntas_
verificado.py) en vez de fiarse solo del conocimiento general del
modelo -- eso reduce mucho el riesgo de afirmaciones tajantes pero
imprecisas. Si el tema_id no resuelve a nada (huerfano/sin cobertura),
se sigue el comportamiento anterior sin respaldo, como red de
seguridad. --cobertura audita, SOLO lectura de Firestore y sin ninguna
llamada a IA, para cuantas preguntas hay de verdad texto legal
recuperable, antes de gastar nada en generar/verificar:
    python regenerar_explicaciones_examenes_oficiales.py --cobertura

Importante: el respaldo NO concatena el tema entero (un tema puede
agrupar varias normas y decenas de articulos) -- localiza el articulo
concreto que la pregunta/opciones/explicacion ya citan (misma regex de
"Articulo N" que usa generador_preguntas_verificado.py) dentro de los
subbloques del tema, filtrando antes por la norma citada si el tema
mezcla varias. Concatenar-y-truncar a ciegas hacia el principio del tema
(primera version de este respaldo) producia ~83% de "invalidas" en
--verificar porque el articulo citado casi nunca caia dentro del trozo
truncado -- no era una senal real de calidad, era un fallo de
recuperacion. Si no hay ninguna cita de articulo detectable (pregunta
descriptiva), cae al contexto general del tema (concatenado y truncado,
comportamiento anterior). Si SI hay cita pero no se encuentra en ningun
subbloque del tema, se trata como sin cobertura (sin respaldo para esa
pregunta), nunca se fuerza un match falso.

Requiere FIREBASE_CREDENTIALS_JSON (o FIREBASE_KEY_PATH) y
DEEPSEEK_API_KEY, igual que el resto de scripts de datos.
"""
import os
import re
import sys
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

from coste_ia import AcumuladorTokens, coste_estimado
from deepseek_utils import call_deepseek_api
from generador_preguntas_verificado import _extraer_articulos
from oposiciones import OPOSICIONES, coleccion_examenes_oficiales, coleccion_temario
from utils import obtener_subbloques_individuales

load_dotenv()

MAX_WORKERS = 8
# Preguntas de muestra a generar en modo auditoria (llamada real, coste
# minimo) para poder juzgar la calidad antes de decidir aplicar nada.
MUESTRAS_AUDITORIA_POR_OPOSICION = 1
# Tope de caracteres del bloque "TEXTO LEGAL" que se antepone al prompt --
# varios subbloques de un tema caben de sobra sin disparar el coste ni el
# tiempo de la llamada.
MAX_CARACTERES_TEXTO_LEGAL_TEMA = 12000

# Una letra seguida de ")" -- p. ej. "A)" -- en cualquier punto del texto.
# Una explicacion se considera "ya buena" si repasa las 4 opciones.
_PATRON_OPCION = {letra: re.compile(rf"{letra}\)") for letra in "ABCD"}


def _init_firebase():
    if firebase_admin._apps:
        return
    cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if cred_json:
        cred = credentials.Certificate(json.loads(cred_json))
    else:
        cred = credentials.Certificate(os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json"))
    firebase_admin.initialize_app(cred)


def _tiene_formato_bueno(explicacion):
    """True si la explicacion ya repasa las 4 opciones (A)/B)/C)/D)) --
    tanto una explicacion vacia como la vieja ("solo la correcta") caen en
    False, que es justo lo que hay que regenerar."""
    explicacion = explicacion or ""
    return all(patron.search(explicacion) for patron in _PATRON_OPCION.values())


# Número de artículo citado en un texto (pregunta/opciones/explicación) --
# "artículo 43", "artículo 43.3", "art. 20.1"... el apartado (.3, .1) no se
# captura, solo el número entero del artículo (ya viene completo dentro del
# fragmento que devuelve _extraer_articulos).
_PATRON_ARTICULO_CITADO = re.compile(r"art[íi]culo\s+(\d+)|art\.\s*(\d+)", re.IGNORECASE)
# "Ley N/AAAA" / "Real Decreto (Legislativo) N/AAAA" -- basta el número/año,
# que es lo que también aparece en el título del subbloque del temario.
_PATRON_NUM_ANIO = re.compile(r"\b(\d{1,3}/\d{4})\b")


def _articulos_citados(texto):
    """Números de artículo (como strings, p. ej. {"43", "3"}) citados en
    texto -- vacío si no hay ninguna cita detectable."""
    numeros = set()
    for m in _PATRON_ARTICULO_CITADO.finditer(texto or ""):
        numeros.add(m.group(1) or m.group(2))
    return numeros


def _normas_citadas(texto):
    """Normas citadas en texto, normalizadas para poder compararlas contra
    el título de un subbloque del temario -- el número/año tal cual (sirve
    para Ley y para Real Decreto/RDLeg, que comparten formato "N/AAAA"), o
    "constitución"/"tfue" para las dos normas sin ese formato que se citan
    con frecuencia en examenes oficiales."""
    texto = texto or ""
    normas = set(_PATRON_NUM_ANIO.findall(texto))
    texto_low = texto.lower()
    if "constituci" in texto_low or re.search(r"\bce\b", texto_low):
        normas.add("constitución")
    if "tfue" in texto_low or "funcionamiento de la unión europea" in texto_low:
        normas.add("tfue")
    return normas


def _subbloque_coincide_norma(titulo, normas):
    """True si no se detectó ninguna norma citada (no hay por qué filtrar)
    o si el título del subbloque coincide con alguna de las citadas."""
    if not normas:
        return True
    titulo_low = (titulo or "").lower()
    for norma in normas:
        if norma == "constitución":
            if "constituci" in titulo_low:
                return True
        elif norma == "tfue":
            if "tfue" in titulo_low or "funcionamiento de la unión" in titulo_low:
                return True
        elif norma in titulo_low:
            return True
    return False


def _concatenar_subbloques(subbloques):
    """Contexto general del tema (concatenado y truncado a un tope
    razonable) -- fallback para preguntas sin ninguna cita de artículo
    detectable, donde no hay un fragmento concreto que localizar."""
    partes = []
    total = 0
    for sub in subbloques:
        fragmento = f"{sub['titulo']}:\n{sub['texto']}"
        espacio_restante = MAX_CARACTERES_TEXTO_LEGAL_TEMA - total
        if espacio_restante <= 0:
            break
        if len(fragmento) > espacio_restante:
            if not partes:
                # Ni siquiera el primer fragmento cabe entero (subbloque
                # inusualmente largo) -- mejor un recorte parcial que
                # quedarse sin nada de respaldo para esta pregunta.
                partes.append(fragmento[:espacio_restante])
            break
        partes.append(fragmento)
        total += len(fragmento)
    return "\n\n".join(partes) if partes else None


def _subbloques_del_tema(db, oposicion, tema_id):
    """Subbloques reales (BOE) del tema al que pertenece una pregunta, SIN
    truncar ni localizar nada todavía -- reutiliza
    utils.obtener_subbloques_individuales, la MISMA fuente que ya usa Test
    Personalizado como "anclas" (generador_preguntas_verificado.py). []
    si el tema_id está mal formado o no resuelve a contenido real (vacío,
    huérfano, o fuera del temario actual)."""
    if not tema_id or "-" not in tema_id:
        return []
    return obtener_subbloques_individuales(db, [tema_id], coleccion_temario(oposicion))


def _texto_legal_para_pregunta(subbloques, pregunta, opciones, texto_adicional=""):
    """A partir de los subbloques YA cargados del tema (ver
    _subbloques_del_tema), localiza el texto legal real que respalda ESTA
    pregunta concreta -- nunca el tema entero a ciegas (ver docstring del
    módulo: concatenar-y-truncar el tema entero producía ~83% de falsos
    positivos en --verificar). Si la pregunta, las opciones o
    texto_adicional (p. ej. una explicación ya escrita a verificar) citan
    un número de artículo concreto, busca ESE fragmento exacto entre los
    subbloques -- filtrando antes por la norma citada, si se detecta
    alguna, para no confundir un mismo número de artículo de dos normas
    distintas dentro del mismo tema. Si no hay ninguna cita de artículo
    detectable, cae al contexto general del tema (concatenado y
    truncado). Si SÍ hay cita pero no se encuentra en ningún subbloque del
    tema, devuelve None A PROPÓSITO (nunca un texto que no la contiene) --
    quien llama debe seguir sin respaldo para esa pregunta, igual que con
    un tema sin cobertura."""
    if not subbloques:
        return None

    texto_deteccion = "\n".join(
        [pregunta or ""] + list((opciones or {}).values()) + [texto_adicional or ""]
    )
    articulos = _articulos_citados(texto_deteccion)
    if not articulos:
        return _concatenar_subbloques(subbloques)

    normas = _normas_citadas(texto_deteccion)
    candidatos = [s for s in subbloques if _subbloque_coincide_norma(s["titulo"], normas)]
    if not candidatos:
        candidatos = subbloques

    fragmentos = []
    vistos = set()
    for sub in candidatos:
        for frag in _extraer_articulos(sub["texto"]):
            if not frag["articulo"]:
                continue
            numero = frag["articulo"].rsplit(" ", 1)[-1]
            if numero not in articulos:
                continue
            clave = (sub["titulo"], frag["articulo"])
            if clave in vistos:
                continue
            vistos.add(clave)
            fragmentos.append(f"{sub['titulo']}, {frag['articulo']}:\n{frag['texto']}")

    return "\n\n".join(fragmentos) if fragmentos else None


def _prompt_explicacion(pregunta, opciones, respuesta_correcta, problemas_previos=None, texto_legal=None):
    opciones_texto = "\n".join(f"{letra}) {texto}" for letra, texto in sorted(opciones.items()))
    aviso_revision = ""
    if problemas_previos:
        lista = "\n".join(f"- {p}" for p in problemas_previos)
        aviso_revision = (
            "\n\nUn revisor jurídico ya detectó estos problemas en un intento anterior de "
            f"explicar esta misma pregunta -- corrígelos explícitamente esta vez:\n{lista}\n"
        )
    if texto_legal:
        instruccion_fuente = (
            "A continuación tienes el TEXTO LEGAL REAL del tema al que pertenece esta pregunta. "
            "Basa la explicación EXCLUSIVAMENTE en ese texto: cita el artículo exacto que "
            "corresponda en la línea de la respuesta correcta, usando la terminología oficial de "
            "la norma (no sinónimos), y copia cualquier plazo, cifra, órgano o clasificación "
            "EXACTAMENTE como aparece ahí -- nunca completes huecos con conocimiento propio ni te "
            "fíes de una afirmación del enunciado que no encuentres en este texto.\n\n"
            f"TEXTO LEGAL:\n{texto_legal}\n\n"
        )
    else:
        instruccion_fuente = (
            "Si el enunciado o alguna opción ya menciona un artículo o una norma concreta, cítalo en "
            "la línea de la respuesta correcta usando la terminología oficial (no sinónimos). Si NO "
            "se menciona ningún artículo o norma, no inventes ninguna referencia legal -- limítate a "
            "explicar el motivo con tus propios conocimientos de la materia. No afirmes una "
            "clasificación legal exacta (p. ej. si algo pertenece a una categoría concreta de la "
            "norma) salvo que estés seguro de que es así -- en ese caso, formúlalo con matiz en vez "
            "de darlo por hecho sin más.\n\n"
        )
    return (
        "Eres un experto en oposiciones y en legislación española. A continuación tienes una "
        "pregunta REAL de un examen oficial de oposición, con su respuesta correcta ya conocida "
        "y verificada -- no la cuestiones, dala por cierta.\n\n"
        "Escribe la explicación repasando TODAS las opciones, una por línea y en orden, con este "
        "formato exacto: \"A) es correcta/incorrecta porque... B) es correcta/incorrecta "
        "porque... C) ... D) ...\". Cada línea debe ser UNA sola frase breve (máximo 25-30 "
        "palabras) que vaya directa al motivo -- nunca repitas el enunciado de la pregunta ni el "
        "texto de las opciones, ni añadas relleno.\n\n"
        f"{instruccion_fuente}"
        f"{aviso_revision}\n"
        f"Pregunta: {pregunta}\n\n{opciones_texto}\n\n"
        f"Respuesta correcta: {respuesta_correcta}) {opciones.get(respuesta_correcta, '')}\n\n"
        "Devuelve SOLO las 4 líneas de la explicación, sin encabezados, comillas ni texto "
        "adicional."
    )


def _generar_explicacion_mejorada(pregunta, opciones, respuesta_correcta, contexto,
                                   acumulador=None, problemas_previos=None, texto_legal=None):
    """Genera la explicacion nueva y valida que sigue el formato pedido --
    un reintento si la primera respuesta no lo cumple. Devuelve None (sin
    reintentar mas) si sigue sin cumplirlo -- nunca se devuelve una
    explicacion que no pasa su propia validacion."""
    prompt = _prompt_explicacion(pregunta, opciones, respuesta_correcta, problemas_previos, texto_legal)
    for _intento in range(2):
        respuesta = call_deepseek_api(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=350,
            on_usage=acumulador.add if acumulador else None,
            contexto=contexto,
        )
        respuesta = (respuesta or "").strip()
        if _tiene_formato_bueno(respuesta):
            return respuesta
    return None


def _prompt_verificacion(pregunta, opciones, respuesta_correcta, explicacion, texto_legal=None):
    """Con texto_legal (mismo respaldo que _prompt_explicacion), esta
    verificación es tan grounded como _prompt_verificacion_normativo de
    Test Personalizado -- compara la explicación contra el texto real,
    no contra la intuición del modelo. Sin texto_legal (tema sin
    cobertura), se mantiene la autocrítica de siempre: pilla
    contradicciones y afirmaciones demasiado tajantes, pero no puede
    detectar un error que el modelo tampoco sabría corregir por su
    cuenta."""
    opciones_texto = "\n".join(f"{letra}) {texto}" for letra, texto in sorted(opciones.items()))

    if texto_legal:
        intro = (
            "Eres un verificador jurídico independiente. Te llega una pregunta REAL de un examen "
            "oficial (la respuesta correcta ya está verificada, no la cuestiones), una explicación "
            "YA ESCRITA por otro proceso, y el TEXTO LEGAL REAL del tema al que pertenece. No des "
            "por buena la explicación solo porque suena segura: comprueba cada afirmación contra "
            "el texto legal, palabra por palabra, como si la vieras por primera vez.\n\n"
            f"TEXTO LEGAL:\n{texto_legal}\n\n"
        )
        reglas = (
            "Marca la explicación como inválida si detectas CUALQUIERA de estos problemas:\n"
            "1. Cita un artículo que no existe en el texto legal proporcionado.\n"
            "2. El contenido que atribuye a un artículo no coincide con lo que dice ese texto "
            "legal.\n"
            "3. Alguna línea se limita a repetir la premisa de la propia pregunta en vez de "
            "justificar de forma independiente, contrastada con el texto legal, por qué esa opción "
            "es correcta o incorrecta.\n"
            "4. Hay una contradicción entre dos líneas, o entre la línea de la respuesta correcta y "
            "cuál es realmente la letra marcada como correcta.\n"
            "5. Alguna línea no tiene sentido, está incompleta, o no sigue el formato \"A) es "
            "correcta/incorrecta porque...\".\n\n"
            "No marques inválida una explicación solo por ser concisa -- si lo que dice coincide "
            "con el texto legal, es correcta. Solo marca problemas que puedas señalar citando el "
            "propio texto legal proporcionado.\n\n"
        )
    else:
        intro = (
            "Eres un revisor jurídico escéptico, especializado en oposiciones españolas. Te llega "
            "una pregunta REAL de un examen oficial (la respuesta correcta ya está verificada, no "
            "la cuestiones) y una explicación YA ESCRITA por otro proceso, que debes revisar con "
            "ojo crítico -- no la des por buena solo porque suena segura.\n\n"
        )
        reglas = (
            "Marca la explicación como inválida si detectas CUALQUIERA de estos problemas:\n"
            "1. Alguna línea afirma como hecho una clasificación legal exacta (p. ej. que algo "
            "pertenece a una categoría concreta de una norma) que podría no ser precisa o que tiene "
            "matices que la explicación no menciona.\n"
            "2. Alguna línea se limita a repetir la premisa de la propia pregunta en vez de "
            "justificar de forma independiente por qué esa opción es correcta o incorrecta.\n"
            "3. Hay una contradicción entre dos líneas, o entre la línea de la respuesta correcta y "
            "cuál es realmente la letra marcada como correcta.\n"
            "4. Se cita un número de artículo o una norma que, por tu propio conocimiento de la "
            "materia, tienes motivos concretos para creer INCORRECTA -- el artículo no existe, "
            "pertenece a otra norma, o el contenido que la explicación le atribuye no es lo que ese "
            "artículo regula en realidad.\n"
            "5. Alguna línea no tiene sentido, está incompleta, o no sigue el formato \"A) es "
            "correcta/incorrecta porque...\".\n\n"
            "No marques inválida una explicación solo por ser concisa o por no citar ningún artículo "
            "cuando la pregunta tampoco lo hace -- eso es correcto. TAMPOCO marques inválida una cita "
            "de artículo únicamente porque su número no aparece de forma literal en el enunciado o "
            "las opciones -- es normal y deseable que la explicación sea más precisa que la pregunta, "
            "citando el artículo concreto de la norma que ya se menciona. Marca la cita SOLO si crees "
            "de verdad que el número o el contenido atribuido a ese artículo es incorrecto, nunca por "
            "el mero hecho de no estar citado literalmente. Solo marca problemas concretos y "
            "señalables en los que tengas una razón real para dudar, nunca por precaución genérica.\n\n"
        )

    return (
        f"{intro}"
        f"{reglas}"
        "Devuelve ÚNICAMENTE un JSON con esta forma exacta, sin texto adicional:\n"
        '{"valido": true, "problemas": []}\n'
        "Si encuentras algún problema, \"valido\" debe ser false y \"problemas\" debe listar cada "
        "motivo -- cada elemento de \"problemas\" debe ser UNA sola frase breve (máximo 20-25 "
        "palabras).\n\n"
        f"Pregunta: {pregunta}\n\n{opciones_texto}\n\n"
        f"Respuesta correcta: {respuesta_correcta}) {opciones.get(respuesta_correcta, '')}\n\n"
        f"Explicación a revisar:\n{explicacion}"
    )


def _verificar_explicacion(pregunta, opciones, respuesta_correcta, explicacion, contexto,
                            acumulador=None, texto_legal=None):
    """Devuelve (estado, problemas): estado es "valida", "invalida" o
    "sin_verificar" (la IA no devolvió un JSON parseable -- fallo raro/
    transitorio, se deja constancia en vez de darla por buena en
    silencio)."""
    prompt = _prompt_verificacion(pregunta, opciones, respuesta_correcta, explicacion, texto_legal)
    respuesta = call_deepseek_api(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=300,
        response_format_json=True,
        on_usage=acumulador.add if acumulador else None,
        contexto=contexto,
    )
    try:
        datos = json.loads(respuesta or "")
    except (json.JSONDecodeError, TypeError):
        return "sin_verificar", []
    if datos.get("valido", True):
        return "valida", []
    return "invalida", datos.get("problemas", [])


def _recolectar_ya_generadas(db):
    """Como _recolectar_pendientes pero con la condición invertida: las
    preguntas activas cuya explicación YA tiene el formato bueno -- el
    universo que --verificar revisa."""
    listas = {oposicion: [] for oposicion in OPOSICIONES}
    for oposicion in OPOSICIONES:
        coleccion = coleccion_examenes_oficiales(oposicion)
        for doc in db.collection(coleccion).stream():
            d = doc.to_dict() or {}
            if d.get("tipo") != "pregunta":
                continue
            if d.get("activa", True) is False:
                continue
            explicacion = (d.get("explicacion") or "").strip()
            if not _tiene_formato_bueno(explicacion):
                continue
            opciones = d.get("opciones") or {}
            respuesta_correcta = d.get("respuesta_correcta")
            if not opciones or respuesta_correcta not in opciones:
                continue
            listas[oposicion].append({
                "doc_id": doc.id,
                "pregunta": d.get("pregunta", ""),
                "opciones": opciones,
                "respuesta_correcta": respuesta_correcta,
                "explicacion": explicacion,
                "tema_id": d.get("tema_id"),
            })
    return listas


def _subbloques_del_tema_cacheado(db, cache, oposicion, tema_id):
    """Envoltorio de _subbloques_del_tema con caché en memoria por
    (oposicion, tema_id) -- muchas preguntas comparten tema, así que evita
    leer el mismo subbloque de Firestore una vez por pregunta. La
    localización (_texto_legal_para_pregunta) es específica de cada
    pregunta y no se cachea aquí, solo la lectura de Firestore. Una
    posible lectura duplicada puntual entre hilos concurrentes es
    inofensiva (solo repite trabajo, nunca corrompe nada)."""
    clave = (oposicion, tema_id)
    if clave not in cache:
        cache[clave] = _subbloques_del_tema(db, oposicion, tema_id)
    return cache[clave]


def _ejecutar_verificacion(db, aplicar):
    ya_generadas = _recolectar_ya_generadas(db)
    tareas = [(oposicion, item) for oposicion in OPOSICIONES for item in ya_generadas[oposicion]]
    total = len(tareas)
    print("=" * 70)
    print(f"Verificando {total} explicaciones ya generadas con {MAX_WORKERS} hilos en paralelo "
          f"(con respaldo del texto legal real cuando hay cobertura de temario, autocrítica sin "
          f"él en el resto)...")

    acumulador = AcumuladorTokens()
    resultados = {}  # doc_id -> (oposicion, item, estado, problemas)
    cache_subbloques = {}

    def _procesar(oposicion, item):
        subbloques = _subbloques_del_tema_cacheado(db, cache_subbloques, oposicion, item.get("tema_id"))
        texto_legal = _texto_legal_para_pregunta(
            subbloques, item["pregunta"], item["opciones"], item["explicacion"]
        )
        estado, problemas = _verificar_explicacion(
            item["pregunta"], item["opciones"], item["respuesta_correcta"], item["explicacion"],
            contexto=f"verificar-explicacion oposicion={oposicion} doc={item['doc_id']}",
            acumulador=acumulador,
            texto_legal=texto_legal,
        )
        return (oposicion, item, estado, problemas)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futuros = [executor.submit(_procesar, oposicion, item) for oposicion, item in tareas]
        hechas = 0
        for futuro in as_completed(futuros):
            oposicion, item, estado, problemas = futuro.result()
            resultados[item["doc_id"]] = (oposicion, item, estado, problemas)
            hechas += 1
            if hechas % 100 == 0 or hechas == total:
                print(f"  {hechas}/{total} revisadas...")

    invalidas = [r for r in resultados.values() if r[2] == "invalida"]
    validas = [r for r in resultados.values() if r[2] == "valida"]
    sin_verificar = [r for r in resultados.values() if r[2] == "sin_verificar"]

    print(f"\nVálidas: {len(validas)}  ·  Inválidas: {len(invalidas)}  ·  "
          f"Sin verificar (fallo al parsear): {len(sin_verificar)}")
    print(f"Coste de la verificación: {coste_estimado(acumulador.tin, acumulador.tout):.4f} €")

    if invalidas:
        print("\n" + "=" * 70)
        print(f"Ejemplos de explicaciones marcadas inválidas (hasta 10 de {len(invalidas)}):")
        for oposicion, item, _estado, problemas in invalidas[:10]:
            print(f"\n--- [{oposicion}] {item['doc_id']} ---")
            print(f"Pregunta: {item['pregunta']}")
            print(f"\nExplicación actual:\n{item['explicacion']}")
            print("\nProblemas detectados:")
            for p in problemas:
                print(f"   - {p}")

    if not aplicar:
        print("\n" + "=" * 70)
        print("(modo AUDITORÍA: no se ha escrito nada en Firestore. "
              "Lanza con --verificar --aplicar para regenerar las inválidas.)")
        return

    if not invalidas:
        print("\nNada que regenerar.")
        return

    print("\n" + "=" * 70)
    print(f"Regenerando {len(invalidas)} explicaciones inválidas (con el problema detectado como "
          f"pista)...")
    acumulador_regen = AcumuladorTokens()
    actualizadas = 0
    siguen_fallando = []

    def _regenerar(oposicion, item, problemas):
        subbloques = _subbloques_del_tema_cacheado(db, cache_subbloques, oposicion, item.get("tema_id"))
        texto_legal = _texto_legal_para_pregunta(
            subbloques, item["pregunta"], item["opciones"], item["explicacion"]
        )
        nueva = _generar_explicacion_mejorada(
            item["pregunta"], item["opciones"], item["respuesta_correcta"],
            contexto=f"regenerar-tras-verificacion oposicion={oposicion} doc={item['doc_id']}",
            acumulador=acumulador_regen,
            problemas_previos=problemas,
            texto_legal=texto_legal,
        )
        if nueva is None:
            return (oposicion, item["doc_id"], False)
        db.collection(coleccion_examenes_oficiales(oposicion)).document(item["doc_id"]).update(
            {"explicacion": nueva}
        )
        return (oposicion, item["doc_id"], True)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futuros = [
            executor.submit(_regenerar, oposicion, item, problemas)
            for oposicion, item, _estado, problemas in invalidas
        ]
        for futuro in as_completed(futuros):
            oposicion, doc_id, ok = futuro.result()
            if ok:
                actualizadas += 1
            else:
                siguen_fallando.append((oposicion, doc_id))

    print(f"\nRegeneradas {actualizadas} de {len(invalidas)}.")
    if siguen_fallando:
        print(f"{len(siguen_fallando)} siguieron sin poder regenerarse:")
        for oposicion, doc_id in siguen_fallando[:30]:
            print(f"   - [{oposicion}] {doc_id}")

    print(f"\nCoste real de la regeneración: "
          f"{coste_estimado(acumulador_regen.tin, acumulador_regen.tout):.4f} €")
    print(f"Coste total de esta ejecución (verificación + regeneración): "
          f"{coste_estimado(acumulador.tin + acumulador_regen.tin, acumulador.tout + acumulador_regen.tout):.4f} €")


def _recolectar_pendientes(db):
    """Devuelve {oposicion: [ {doc_id, pregunta, opciones, respuesta_correcta,
    explicacion_actual}, ... ]} -- solo las preguntas activas cuya
    explicacion actual no repasa las 4 opciones y cuyos datos son lo
    bastante completos como para generar algo fiable."""
    pendientes = {oposicion: [] for oposicion in OPOSICIONES}
    totales = {oposicion: 0 for oposicion in OPOSICIONES}
    for oposicion in OPOSICIONES:
        coleccion = coleccion_examenes_oficiales(oposicion)
        for doc in db.collection(coleccion).stream():
            d = doc.to_dict() or {}
            if d.get("tipo") != "pregunta":
                continue
            if d.get("activa", True) is False:
                continue
            totales[oposicion] += 1
            explicacion_actual = (d.get("explicacion") or "").strip()
            if _tiene_formato_bueno(explicacion_actual):
                continue
            opciones = d.get("opciones") or {}
            respuesta_correcta = d.get("respuesta_correcta")
            if not opciones or respuesta_correcta not in opciones:
                continue
            pendientes[oposicion].append({
                "doc_id": doc.id,
                "pregunta": d.get("pregunta", ""),
                "opciones": opciones,
                "respuesta_correcta": respuesta_correcta,
                "explicacion_actual": explicacion_actual,
                "tema_id": d.get("tema_id"),
            })
    return pendientes, totales


def _auditar(db):
    pendientes, totales = _recolectar_pendientes(db)
    print("=" * 70)
    total_pendientes = 0
    for oposicion in OPOSICIONES:
        n_pend = len(pendientes[oposicion])
        total_pendientes += n_pend
        print(f"[{oposicion}] preguntas activas: {totales[oposicion]}  ·  "
              f"necesitan regenerar explicación: {n_pend}")
    print(f"\nTOTAL a regenerar: {total_pendientes}")

    if total_pendientes:
        print("\n" + "=" * 70)
        print(f"MUESTRA de antes/después (llamada real a la IA, coste mínimo -- "
              f"no se escribe nada en Firestore):")
        acumulador = AcumuladorTokens()
        cache_subbloques = {}
        for oposicion in OPOSICIONES:
            muestra = pendientes[oposicion][:MUESTRAS_AUDITORIA_POR_OPOSICION]
            for item in muestra:
                subbloques = _subbloques_del_tema_cacheado(db, cache_subbloques, oposicion, item.get("tema_id"))
                texto_legal = _texto_legal_para_pregunta(
                    subbloques, item["pregunta"], item["opciones"], item.get("explicacion_actual")
                )
                nueva = _generar_explicacion_mejorada(
                    item["pregunta"], item["opciones"], item["respuesta_correcta"],
                    contexto=f"auditoria-explicacion oposicion={oposicion} doc={item['doc_id']}",
                    acumulador=acumulador,
                    texto_legal=texto_legal,
                )
                print(f"\n[respaldo: {'texto legal real' if texto_legal else 'sin cobertura de temario'}]")
                print(f"\n--- [{oposicion}] {item['doc_id']} ---")
                print(f"Pregunta: {item['pregunta']}")
                for letra, texto in sorted(item["opciones"].items()):
                    marca = " <- correcta" if letra == item["respuesta_correcta"] else ""
                    print(f"   {letra}) {texto}{marca}")
                print(f"\nANTES:\n{item['explicacion_actual'] or '(vacía)'}")
                print(f"\nDESPUÉS:\n{nueva or '(la IA no siguió el formato pedido ni al reintentar)'}")
        print(f"\nCoste de la muestra: {coste_estimado(acumulador.tin, acumulador.tout):.4f} €")
        # Estimación grosera del coste total a partir del coste medio real
        # de la muestra generada -- solo orientativa, el coste final tras
        # --aplicar se imprime con el gasto real acumulado.
        if acumulador.llamadas:
            coste_medio = coste_estimado(acumulador.tin, acumulador.tout) / acumulador.llamadas
            print(f"Coste estimado de regenerar las {total_pendientes} pendientes: "
                  f"~{coste_medio * total_pendientes:.2f} €")

    print("\n" + "=" * 70)
    print("(modo AUDITORÍA: no se ha escrito nada en Firestore. "
          "Lanza con --aplicar para regenerar de verdad.)")
    return pendientes


def _aplicar(db, pendientes):
    tareas = [
        (oposicion, item)
        for oposicion in OPOSICIONES
        for item in pendientes[oposicion]
    ]
    total = len(tareas)
    if not total:
        print("Nada pendiente, no hay nada que aplicar.")
        return

    print(f"Regenerando {total} explicaciones con {MAX_WORKERS} hilos en paralelo...")
    acumulador = AcumuladorTokens()
    actualizadas = 0
    fallidas = []
    cache_subbloques = {}

    def _procesar(oposicion, item):
        subbloques = _subbloques_del_tema_cacheado(db, cache_subbloques, oposicion, item.get("tema_id"))
        texto_legal = _texto_legal_para_pregunta(
            subbloques, item["pregunta"], item["opciones"], item.get("explicacion_actual")
        )
        nueva = _generar_explicacion_mejorada(
            item["pregunta"], item["opciones"], item["respuesta_correcta"],
            contexto=f"regenerar-explicacion oposicion={oposicion} doc={item['doc_id']}",
            acumulador=acumulador,
            texto_legal=texto_legal,
        )
        if nueva is None:
            return (oposicion, item["doc_id"], False)
        db.collection(coleccion_examenes_oficiales(oposicion)).document(item["doc_id"]).update(
            {"explicacion": nueva}
        )
        return (oposicion, item["doc_id"], True)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futuros = [executor.submit(_procesar, oposicion, item) for oposicion, item in tareas]
        hechas = 0
        for futuro in as_completed(futuros):
            oposicion, doc_id, ok = futuro.result()
            hechas += 1
            if ok:
                actualizadas += 1
            else:
                fallidas.append((oposicion, doc_id))
            if hechas % 100 == 0 or hechas == total:
                print(f"  {hechas}/{total} procesadas ({actualizadas} actualizadas, "
                      f"{len(fallidas)} fallidas)...")

    print(f"\nActualizadas {actualizadas} de {total}.")
    if fallidas:
        print(f"{len(fallidas)} preguntas fallidas (la IA no siguió el formato ni al "
              f"reintentar -- se dejaron sin tocar, vuelve a lanzar el script para "
              f"reintentarlas):")
        for oposicion, doc_id in fallidas[:30]:
            print(f"   - [{oposicion}] {doc_id}")
        if len(fallidas) > 30:
            print(f"   ... y {len(fallidas) - 30} más")

    print(f"\nCoste real de esta ejecución: {coste_estimado(acumulador.tin, acumulador.tout):.4f} €"
          f"  ({acumulador.llamadas} llamadas, {acumulador.tin} tokens entrada, "
          f"{acumulador.tout} tokens salida)")


def _auditar_cobertura_temario(db):
    """Solo lectura de Firestore, SIN ninguna llamada a DeepSeek -- mide
    para cuántas preguntas activas de exámenes oficiales el tema_id ya
    asignado resuelve a texto legal real y recuperable del temario, antes
    de invertir nada en generación/verificación respaldada por ese
    texto."""
    print("=" * 70)
    print("Auditoría de cobertura de temario (solo lectura, sin llamadas a IA)...")
    total_general = 0
    con_texto_general = 0
    for oposicion in OPOSICIONES:
        coleccion = coleccion_examenes_oficiales(oposicion)
        total = 0
        sin_tema = 0
        con_texto = 0
        temas_vistos = {}  # tema_id -> bool (resuelve a contenido)
        for doc in db.collection(coleccion).stream():
            d = doc.to_dict() or {}
            if d.get("tipo") != "pregunta" or d.get("activa", True) is False:
                continue
            total += 1
            tema_id = d.get("tema_id")
            if not tema_id:
                sin_tema += 1
                continue
            if tema_id not in temas_vistos:
                temas_vistos[tema_id] = bool(_subbloques_del_tema(db, oposicion, tema_id))
            if temas_vistos[tema_id]:
                con_texto += 1
        total_general += total
        con_texto_general += con_texto
        pct = (con_texto / total * 100) if total else 0
        temas_con_contenido = sum(1 for v in temas_vistos.values() if v)
        print(f"[{oposicion}] preguntas activas: {total}  ·  sin tema_id: {sin_tema}  ·  "
              f"con texto legal recuperable: {con_texto} ({pct:.1f}%)  ·  "
              f"temas distintos usados: {len(temas_vistos)} ({temas_con_contenido} con contenido)")

    pct_general = (con_texto_general / total_general * 100) if total_general else 0
    print(f"\nTOTAL: {con_texto_general}/{total_general} preguntas con texto legal recuperable "
          f"({pct_general:.1f}%).")
    print("\n" + "=" * 70)
    print("(auditoría de cobertura: solo lectura, no se ha llamado a ninguna IA ni escrito nada.)")


def main(aplicar, verificar, cobertura):
    _init_firebase()
    db = firestore.client()

    if cobertura:
        _auditar_cobertura_temario(db)
        return

    if verificar:
        _ejecutar_verificacion(db, aplicar)
        return

    pendientes = _auditar(db)
    if not aplicar:
        return

    total_pendientes = sum(len(v) for v in pendientes.values())
    if not total_pendientes:
        return

    print("\n" + "=" * 70)
    _aplicar(db, pendientes)

    print("\n" + "=" * 70)
    print("DESPUÉS de aplicar:")
    _auditar(db)


if __name__ == "__main__":
    _args = sys.argv[1:]
    main(
        aplicar="--aplicar" in _args,
        verificar="--verificar" in _args,
        cobertura="--cobertura" in _args,
    )
