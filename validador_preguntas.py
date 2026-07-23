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

    if not isinstance(pregunta["pregunta"], str) or not isinstance(pregunta["explicacion"], str):
        return False

    # ❌ Filtro de frases prohibidas -- referencias a "el contenido"/"el
    # documento"/"el texto" como si quien hace el test pudiera verlo: solo ve
    # la pregunta, nunca el material de origen, así que una pregunta que
    # remita a él ("¿qué tienen en común... mencionados en el contenido?")
    # queda sin sentido para quien la responde.
    texto_total = (pregunta["pregunta"] + " " + pregunta["explicacion"]).lower()
    frases_prohibidas = [
        "según el contenido", "según el texto", "en el contenido proporcionado",
        "de acuerdo con lo anterior", "según lo anterior", "tal como se indica", "como se ha dicho",
        "del contenido proporcionado", "en el documento proporcionado",
        "en el texto proporcionado", "en el fragmento proporcionado",
        "mencionado en el contenido", "mencionada en el contenido",
        "mencionados en el contenido", "mencionadas en el contenido",
        "mencionado en el documento", "mencionada en el documento",
        "mencionados en el documento", "mencionadas en el documento",
        "mencionado en el texto", "mencionada en el texto",
        "mencionados en el texto", "mencionadas en el texto",
        "arriba mencionado", "arriba mencionada", "arriba mencionados", "arriba mencionadas",
        "anteriormente mencionado", "anteriormente mencionada",
        "anteriormente mencionados", "anteriormente mencionadas", "mencionado anteriormente",
    ]
    if any(frase in texto_total for frase in frases_prohibidas):
        return False

    # ❌ Filtro de siglas de normas -- los exámenes oficiales de estas
    # oposiciones siempre escriben el nombre completo de la ley (nunca "CE"
    # en vez de "Constitución Española", ni "TREBEP", "LPAC"...). Se compara
    # contra el texto ORIGINAL (no en minúsculas): las siglas se escriben en
    # mayúsculas, así que con \b de por medio no coincide con una palabra
    # normal que contenga esas letras (p. ej. "acerca" no matchea "CE").
    texto_original = pregunta["pregunta"] + " " + pregunta["explicacion"]
    siglas_prohibidas = ["CE", "TREBEP", "LPAC", "LRJSP", "LOTC", "LOPJ", "LGP", "LJCA", "LOFAGE", "LOREG"]
    if any(re.search(rf"\b{re.escape(sigla)}\b", texto_original) for sigla in siglas_prohibidas):
        return False

    # ❌ Filtro de "LO 3/2007" / "RD 203/2021" / "RDL 5/2015" -- otra forma
    # habitual de abreviar (aquí "Ley Orgánica"/"Real Decreto"/"Real
    # Decreto-ley" en vez del nombre completo) que no pilla la lista de
    # arriba porque va seguida de un número, no sola. Exigir el número
    # X/YYYY justo detrás evita falsos positivos con "LO" u otras letras
    # sueltas que no estén citando una norma.
    if re.search(r"\b(LO|RDL|RDLeg|RD)\s*\d+/\d{2,4}\b", texto_original):
        return False

    # ❌ Filtro de explicaciones demasiado cortas
    if len(pregunta["explicacion"].strip()) < 15:
        return False

    # ⚠️ (Opcional) Puedes activar esto si quieres rechazar preguntas muy cortas
    # if len(pregunta["pregunta"].strip()) < 20:
    #     return False

    return True
