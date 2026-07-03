
from datetime import datetime
from firebase_admin import firestore
from utils import obtener_contexto_por_temas
from deepseek_utils import call_deepseek_api

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

# 📌 Asistente tipo chat con el temario (IA + Firestore + historial)

def responder_chat(mensaje, temas, db, usuario_id="anonimo", chat_id=None, coleccion="Temario AGE"):
    contexto = obtener_contexto_por_temas(db, temas, coleccion=coleccion)

    prompt = f"""Eres un asistente experto en oposiciones. Utiliza el siguiente contenido del temario para responder con claridad y precisión a la pregunta del usuario.

CONTENIDO DEL TEMARIO:
{contexto}

PREGUNTA DEL USUARIO:
{mensaje}
"""

    respuesta = call_deepseek_api(
        messages=[
            {"role": "system", "content": "Eres un asistente experto en oposiciones."},
            {"role": "user", "content": prompt}
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

    return texto_respuesta, chat_id

# ✅ Asistente premium especializado en el examen AGE
INSTRUCCIONES_ASISTENTE_EXAMEN = (
    "Eres el Asistente Premium de Oposición AGE, especializado en el proceso selectivo del "
    "Cuerpo General Administrativo del Estado. Ayudas con la estructura del examen, el temario "
    "actualizado y consejos de estudio. Responde en español, de forma clara, precisa y con "
    "formato técnico-formal propio de una oposición. Si no tienes datos concretos y actualizados "
    "sobre una convocatoria, dilo explícitamente en vez de inventarlos."
)

def consultar_asistente_examen_AGE(mensaje_usuario):
    respuesta = call_deepseek_api(
        messages=[
            {"role": "system", "content": INSTRUCCIONES_ASISTENTE_EXAMEN},
            {"role": "user", "content": mensaje_usuario}
        ],
        temperature=0.6,
        max_tokens=900
    )
    if not respuesta:
        raise Exception("❌ Error al consultar el asistente.")
    return respuesta.strip()
