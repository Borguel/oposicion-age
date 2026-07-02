
import os
from openai import OpenAI
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
firebase_path = os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json")

# Inicializar Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()

def generar_explicacion(pregunta: str, opciones: dict, respuesta_correcta: str) -> str:
    opciones_texto = "\n".join([f"{k}) {v}" for k, v in opciones.items()])
    prompt = f"""Eres un experto en legislación y oposiciones. Dada la siguiente pregunta de tipo test, explica por qué la opción '{respuesta_correcta}' es la correcta y por qué las demás no lo son. Sé claro, técnico y directo.

Pregunta:
{pregunta}

Opciones:
{opciones_texto}

Respuesta correcta: {respuesta_correcta}

Explicación:
""" 
    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            temperature=0.5,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ Error generando explicación: {e}")
        return ""

def completar_explicaciones():
    print("🧠 Buscando preguntas sin explicación...")
    docs = db.collection("examenes_oficiales_AGE").stream()
    total = 0
    actualizadas = 0

    for doc in docs:
        data = doc.to_dict()
        total += 1
        if not data.get("explicacion") and data.get("pregunta") and data.get("opciones") and data.get("respuesta_correcta"):
            print(f"➡️ Generando explicación para: {doc.id}")
            explicacion = generar_explicacion(data["pregunta"], data["opciones"], data["respuesta_correcta"])
            if explicacion:
                db.collection("examenes_oficiales_AGE").document(doc.id).update({"explicacion": explicacion})
                print("✅ Explicación guardada.")
                actualizadas += 1
            else:
                print("⚠️ No se pudo generar la explicación.")

    print(f"🎯 Proceso completado: {actualizadas} de {total} preguntas actualizadas.")

if __name__ == "__main__":
    completar_explicaciones()
