import random
import re
import time
import tiktoken
from typing import List, Dict
from google.cloud import firestore

from oposiciones import coleccion_examenes_oficiales

# ✅ Cuenta los tokens de un texto
def contar_tokens(texto: str, modelo="gpt-3.5-turbo") -> int:
    try:
        encoding = tiktoken.encoding_for_model(modelo)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(texto))


def ejecutar_en_transaccion(db, fn):
    """Ejecuta fn(transaction) dentro de una transacción de Firestore, para
    que una lectura seguida de una escritura (p. ej. "lee el contador,
    súmale 1, escribe") sea atómica frente a otra petición concurrente del
    mismo usuario (dos pestañas, un reintento del frontend) -- sin esto,
    dos peticiones podían leer el mismo valor y perder un incremento.

    Con el cliente real de Firestore, delega en @firestore.transactional
    (reintentos automáticos ante conflictos incluidos). El FakeFirestore
    de los tests no tiene esa maquinaria (exigiría replicar métodos
    internos de la Transaction real solo para simular una concurrencia que
    no existe en un test secuencial de un solo hilo), así que ahí se
    detecta por duck typing (ver FakeTransaction en tests/fakes.py) y se
    llama a fn directamente."""
    transaction = db.transaction()
    if hasattr(transaction, "_begin"):
        @firestore.transactional
        def _en_transaccion_real(transaction):
            return fn(transaction)
        return _en_transaccion_real(transaction)
    return fn(transaction)

# ✅ Agrupa subbloques por tema para prompts largos (estructura anterior, por si la usas aún)
def agrupar_subbloques_por_tema(db, temas: List[str], limite_tokens=3000, coleccion="Temario AGE") -> Dict[str, List[List[dict]]]:
    resultado = {}
    for tema_completo in temas:
        if "-" not in tema_completo:
            continue
        bloque_id, tema_id = tema_completo.split("-", 1)
        subbloques_ref = db.collection(coleccion).document(bloque_id).collection("temas").document(tema_id).collection("subbloques").stream()
        grupo_actual = []
        total_tokens = 0
        todos_grupos = []

        for sub in subbloques_ref:
            datos = sub.to_dict()
            if not datos:
                continue
            texto = datos.get("texto", "").strip()
            titulo = datos.get("titulo", "")
            etiqueta = f"{bloque_id}-{tema_id}-{sub.id}"
            tokens = contar_tokens(texto)

            if tokens > limite_tokens:
                todos_grupos.append([{"etiqueta": etiqueta, "titulo": titulo, "texto": texto}])
                continue

            if total_tokens + tokens > limite_tokens:
                todos_grupos.append(grupo_actual)
                grupo_actual = []
                total_tokens = 0

            grupo_actual.append({"etiqueta": etiqueta, "titulo": titulo, "texto": texto})
            total_tokens += tokens

        if grupo_actual:
            todos_grupos.append(grupo_actual)
        resultado[tema_completo] = todos_grupos
    return resultado

# ✅ Obtiene el contexto completo de varios temas para usarlo en respuestas IA
def obtener_contexto_por_temas(db, temas, token_limit=3000, coleccion="Temario AGE"):
    contexto_total = ""
    usados = set()

    bloques = db.collection(coleccion).list_documents()

    for bloque_doc in bloques:
        temas_ref = bloque_doc.collection("temas")
        for tema in temas:
            tema_doc = temas_ref.document(tema).get()
            if not tema_doc.exists:
                continue
            subbloques_ref = temas_ref.document(tema).collection("subbloques")
            subbloques = subbloques_ref.stream()

            for sub in subbloques:
                sub_id = f"{bloque_doc.id}-{tema}-{sub.id}"
                if sub_id in usados:
                    continue
                usados.add(sub_id)

                texto = sub.to_dict().get("texto", "")
                titulo = sub.to_dict().get("titulo", "")
                fragmento = f"[{sub_id}]\n{titulo}\n{texto.strip()}\n"
                if contar_tokens(contexto_total + fragmento) > token_limit:
                    return contexto_total.strip()
                contexto_total += fragmento

    return contexto_total.strip()

# El temario apenas cambia (solo cuando se recarga a mano desde un script),
# así que catálogo y resumen se cachean en memoria un rato en vez de
# recorrer TODO el temario en cada mensaje de Tu Tutor o cada llamada a
# /temas-disponibles.
_CACHE_TEMARIO = {}
_TTL_CACHE_TEMARIO_SEGUNDOS = 300


def _limpiar_cache_temario():
    """Vacía la caché en memoria del catálogo/resumen de temario. Se
    engancha al fixture autouse de tests (ver conftest.py) para que cada
    test siga viendo datos frescos del FakeFirestore, que sí se resetea
    por test -- sin esto, el primer test que llenase la caché dejaría
    datos obsoletos para los siguientes."""
    _CACHE_TEMARIO.clear()


def _desde_cache_o_calcular(clave, calcular):
    ahora = time.time()
    en_cache = _CACHE_TEMARIO.get(clave)
    if en_cache is not None:
        timestamp, valor = en_cache
        if ahora - timestamp < _TTL_CACHE_TEMARIO_SEGUNDOS:
            return valor
    valor = calcular()
    _CACHE_TEMARIO[clave] = (ahora, valor)
    return valor


# ✅ Catálogo (bloque + tema, con sus títulos) de una oposición, para poder
# detectar si un mensaje del usuario menciona un tema concreto sin tener
# que descargar el contenido completo del temario.
def obtener_catalogo_temas(db, coleccion="Temario AGE") -> List[dict]:
    def _calcular():
        catalogo = []
        for bloque in db.collection(coleccion).stream():
            bloque_titulo = (bloque.to_dict() or {}).get("titulo", bloque.id)
            temas_ref = db.collection(coleccion).document(bloque.id).collection("temas").stream()
            for tema in temas_ref:
                titulo = (tema.to_dict() or {}).get("titulo", tema.id)
                catalogo.append({"id": f"{bloque.id}-{tema.id}", "titulo": titulo, "bloque_titulo": bloque_titulo})
        return catalogo
    return _desde_cache_o_calcular(("catalogo", coleccion), _calcular)

# ✅ Datos oficiales de la convocatoria vigente (plazas, estructura de los
# ejercicios, tiempos, penalización, calificación), transcritos a mano de las
# normas específicas publicadas en el BOE -- para que Tu Tutor no tenga que
# adivinar estas cifras ni inventarlas. Un único documento por oposición en
# la colección "datos_convocatoria", con un campo "texto" ya redactado para
# inyectar tal cual en el prompt (ver cargar_datos_convocatoria.py).
def obtener_datos_convocatoria(db, oposicion):
    doc = db.collection("datos_convocatoria").document(oposicion).get()
    if not doc.exists:
        return None
    return (doc.to_dict() or {}).get("texto")

_NUMEROS_ROMANOS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]

# ✅ Estructura REAL del temario (bloques y temas tal y como están cargados en
# Firestore), en texto listo para inyectar en el prompt de Tu Tutor -- para
# que describa el temario a partir de los datos reales en vez de un resumen
# escrito a mano que puede quedar desactualizado. Se agrupa por bloque y se
# ordena por el id del documento (bloque_01, bloque_02... / tema_01, tema_02...)
# ya que stream() no garantiza ningún orden.
def obtener_resumen_temario(db, coleccion="Temario AGE"):
    def _calcular():
        bloques = {}
        for bloque in db.collection(coleccion).stream():
            bloque_titulo = (bloque.to_dict() or {}).get("titulo", bloque.id)
            temas = []
            for tema in db.collection(coleccion).document(bloque.id).collection("temas").stream():
                titulo = (tema.to_dict() or {}).get("titulo", tema.id)
                temas.append((tema.id, titulo))
            if not temas:
                continue
            temas.sort(key=lambda t: t[0])
            bloques[bloque.id] = (bloque_titulo, temas)

        if not bloques:
            return None

        lineas = []
        for indice, bloque_id in enumerate(sorted(bloques.keys())):
            bloque_titulo, temas = bloques[bloque_id]
            numero_romano = _NUMEROS_ROMANOS[indice] if indice < len(_NUMEROS_ROMANOS) else str(indice + 1)
            lineas.append(f"Bloque {numero_romano}. {bloque_titulo} ({len(temas)} temas)")
            for numero, (_tema_id, titulo) in enumerate(temas, start=1):
                lineas.append(f"  {numero}. {titulo}")
        return "\n".join(lineas)
    return _desde_cache_o_calcular(("resumen", coleccion), _calcular)

# ✅ Contexto de temas identificados por su id combinado "bloque_id-tema_id"
# (a diferencia de obtener_contexto_por_temas, que solo recibe el tema_id y
# por tanto no distingue entre bloques distintos que reutilicen el mismo
# tema_id). La usa el detector de temas mencionados de Tu Tutor.
def obtener_contexto_por_temas_exactos(db, temas_combinados: List[str], token_limit=3000, coleccion="Temario AGE") -> str:
    contexto_total = ""
    for tema_completo in temas_combinados:
        if "-" not in tema_completo:
            continue
        bloque_id, tema_id = tema_completo.split("-", 1)
        subbloques = db.collection(coleccion).document(bloque_id).collection("temas") \
                       .document(tema_id).collection("subbloques").stream()
        for sub in subbloques:
            datos = sub.to_dict() or {}
            texto = datos.get("texto", "").strip()
            titulo = datos.get("titulo", "")
            fragmento = f"[{tema_completo}-{sub.id}]\n{titulo}\n{texto}\n"
            if contar_tokens(contexto_total + fragmento) > token_limit:
                return contexto_total.strip()
            contexto_total += fragmento
    return contexto_total.strip()

# ✅ NUEVA: Extrae todos los subbloques de todos los temas sin límite de tokens acumulados
def obtener_subbloques_individuales(db, temas: List[str], coleccion="Temario AGE") -> List[dict]:
    subbloques_utilizados = []

    for tema_completo in temas:
        if "-" not in tema_completo:
            continue

        bloque_id, tema_id = tema_completo.split("-", 1)
        temas_ref = db.collection(coleccion).document(bloque_id).collection("temas")
        subbloques_ref = temas_ref.document(tema_id).collection("subbloques").stream()

        for sub in subbloques_ref:
            datos = sub.to_dict()
            if not datos:
                continue
            texto = datos.get("texto", "").strip()
            if len(texto.split()) < 30:
                continue
            if contar_tokens(texto) > 3000:
                texto = texto[:4000]  # recorte de seguridad

            subbloques_utilizados.append({
                "etiqueta": f"{bloque_id}-{tema_id}-{sub.id}",
                "titulo": datos.get("titulo", ""),
                "texto": texto
            })

    return subbloques_utilizados


def calcular_resultado_test(aciertos, fallos, blancos):
    """Único criterio de "aprobado/suspendido" de toda la web, replicando
    la tipología oficial de corrección de los exámenes (aciertos menos
    fallos/3, sobre el total de preguntas -- las respuestas en blanco no
    penalizan, pero sí cuentan en el total). Antes existían 3 versiones
    distintas de este cálculo (guardar_resultado.py, resultados-test.js y
    registro_progreso_usuario.py) que no siempre coincidían entre sí."""
    puntuacion = round(aciertos - (fallos / 3), 2)
    total = aciertos + fallos + blancos
    nota_sobre_10 = round((puntuacion / total) * 10, 2) if total else 0.0
    resultado = "aprobado" if nota_sobre_10 >= 5 else "suspendido"
    return puntuacion, nota_sobre_10, resultado


def repartir_cupos_por_tema(temas_ids, cantidad):
    """Reparte 'cantidad' unidades lo más equitativamente posible entre
    temas_ids (división entera + resto). Se baraja el orden antes de asignar
    el resto para que este no recaiga siempre sobre los mismos temas.
    Compartido por la generación del test personalizado
    (generador_preguntas_verificado.py) y la selección de preguntas
    oficiales por tema (ver
    seleccionar_preguntas_con_cuota más abajo), para que elegir varios temas
    reparta el test entre ellos en vez de dejar que gane el que más
    contenido tenga cargado."""
    ids = list(temas_ids)
    if not ids:
        return {}
    random.shuffle(ids)
    base, resto = divmod(cantidad, len(ids))
    return {tid: base + (1 if i < resto else 0) for i, tid in enumerate(ids)}


def calcular_pesos_reales_por_bloque(db, oposicion):
    """Peso relativo (0-1) de cada bloque según cuántas preguntas de
    exámenes oficiales YA CARGADOS (examenes_oficiales_<oposicion>,
    etiquetadas con tema_id "bloque_XX-tema_YY") pertenecen a cada uno --
    la mejor aproximación disponible al peso real de cada bloque en el
    examen. Para AGE esta cuenta empírica ya coincide de hecho con el peso
    oficial publicado en el BOE (ver datos_convocatoria_AGE.json): el
    bloque de informática concentra ~40% de las preguntas históricas
    cargadas, muy cerca del 30/70≈43% documentado. Para GACE el BOE no
    publica ningún desglose por bloque, así que esta cuenta empírica es la
    única fuente disponible. Si la oposición todavía no tiene ningún
    examen oficial cargado (p. ej. Auxiliar), devuelve {} y quien la use
    debe caer de vuelta a un reparto equitativo.

    Se cachea con el mismo TTL que el resto del temario (ver
    _desde_cache_o_calcular) porque los exámenes oficiales solo cambian al
    cargar una convocatoria nueva a mano."""
    def _calcular():
        coleccion = coleccion_examenes_oficiales(oposicion)
        contador = {}
        for doc in db.collection(coleccion).stream():
            d = doc.to_dict() or {}
            if d.get("tipo") != "pregunta":
                continue
            tema_id = d.get("tema_id") or ""
            if "-" not in tema_id:
                continue
            bloque_id = tema_id.split("-")[0]
            contador[bloque_id] = contador.get(bloque_id, 0) + 1
        total = sum(contador.values())
        if not total:
            return {}
        return {b: c / total for b, c in contador.items()}
    return _desde_cache_o_calcular(("pesos_bloque", oposicion), _calcular)


def _repartir_por_peso(ids, cantidad, pesos_norm):
    """Reparto proporcional de 'cantidad' unidades ENTERAS entre ids según
    pesos_norm (método del resto mayor / Hamilton): cada id recibe
    primero la parte entera de cantidad*peso, y las unidades que faltan
    por el redondeo se asignan a quienes tuvieran el resto decimal más
    alto -- así la suma final cuadra siempre con 'cantidad' exacto, en vez
    de perder o sobrar unidades al redondear cada peso por separado."""
    crudo = {i: cantidad * pesos_norm.get(i, 0) for i in ids}
    base = {i: int(v) for i, v in crudo.items()}
    restante = cantidad - sum(base.values())
    orden_restos = sorted(ids, key=lambda i: crudo[i] - base[i], reverse=True)
    for i in orden_restos[:restante]:
        base[i] += 1
    return base


def repartir_cupos_por_tema_realista(temas_ids, cantidad, pesos_por_bloque):
    """Alternativa a repartir_cupos_por_tema que, en vez de repartir
    'cantidad' a partes iguales entre TEMAS, reparte primero entre los
    BLOQUES representados en temas_ids según su peso real
    (pesos_por_bloque, ver calcular_pesos_reales_por_bloque) y solo
    entonces reparte el cupo de cada bloque a partes iguales entre sus
    temas seleccionados -- no existe ninguna fuente fiable de peso más
    fina que a nivel de bloque (el BOE tampoco la publica). Un bloque sin
    datos históricos (o si pesos_por_bloque está vacío del todo, p. ej.
    Auxiliar) recibe el peso medio de los demás bloques seleccionados, en
    vez de quedarse sin preguntas."""
    ids = list(temas_ids)
    if not ids:
        return {}
    temas_por_bloque = {}
    for tid in ids:
        bloque_id = tid.split("-")[0] if "-" in tid else tid
        temas_por_bloque.setdefault(bloque_id, []).append(tid)

    bloques = list(temas_por_bloque.keys())
    pesos_conocidos = [pesos_por_bloque[b] for b in bloques if pesos_por_bloque.get(b)]
    peso_medio = (sum(pesos_conocidos) / len(pesos_conocidos)) if pesos_conocidos else (1 / len(bloques))
    pesos = {b: pesos_por_bloque.get(b) or peso_medio for b in bloques}
    total_peso = sum(pesos.values()) or 1
    pesos_norm = {b: p / total_peso for b, p in pesos.items()}

    cupos_bloque = _repartir_por_peso(bloques, cantidad, pesos_norm)

    cupos = {}
    for bloque_id, cupo_bloque in cupos_bloque.items():
        cupos.update(repartir_cupos_por_tema(temas_por_bloque[bloque_id], cupo_bloque))
    return cupos


def seleccionar_preguntas_con_cuota(preguntas, num_preguntas, temas_filtro=None, modo_reparto="equitativo", pesos_por_bloque=None):
    """Selecciona num_preguntas de una lista ya completa de preguntas (cada
    una con su propio campo 'tema_id'), repartiendo entre los temas de
    temas_filtro que sí tengan preguntas disponibles. Si temas_filtro es
    None/vacío, se comporta como el muestreo aleatorio simple de siempre
    (sin tema elegido = sin filtrar; con exámenes reales completos
    cargados esto ya sale ponderado por sí solo, al venir de la
    distribución real de las convocatorias). Con temas_filtro, modo_reparto
    decide si el cupo se reparte a partes iguales entre temas
    ("equitativo", por defecto) o según el peso real de cada bloque
    ("realista", requiere pesos_por_bloque -- ver
    calcular_pesos_reales_por_bloque). Usado por /generar-test-oficial."""
    if not temas_filtro:
        return random.sample(preguntas, min(num_preguntas, len(preguntas)))

    filtro = set(temas_filtro)
    pendientes_por_tema = {}
    for p in preguntas:
        tid = p.get("tema_id")
        if tid in filtro:
            pendientes_por_tema.setdefault(tid, []).append(p)
    for lista in pendientes_por_tema.values():
        random.shuffle(lista)

    seleccionadas = []
    candidatos = list(pendientes_por_tema.keys())
    restante = num_preguntas
    while restante > 0 and candidatos:
        if modo_reparto == "realista":
            cupos = repartir_cupos_por_tema_realista(candidatos, restante, pesos_por_bloque or {})
        else:
            cupos = repartir_cupos_por_tema(candidatos, restante)
        avance = 0
        for tid, cupo in cupos.items():
            tomadas = pendientes_por_tema[tid][:cupo]
            del pendientes_por_tema[tid][:cupo]
            seleccionadas.extend(tomadas)
            avance += len(tomadas)
        restante -= avance
        if avance == 0:
            break
        candidatos = [tid for tid in candidatos if pendientes_por_tema[tid]]

    random.shuffle(seleccionadas)  # no dejar el orden agrupado por tema
    return seleccionadas


def obtener_titulos_temas_reales(db, coleccion, lista_codigos):
    """Traduce códigos "bloque-tema" (p. ej. "bloque_01-tema_02") a sus
    títulos reales guardados en Firestore -- la misma fuente que usa
    /temas-disponibles -- en vez de una lista fija en el código que solo
    cubría los temas de AGE y no servía para el resto de oposiciones.

    Antes hacía un .get() por código en un bucle (N peticiones a
    Firestore para N códigos); ahora se piden todos de una vez con
    get_all(), una sola llamada. get_all() no garantiza que el orden de
    las instantáneas devueltas coincida con el de las referencias
    pedidas, así que se emparejan por el "path" de cada referencia, no
    por posición."""
    titulos = [None] * len(lista_codigos)
    refs = []
    por_path = {}
    for indice, codigo in enumerate(lista_codigos):
        partes = codigo.split("-", 1)
        if len(partes) < 2:
            titulos[indice] = codigo
            continue
        bloque_id, tema_id = partes
        ref = db.collection(coleccion).document(bloque_id).collection("temas").document(tema_id)
        refs.append(ref)
        por_path[ref.path] = (indice, codigo)

    for doc in db.get_all(refs):
        indice, codigo = por_path[doc.reference.path]
        titulos[indice] = doc.to_dict().get("titulo", codigo) if doc.exists else codigo

    return titulos


_LETRAS_OPCION = ["A", "B", "C", "D"]


def _remapear_explicacion_por_letra(explicacion, mapa_original_a_nueva):
    """La explicación de una pregunta de test se pide con el patrón
    "A) ... B) ... C) ... D) ...", una línea por opción en el orden
    ORIGINAL que decidió la IA. Al barajar las opciones hay que reescribir
    esos prefijos de letra para que sigan señalando a la opción correcta --
    si no, tras barajar, la explicación podría decir "B) es correcta" sobre
    una opción que ahora es la C."""
    texto = (explicacion or "").strip()
    if not re.match(r"^[A-D]\)\s", texto):
        return explicacion  # no sigue el formato esperado: se deja tal cual
    partes = re.split(r"\s(?=[A-D]\)\s)", texto)
    segmentos = {}
    for parte in partes:
        m = re.match(r"^([A-D])\)\s*(.*)$", parte, re.DOTALL)
        if not m:
            return explicacion  # forma inesperada: no arriesgar a corromper el texto
        segmentos[m.group(1)] = m.group(2)
    if set(segmentos) != set(_LETRAS_OPCION):
        return explicacion
    inversa = {nueva: original for original, nueva in mapa_original_a_nueva.items()}
    return " ".join(f"{letra}) {segmentos[inversa[letra]]}" for letra in _LETRAS_OPCION)


def barajar_opciones_pregunta(pregunta):
    """Los LLM tienden a poner la respuesta correcta en la opción A con
    mucha más frecuencia de la que correspondería al azar (sesgo de
    posición ya documentado en generación con IA) -- sin este barajado, un
    usuario que haga suficientes tests de una herramienta con IA podría
    acabar detectando el patrón y aprobando sin saberse el temario. Se
    baraja la posición de las 4 opciones con random.shuffle (nunca decidido
    por la IA) y se remapean tanto "respuesta_correcta" como la explicación
    para que sigan señalando a la opción que corresponde. Usada por los tres
    generadores de test con IA (temario oficial, PDF subido, test
    "inteligente")."""
    opciones = pregunta.get("opciones")
    if not isinstance(opciones, dict) or set(opciones.keys()) != set(_LETRAS_OPCION):
        return pregunta  # forma inesperada: no arriesgar a corromper la pregunta
    correcta_original = pregunta.get("respuesta_correcta")
    permutacion = list(_LETRAS_OPCION)
    random.shuffle(permutacion)
    mapa_original_a_nueva = {permutacion[i]: _LETRAS_OPCION[i] for i in range(4)}
    pregunta["opciones"] = {_LETRAS_OPCION[i]: opciones[permutacion[i]] for i in range(4)}
    if correcta_original in mapa_original_a_nueva:
        pregunta["respuesta_correcta"] = mapa_original_a_nueva[correcta_original]
    pregunta["explicacion"] = _remapear_explicacion_por_letra(pregunta.get("explicacion"), mapa_original_a_nueva)
    return pregunta

