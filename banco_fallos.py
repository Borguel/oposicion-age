"""Banco persistente de "preguntas falladas" por usuario/oposición.

Antes, el test de "preguntas falladas" recorría todo el historial de
usuarios/{uid}/tests cada vez que se pedía, sin distinguir de qué tipo de
test venía cada pregunta y sin ninguna forma de "dejar de fallar" una
pregunta salvo dejar de aparecer en el muestreo aleatorio. Este módulo la
sustituye por una colección propia, deduplicada, que se actualiza cada vez
que se corrige un test:

  usuarios/{uid}/preguntas_falladas/{hash(oposicion+pregunta)}

Solo los tests "personalizado", "oficial" y el propio repaso de "falladas"
alimentan/vacían este banco (un test "inteligente" o "repetido" nunca lo
toca, tal y como se pidió). Una pregunta desaparece del banco en cuanto se
acierta en cualquiera de esos tres tipos; si se vuelve a fallar en el
repaso de "falladas" se actualiza la misma entrada (nunca se duplica).
"""
import hashlib
from datetime import datetime
from firebase_admin import firestore

TIPOS_QUE_ALIMENTAN_BANCO = {"personalizado", "oficial", "falladas"}


def _id_pregunta(oposicion, pregunta):
    clave = f"{oposicion}||{(pregunta or '').strip()}"
    return hashlib.sha256(clave.encode("utf-8", "ignore")).hexdigest()[:24]


def actualizar_banco_fallos(db, usuario_id, oposicion, tipo_test, contenido, respuestas):
    if tipo_test not in TIPOS_QUE_ALIMENTAN_BANCO:
        return

    coleccion = db.collection("usuarios").document(usuario_id).collection("preguntas_falladas")
    for i, p in enumerate(contenido):
        seleccion = respuestas[i] if i < len(respuestas) else None
        if seleccion is None:
            continue  # en blanco: no es un fallo, pero tampoco confirma que se domine

        correcta = p.get("respuesta_correcta")
        ref = coleccion.document(_id_pregunta(oposicion, p.get("pregunta", "")))
        if seleccion == correcta:
            ref.delete()
        else:
            ref.set({
                "oposicion": oposicion,
                "tema_id": p.get("tema_id") or "",
                "pregunta": p.get("pregunta", ""),
                "opciones": p.get("opciones", {}),
                "respuesta_correcta": correcta,
                "explicacion": p.get("explicacion", "Sin explicación."),
                "origen": tipo_test,
                "fecha_ultimo_fallo": datetime.utcnow().isoformat(),
                "veces_fallada": firestore.Increment(1),
            }, merge=True)
