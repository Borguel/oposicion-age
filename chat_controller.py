
import re
import unicodedata
from datetime import datetime
from firebase_admin import firestore
from utils import obtener_catalogo_temas, obtener_contexto_por_temas_exactos
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
        f"Eres el Asistente Premium de Oposición, especializado en el proceso selectivo del "
        f"{nombre}. Ayudas con la estructura del examen, el temario actualizado y consejos de "
        "estudio. Responde en español, de forma clara, precisa y con formato técnico-formal propio "
        "de una oposición. Si no tienes datos concretos y actualizados sobre una convocatoria, dilo "
        "explícitamente en vez de inventarlos."
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
