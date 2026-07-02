
import os
import time
from datetime import datetime
from openai import OpenAI
from firebase_admin import firestore
from utils import obtener_contexto_por_temas

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

def responder_chat(mensaje, temas, db, usuario_id="anonimo", chat_id=None):
    contexto = obtener_contexto_por_temas(db, temas)

    prompt = f"""Eres un asistente experto en oposiciones. Utiliza el siguiente contenido del temario para responder con claridad y precisión a la pregunta del usuario.

CONTENIDO DEL TEMARIO:
{contexto}

PREGUNTA DEL USUARIO:
{mensaje}
"""

    respuesta = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Eres un asistente experto en oposiciones."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=800
    )

    texto_respuesta = respuesta.choices[0].message.content.strip()

    if chat_id:
        agregar_mensaje_a_conversacion(db, usuario_id, chat_id, "user", mensaje)
        agregar_mensaje_a_conversacion(db, usuario_id, chat_id, "assistant", texto_respuesta)
    else:
        chat_id = crear_conversacion(db, usuario_id, mensaje, texto_respuesta)

    return texto_respuesta, chat_id

# ✅ Asistente OpenAI con instrucciones predefinidas (examen AGE)
ASSISTANT_EXAMEN_ID = "asst_EDmGPHxH7FNsEXtFpMWd4Ip4"  # ← reemplaza si cambia tu ID

def consultar_asistente_examen_AGE(mensaje_usuario):
    thread = client.beta.threads.create()

    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=mensaje_usuario
    )

    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=ASSISTANT_EXAMEN_ID
    )

    while True:
        run_status = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
        if run_status.status == "completed":
            break
        elif run_status.status in ["failed", "cancelled", "expired"]:
            raise Exception("❌ Error al ejecutar el asistente.")
        time.sleep(1)

    messages = client.beta.threads.messages.list(thread_id=thread.id)
    return messages.data[0].content[0].text.value
