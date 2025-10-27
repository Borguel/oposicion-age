import os
import json
from deepseek_utils import call_deepseek_api

def generar_tarjetas_desde_texto(texto, num_tarjetas=10):
    """
    Genera tarjetas de memoria desde texto usando DeepSeek
    """
    prompt = f"""
Eres un experto en crear tarjetas de memoria para estudiar oposiciones.
Crea {num_tarjetas} tarjetas con preguntas claras en el anverso y respuestas concisas en el reverso.

Texto del documento:
{texto}

Formato requerido (JSON):
[{{"pregunta": "¿Pregunta aquí?", "respuesta": "Respuesta concisa aquí."}}]

Las tarjetas deben cubrir los conceptos más importantes del documento.
"""

    messages = [
        {"role": "system", "content": "Eres un asistente especializado en crear material de estudio para opositores."},
        {"role": "user", "content": prompt}
    ]

    respuesta = call_deepseek_api(messages, max_tokens=2000, temperature=0.3)
    
    if respuesta:
        try:
            tarjetas = json.loads(respuesta)
            return tarjetas
        except json.JSONDecodeError:
            # Si falla el parseo, devolver la respuesta cruda
            return [{"pregunta": "Error parseando respuesta", "respuesta": respuesta}]
    
    return []