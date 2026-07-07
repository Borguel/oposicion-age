
import re
import unicodedata
from datetime import datetime
from firebase_admin import firestore
from utils import obtener_catalogo_temas, obtener_contexto_por_temas_exactos, obtener_datos_convocatoria
from deepseek_utils import call_deepseek_api
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
        "redactados, sin encabezados innecesarios."
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


# 📌 Tu Tutor: chat unificado que decide, mensaje a mensaje, si busca
# contexto real del temario (RAG) o responde como coach genérico del
# proceso selectivo. Guarda siempre el historial en Firestore.
def responder_tutor(mensaje, db, usuario_id="anonimo", chat_id=None, coleccion="Temario AGE", oposicion=OPOSICION_POR_DEFECTO):
    catalogo = obtener_catalogo_temas(db, coleccion)
    temas_detectados = _temas_mencionados(mensaje, catalogo)
    usar_rag = _necesita_rag(mensaje, temas_detectados)

    if usar_rag:
        # Si se detectó un tema concreto por título, se busca solo ahí; si
        # el mensaje solo menciona un patrón genérico ("artículo 14") sin
        # calzar con ningún título, se busca en todo el catálogo en vez de
        # quedarse sin contexto -- mejor un poco de contenido de más que
        # ninguno cuando ya se decidió que hace falta RAG.
        temas_para_buscar = temas_detectados or [tema["id"] for tema in catalogo]
        contexto = obtener_contexto_por_temas_exactos(db, temas_para_buscar, coleccion=coleccion)
        system_prompt = "Eres un asistente experto en oposiciones."
        prompt_usuario = (
            f"Eres un asistente experto en oposiciones. Utiliza el siguiente contenido del temario "
            f"para responder con claridad y precisión a la pregunta del usuario.\n\n"
            f"CONTENIDO DEL TEMARIO:\n{contexto}\n\n"
            f"PREGUNTA DEL USUARIO:\n{mensaje}"
        ) if contexto else mensaje
    else:
        system_prompt = _instrucciones_asistente_examen(oposicion)
        datos_convocatoria = obtener_datos_convocatoria(db, oposicion) if _necesita_datos_convocatoria(mensaje) else None
        if datos_convocatoria:
            prompt_usuario = (
                "A continuación tienes datos OFICIALES de la convocatoria vigente de esta "
                "oposición, transcritos de las normas específicas publicadas en el BOE. "
                "OJO: el usuario NO te ha dado estos datos en su mensaje, son información de "
                "referencia que ya tienes -- así que nunca digas cosas como \"según los datos "
                "que me has facilitado/proporcionado\" ni le atribuyas al usuario esta "
                "información. Cítalos como lo que son, datos públicos, con frases del tipo "
                "\"según los datos oficiales de la convocatoria de 2025...\" o \"según las "
                "normas específicas publicadas en el BOE...\". Úsalos como fuente principal si "
                "la pregunta trata sobre ellos, en vez de inventar cifras:\n\n"
                f"{datos_convocatoria}\n\n"
                f"PREGUNTA DEL USUARIO:\n{mensaje}"
            )
        else:
            prompt_usuario = mensaje

    respuesta = call_deepseek_api(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt_usuario}
        ],
        temperature=0.7,
        max_tokens=800
    )
    texto_respuesta = (respuesta or "No se pudo generar una respuesta. Inténtalo de nuevo.").strip()

    if chat_id:
        agregar_mensaje_a_conversacion(db, usuario_id, chat_id, "user", mensaje)
        agregar_mensaje_a_conversacion(db, usuario_id, chat_id, "assistant", texto_respuesta)
    else:
        chat_id = crear_conversacion(db, usuario_id, mensaje, texto_respuesta)

    return texto_respuesta, chat_id, usar_rag
