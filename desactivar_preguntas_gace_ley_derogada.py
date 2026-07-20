"""
Desactiva en Firestore las preguntas del banco de GACE que preguntan
literalmente por artículos de leyes ya derogadas y sustituidas por normas
con una estructura y numeración de artículos completamente distinta -- no
son solo "la misma ley renombrada": memorizar el artículo citado no sirve
de nada hoy porque ese artículo ya no existe con ese número ni en esa ley.

Se identificaron 41 preguntas así, todas en los exámenes 2008-2013 (ningún
examen de 2018 en adelante cae aquí, porque ya se hicieron con la ley
actual). De esas 41, la pregunta 58 de 2008 estaba ANULADA en la
convocatoria original y por tanto nunca se subió a Firestore (se omite
aquí; quedan 40 doc_id reales a desactivar):

  - Ley 30/1992, de Régimen Jurídico de las AAPP y del Procedimiento
    Administrativo Común -> derogada por la Ley 39/2015 (procedimiento) y
    la Ley 40/2015 (régimen jurídico del sector público), en vigor desde
    el 2 de octubre de 2016.
  - LOFAGE (Ley 6/1997) -> derogada por la Ley 40/2015, Título II.
  - Ley 30/2007, de Contratos del Sector Público -> derogada por la Ley
    9/2017, de Contratos del Sector Público.

Se descartó deliberadamente incluir aquí las preguntas que citan la Ley
30/1984 (de Medidas para la Reforma de la Función Pública): varios
artículos suyos siguen vigentes tras el EBEP (de hecho exámenes tan
recientes como el de 2025 siguen preguntando por ella), así que no está
obsoleta.

USO:
  python desactivar_preguntas_gace_ley_derogada.py --preview
  python desactivar_preguntas_gace_ley_derogada.py --subir
  python desactivar_preguntas_gace_ley_derogada.py --reactivar   (deshace el soft delete)

Variables de entorno necesarias (solo para --subir/--reactivar):
  FIREBASE_CREDENTIALS_JSON (o FIREBASE_KEY_PATH apuntando a clave-firebase.json)
"""
import argparse
import json
import os
import sys

from oposiciones import coleccion_examenes_oficiales

MOTIVOS = {
    "30/1992": (
        "Pregunta redactada sobre la Ley 30/1992 (Régimen Jurídico de las AAPP y del "
        "Procedimiento Administrativo Común), derogada y sustituida por la Ley 39/2015 "
        "y la Ley 40/2015 desde el 2/10/2016, con distinta numeración de artículos."
    ),
    "LOFAGE": (
        "Pregunta redactada sobre la LOFAGE (Ley 6/1997), derogada y sustituida por la "
        "Ley 40/2015 (Título II) desde el 2/10/2016, con distinta numeración de artículos."
    ),
    "30/2007": (
        "Pregunta redactada sobre la Ley 30/2007 de Contratos del Sector Público, "
        "derogada y sustituida por la Ley 9/2017 de Contratos del Sector Público."
    ),
}

# (anio, numero, motivo) -- las 41 preguntas identificadas en la auditoría.
PREGUNTAS = [
    (2008, 8, "LOFAGE"), (2008, 10, "LOFAGE"), (2008, 12, "LOFAGE"),
    (2008, 56, "30/1992"), (2008, 57, "30/1992"), (2008, 67, "30/1992"),
    # (2008, 58, "30/2007") queda fuera: es la pregunta 58 de 2008, ANULADA en
    # la convocatoria original, así que nunca se subió a Firestore.
    (2008, 59, "30/2007"), (2008, 60, "30/2007"),

    (2009, 11, "LOFAGE"), (2009, 13, "LOFAGE"),
    (2009, 53, "30/1992"), (2009, 58, "30/1992"), (2009, 60, "30/1992"),
    (2009, 67, "30/1992"), (2009, 68, "30/1992"), (2009, 69, "30/1992"),
    (2009, 70, "30/1992"), (2009, 71, "30/1992"),

    (2010, 10, "LOFAGE"), (2010, 11, "LOFAGE"), (2010, 12, "LOFAGE"), (2010, 13, "LOFAGE"),
    (2010, 54, "30/1992"), (2010, 65, "30/1992"), (2010, 66, "30/1992"),
    (2010, 67, "30/1992"), (2010, 68, "30/1992"),
    (2010, 55, "30/2007"),

    (2011, 9, "LOFAGE"), (2011, 11, "LOFAGE"),
    (2011, 60, "30/2007"),

    (2013, 16, "LOFAGE"), (2013, 18, "LOFAGE"),
    (2013, 14, "30/1992"), (2013, 56, "30/1992"), (2013, 58, "30/1992"),
    (2013, 71, "30/1992"), (2013, 72, "30/1992"), (2013, 73, "30/1992"), (2013, 74, "30/1992"),
]


def doc_ids():
    """(doc_id, anio, numero, motivo_clave) de las 41 preguntas afectadas."""
    return [(f"gacel_{anio}_1ej_{numero:03d}", anio, numero, motivo) for anio, numero, motivo in PREGUNTAS]


def _firestore_client():
    import firebase_admin
    from firebase_admin import credentials, firestore

    if not firebase_admin._apps:
        cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
        if cred_json:
            cred = credentials.Certificate(json.loads(cred_json))
        else:
            cred = credentials.Certificate(os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json"))
        firebase_admin.initialize_app(cred)
    return firestore.client()


def preview():
    ids = doc_ids()
    print(f"📋 {len(ids)} preguntas de GACE a desactivar (activa=false) por citar una ley ya derogada:\n")
    por_anio = {}
    for doc_id, anio, numero, motivo in ids:
        por_anio.setdefault(anio, []).append((numero, motivo, doc_id))
    for anio in sorted(por_anio):
        print(f"  {anio}:")
        for numero, motivo, doc_id in por_anio[anio]:
            print(f"    #{numero} ({motivo}) -> {doc_id}")
    print("\nEjecuta con --subir para aplicar el soft delete en Firestore, "
          "o --reactivar para deshacerlo.")


def aplicar(activa):
    db = _firestore_client()
    coleccion = coleccion_examenes_oficiales("GACE")
    ids = doc_ids()
    tocadas = no_encontradas = 0
    for doc_id, anio, numero, motivo in ids:
        ref = db.collection(coleccion).document(doc_id)
        if not ref.get().exists:
            print(f"  ⚠️  {doc_id} no existe en Firestore, se omite.")
            no_encontradas += 1
            continue
        datos = {"activa": activa}
        if not activa:
            datos["motivo_desactivacion"] = MOTIVOS[motivo]
        ref.set(datos, merge=True)
        estado = "reactivada" if activa else "desactivada"
        print(f"  ✅ {doc_id} ({anio}, #{numero}, {motivo}) {estado}.")
        tocadas += 1
    accion = "reactivadas" if activa else "desactivadas"
    print(f"\n{tocadas} preguntas {accion}, {no_encontradas} no encontradas en Firestore.")


def main():
    parser = argparse.ArgumentParser(
        description="Desactiva (o reactiva) en Firestore las preguntas de GACE que citan "
        "una ley ya derogada (Ley 30/1992, LOFAGE, Ley 30/2007)."
    )
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--subir", action="store_true")
    parser.add_argument("--reactivar", action="store_true")
    args = parser.parse_args()

    if not any((args.preview, args.subir, args.reactivar)):
        print("Indica --preview, --subir o --reactivar.")
        sys.exit(1)

    if args.preview:
        preview()
    elif args.subir:
        aplicar(activa=False)
    elif args.reactivar:
        aplicar(activa=True)


if __name__ == "__main__":
    main()
