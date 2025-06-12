
import os
from openai import OpenAI
from dotenv import load_dotenv
from utils import obtener_contexto_por_temas

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generar_esquema(temas, db, instrucciones="Resume los puntos clave del temario", nivel="general"):
    """
    Genera un esquema a partir de los temas indicados y el contenido del temario en Firestore.
    """
    contexto = obtener_contexto_por_temas(db, temas)

    prompt = f"""
Eres un experto en oposiciones. A continuación tienes contenido legal y técnico relacionado con los temas {temas}.

{instrucciones}

Nivel de detalle: {nivel}

Contenido del temario:
{contexto}

Esquema generado:
"""

    respuesta = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Eres un generador de esquemas claros y organizados para opositores."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=700,
        temperature=0.4
    )

    return respuesta.choices[0].message.content.strip()
