
import logging
import re
import unicodedata
from datetime import datetime
from firebase_admin import firestore

logger = logging.getLogger(__name__)
from utils import calcular_resultado_test, obtener_catalogo_temas, obtener_contexto_por_temas_exactos, obtener_datos_convocatoria, obtener_resumen_temario
from deepseek_utils import call_deepseek_api, call_deepseek_api_stream
from oposiciones import OPOSICIONES, OPOSICION_POR_DEFECTO

# ✅ Crear conversación con título y mensajes en subcolección por usuario

def crear_conversacion(db, usuario_id, mensaje_usuario, respuesta_ia):
    titulo = mensaje_usuario[:80] + ("..." if len(mensaje_usuario) > 80 else "")
    nueva = db.collection("conversaciones_IA") \
              .document(usuario_id) \
              .collection("conversaciones") \
              .document()
    nueva.set({
        "usuario_id": usuario_id,
        "titulo": titulo,
        "timestamp_inicio": datetime.utcnow().isoformat(),
        "mensajes": [
            {"role": "user", "content": mensaje_usuario},
            {"role": "assistant", "content": respuesta_ia}
        ]
    })
    return nueva.id

# ✅ Añadir mensaje a conversación existente

def agregar_mensaje_a_conversacion(db, usuario_id, conversacion_id, role, content):
    ref = db.collection("conversaciones_IA") \
            .document(usuario_id) \
            .collection("conversaciones") \
            .document(conversacion_id)
    mensaje = {"role": role, "content": content}
    # En Firestore, update() sobre un documento inexistente LANZA (y eso hacía
    # que el turno no se guardara y la conversación desapareciera del
    # histórico si llegaba un chat_id obsoleto). Se comprueba primero si
    # existe: si no, se crea con los campos mínimos en vez de fallar.
    try:
        existe = ref.get().exists
    except Exception:
        existe = False
    if existe:
        ref.update({"mensajes": firestore.ArrayUnion([mensaje])})
    else:
        logger.warning("Conversación %s no existía al añadir mensaje; se crea de cero", conversacion_id)
        ref.set({
            "usuario_id": usuario_id,
            "titulo": (content[:80] if role == "user" else "Conversación"),
            "timestamp_inicio": datetime.utcnow().isoformat(),
            "mensajes": [mensaje],
        }, merge=True)

# ✅ Historial previo de una conversación ya existente, para que el modelo
# tenga memoria real de lo hablado (antes de esto, cada mensaje se mandaba
# aislado y el modelo no tenía forma de saber a qué se refería un "cuéntame
# más" o un "¿y el segundo?"). Se limita a los últimos N mensajes para no
# dejar crecer el prompt sin límite en conversaciones muy largas.
_HISTORIAL_MAXIMO_MENSAJES = 30

# En vez de perder de golpe TODO el contexto anterior al pasar de
# _HISTORIAL_MAXIMO_MENSAJES (el mensaje 31 se quedaría sin ningún rastro de
# los 30 primeros), los mensajes que caen fuera de la ventana se comprimen
# en un resumen que se antepone al historial reciente. Para no llamar al
# modelo a resumir en cada turno (coste/latencia), el resumen solo se
# regenera cuando se acumula un lote nuevo de mensajes fuera de ventana, no
# mensaje a mensaje -- mientras tanto se reutiliza el resumen ya guardado
# (los pocos mensajes más recientes que aún no entran en él se pierden
# temporalmente, hasta el siguiente lote).
_LOTE_RESUMEN_HISTORIAL = 10


def _resumir_mensajes_antiguos(resumen_previo, mensajes_a_resumir):
    system_prompt = (
        "Resumes conversaciones de un chat de tutoría para oposiciones. Quédate solo con lo que "
        "pueda hacer falta más adelante: temas tratados, dudas ya resueltas, dificultades o "
        "preferencias que haya mencionado el usuario. Sé breve, unas pocas frases, sin adornos."
    )
    texto_mensajes = "\n".join(f"{m['role']}: {m['content']}" for m in mensajes_a_resumir)
    if resumen_previo:
        prompt_usuario = (
            f"Resumen de la conversación hasta ahora:\n{resumen_previo}\n\n"
            f"Nuevos mensajes a incorporar (fusiona todo en un único resumen actualizado, sin "
            f"separarlo en partes):\n{texto_mensajes}"
        )
    else:
        prompt_usuario = f"Mensajes a resumir:\n{texto_mensajes}"
    resumen = call_deepseek_api(
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt_usuario}],
        temperature=0.3,
        max_tokens=300
    )
    return (resumen or resumen_previo or "").strip() or None


def _actualizar_resumen_si_hace_falta(db, usuario_id, chat_id, conversacion):
    mensajes = conversacion.get("mensajes", [])
    if len(mensajes) <= _HISTORIAL_MAXIMO_MENSAJES:
        return None

    mensajes_fuera_de_ventana = mensajes[:-_HISTORIAL_MAXIMO_MENSAJES]
    ya_cubiertos = conversacion.get("resumen_cubre_mensajes", 0)
    pendientes = mensajes_fuera_de_ventana[ya_cubiertos:]
    resumen_previo = conversacion.get("resumen_antiguo")
    if len(pendientes) < _LOTE_RESUMEN_HISTORIAL:
        return resumen_previo

    nuevo_resumen = _resumir_mensajes_antiguos(resumen_previo, pendientes)
    db.collection("conversaciones_IA").document(usuario_id).collection("conversaciones").document(chat_id).update({
        "resumen_antiguo": nuevo_resumen,
        "resumen_cubre_mensajes": len(mensajes_fuera_de_ventana),
    })
    return nuevo_resumen


def _historial_previo(db, usuario_id, chat_id):
    if not chat_id:
        return []
    conversacion_snap = db.collection("conversaciones_IA") \
                           .document(usuario_id) \
                           .collection("conversaciones") \
                           .document(chat_id) \
                           .get()
    if not conversacion_snap.exists:
        return []
    conversacion = conversacion_snap.to_dict() or {}
    mensajes = conversacion.get("mensajes", [])
    resumen = _actualizar_resumen_si_hace_falta(db, usuario_id, chat_id, conversacion)
    mensajes_recientes = mensajes[-_HISTORIAL_MAXIMO_MENSAJES:]
    historial = [{"role": m["role"], "content": m["content"]} for m in mensajes_recientes]
    if resumen:
        historial.insert(0, {
            "role": "system",
            "content": "Resumen de la parte anterior de esta conversación (esos mensajes ya no "
                       f"están disponibles palabra por palabra): {resumen}"
        })
    return historial

# ✅ Asistente premium especializado en el examen, adaptado a la oposición
# concreta que esté estudiando el usuario (mismo asistente, distinto "traje").
def _instrucciones_asistente_examen(oposicion):
    nombre = OPOSICIONES.get(oposicion, OPOSICIONES[OPOSICION_POR_DEFECTO])["nombre"]
    return (
        f"Eres Tu Tutor, el asistente conversacional de oposiciones especializado en el proceso "
        f"selectivo del {nombre}. Ayudas con la estructura del examen, el temario y consejos de "
        "estudio. Responde en español, en un tono natural y cercano de chat (no un informe "
        "administrativo) pero preciso.\n\n"
        "Sobre la precisión de los datos: distingue siempre entre lo que es estructura estable y "
        "bien conocida del proceso selectivo (que existen varios ejercicios, que suele haber una "
        "parte tipo test y otra práctica, etc.) y los datos concretos que cambian con cada "
        "convocatoria (fechas exactas, número de la Resolución del BOE, número exacto de preguntas, "
        "ponderación exacta de cada parte, notas de corte). Para estos últimos, si no tienes la "
        "certeza de que corresponden a la convocatoria vigente, dilo explícitamente (p. ej. \"esto "
        "puede variar según la convocatoria; consúltalo en la última publicada en el BOE\") en vez "
        "de inventar cifras concretas con aparente seguridad. Nunca cites una fecha, un número de "
        "Resolución o una cifra de puntuación exacta como si fuera un hecho verificado si no lo es.\n\n"
        "Sobre el formato: estructura la respuesta con markdown ligero (## para algún encabezado "
        "si hay varias secciones claras, **negrita** para lo importante, listas con - cuando ayude "
        "a leer mejor), pero sin abusar -- para preguntas sencillas basta con un párrafo o dos bien "
        "redactados, sin encabezados innecesarios.\n\n"
        "Sobre sonar a una persona real y no a una IA genérica: varía cómo empiezas cada respuesta "
        "-- no abras siempre con \"¡Claro!\" o \"¡Por supuesto!\", a veces basta con ir directo al "
        "grano o reaccionar a lo que ha dicho el usuario. Evita coletillas típicas de IA como "
        "\"es importante destacar que\", \"cabe mencionar que\", \"recuerda que\" al final a modo de "
        "moraleja, o resumir con \"en definitiva\" cada vez. Escribe como alguien que conoce la "
        "materia y le importa que a esa persona en concreto le vaya bien, no como un manual. Cuando "
        "tenga sentido, termina con una pregunta breve que invite a seguir la conversación (qué tal "
        "lleva ese tema, si quiere que le tome unas preguntas, etc.) en vez de dejarlo en un punto "
        "final seco -- pero no lo fuerces en respuestas muy cortas donde no pinte nada."
    )

# ============================================================
# Detección de si un mensaje necesita RAG (buscar contenido real del
# temario) o si es una pregunta genérica sobre el proceso selectivo, para
# la que basta el system prompt fijo del coach.
# ============================================================

_PATRONES_TEMARIO = [
    re.compile(r"\btema\s*n?\W*\d+\b"),
    re.compile(r"\bbloque\s*n?\W*\d+\b"),
    re.compile(r"\bart(?:iculo|\.)?\s*\d+\b"),
]


def _normalizar(texto):
    descompuesto = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def _tokens(texto):
    # split() a secas deja signos de puntuación pegados a la palabra
    # ("temario?", "¿como") -- \w+ los separa, para que las comparaciones
    # por palabra suelta (_necesita_resumen_temario) no fallen solo porque
    # la pregunta termine en "?" o empiece por "¿".
    return set(re.findall(r"\w+", _normalizar(texto)))


def _palabras_significativas(titulo, minimo=5):
    return [p for p in _normalizar(titulo).split() if len(p) >= minimo]


def _temas_mencionados(mensaje, catalogo):
    """Compara el mensaje (normalizado, sin acentos) contra el título de
    cada tema del catálogo: si al menos 2 palabras significativas del
    título aparecen en el mensaje, se considera que ese tema fue
    mencionado."""
    mensaje_norm = _normalizar(mensaje)
    encontrados = []
    for tema in catalogo:
        palabras = _palabras_significativas(tema["titulo"])
        if palabras and sum(1 for p in palabras if p in mensaje_norm) >= 2:
            encontrados.append(tema["id"])
    return encontrados


# Nº de mensajes del historial (inmediatamente anteriores al actual) que se
# reutilizan para detectar de qué tema va la conversación cuando el mensaje
# nuevo no lo menciona explícitamente -- p. ej. "¿y las causas de disolución?"
# justo después de haber preguntado por un tema concreto. Se limita al último
# intercambio (usuario + asistente) para no seguir arrastrando el mismo tema
# mucho después de que la conversación haya cambiado de asunto.
_MENSAJES_CONTEXTO_TEMAS = 2


def _titulos_legibles(ids_temas, catalogo):
    catalogo_por_id = {tema["id"]: tema["titulo"] for tema in catalogo}
    return [catalogo_por_id[id_tema] for id_tema in ids_temas if id_tema in catalogo_por_id]


def _temas_mencionados_en_la_conversacion(mensaje, historial, catalogo):
    temas_detectados = _temas_mencionados(mensaje, catalogo)
    if temas_detectados or not historial:
        return temas_detectados
    contexto_reciente = " ".join(m["content"] for m in historial[-_MENSAJES_CONTEXTO_TEMAS:])
    return _temas_mencionados(contexto_reciente, catalogo)


def _necesita_rag(mensaje, temas_detectados):
    if temas_detectados:
        return True
    mensaje_norm = _normalizar(mensaje)
    return any(patron.search(mensaje_norm) for patron in _PATRONES_TEMARIO)


# ============================================================
# Detección de que el usuario ha PEGADO una pregunta tipo test (con sus
# opciones) para que se la resuelvas. Aquí el tutor debe identificar la
# respuesta correcta directamente, no forzar RAG sobre un tema arrastrado de
# la conversación anterior ni negarse a responder "porque no está en el
# temario". Detecta tanto opciones en mayúscula sueltas (formato en que las
# pega el frontend del test: "... A La Comisión B El Ministro C ...") como el
# clásico "a) ... b) ... c) ...".
# ============================================================
_PATRON_OPCION_MAYUS = re.compile(r"(?:^|\s)([ABCD])(?=\s|\))")
_PATRON_OPCION_MINUS = re.compile(r"\b([abcd])[)\.]")


def _es_pregunta_de_test(mensaje):
    texto = mensaje or ""
    if len(set(_PATRON_OPCION_MAYUS.findall(texto))) >= 3:
        return True
    if len(set(_PATRON_OPCION_MINUS.findall(texto.lower()))) >= 3:
        return True
    return False


# Instrucción que se añade al prompt cuando el usuario pega una pregunta de
# test: fuerza a resolverla directamente y prohíbe las dos conductas que se
# vieron fallar (pedir de qué tema es, o negarse "porque no está en el
# temario").
_INSTRUCCION_TEST = (
    "El usuario está haciendo un test y te pega una pregunta tipo test con sus opciones. "
    "Dile con claridad cuál es la opción correcta (indica la letra) y explica de forma breve por qué "
    "lo es y, si ayuda, por qué las demás no. Resuélvela tú directamente: NO le pidas que te diga de "
    "qué tema es, y NO le digas que la pregunta no corresponde al temario o que no puedes ayudarle "
    "con ella. Si no tienes plena certeza, dilo con honestidad pero dale igualmente tu mejor opción "
    "razonada."
)


# ============================================================
# Detección de preguntas sobre la ESTRUCTURA/logística del proceso
# selectivo (nº de preguntas, tiempo, penalización, plazas, calificación...)
# -- justo el tipo de dato concreto que antes el modelo tendía a inventar
# con aparente seguridad. Si hay datos oficiales cargados para la
# oposición (obtener_datos_convocatoria), se inyectan en el prompt en vez
# de dejar que el modelo adivine.
# ============================================================
_PALABRAS_CONVOCATORIA = [
    "cuantas preguntas", "numero de preguntas", "cuanto tiempo", "duracion del examen",
    "cuanto dura el examen", "penaliza", "penalizacion", "descuenta", "resta por fallo",
    "plazas convocadas", "cuantas plazas", "numero de plazas",
    "primer ejercicio", "segundo ejercicio", "supuesto practico",
    "nota minima", "nota de corte", "puntuacion minima",
    "como se califica", "como puntua", "calificacion final",
    "aprobar el examen", "aprobar la oposicion",
    "estructura del examen", "como es el examen", "partes tiene el examen",
    "fase de oposicion", "curso selectivo",
]


def _necesita_datos_convocatoria(mensaje):
    mensaje_norm = _normalizar(mensaje)
    return any(palabra in mensaje_norm for palabra in _PALABRAS_CONVOCATORIA)


# ============================================================
# Detección de preguntas sobre la ESTRUCTURA DEL TEMARIO en sí (bloques,
# temas, cuántos hay, cómo se organizan) -- a diferencia de
# _necesita_datos_convocatoria (logística del examen), aquí la fuente de
# verdad no es un texto escrito a mano sino el catálogo real ya cargado en
# Firestore (obtener_resumen_temario), para que Tu Tutor nunca invente
# bloques/temas que no existen de verdad.
# ============================================================
# Antes esto comparaba frases completas exactas ("estructura del temario",
# "divide el temario"...) contra el mensaje -- se rompía con cualquier
# reordenación de las mismas palabras (p. ej. "¿Qué estructura tiene el
# temario?" o "¿Cómo está organizado el temario?" no contienen esas frases
# tal cual, así que no activaban nada y el modelo acababa inventando la
# estructura). Ahora se comprueba por palabras sueltas, sin importar el
# orden: basta con que aparezca una palabra "ancla" (temario/oposición) y
# una palabra que indique que se pregunta por su estructura.
_TEMARIO_ANCLAS = {"temario", "oposicion"}
_TEMARIO_INDICADORES_ESTRUCTURA = {
    "estructura", "divide", "dividen", "dividido", "organiza", "organizado",
    "organizada", "partes", "compone", "compuesto", "consta", "completo",
    "lista", "listado", "bloques",
}


def _necesita_resumen_temario(mensaje):
    palabras = _tokens(mensaje)
    if palabras & _TEMARIO_ANCLAS and palabras & _TEMARIO_INDICADORES_ESTRUCTURA:
        return True
    # "cuántos temas/bloques tiene..." -- "cuantos"/"cuantas" solos son
    # demasiado genéricos (chocarían con preguntas de plazas o del número
    # de preguntas del examen), pero junto a "temas"/"bloques" no dejan
    # lugar a dudas de que la pregunta es sobre el temario.
    if {"cuantos", "cuantas"} & palabras and {"temas", "bloques"} & palabras:
        return True
    # "dame la lista/listado de todos los temas" -- sin la palabra
    # "temario" ni "oposición" delante.
    if {"lista", "listado", "todos"} & palabras and "temas" in palabras:
        return True
    return False


# ============================================================
# Datos reales del propio usuario (nombre, racha de estudio, fecha de
# examen, temas donde más falla) para que Tu Tutor hable como alguien que
# conoce a esa persona en concreto, en vez de dar una respuesta genérica
# que serviría para cualquiera.
# ============================================================
_MINIMO_INTENTOS_TEMA_FLOJO = 3
_UMBRAL_ACIERTO_TEMA_FLOJO = 0.7
_MAX_TEMAS_FLOJOS = 5
_MAX_TEMAS_PENDIENTES_EN_CONTEXTO = 5


def _temas_flojos(rendimiento_por_tema, catalogo):
    """Temas con suficientes intentos acumulados (a través de TODOS los
    tests, no solo el último) y un ratio de acierto por debajo del umbral --
    así detecta también el caso de "aprueba el test en conjunto pero falla
    mucho en un tema concreto", no solo un suspenso genérico."""
    catalogo_por_id = {tema["id"]: tema["titulo"] for tema in catalogo}
    candidatos = []
    for tema_id, datos in (rendimiento_por_tema or {}).items():
        intentos = datos.get("aciertos", 0) + datos.get("fallos", 0)
        titulo = catalogo_por_id.get(tema_id)
        if intentos < _MINIMO_INTENTOS_TEMA_FLOJO or not titulo:
            continue
        ratio_acierto = datos.get("aciertos", 0) / intentos
        if ratio_acierto >= _UMBRAL_ACIERTO_TEMA_FLOJO:
            continue
        candidatos.append((ratio_acierto, tema_id, titulo))
    candidatos.sort(key=lambda candidato: candidato[0])
    # Se devuelve también el tema_id (además de título y % de acierto) para
    # que quien lo consuma pueda enlazar a "generar un test de este tema",
    # no solo mencionarlo por su nombre.
    return [(tema_id, titulo, round(ratio * 100)) for ratio, tema_id, titulo in candidatos[:_MAX_TEMAS_FLOJOS]]


def _temas_pendientes(stats, catalogo):
    """Temas del catálogo que el usuario todavía no ha tocado en ningún
    test -- se combinan temas_test (lista explícita) y las claves de
    rendimiento_por_tema (por si alguna vía antigua solo rellenó una de
    las dos), para no depender de un único campo. Devuelve pares
    (tema_id, titulo)."""
    tocados = set(stats.get("temas_test") or []) | set((stats.get("rendimiento_por_tema") or {}).keys())
    return [(tema["id"], tema["titulo"]) for tema in catalogo if tema["id"] not in tocados]


# Nombre legible del tipo de test guardado en historial_tests / ultimo_test
# (el campo "tipo" que pone actualizar_estadisticas_test), para que Tu Tutor
# hable del "último test oficial" o "de fallos" en vez de un genérico "test".
_NOMBRE_TIPO_TEST = {
    "personalizado": "personalizado",
    "avanzado_verificado": "personalizado",
    "oficial": "de examen oficial",
    "inteligente": "inteligente",
    "fallos": "de preguntas falladas",
    "favoritas": "de preguntas marcadas",
    "repetir": "repetido",
}


def _nota_sobre_10_de(entrada):
    """Nota sobre 10 de un test guardado, con el mismo criterio oficial que
    el resto de la web (aciertos - fallos/3, sobre el total). Devuelve None
    si el registro no trae datos suficientes."""
    aciertos = entrada.get("aciertos", 0)
    fallos = entrada.get("fallos", 0)
    blancos = entrada.get("blancos", 0)
    if aciertos + fallos + blancos == 0:
        return None
    _puntuacion, nota, _resultado = calcular_resultado_test(aciertos, fallos, blancos)
    return nota


def _hace_cuanto(fecha_iso):
    """Texto relativo ("hoy", "ayer", "hace 3 días") a partir de una fecha
    ISO (la que guarda actualizar_estadisticas_test con datetime.utcnow()).
    Devuelve None si no se puede interpretar."""
    if not fecha_iso:
        return None
    try:
        fecha = datetime.fromisoformat(str(fecha_iso).replace("Z", ""))
    except (ValueError, TypeError):
        return None
    dias = (datetime.utcnow().date() - fecha.date()).days
    if dias <= 0:
        return "hoy"
    if dias == 1:
        return "ayer"
    if dias < 7:
        return f"hace {dias} días"
    if dias < 30:
        semanas = dias // 7
        return "hace una semana" if semanas == 1 else f"hace {semanas} semanas"
    meses = dias // 30
    return "hace un mes" if meses == 1 else f"hace {meses} meses"


def _lineas_rendimiento_tests(stats):
    """Frases sobre el rendimiento REAL en tests (última nota, tendencia,
    nota media sobre 10) a partir del historial guardado -- para que Tu Tutor
    pueda responder con datos concretos a "¿qué nota saqué?" en vez de decir
    que no tiene acceso al historial. Se apoya en historial_tests (que trae
    aciertos/fallos/blancos por test); si está vacío, no dice nada."""
    historial = stats.get("historial_tests") or []
    if not historial:
        return []

    lineas = []
    ultimo = historial[-1]
    nota_ultimo = _nota_sobre_10_de(ultimo)
    if nota_ultimo is not None:
        total_preg = ultimo.get("aciertos", 0) + ultimo.get("fallos", 0) + ultimo.get("blancos", 0)
        resultado = ultimo.get("resultado") or ("aprobado" if nota_ultimo >= 5 else "suspendido")
        tipo = _NOMBRE_TIPO_TEST.get(ultimo.get("tipo"), "")
        cuando = _hace_cuanto(ultimo.get("fecha"))
        descripcion = "En su último test"
        if tipo:
            descripcion += f" {tipo}"
        if cuando:
            descripcion += f" ({cuando})"
        lineas.append(
            f"{descripcion} sacó un {nota_ultimo} sobre 10 "
            f"({ultimo.get('aciertos', 0)} aciertos y {ultimo.get('fallos', 0)} fallos "
            f"de {total_preg} preguntas): {resultado}."
        )

    # Nota media real sobre 10 (no confundir con puntuacion_media_test, que es
    # la media de aciertos por test, no una nota) y mejor nota, calculadas
    # sobre todo el historial disponible.
    notas = [n for n in (_nota_sobre_10_de(e) for e in historial) if n is not None]
    if len(notas) >= 2:
        media = round(sum(notas) / len(notas), 2)
        mejor = max(notas)
        lineas.append(f"Su nota media en tests es {media} sobre 10 y su mejor nota hasta ahora es {mejor}.")

        # Tendencia con los últimos tests: ¿va mejorando o de capa caída?
        recientes = notas[-3:]
        if len(recientes) >= 3:
            if recientes[-1] > recientes[0] + 0.5:
                lineas.append("En sus últimos tests la nota va subiendo (está mejorando).")
            elif recientes[-1] < recientes[0] - 0.5:
                lineas.append("En sus últimos tests la nota ha bajado un poco respecto a antes.")

    return lineas


def _contexto_personal_usuario(db, usuario_id, oposicion, catalogo):
    doc = db.collection("usuarios").document(usuario_id).get()
    if not doc.exists:
        return None
    datos = doc.to_dict() or {}
    nombre = (datos.get("nombre") or "").strip()
    racha_actual = (datos.get("racha") or {}).get("racha_actual", 0)
    fecha_examen = (datos.get("fechas_examen") or {}).get(oposicion)
    stats = (datos.get("estadisticas") or {}).get(oposicion) or {}
    temas_flojos = _temas_flojos(stats.get("rendimiento_por_tema", {}), catalogo)
    # Solo se calculan pendientes para alguien que ya ha hecho algún test --
    # si no ha hecho ninguno, "pendiente" es todo el catálogo por defecto y
    # no aporta nada personal que decir (y el propio doc de usuario se crea
    # en el primer turno de chat, antes de tocar ningún test).
    temas_pendientes = _temas_pendientes(stats, catalogo) if stats.get("tests_realizados") else []

    memoria_cruzada = (datos.get("memoria_tutor") or {}).get("resumen")

    lineas = []
    if nombre:
        lineas.append(f"Se llama {nombre}.")
    if racha_actual and racha_actual >= 2:
        lineas.append(f"Lleva {racha_actual} días seguidos estudiando (racha activa).")
    if fecha_examen:
        lineas.append(f"Tiene marcada la fecha de su examen para el {fecha_examen}.")

    tests_realizados = stats.get("tests_realizados", 0)
    if tests_realizados:
        pct_aprobados = round(stats.get("tests_aprobados", 0) / tests_realizados * 100)
        lineas.append(
            f"Lleva {tests_realizados} tests hechos en esta oposición y aprueba el {pct_aprobados}% de ellos."
        )
        # Última nota, nota media real sobre 10 y tendencia -- para que pueda
        # responder con datos concretos a "¿qué nota saqué?" en vez de decir
        # que no tiene acceso al historial.
        lineas.extend(_lineas_rendimiento_tests(stats))

    if temas_flojos:
        detalle = ", ".join(f"{titulo} ({pct}% de acierto)" for _tema_id, titulo, pct in temas_flojos)
        lineas.append(
            "Los temas donde peor rinde (aunque el test en conjunto lo apruebe) son: " + detalle + "."
        )

    if temas_pendientes:
        mostrados = temas_pendientes[:_MAX_TEMAS_PENDIENTES_EN_CONTEXTO]
        resto = len(temas_pendientes) - len(mostrados)
        detalle_pendientes = ", ".join(titulo for _tema_id, titulo in mostrados)
        if resto > 0:
            detalle_pendientes += f" y {resto} más"
        lineas.append("Todavía no ha hecho ningún test de estos temas: " + detalle_pendientes + ".")

    if memoria_cruzada:
        lineas.append("De conversaciones anteriores (con otro chat) recuerdas esto sobre él/ella: " + memoria_cruzada)

    return " ".join(lineas) if lineas else None


# ============================================================
# Sugerencia proactiva para el saludo inicial de Tu Tutor: en vez de
# esperar a que el usuario pregunte "¿qué estudio?", el chat abre ya con
# una recomendación basada en sus estadísticas. Se calcula con plantillas
# deterministas sobre los mismos datos que _contexto_personal_usuario --
# SIN llamar a DeepSeek-- para que sea instantánea y no gaste cuota ni
# dinero en cada carga de la página.
# ============================================================
def sugerencia_inicial_usuario(db, usuario_id, oposicion, catalogo):
    """Devuelve un dict con el saludo inicial personalizado, un mensaje de
    recomendación, una acción opcional (datos para enlazar a "generar un
    test de este tema") y unas sugerencias rápidas contextualizadas. Todos
    los campos son texto plano (sin HTML): el frontend los inserta de forma
    segura, escapando el nombre y el título del tema."""
    doc = db.collection("usuarios").document(usuario_id).get()
    datos = (doc.to_dict() or {}) if doc.exists else {}
    nombre = (datos.get("nombre") or "").strip()
    stats = (datos.get("estadisticas") or {}).get(oposicion) or {}
    tests_realizados = stats.get("tests_realizados", 0)

    saludo = f"¡Hola, {nombre}! 👋" if nombre else "¡Hola! 👋"

    temas_flojos = _temas_flojos(stats.get("rendimiento_por_tema", {}), catalogo)
    temas_pendientes = _temas_pendientes(stats, catalogo) if tests_realizados else []

    accion = None
    if temas_flojos:
        tema_id, titulo, pct = temas_flojos[0]
        mensaje = (
            f"He revisado tus tests y donde más se te resiste es {titulo}: aciertas el {pct}%. "
            f"Un repaso rápido con un test centrado en ese tema te vendría muy bien."
        )
        accion = {"tema_id": tema_id, "titulo": titulo, "label": f"Practicar {titulo}"}
        sugerencias = [f"Explícame lo esencial de {titulo}", "¿Qué me recomiendas estudiar hoy?"]
    elif temas_pendientes:
        tema_id, titulo = temas_pendientes[0]
        mensaje = (
            f"Vas bien de rendimiento. Todavía no has hecho ningún test de {titulo}: "
            f"podría ser un buen momento para estrenarlo."
        )
        accion = {"tema_id": tema_id, "titulo": titulo, "label": f"Empezar test de {titulo}"}
        sugerencias = [f"Explícame {titulo}", "¿Cómo es la estructura del examen?"]
    elif tests_realizados:
        mensaje = (
            "Vas muy bien: ahora mismo no detecto ningún tema flojo. "
            "Pregúntame lo que quieras o repasa el tema que te apetezca."
        )
        sugerencias = ["¿Qué me recomiendas repasar?", "Dame consejos para el examen"]
    else:
        mensaje = (
            "Pregúntame cualquier duda sobre el temario o el proceso selectivo. "
            "En cuanto hagas algún test, te iré diciendo en qué te conviene centrarte."
        )
        sugerencias = ["¿Cómo es la estructura del examen?", "Consejos de estudio", "Dame un plan para empezar"]

    return {"saludo": saludo, "mensaje": mensaje, "accion": accion, "sugerencias": sugerencias}


# 📌 Construye todo lo necesario para llamar al modelo (system prompt,
# prompt de usuario ya enriquecido con RAG/datos oficiales si toca, e
# historial previo) sin llamar todavía a DeepSeek -- lo comparten
# responder_tutor (respuesta de una vez) y responder_tutor_stream
# (respuesta en streaming), para no duplicar la lógica de detección.
def _preparar_contexto(mensaje, db, usuario_id, chat_id, coleccion, oposicion):
    historial = _historial_previo(db, usuario_id, chat_id)
    catalogo = obtener_catalogo_temas(db, coleccion)

    es_test = _es_pregunta_de_test(mensaje)
    # Una pregunta de test (o un mensaje que solo dice "ayúdame con un test")
    # es autocontenido: NO se hereda el tema del turno anterior. Antes se
    # heredaba, y eso hacía que el tutor respondiera con el contenido de un
    # tema que no venía a cuento -- o se negara a responder "porque no está en
    # el temario que me has pasado" -- cuando en realidad la pregunta era de
    # otra cosa.
    mensaje_sobre_test = es_test or "test" in _tokens(mensaje)
    if mensaje_sobre_test:
        temas_detectados = _temas_mencionados(mensaje, catalogo)
    else:
        temas_detectados = _temas_mencionados_en_la_conversacion(mensaje, historial, catalogo)

    # Para una pregunta de test solo se consulta el temario si se ha
    # identificado un tema CONCRETO por su título; si no, se responde con el
    # conocimiento propio del tutor en vez de volcar todo el catálogo (que
    # además suele ser el tema equivocado).
    if es_test:
        usar_rag = bool(temas_detectados)
    else:
        usar_rag = _necesita_rag(mensaje, temas_detectados)

    # Temas concretos a los que va referida la respuesta (id + título), para
    # que el frontend pueda ofrecer un "Generar test de este tema" debajo del
    # mensaje. Solo cuando se ha detectado un tema específico por su título;
    # el fallback de "buscar en todo el catálogo" (patrón genérico sin tema
    # claro) no cuenta, porque ahí no hay un tema concreto que practicar.
    catalogo_por_id = {tema["id"]: tema["titulo"] for tema in catalogo}
    temas_relacionados = [
        {"tema_id": id_tema, "titulo": catalogo_por_id[id_tema]}
        for id_tema in temas_detectados if id_tema in catalogo_por_id
    ][:2]

    if usar_rag:
        # Si se detectó un tema concreto por título, se busca solo ahí; si
        # el mensaje solo menciona un patrón genérico ("artículo 14") sin
        # calzar con ningún título, se busca en todo el catálogo en vez de
        # quedarse sin contexto -- mejor un poco de contenido de más que
        # ninguno cuando ya se decidió que hace falta RAG.
        temas_para_buscar = temas_detectados or [tema["id"] for tema in catalogo]
        contexto = obtener_contexto_por_temas_exactos(db, temas_para_buscar, coleccion=coleccion)
        # Mismo system prompt que el resto de respuestas (persona, tono y
        # reglas de honestidad de Tu Tutor) -- antes esta rama usaba uno
        # genérico aparte y perdía todo eso justo cuando respondía con
        # contenido real del temario.
        system_prompt = _instrucciones_asistente_examen(oposicion)
        if contexto:
            titulos_temas = _titulos_legibles(temas_detectados, catalogo)
            partes = [
                "Tienes cargado automáticamente el siguiente contenido del temario oficial de la "
                "plataforma. IMPORTANTE: el usuario NO te ha pasado este contenido en su mensaje, así "
                "que nunca digas \"según el contenido/temario que me has facilitado o pasado\" ni se lo "
                "atribuyas a él. Úsalo como fuente principal SI la pregunta trata sobre ello. Si la "
                "pregunta trata de otra norma o de algo que no aparece aquí, respóndela igualmente con "
                "tu propio conocimiento como tutor: no digas que la pregunta no corresponde al temario "
                "ni te niegues a responder por ese motivo."
            ]
            if titulos_temas:
                partes.append(
                    "Cuando te apoyes en este contenido, menciona con naturalidad el tema del que "
                    "procede citando su título exacto: " + "; ".join(titulos_temas) + "."
                )
            if es_test:
                partes.append(_INSTRUCCION_TEST)
            partes.append("CONTENIDO DEL TEMARIO:\n" + contexto)
            partes.append("MENSAJE DEL USUARIO:\n" + mensaje)
            prompt_usuario = "\n\n".join(partes)
        else:
            prompt_usuario = (_INSTRUCCION_TEST + "\n\n" + mensaje) if es_test else mensaje
    else:
        system_prompt = _instrucciones_asistente_examen(oposicion)
        datos_convocatoria = obtener_datos_convocatoria(db, oposicion) if _necesita_datos_convocatoria(mensaje) else None
        resumen_temario = obtener_resumen_temario(db, coleccion) if _necesita_resumen_temario(mensaje) else None

        bloques_contexto = []
        if resumen_temario:
            bloques_contexto.append(
                "ESTRUCTURA REAL DEL TEMARIO (bloques y temas tal y como están cargados "
                "en la plataforma, en este orden exacto):\n" + resumen_temario
            )
        if datos_convocatoria:
            bloques_contexto.append(
                "DATOS OFICIALES de la convocatoria vigente de esta oposición, transcritos "
                "de las normas específicas publicadas en el BOE:\n" + datos_convocatoria
            )

        if bloques_contexto:
            prompt_usuario = (
                "A continuación tienes información de referencia que ya tienes disponible. "
                "OJO: el usuario NO te ha dado estos datos en su mensaje -- así que nunca digas "
                "cosas como \"según los datos que me has facilitado/proporcionado\" ni le "
                "atribuyas al usuario esta información. Cítalos como lo que son, datos "
                "públicos, con frases del tipo \"según el temario de la plataforma...\" o "
                "\"según los datos oficiales de la convocatoria de 2025...\". Si hay una lista "
                "de bloques y temas, respétala tal cual (no la resumas de forma distinta ni "
                "inventes bloques/temas que no aparezcan en ella). Úsalos como fuente principal "
                "si la pregunta trata sobre ellos, en vez de inventar datos:\n\n"
                + "\n\n".join(bloques_contexto)
                + f"\n\nPREGUNTA DEL USUARIO:\n{mensaje}"
            )
        else:
            prompt_usuario = mensaje
        # Sin contenido del temario detrás (o con datos oficiales), pero el
        # usuario ha pegado una pregunta de test: se resuelve directamente.
        if es_test:
            prompt_usuario = _INSTRUCCION_TEST + "\n\n" + prompt_usuario

    mensajes = [{"role": "system", "content": system_prompt}]
    contexto_personal = _contexto_personal_usuario(db, usuario_id, oposicion, catalogo)
    if contexto_personal:
        mensajes.append({
            "role": "system",
            "content": (
                "Datos REALES de la persona con la que hablas ahora mismo, sacados de su actividad en "
                "la plataforma (sus tests, sus notas, su progreso). SÍ tienes acceso a esta información: "
                "cuando te pregunte por su última nota, cómo va, en qué falla o qué debería estudiar, "
                "respóndele con estos datos concretos en vez de decir que no tienes acceso a su historial. "
                "Si un dato concreto no apariece aquí (p. ej. te pregunta por un test muy antiguo que no "
                "figura), dilo con naturalidad, pero no niegues tener acceso a su progreso en general.\n\n"
                + contexto_personal +
                "\n\nMenciónalos solo cuando venga a cuento y con naturalidad -- nunca los enumeres todos "
                "de golpe ni suenes a ficha de cliente."
            )
        })
    mensajes.extend(historial)
    mensajes.append({"role": "user", "content": prompt_usuario})
    return mensajes, usar_rag, temas_relacionados


# ============================================================
# Memoria persistente ENTRE conversaciones distintas (a diferencia del
# resumen de _actualizar_resumen_si_hace_falta, que vive dentro de una sola
# conversación) -- para que si en un chat de la semana pasada el usuario
# contó que estaba agobiado o algo puntual relevante, Tu Tutor lo recuerde
# al abrir un chat nuevo, no solo dentro del mismo hilo. Igual que el
# resumen dentro de conversación, se actualiza por lotes (no en cada turno)
# para no llamar al modelo de más.
# ============================================================
_LOTE_MEMORIA_CRUZADA = 6


def _resumir_memoria_cruzada(resumen_previo, mensajes_recientes):
    system_prompt = (
        "Mantienes una memoria persistente y muy breve sobre un usuario de una plataforma de "
        "oposiciones, a partir de fragmentos de sus conversaciones con un tutor de IA. Quédate "
        "solo con lo que merezca la pena recordar en una conversación FUTURA y DISTINTA a esta: "
        "cómo lleva el ánimo respecto al examen, dificultades o preocupaciones puntuales que haya "
        "mencionado, preferencias de estudio. No repitas datos que ya se guardan aparte (nombre, "
        "racha, fecha de examen, temas flojos). Un par de frases como mucho, nunca una lista larga."
    )
    texto_mensajes = "\n".join(f"{m['role']}: {m['content']}" for m in mensajes_recientes)
    if resumen_previo:
        prompt_usuario = (
            f"Memoria actual sobre este usuario:\n{resumen_previo}\n\n"
            "Fragmento nuevo de conversación a incorporar (fusiona todo en una única memoria "
            f"actualizada, sin alargarla innecesariamente):\n{texto_mensajes}"
        )
    else:
        prompt_usuario = f"Fragmento de conversación:\n{texto_mensajes}"
    resumen = call_deepseek_api(
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt_usuario}],
        temperature=0.3,
        max_tokens=200
    )
    return (resumen or resumen_previo or "").strip() or None


def _actualizar_memoria_cruzada(db, usuario_id, chat_id):
    ref_usuario = db.collection("usuarios").document(usuario_id)
    memoria = (ref_usuario.get().to_dict() or {}).get("memoria_tutor") or {}
    turnos_pendientes = memoria.get("turnos_pendientes", 0) + 1

    if turnos_pendientes < _LOTE_MEMORIA_CRUZADA:
        ref_usuario.set({"memoria_tutor": {"turnos_pendientes": turnos_pendientes}}, merge=True)
        return

    conversacion_snap = db.collection("conversaciones_IA").document(usuario_id) \
                          .collection("conversaciones").document(chat_id).get()
    mensajes_recientes = (conversacion_snap.to_dict() or {}).get("mensajes", [])[-_LOTE_MEMORIA_CRUZADA:]
    nuevo_resumen = _resumir_memoria_cruzada(memoria.get("resumen"), mensajes_recientes)
    ref_usuario.set({"memoria_tutor": {"resumen": nuevo_resumen, "turnos_pendientes": 0}}, merge=True)


def _guardar_turno(db, usuario_id, chat_id, mensaje, texto_respuesta):
    if chat_id:
        agregar_mensaje_a_conversacion(db, usuario_id, chat_id, "user", mensaje)
        agregar_mensaje_a_conversacion(db, usuario_id, chat_id, "assistant", texto_respuesta)
    else:
        chat_id = crear_conversacion(db, usuario_id, mensaje, texto_respuesta)
    # La memoria cruzada es un extra (resumen entre conversaciones): si falla
    # NO debe tirar abajo el guardado del turno ni romper el stream, que es lo
    # que dejaría el historial vacío. La conversación ya está persistida arriba.
    try:
        _actualizar_memoria_cruzada(db, usuario_id, chat_id)
    except Exception:
        logger.exception("Fallo al actualizar la memoria cruzada del tutor (no crítico)")
    return chat_id


# 📌 Tu Tutor: chat unificado que decide, mensaje a mensaje, si busca
# contexto real del temario (RAG) o responde como coach genérico del
# proceso selectivo. Guarda siempre el historial en Firestore.
#
# Si DeepSeek falla (timeout, rate limit, error del servidor...) se
# devuelve None como respuesta -- a propósito, para no guardar en Firestore
# ni reenviar al modelo en el siguiente turno un mensaje de error genérico
# como si fuera una respuesta real del asistente. El llamador (la ruta
# /tu-tutor) es quien decide qué mostrarle al usuario en ese caso.
def responder_tutor(mensaje, db, usuario_id="anonimo", chat_id=None, coleccion="Temario AGE", oposicion=OPOSICION_POR_DEFECTO):
    mensajes, usar_rag, _temas_relacionados = _preparar_contexto(mensaje, db, usuario_id, chat_id, coleccion, oposicion)
    respuesta = call_deepseek_api(messages=mensajes, temperature=0.7, max_tokens=1500)
    if not respuesta:
        return None, chat_id, usar_rag

    texto_respuesta = respuesta.strip()
    chat_id = _guardar_turno(db, usuario_id, chat_id, mensaje, texto_respuesta)
    return texto_respuesta, chat_id, usar_rag


# 📌 Misma lógica que responder_tutor, pero en streaming: genera diccionarios
# {"tipo": "delta", "texto": ...} a medida que van llegando fragmentos de
# DeepSeek (para el efecto de "escritura" en el frontend) y termina con
# {"tipo": "fin", "chat_id": ..., "usar_rag": ...} una vez guardado en
# Firestore, o {"tipo": "error"} si DeepSeek falla o no llega ningún
# fragmento (mismo criterio que responder_tutor: nada se guarda en ese caso).
def responder_tutor_stream(mensaje, db, usuario_id="anonimo", chat_id=None, coleccion="Temario AGE", oposicion=OPOSICION_POR_DEFECTO):
    mensajes, usar_rag, temas_relacionados = _preparar_contexto(mensaje, db, usuario_id, chat_id, coleccion, oposicion)

    fragmentos = []
    for fragmento in call_deepseek_api_stream(messages=mensajes, temperature=0.7, max_tokens=1500):
        if not fragmento:
            continue
        fragmentos.append(fragmento)
        yield {"tipo": "delta", "texto": fragmento}

    texto_respuesta = "".join(fragmentos).strip()
    if not texto_respuesta:
        yield {"tipo": "error"}
        return

    chat_id = _guardar_turno(db, usuario_id, chat_id, mensaje, texto_respuesta)
    # temas_relacionados va en el "fin" para que el frontend pueda ofrecer un
    # "Generar test de este tema" debajo de la respuesta (deep-link al Test
    # Personalizado con ese tema ya marcado).
    yield {"tipo": "fin", "chat_id": chat_id, "usar_rag": usar_rag, "temas_relacionados": temas_relacionados}
