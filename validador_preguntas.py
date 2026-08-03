import re
from collections import Counter

# Frases que delatan que la pregunta/respuesta remite al documento de origen
# en vez de tener sentido por sí sola (p. ej. "¿Qué tipos de costumbre
# existen SEGÚN EL TEXTO...?") -- inútiles para quien responde sin ver ese
# documento, sea un test (validar_pregunta, abajo) o una tarjeta de memoria
# suelta (tarjetas_generator.py, que reutiliza esta misma lista).
FRASES_PROHIBIDAS = [
    "según el contenido", "según el texto", "según el documento", "en el contenido proporcionado",
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
    "de acuerdo con el contenido", "de acuerdo con el texto",
    "de acuerdo con el documento", "de acuerdo con el fragmento",
    "lo que has subido", "el documento que has subido", "el pdf que has subido",
]

# Igual que FRASES_PROHIBIDAS pero como PATRONES (no frases exactas): dos
# construcciones muy habituales de referencia al documento de origen que la
# lista de arriba no cazaba porque no es una frase fija, sino [preposición]
# + [documento/contenido/texto/tema/fragmento] o [documento/contenido/
# texto/tema/fragmento] + [verbo] con cualquier redacción intermedia --
# vistas repetidas veces en un test real generado desde PDF (03/08/2026):
# la primera pregunta empezaba con "Conforme al contenido del tema..."
# (FRASES_PROHIBIDAS solo cubre "según"/"de acuerdo con", no "conforme a"),
# y varias explicaciones decían "el documento establece/indica/menciona
# que..." o "el tema cita el artículo..." (sujeto + verbo, no una frase fija
# que se pueda listar una a una).
#
# El [sujeto]+[verbo] admite una cláusula intercalada entre comas (03/08/2026,
# bug real, documento real): "el documento, al detallar la iniciativa de
# reforma, señala que..." se coló porque el patrón exigía que el verbo
# viniera INMEDIATAMENTE después del sustantivo (solo espacios de por
# medio) -- cualquier inciso entre comas antes del verbo lo dejaba sin
# detectar aunque la referencia al documento fuera exactamente la misma.
PATRON_REFERENCIA_META = re.compile(
    r"\b(seg[uú]n|de\s+acuerdo\s+con)\s+(el|la|lo)\s+(documento|contenido|texto|tema|fragmento)\b"
    r"|\bconforme\s+(al|a\s+la|a\s+lo)\s+(documento|contenido|texto|tema|fragmento)\b"
    r"|\b(el|la)\s+(documento|contenido|texto|tema|fragmento)\b"
    r"(?:\s*,\s*[^,.]{1,80}\s*,)?\s+"
    r"(establece|indica|se[ñn]ala|menciona|dice|cita|dispone|regula|recoge|prev[ée]|afirma|explica)\b",
    re.IGNORECASE,
)


def contiene_referencia_meta(texto):
    """True si 'texto' remite al documento/tema/contenido de origen en vez
    de tener sentido por sí solo -- ver PATRON_REFERENCIA_META arriba.
    Complementa (no sustituye) a FRASES_PROHIBIDAS: esta lista cubre frases
    FIJAS que un simple 'in' ya detecta, mientras que este patrón cubre
    construcciones con verbo o preposición que varían de redacción."""
    return bool(PATRON_REFERENCIA_META.search(texto or ""))

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
    if any(frase in texto_total for frase in FRASES_PROHIBIDAS):
        return False

    # ❌ Igual que el filtro de arriba pero por patrón, no por frase fija --
    # ver PATRON_REFERENCIA_META: "conforme al contenido", "el documento
    # establece que...", "el tema cita el artículo..." etc.
    if contiene_referencia_meta(texto_total):
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
