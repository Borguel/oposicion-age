import re
from collections import Counter

# ✅ Detección de conceptos repetidos
def detectar_repeticiones(preguntas, max_repeticiones=2):
    referencias = []
    for p in preguntas:
        texto = p.get("pregunta", "") + " " + p.get("explicacion", "")
        matches = re.findall(r"(art[ií]culo\\s*\\d+|Constitución Española|Ley Orgánica [\\d/]+|Poder Judicial|Defensor del Pueblo)", texto, re.IGNORECASE)
        referencias.extend([m.lower() for m in matches])
    conteo = Counter(referencias)
    repetidas = {k: v for k, v in conteo.items() if v > max_repeticiones}
    return repetidas

# ✅ Filtro por conceptos repetidos
def filtrar_preguntas_repetidas(preguntas, conceptos_repetidos):
    preguntas_filtradas = []
    for p in preguntas:
        texto = p.get("pregunta", "") + " " + p.get("explicacion", "")
        if any(rep in texto.lower() for rep in conceptos_repetidos):
            continue
        preguntas_filtradas.append(p)
    return preguntas_filtradas

# ✅ Validación estructural y de calidad
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

    # ❌ Filtro de frases prohibidas
    texto_total = (pregunta["pregunta"] + " " + pregunta["explicacion"]).lower()
    frases_prohibidas = [
        "según el contenido", "según el texto", "en el contenido proporcionado",
        "de acuerdo con lo anterior", "según lo anterior", "tal como se indica", "como se ha dicho"
    ]
    if any(frase in texto_total for frase in frases_prohibidas):
        return False

    # ❌ Filtro de explicaciones demasiado cortas
    if len(pregunta["explicacion"].strip()) < 15:
        return False

    # ⚠️ (Opcional) Puedes activar esto si quieres rechazar preguntas muy cortas
    # if len(pregunta["pregunta"].strip()) < 20:
    #     return False

    return True
