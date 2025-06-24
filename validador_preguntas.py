import re
from collections import Counter

def detectar_repeticiones(preguntas, max_repeticiones=2):
    referencias = []

    for p in preguntas:
        texto = p.get("pregunta", "") + " " + p.get("explicacion", "")
        # Buscar referencias a artículos o frases repetidas
        matches = re.findall(r"(art[ií]culo\s*\d+|Constitución Española|Ley Orgánica [\d/]+|Poder Judicial|Defensor del Pueblo)", texto, re.IGNORECASE)
        referencias.extend([m.lower() for m in matches])

    # Contar cuántas veces se repite cada concepto
    conteo = Counter(referencias)
    repetidas = {k: v for k, v in conteo.items() if v > max_repeticiones}

    return repetidas  # Diccionario con los conceptos repetidos

def filtrar_preguntas_repetidas(preguntas, conceptos_repetidos):
    preguntas_filtradas = []
    for p in preguntas:
        texto = p.get("pregunta", "") + " " + p.get("explicacion", "")
        if any(rep in texto.lower() for rep in conceptos_repetidos):
            continue
        preguntas_filtradas.append(p)
    return preguntas_filtradas

# ✅ Añadir esta función al final del archivo
def validar_pregunta(pregunta):
    if not isinstance(pregunta, dict):
        return False

    claves = ["pregunta", "opciones", "respuesta_correcta", "explicacion"]
    if not all(clave in pregunta for clave in claves):
        return False

    if not isinstance(pregunta["opciones"], dict):
        return False

    opciones = pregunta["opciones"]
    if not all(opcion in opciones for opcion in ["A", "B", "C", "D"]):
        return False

    return True
