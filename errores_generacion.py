"""Captura estructurada de errores de generación de contenido (paso 1 de un
loop de mejora de calidad), colección global `errores_generacion`. Dos
fuentes escriben aquí con el MISMO esquema, para poder analizarlas juntas
más adelante:

- "auto_verificacion": cada vez que la verificación legal automática
  rechaza una pregunta durante la generación (ver
  generador_preguntas_verificado._generar_pregunta_verificada).
- "usuario_admin": cada vez que un usuario reporta una pregunta con algún
  error desde la app, revisado luego en el panel admin (ver
  /reportar-pregunta en blueprints/test_ia.py).

De momento esto es solo captura: el análisis agregado y los cambios al
prompt de generación son la siguiente fase.
"""
import logging

from firebase_admin import firestore

logger = logging.getLogger(__name__)

TIPOS_ERROR = ("respuesta_incorrecta", "distractor_implausible", "desfase_legal", "ambiguedad", "otro")
FUENTES = ("auto_verificacion", "usuario_admin")

# Heurística por palabras clave para etiquetar un rechazo con uno de los
# tipos de arriba a partir de su texto, cuando quien llama no indica
# tipo_error explícitamente -- se evalúa en orden y gana el primer tipo
# cuyas palabras aparezcan. No decide si la pregunta se acepta o rechaza
# (eso ya lo hizo la verificación o el usuario), solo clasifica el
# documento de log para el análisis agregado de la siguiente fase.
_PALABRAS_POR_TIPO = (
    ("respuesta_incorrecta", ("respuesta marcada", "respuesta correcta no es", "no es completamente correcta")),
    ("distractor_implausible", ("otra opción", "otras opciones", "opción distinta", "defendible", "tribunal")),
    ("desfase_legal", ("artículo", "articulo", "texto legal", "norma", "plazo", "cifra", "porcentaje",
                        "cuantía", "cuantia", "órgano competente", "organo competente")),
    ("ambiguedad", ("contradicción", "contradiccion", "ambig", "no repasa", "no coincide exactamente")),
)


def _clasificar_tipo_error(detalle):
    texto = (detalle or "").lower()
    for tipo, palabras in _PALABRAS_POR_TIPO:
        if any(p in texto for p in palabras):
            return tipo
    return "otro"


def registrar_error_generacion(db, *, tema_id, fuente, pregunta_texto, detalle,
                                tipo_error=None, intento_numero=None, **campos_extra):
    """Escribe un documento en la colección global `errores_generacion`.

    No bloqueante: esto es solo señal para el loop de mejora de calidad, un
    fallo al escribir se loguea como warning pero nunca se propaga -- no
    debe poder romper ni la generación de tests ni el reporte de un
    usuario.

    campos_extra permite a cada llamante conservar campos propios útiles
    que no forman parte del esquema común (p. ej. uid, oposicion,
    pregunta_id en los reportes de usuario) sin descartarlos.
    """
    tipo = tipo_error or _clasificar_tipo_error(detalle)
    try:
        db.collection("errores_generacion").document().set({
            "tema_id": tema_id,
            "tipo_error": tipo,
            "fuente": fuente,
            "pregunta_texto": (pregunta_texto or "")[:2000],
            "detalle": (detalle or "")[:2000],
            "intento_numero": intento_numero,
            "resuelto": False,
            "timestamp": firestore.SERVER_TIMESTAMP,
            **campos_extra,
        })
        logger.info("[errores_generacion] documento creado: tema_id=%s tipo_error=%s fuente=%s",
                    tema_id, tipo, fuente)
    except Exception:
        logger.warning("[errores_generacion] no se pudo escribir el documento (tema_id=%s fuente=%s)",
                        tema_id, fuente, exc_info=True)
