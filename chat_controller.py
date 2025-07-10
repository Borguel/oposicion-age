
import os
import time
from openai import OpenAI
from utils import obtener_contexto_por_temas

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 📌 Asistente tipo chat con el temario (IA + Firestore)
def responder_chat(mensaje, temas, db):
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

    return respuesta.choices[0].message.content.strip()

# ✅ Asistente OpenAI con instrucciones predefinidas (examen AGE)
ASSISTANT_EXAMEN_ID = "asst_EDmGPHxH7FNsEXtFpMWd4Ip4"  # ← cambia esto por tu ID real

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
