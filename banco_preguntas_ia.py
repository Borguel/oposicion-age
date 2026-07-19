"""Repositorio interno de preguntas de Test Personalizado ya generadas y
verificadas (ver generador_preguntas_verificado.py), guardado aparte por
oposición en Firestore.

De momento esto es solo almacenamiento: ninguna ruta pública lo lee
todavía. La idea es ir acumulando un banco de preguntas ya verificadas
mientras la web tiene pocos usuarios, para más adelante poder reutilizar
preguntas (ahorrando llamadas a DeepSeek) y buscar por tema en vez de
generar siempre desde cero.
"""
import logging
import re
from datetime import datetime

from oposiciones import OPOSICION_POR_DEFECTO, oposicion_valida

logger = logging.getLogger(__name__)


def coleccion_banco_preguntas(oposicion):
    if not oposicion_valida(oposicion):
        oposicion = OPOSICION_POR_DEFECTO
    return f"banco_preguntas_ia_{oposicion}"


def guardar_pregunta_generada(db, oposicion, pregunta):
    """Guarda una pregunta de Test Personalizado ya verificada en el banco
    de esa oposición. Nunca propaga un error hacia arriba: esto es
    almacenamiento auxiliar, no debe romper la generación del test del
    usuario si Firestore falla."""
    try:
        clave_normalizada = re.sub(r"\s+", " ", str(pregunta.get("pregunta", "")).strip().lower())
        db.collection(coleccion_banco_preguntas(oposicion)).document().set({
            "pregunta": pregunta.get("pregunta"),
            "opciones": pregunta.get("opciones"),
            "respuesta_correcta": pregunta.get("respuesta_correcta"),
            "explicacion": pregunta.get("explicacion"),
            "tema_id": pregunta.get("tema_id"),
            "tipo_pregunta": pregunta.get("tipo_pregunta"),
            "clave_normalizada": clave_normalizada,
            "fecha_generacion": datetime.utcnow().isoformat(),
        })
    except Exception:
        logger.exception("No se pudo guardar en el banco de preguntas (oposición %s)", oposicion)
