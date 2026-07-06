"""
Borra las subdivisiones ("subbloques") con el campo "texto" vacío dentro de
unos temas concretos de una colección de Temario -- pensado para limpiar las
subdivisiones en blanco que se hubieran precreado a mano (p. ej. para rellenar
más rápido después) y que sigan vacías tras subir contenido real con
completar_temario_age.py o cargar_temario_boe.py.

Nunca toca un subbloque cuyo campo "texto" tenga contenido (aunque sea corto);
solo borra los que estén realmente vacíos (ausentes, None, o solo espacios).

USO:
  # 1) Simulación (no borra nada, solo imprime qué borraría):
  python limpiar_subdivisiones_vacias.py --coleccion "Temario AGE" --bloque-tema 4:6 --bloque-tema 4:7 --bloque-tema 4:8 --bloque-tema 4:9 --bloque-tema 5:1 --bloque-tema 5:2 --bloque-tema 5:3 --bloque-tema 5:4 --bloque-tema 5:5 --bloque-tema 5:6

  # 2) Si la simulación se ve bien, borra de verdad:
  python limpiar_subdivisiones_vacias.py --coleccion "Temario AGE" --bloque-tema 4:6 ... --aplicar

Variables de entorno necesarias:
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)
"""
import argparse
import json
import os


def conectar_firestore():
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


def parsear_bloque_tema(valor):
    bloque_str, tema_str = valor.split(":")
    return int(bloque_str), int(tema_str)


def limpiar(db, coleccion, pares_bloque_tema, aplicar=False):
    total_vacios = 0
    total_con_contenido = 0
    for bloque_num, tema_num in pares_bloque_tema:
        bloque_id = f"bloque_{bloque_num:02d}"
        tema_id = f"tema_{tema_num:02d}"
        subbloques_ref = db.collection(coleccion).document(bloque_id).collection("temas") \
            .document(tema_id).collection("subbloques")
        docs = list(subbloques_ref.stream())
        vacios_aqui = 0
        for doc in docs:
            datos = doc.to_dict() or {}
            texto = (datos.get("texto") or "").strip()
            if texto:
                total_con_contenido += 1
                continue
            vacios_aqui += 1
            total_vacios += 1
            print(f"  → {bloque_id}/{tema_id}/{doc.id}: vacío" + (" (se borra)" if aplicar else " (se borraría)"))
            if aplicar:
                doc.reference.delete()
        if vacios_aqui == 0:
            print(f"  {bloque_id}/{tema_id}: ningún subbloque vacío ({len(docs)} en total, todos con contenido)")

    print()
    print(f"{'Borrados' if aplicar else 'A borrar'}: {total_vacios} subbloques vacíos")
    print(f"Conservados (con contenido real): {total_con_contenido} subbloques")
    if not aplicar:
        print("👀 Esto ha sido solo una SIMULACIÓN, no se ha borrado nada. Ejecuta con --aplicar para borrar de verdad.")


def main():
    parser = argparse.ArgumentParser(description="Borra subdivisiones vacías (sin texto) de unos temas concretos.")
    parser.add_argument("--coleccion", required=True, help='p. ej. "Temario AGE" o "Temario GACE"')
    parser.add_argument(
        "--bloque-tema", action="append", required=True, dest="bloque_tema",
        help='Par "bloque:tema" a limpiar, p. ej. --bloque-tema 4:6 (repetible, uno por cada tema)',
    )
    parser.add_argument("--aplicar", action="store_true", help="Borra de verdad (si no, solo simula)")
    args = parser.parse_args()

    pares = [parsear_bloque_tema(v) for v in args.bloque_tema]
    db = conectar_firestore()
    limpiar(db, args.coleccion, pares, aplicar=args.aplicar)


if __name__ == "__main__":
    main()
