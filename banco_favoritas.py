"""Banco persistente de "preguntas favoritas" marcadas por el usuario para
repasar más tarde, independientemente de si las acertó o falló.

Usa el mismo patrón de deduplicación por hash que ya prueba
banco_fallos.py para las preguntas falladas:

  usuarios/{uid}/preguntas_favoritas/{hash(oposicion+pregunta)}

A diferencia del banco de fallos, aquí no hay ninguna lógica automática
(nada la añade ni la quita salvo que el usuario pulse la estrella): marcar
guarda la pregunta completa (para poder generar un test después sin volver
a buscarla), desmarcar simplemente borra ese documento.
"""
import hashlib
from datetime import datetime


def _id_pregunta(oposicion, pregunta):
    clave = f"{oposicion}||{(pregunta or '').strip()}"
    return hashlib.sha256(clave.encode("utf-8", "ignore")).hexdigest()[:24]


def marcar_favorita(db, usuario_id, oposicion, pregunta):
    ref = db.collection("usuarios").document(usuario_id).collection("preguntas_favoritas") \
        .document(_id_pregunta(oposicion, pregunta.get("pregunta", "")))
    ref.set({
        "oposicion": oposicion,
        "tema_id": pregunta.get("tema_id") or "",
        "pregunta": pregunta.get("pregunta", ""),
        "opciones": pregunta.get("opciones", {}),
        "respuesta_correcta": pregunta.get("respuesta_correcta"),
        "explicacion": pregunta.get("explicacion", "Sin explicación."),
        "fecha_marcada": datetime.utcnow().isoformat(),
    }, merge=True)


def desmarcar_favorita(db, usuario_id, oposicion, texto_pregunta):
    db.collection("usuarios").document(usuario_id).collection("preguntas_favoritas") \
        .document(_id_pregunta(oposicion, texto_pregunta)).delete()


def listar_favoritas(db, usuario_id, oposicion):
    docs = db.collection("usuarios").document(usuario_id).collection("preguntas_favoritas") \
        .where("oposicion", "==", oposicion).stream()
    return [d.to_dict() for d in docs]
