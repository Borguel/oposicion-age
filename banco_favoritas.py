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
import random
from datetime import datetime

from banco_preguntas_comun import id_pregunta as _id_pregunta


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
        "imagen": pregunta.get("imagen", ""),
        "fecha_marcada": datetime.utcnow().isoformat(),
    }, merge=True)


def desmarcar_favorita(db, usuario_id, oposicion, texto_pregunta):
    db.collection("usuarios").document(usuario_id).collection("preguntas_favoritas") \
        .document(_id_pregunta(oposicion, texto_pregunta)).delete()


def listar_favoritas(db, usuario_id, oposicion):
    docs = db.collection("usuarios").document(usuario_id).collection("preguntas_favoritas") \
        .where("oposicion", "==", oposicion).stream()
    return [d.to_dict() for d in docs]


def ordenar_por_prioridad_repaso(candidatas):
    """Repaso espaciado para favoritas: al no haber un contador de fallos
    (el usuario las marca, no importa si acertó o falló), la prioridad es
    simplemente "cuánto tiempo llevas sin repasar esta" -- las nunca
    repasadas en un test de favoritas van primero, luego las más antiguas.
    Así, con un banco grande, el test rota por todas en vez de repetir
    siempre por azar las mismas."""
    ahora = datetime.utcnow()

    def _antiguedad_segundos(pregunta):
        fecha_str = pregunta.get("fecha_ultimo_repaso")
        if not fecha_str:
            return float("inf")  # nunca repasada: máxima prioridad
        try:
            return (ahora - datetime.fromisoformat(fecha_str)).total_seconds()
        except ValueError:
            return float("inf")

    random.shuffle(candidatas)
    candidatas.sort(key=_antiguedad_segundos, reverse=True)
    return candidatas


def marcar_repasadas(db, usuario_id, oposicion, preguntas):
    """Actualiza fecha_ultimo_repaso de las preguntas que acaban de salir
    en un test de favoritas, para que el repaso espaciado deje de
    priorizarlas una temporada y rote hacia el resto del banco."""
    coleccion = db.collection("usuarios").document(usuario_id).collection("preguntas_favoritas")
    ahora = datetime.utcnow().isoformat()
    for p in preguntas:
        coleccion.document(_id_pregunta(oposicion, p.get("pregunta", ""))).set(
            {"fecha_ultimo_repaso": ahora}, merge=True
        )
