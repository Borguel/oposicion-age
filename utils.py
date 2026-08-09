import logging
import random
import re
import time
import tiktoken
from typing import List, Dict, Tuple
from google.cloud import firestore

from oposiciones import coleccion_examenes_oficiales, coleccion_psicotecnico
from banco_preguntas_ia import coleccion_banco_preguntas

logger = logging.getLogger(__name__)

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


def invalidar_cache(clave):
    """Elimina UNA entrada concreta de la caché en memoria compartida (ver
    _desde_cache_o_calcular) sin tocar el resto -- para cuando solo hace
    falta invalidar lo que acaba de cambiar (p. ej. el banco de preguntas
    IA de una oposición) sin forzar un recálculo innecesario de todo lo
    demás cacheado (temario, pesos por bloque, exámenes oficiales de otras
    oposiciones...), que es lo que haría _limpiar_cache_temario()."""
    _CACHE_TEMARIO.pop(clave, None)


def limpiar_cache_preguntas_banco_ia(oposicion):
    """Invalida en ESTE proceso la caché de obtener_preguntas_banco_ia para
    `oposicion`. Se llama justo después de guardar una pregunta nueva en el
    banco (ver generador_preguntas_verificado.py) para que la siguiente
    consulta de Tu Tutor (buscar_pregunta_banco_ia) la vea sin esperar al
    TTL -- antes de esto, un test personalizado recién generado no era
    encontrado por su propio Tu Tutor durante hasta 30 min (bug real visto
    en producción).

    Limitación conocida y aceptada: esta caché es un dict en memoria POR
    PROCESO. Con varios workers de Gunicorn, esto solo limpia la copia del
    proceso donde corrió la generación -- los demás workers seguirán
    sirviendo su copia cacheada hasta que venza su propio TTL. Por eso el
    TTL de obtener_preguntas_banco_ia se ha acortado (ver más abajo) en vez
    de asumir que esta invalidación por sí sola resuelve el problema en
    todos los workers."""
    invalidar_cache(("preguntas_banco_ia", oposicion))


def _desde_cache_o_calcular(clave, calcular, ttl_segundos=None):
    ttl = ttl_segundos if ttl_segundos is not None else _TTL_CACHE_TEMARIO_SEGUNDOS
    ahora = time.time()
    en_cache = _CACHE_TEMARIO.get(clave)
    if en_cache is not None:
        timestamp, valor = en_cache
        if ahora - timestamp < ttl:
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


# Temas navegables (bloque_id y bloque_titulo por separado, respetando
# "publicado" a nivel de bloque y de tema) para el selector de Test
# Personalizado/Test Oficial -- 07/08/2026: antes /temas-disponibles hacía
# esta misma consulta N+1 (una lectura de "temas" por cada bloque) sin
# ninguna caché en cada carga de esas páginas; usa el mismo store que
# obtener_catalogo_temas (ver _desde_cache_o_calcular) así que ya se
# invalida sola con las llamadas a _limpiar_cache_temario() que hace el
# panel admin al editar el temario. No se reutiliza obtener_catalogo_temas
# directamente porque esa no filtra "publicado" ni expone bloque_id aparte
# -- son formas del mismo dato para consumidores distintos (Tu Tutor vs.
# navegación de usuario), no el mismo cálculo.
def obtener_temas_navegables(db, coleccion) -> List[dict]:
    def _calcular():
        temas_disponibles = []
        for bloque in db.collection(coleccion).stream():
            bloque_id = bloque.id
            bloque_dict = bloque.to_dict() or {}
            if bloque_dict.get("publicado", True) is False:
                continue
            bloque_titulo = bloque_dict.get("titulo", bloque_id)
            temas_ref = db.collection(coleccion).document(bloque_id).collection("temas").stream()
            for tema in temas_ref:
                tema_data = tema.to_dict()
                tema_id = tema.id
                if tema_data.get("publicado", True) is False:
                    continue
                titulo = tema_data.get("titulo", f"{tema_id}")
                temas_disponibles.append({
                    "id": f"{bloque_id}-{tema_id}",
                    "titulo": titulo,
                    "bloque_id": bloque_id,
                    "bloque_titulo": bloque_titulo,
                })
        return temas_disponibles
    return _desde_cache_o_calcular(("temas_navegables", coleccion), _calcular)

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
def _puntuar_relevancia_subbloque(texto, tokens_mensaje):
    """Solapamiento de palabras significativas (>=4 letras, para que
    "el"/"la"/"de" no infle por igual la puntuación de todos los
    subbloques) entre el mensaje del usuario y el texto+título de un
    subbloque -- sirve para incluir primero lo más relevante cuando no
    cabe todo el tema en el presupuesto de tokens."""
    if not tokens_mensaje:
        return 0
    palabras_texto = {p for p in _normalizar_enunciado(texto).split() if len(p) >= 4}
    return len(palabras_texto & tokens_mensaje)


def obtener_contexto_por_temas_exactos(
    db, temas_combinados: List[str], mensaje: str = "", token_limit=4000, coleccion="Temario AGE"
) -> Tuple[str, bool]:
    """Devuelve (contexto, truncado). Los subbloques se incluyen por
    relevancia respecto a `mensaje` (de mayor a menor solapamiento de
    palabras), no por el orden arbitrario de Firestore -- así, si hay que
    recortar por presupuesto de tokens, se descarta primero lo MENOS
    relevante. `truncado=True` si NO cupo todo el contenido recuperado (para
    que quien llame pueda avisar de que el contenido puede ser parcial, en
    vez de tratarlo como si fuera el tema completo)."""
    tokens_mensaje = {p for p in _normalizar_enunciado(mensaje).split() if len(p) >= 4} if mensaje else set()
    candidatos = []  # (puntuacion, orden_original, fragmento)
    orden = 0
    for tema_completo in temas_combinados:
        if "-" not in tema_completo:
            continue
        bloque_id, tema_id = tema_completo.split("-", 1)
        subbloques = list(
            db.collection(coleccion).document(bloque_id).collection("temas")
              .document(tema_id).collection("subbloques").stream()
        )
        # Orden estable por id de documento (sub_div_001, sub_div_002...):
        # Firestore no garantiza ningún orden en .stream(), y ese id nunca
        # se guarda como campo consultable -- se ordena aquí en Python (no
        # con .order_by(), que el FakeFirestore de los tests no implementa).
        subbloques.sort(key=lambda s: s.id)
        for sub in subbloques:
            datos = sub.to_dict() or {}
            texto = datos.get("texto", "").strip()
            titulo = datos.get("titulo", "")
            fragmento = f"[{tema_completo}-{sub.id}]\n{titulo}\n{texto}\n"
            puntuacion = _puntuar_relevancia_subbloque(f"{titulo} {texto}", tokens_mensaje)
            candidatos.append((puntuacion, orden, fragmento))
            orden += 1

    candidatos.sort(key=lambda c: (-c[0], c[1]))

    contexto_total = ""
    truncado = False
    for _puntuacion, _orden, fragmento in candidatos:
        if contar_tokens(contexto_total + fragmento) > token_limit:
            truncado = True
            continue  # puede que un fragmento más pequeño y menos relevante aún quepa
        contexto_total += fragmento
    return contexto_total.strip(), truncado

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
        # Filtro "tipo"=="pregunta" ya en la propia consulta (07/08/2026,
        # igual que en tiene_preguntas_psicotecnicas): sigue habiendo que
        # traer todas las preguntas para contar por bloque, pero al menos no
        # se transfieren los documentos que no son de tipo "pregunta".
        for doc in db.collection(coleccion).where("tipo", "==", "pregunta").stream():
            d = doc.to_dict() or {}
            tema_id = d.get("tema_id") or ""
            if "-" not in tema_id:
                continue
            bloque_id = tema_id.split("-")[0]
            contador[bloque_id] = contador.get(bloque_id, 0) + 1
        total = sum(contador.values())
        if not total:
            return {}
        return {b: c / total for b, c in contador.items()}
    # TTL más largo que el resto del temario (30 min en vez de 5): esta
    # cuenta recorre TODA la colección de exámenes oficiales de la
    # oposición (cientos de documentos ya, con varios años cargados), y
    # /oposiciones-disponibles la calcula para las 3 oposiciones en cada
    # petición sin caché -- con el TTL corto, cualquier rato sin tráfico
    # bastaba para que la siguiente visita disparase de nuevo ese barrido
    # completo y la carga de "Test Oficial" se notase lenta.
    return _desde_cache_o_calcular(("pesos_bloque", oposicion), _calcular, ttl_segundos=1800)


def obtener_preguntas_examenes_oficiales(db, oposicion):
    """Todas las preguntas (tipo "pregunta") de examenes_oficiales_<oposicion>,
    ya convertidas a dict -- se cachea con el mismo TTL largo que
    calcular_pesos_reales_por_bloque/tiene_preguntas_psicotecnicas porque
    recorre la misma colección completa y por el mismo motivo: la usa
    /generar-test-oficial en cada petición, y sin caché cualquier rato sin
    tráfico bastaba para que la siguiente visita disparase de nuevo ese
    barrido completo."""
    def _calcular():
        coleccion = coleccion_examenes_oficiales(oposicion)
        # "tipo"=="pregunta" ya en la consulta (07/08/2026); "activa" se
        # sigue filtrando en Python a propósito -- un "!=" de Firestore
        # excluiría también los documentos que NO tienen el campo "activa"
        # en absoluto, cambiando el criterio de "sin el campo se consideran
        # activas" que ya usa este mismo filtro.
        return [
            d for d in (doc.to_dict() or {} for doc in db.collection(coleccion).where("tipo", "==", "pregunta").stream())
            if d.get("activa", True) is not False
        ]
    return _desde_cache_o_calcular(("preguntas_oficiales", oposicion), _calcular, ttl_segundos=1800)


def obtener_preguntas_psicotecnico(db, oposicion):
    """Todas las preguntas (activas) de la prueba psicotécnica de la
    oposición -- ver oposiciones.coleccion_psicotecnico y
    cargar_psicotecnico_metro.py. Mismo patrón de caché con TTL largo que
    obtener_preguntas_examenes_oficiales: es una colección pequeña y estable
    que no cambia salvo carga manual."""
    def _calcular():
        coleccion = coleccion_psicotecnico(oposicion)
        return [
            d for d in (doc.to_dict() or {} for doc in db.collection(coleccion).stream())
            if d.get("activa", True) is not False
        ]
    return _desde_cache_o_calcular(("preguntas_psicotecnico", oposicion), _calcular, ttl_segundos=1800)


def tiene_prueba_psicotecnica(db, oposicion):
    """True si la oposición tiene una prueba psicotécnica propia cargada
    (hoy, solo Metro) -- usado para mostrar/ocultar la tarjeta
    "Psicotécnico" en /test-generator/ sin fijarlo a una oposición
    concreta, igual que tiene_preguntas_psicotecnicas."""
    def _calcular():
        coleccion = coleccion_psicotecnico(oposicion)
        docs = db.collection(coleccion).limit(1).stream()
        return next(docs, None) is not None
    return _desde_cache_o_calcular(("tiene_psicotecnico", oposicion), _calcular, ttl_segundos=1800)


def _normalizar_enunciado(texto):
    """Minúsculas, sin acentos, sin signos y con espacios colapsados -- para
    comparar el enunciado de una pregunta que el usuario pega en el chat con
    los enunciados del banco oficial sin que un acento o un espacio de más
    impidan el emparejamiento."""
    import unicodedata
    descompuesto = unicodedata.normalize("NFD", (texto or "").lower())
    sin_acentos = "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", sin_acentos)).strip()


def _mejor_coincidencia_por_enunciado(candidatas, texto):
    """Emparejamiento común de buscar_pregunta_oficial y
    buscar_pregunta_banco_ia: por contención del enunciado normalizado
    (exige que el enunciado candidato, >= 20 caracteres para no casar con
    fragmentos triviales, aparezca íntegro dentro del texto pegado). Si
    varios encajan, gana el enunciado más largo (el más específico)."""
    consulta = _normalizar_enunciado(texto)
    if len(consulta) < 20:
        return None
    mejor = None
    mejor_longitud = 0
    for d in candidatas:
        if not d.get("respuesta_correcta"):
            continue
        enunciado = _normalizar_enunciado(d.get("pregunta", ""))
        if len(enunciado) < 20:
            continue
        if enunciado in consulta and len(enunciado) > mejor_longitud:
            mejor = d
            mejor_longitud = len(enunciado)
    return mejor


def buscar_pregunta_oficial(db, oposicion, texto):
    """Busca en el banco de exámenes oficiales de la oposición una pregunta
    cuyo enunciado esté contenido en `texto` (lo que el usuario pega en el
    chat suele traer el enunciado + las opciones). Devuelve el dict de la
    pregunta oficial (con respuesta_correcta y explicacion) o None.

    Sirve para que Tu Tutor responda con la respuesta OFICIAL ya corregida
    cuando el usuario pega una pregunta de un test oficial, en vez de
    razonarla desde cero (más fiable y coherente con lo que marca el test)."""
    if len(_normalizar_enunciado(texto)) < 20:
        return None
    try:
        candidatas = obtener_preguntas_examenes_oficiales(db, oposicion)
    except Exception:
        return None
    coincidencia = _mejor_coincidencia_por_enunciado(candidatas, texto)
    if coincidencia is None:
        logger.info(
            "buscar_pregunta_oficial: sin coincidencia (oposicion=%s, candidatas=%d)",
            oposicion, len(candidatas),
        )
    return coincidencia


def obtener_preguntas_banco_ia(db, oposicion):
    """Todas las preguntas guardadas en banco_preguntas_ia_<oposicion>
    (preguntas de Test Personalizado ya generadas y VERIFICADAS -- ver
    generador_preguntas_verificado.py). TTL corto (a diferencia de
    obtener_preguntas_examenes_oficiales, que sí usa uno largo): esta
    colección recibe escrituras en vivo cada vez que alguien genera un
    test nuevo, y aunque generador_preguntas_verificado.py invalida esta
    caché en el proceso donde generó (ver limpiar_cache_preguntas_banco_ia),
    con varios workers de Gunicorn los demás procesos no se enteran -- el
    TTL corto acota su desfase a como mucho estos 90s en vez de los 30 min
    de antes. La recorre entera buscar_pregunta_banco_ia en cada mensaje de
    Tu Tutor que parezca una pregunta de test."""
    def _calcular():
        return [
            doc.to_dict() or {}
            for doc in db.collection(coleccion_banco_preguntas(oposicion)).stream()
        ]
    return _desde_cache_o_calcular(("preguntas_banco_ia", oposicion), _calcular, ttl_segundos=90)


def buscar_pregunta_banco_ia(db, oposicion, texto):
    """Como buscar_pregunta_oficial pero sobre el banco de preguntas de Test
    Personalizado ya verificadas, en vez de exámenes oficiales reales.
    Cubre el hueco que deja buscar_pregunta_oficial: si el usuario pega en
    Tu Tutor una pregunta de un test personalizado/generado por IA (que no
    existe en ningún examen oficial), sin esto el tutor la razona desde
    cero -- y puede contradecir la respuesta ya verificada de la propia
    pregunta (visto en producción: dio una respuesta distinta a la que
    marcaba como correcta la explicación ya guardada de esa pregunta)."""
    if len(_normalizar_enunciado(texto)) < 20:
        return None
    try:
        candidatas = obtener_preguntas_banco_ia(db, oposicion)
    except Exception:
        return None
    coincidencia = _mejor_coincidencia_por_enunciado(candidatas, texto)
    if coincidencia is None:
        logger.info(
            "buscar_pregunta_banco_ia: sin coincidencia (oposicion=%s, candidatas=%d)",
            oposicion, len(candidatas),
        )
    return coincidencia


def tiene_preguntas_psicotecnicas(db, oposicion):
    """True si la colección de exámenes oficiales de esta oposición tiene
    alguna pregunta marcada como "psicotecnico" (aptitud administrativa,
    numérica o verbal, sin relación con ningún tema del temario -- ver
    cargar_examen_oficial_auxiliar.py). Hoy solo ocurre en Auxiliar, pero se
    calcula empíricamente en vez de fijarlo a una oposición concreta, igual
    que calcular_pesos_reales_por_bloque, para que el frontend solo ofrezca
    el filtro "excluir psicotécnicas" cuando de verdad hay alguna que
    excluir."""
    def _calcular():
        coleccion = coleccion_examenes_oficiales(oposicion)
        # Consulta filtrada + limit(1) en vez de traer la colección entera y
        # mirar documento a documento en Python (07/08/2026: para AGE y GACE,
        # que hoy no tienen ninguna psicotécnica, esto recorría TODA la
        # colección -- cientos de documentos -- solo para concluir "no hay
        # ninguna"). Dos filtros de igualdad no requieren índice compuesto en
        # Firestore.
        docs = (
            db.collection(coleccion)
            .where("tipo", "==", "pregunta")
            .where("psicotecnico", "==", True)
            .limit(1)
            .stream()
        )
        return next(docs, None) is not None
    # Mismo TTL largo que calcular_pesos_reales_por_bloque y por el mismo
    # motivo: recorre toda la colección de exámenes oficiales.
    return _desde_cache_o_calcular(("tiene_psicotecnicas", oposicion), _calcular, ttl_segundos=1800)


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


def parsear_explicacion_por_opcion(explicacion):
    """Parsea una explicación con el patrón "A) ... B) ... C) ... D) ..." en
    un dict {letra: texto}. Devuelve None si el texto no sigue ese formato
    exacto (nunca arriesga a inventar/cortar mal un segmento) -- usado tanto
    para remapear letras tras barajar opciones como para que Tu Tutor pueda
    citar por separado el razonamiento de la opción correcta."""
    texto = (explicacion or "").strip()
    if not re.match(r"^[A-D]\)\s", texto):
        return None  # no sigue el formato esperado
    partes = re.split(r"\s(?=[A-D]\)\s)", texto)
    segmentos = {}
    for parte in partes:
        m = re.match(r"^([A-D])\)\s*(.*)$", parte, re.DOTALL)
        if not m:
            return None  # forma inesperada: no arriesgar a corromper el texto
        segmentos[m.group(1)] = m.group(2)
    if set(segmentos) != set(_LETRAS_OPCION):
        return None
    return segmentos


def _remapear_explicacion_por_letra(explicacion, mapa_original_a_nueva):
    """La explicación de una pregunta de test se pide con el patrón
    "A) ... B) ... C) ... D) ...", una línea por opción en el orden
    ORIGINAL que decidió la IA. Al barajar las opciones hay que reescribir
    esos prefijos de letra para que sigan señalando a la opción correcta --
    si no, tras barajar, la explicación podría decir "B) es correcta" sobre
    una opción que ahora es la C."""
    segmentos = parsear_explicacion_por_opcion(explicacion)
    if segmentos is None:
        return explicacion  # no sigue el formato esperado: se deja tal cual
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

