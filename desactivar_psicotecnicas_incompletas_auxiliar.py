"""
Desactiva en Firestore las preguntas psicotécnicas de Auxiliar cuyo
enunciado remite a una tabla de datos (p. ej. "49 a 54 (Tabla Ponencias).
Según los datos anteriores...") que nunca se transcribió del examen
original: la IA no pudo localizarla al extraer el PDF, así que el usuario
ve una pregunta con opciones de respuesta pero sin la información
necesaria para poder resolverla.

Se identificaron 48 preguntas así repartidas en los 4 exámenes ya
cargados (12 por examen, en dos bloques de 6 preguntas sobre una tabla
distinta cada uno):
  - 2019: preguntas 31-36 (tabla de salas) y 44-49 (tabla academia idiomas)
  - 2022: preguntas 49-54 (Tabla Ponencias) y 55-60 (Tablas Flores)
  - 2024: preguntas 49-54 (cuadro Biblioteca) y 55-60 (cuadro Laboratorios)
  - 2025: preguntas 49-54 (tabla "Préstamos") y 55-60 (tabla "Desplazamientos")

datos_examenes/auxiliar_<anio>_ejercicio_unico.json ya se actualizó para
marcar estas 48 preguntas con "incompleta": true (cargar_examen_oficial_
auxiliar.py las omite desde ahora en cualquier subida futura), pero las 4
convocatorias ya estaban subidas a Firestore antes de detectar el
problema. Este script marca esos documentos ya existentes con
activa=false (el mismo soft delete que usa el panel admin en
/admin/api/preguntas/<id>, ver blueprints/admin.py:preguntas_desactivar):
obtener_preguntas_examenes_oficiales() en utils.py ya excluye
activa=false, así que /generar-test-oficial deja de servirlas de
inmediato sin necesidad de volver a cargar el examen entero (lo que
regeneraría explicaciones ya existentes sin necesidad).

No completa el enunciado con datos inventados: si en el futuro se
localiza la tabla original, se puede reactivar la pregunta a mano desde
el panel admin (o con --reactivar) y editar su enunciado con la tabla
real.

USO:
  python desactivar_psicotecnicas_incompletas_auxiliar.py --preview
  python desactivar_psicotecnicas_incompletas_auxiliar.py --subir
  python desactivar_psicotecnicas_incompletas_auxiliar.py --reactivar   (deshace el soft delete)

Variables de entorno necesarias (solo para --subir/--reactivar):
  FIREBASE_CREDENTIALS_JSON (o FIREBASE_KEY_PATH apuntando a clave-firebase.json)
"""
import argparse
import json
import os
import sys

from oposiciones import coleccion_examenes_oficiales

MOTIVO = (
    "Enunciado remite a una tabla de datos que no se transcribió del "
    "examen original: sin esos datos la pregunta no se puede responder "
    "con la información disponible."
)

# (anio, numero_inicio, numero_fin, nombre_tabla) -- todas en la parte
# "primera", que es donde vive el bloque de psicotécnicas de Auxiliar.
RANGOS = [
    (2019, 31, 36, "tabla de salas"),
    (2019, 44, 49, "tabla academia idiomas"),
    (2022, 49, 54, "Tabla Ponencias"),
    (2022, 55, 60, "Tablas Flores"),
    (2024, 49, 54, "cuadro Biblioteca"),
    (2024, 55, 60, "cuadro Laboratorios"),
    (2025, 49, 54, 'tabla "Préstamos"'),
    (2025, 55, 60, 'tabla "Desplazamientos"'),
]


def doc_ids():
    """(doc_id, anio, numero, nombre_tabla) de las 48 preguntas afectadas."""
    resultado = []
    for anio, ini, fin, nombre_tabla in RANGOS:
        for numero in range(ini, fin + 1):
            doc_id = f"auxiliar_{anio}_eu_p1_{numero:03d}"
            resultado.append((doc_id, anio, numero, nombre_tabla))
    return resultado


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
    print(f"📋 {len(ids)} preguntas psicotécnicas de Auxiliar a desactivar (activa=false):\n")
    por_anio = {}
    for doc_id, anio, numero, nombre_tabla in ids:
        por_anio.setdefault(anio, []).append((numero, nombre_tabla, doc_id))
    for anio in sorted(por_anio):
        print(f"  {anio}:")
        for numero, nombre_tabla, doc_id in por_anio[anio]:
            print(f"    primera_{numero} ({nombre_tabla}) -> {doc_id}")
    print("\nEjecuta con --subir para aplicar el soft delete en Firestore, "
          "o --reactivar para deshacerlo.")


def aplicar(activa):
    db = _firestore_client()
    coleccion = coleccion_examenes_oficiales("AUXILIAR")
    ids = doc_ids()
    tocadas = no_encontradas = 0
    for doc_id, anio, numero, nombre_tabla in ids:
        ref = db.collection(coleccion).document(doc_id)
        if not ref.get().exists:
            print(f"  ⚠️  {doc_id} no existe en Firestore, se omite.")
            no_encontradas += 1
            continue
        datos = {"activa": activa}
        if not activa:
            datos["motivo_desactivacion"] = MOTIVO
        ref.set(datos, merge=True)
        estado = "reactivada" if activa else "desactivada"
        print(f"  ✅ {doc_id} ({anio}, primera_{numero}, {nombre_tabla}) {estado}.")
        tocadas += 1
    accion = "reactivadas" if activa else "desactivadas"
    print(f"\n{tocadas} preguntas {accion}, {no_encontradas} no encontradas en Firestore.")


def main():
    parser = argparse.ArgumentParser(
        description="Desactiva (o reactiva) en Firestore las preguntas psicotécnicas "
        "de Auxiliar cuyo enunciado remite a una tabla de datos no transcrita."
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
