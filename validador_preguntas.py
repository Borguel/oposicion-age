# ✅ validador_preguntas.py mejorado

import re
import unicodedata
from collections import Counter

def normalizar(texto):
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()

def detectar_repeticiones(preguntas, max_repeticiones=2):
    referencias = []

    patron = re.compile(r"(art[ií]culo\s*\d+|constitucion espanola|ley organica \d+/\d+|ley \d+/\d+|poder judicial|defensor del pueblo|estatuto de autonomia)", re.IGNORECASE)

    for p in preguntas:
        texto = p.get("pregunta", "") + " " + p.get("explicacion", "")
        texto_normalizado = normalizar(texto)
        matches = patron.findall(texto_normalizado)
        referencias.extend(matches)

    conteo = Counter(referencias)
    repetidas = {k: v for k, v in conteo.items() if v > max_repeticiones}

    return repetidas

def filtrar_preguntas_repetidas(preguntas, conceptos_repetidos):
    preguntas_filtradas = []
    conceptos_norm = [normalizar(c) for c in conceptos_repetidos]

    for p in preguntas:
        texto = p.get("pregunta", "") + " " + p.get("explicacion", "")
        texto_norm = normalizar(texto)
        if any(rep in texto_norm for rep in conceptos_norm):
            continue
        preguntas_filtradas.append(p)

    return preguntas_filtradas
