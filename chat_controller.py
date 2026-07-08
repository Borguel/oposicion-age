
import re
import unicodedata
from datetime import datetime
from firebase_admin import firestore
from utils import obtener_catalogo_temas, obtener_contexto_por_temas_exactos, obtener_datos_convocatoria, obtener_resumen_temario
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
    db.collection("conversaciones_IA") \
      .document(usuario_id) \
      .collection("conversaciones") \
      .document(conversacion_id) \
      .update({
          "mensajes": firestore.ArrayUnion([{"role": role, "content": content}])
      })

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
_MAX_TEMAS_FLOJOS = 2


def _temas_flojos(rendimiento_por_tema, catalogo):
    catalogo_por_id = {tema["id"]: tema["titulo"] for tema in catalogo}
    candidatos = []
    for tema_id, datos in (rendimiento_por_tema or {}).items():
        intentos = datos.get("aciertos", 0) + datos.get("fallos", 0)
        titulo = catalogo_por_id.get(tema_id)
        if intentos < _MINIMO_INTENTOS_TEMA_FLOJO or not titulo:
            continue
        ratio_acierto = datos.get("aciertos", 0) / intentos
        candidatos.append((ratio_acierto, titulo))
    candidatos.sort(key=lambda candidato: candidato[0])
    return [titulo for _ratio, titulo in candidatos[:_MAX_TEMAS_FLOJOS]]


def _contexto_personal_usuario(db, usuario_id, oposicion, catalogo):
    doc = db.collection("usuarios").document(usuario_id).get()
    if not doc.exists:
        return None
    datos = doc.to_dict() or {}
    nombre = (datos.get("nombre") or "").strip()
    racha_actual = (datos.get("racha") or {}).get("racha_actual", 0)
    fecha_examen = (datos.get("fechas_examen") or {}).get(oposicion)
    rendimiento_por_tema = ((datos.get("estadisticas") or {}).get(oposicion) or {}).get("rendimiento_por_tema", {})
    temas_flojos = _temas_flojos(rendimiento_por_tema, catalogo)

    memoria_cruzada = (datos.get("memoria_tutor") or {}).get("resumen")

    lineas = []
    if nombre:
        lineas.append(f"Se llama {nombre}.")
    if racha_actual and racha_actual >= 2:
        lineas.append(f"Lleva {racha_actual} días seguidos estudiando (racha activa).")
    if fecha_examen:
        lineas.append(f"Tiene marcada la fecha de su examen para el {fecha_examen}.")
    if temas_flojos:
        lineas.append("Los temas donde más está fallando últimamente son: " + ", ".join(temas_flojos) + ".")
    if memoria_cruzada:
        lineas.append("De conversaciones anteriores (con otro chat) recuerdas esto sobre él/ella: " + memoria_cruzada)

    return " ".join(lineas) if lineas else None


# 📌 Construye todo lo necesario para llamar al modelo (system prompt,
# prompt de usuario ya enriquecido con RAG/datos oficiales si toca, e
# historial previo) sin llamar todavía a DeepSeek -- lo comparten
# responder_tutor (respuesta de una vez) y responder_tutor_stream
# (respuesta en streaming), para no duplicar la lógica de detección.
def _preparar_contexto(mensaje, db, usuario_id, chat_id, coleccion, oposicion):
    historial = _historial_previo(db, usuario_id, chat_id)
    catalogo = obtener_catalogo_temas(db, coleccion)
    temas_detectados = _temas_mencionados_en_la_conversacion(mensaje, historial, catalogo)
    usar_rag = _necesita_rag(mensaje, temas_detectados)

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
            if titulos_temas:
                nota_fuente = (
                    "Indica de forma natural en tu respuesta de qué tema del temario procede el "
                    "contenido (p. ej. \"según el tema de " + titulos_temas[0] + "...\"), citando el "
                    "título exacto: " + "; ".join(titulos_temas) + "."
                )
            else:
                nota_fuente = (
                    "Deja claro que la respuesta se basa en el contenido oficial del temario de la "
                    "plataforma, no en tu conocimiento general."
                )
            prompt_usuario = (
                "Utiliza el siguiente contenido del temario oficial para responder con claridad y "
                f"precisión a la pregunta del usuario. {nota_fuente}\n\n"
                f"CONTENIDO DEL TEMARIO:\n{contexto}\n\n"
                f"PREGUNTA DEL USUARIO:\n{mensaje}"
            )
        else:
            prompt_usuario = mensaje
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

    mensajes = [{"role": "system", "content": system_prompt}]
    contexto_personal = _contexto_personal_usuario(db, usuario_id, oposicion, catalogo)
    if contexto_personal:
        mensajes.append({
            "role": "system",
            "content": (
                "Datos de la persona con la que hablas ahora mismo, para que la respuesta se sienta "
                "cercana y personal: " + contexto_personal + " Menciónalos solo cuando venga a cuento "
                "y con naturalidad -- nunca los enumeres todos de golpe ni suenes a ficha de cliente."
            )
        })
    mensajes.extend(historial)
    mensajes.append({"role": "user", "content": prompt_usuario})
    return mensajes, usar_rag


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
    _actualizar_memoria_cruzada(db, usuario_id, chat_id)
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
    mensajes, usar_rag = _preparar_contexto(mensaje, db, usuario_id, chat_id, coleccion, oposicion)
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
    mensajes, usar_rag = _preparar_contexto(mensaje, db, usuario_id, chat_id, coleccion, oposicion)

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
    yield {"tipo": "fin", "chat_id": chat_id, "usar_rag": usar_rag}
