"""Identificador compartido de pregunta entre los bancos por-usuario
(banco_fallos.py, banco_favoritas.py): antes cada módulo definía su propia
copia, byte a byte idéntica, de esta misma función -- con el riesgo real
de que un cambio futuro del esquema de hash se aplicara a una sin
acordarse de la otra, rompiendo la deduplicación en silencio (dos
documentos distintos para la "misma" pregunta, o al revés)."""

import hashlib


def id_pregunta(oposicion, pregunta):
    """Id estable y determinista para una pregunta dentro de una oposición
    (no hay ningún id de Firestore que viaje de vuelta desde el banco de
    origen): hash truncado de "oposicion||enunciado", para poder
    encontrar/actualizar siempre el mismo documento en vez de duplicarlo."""
    clave = f"{oposicion}||{(pregunta or '').strip()}"
    return hashlib.sha256(clave.encode("utf-8", "ignore")).hexdigest()[:24]
