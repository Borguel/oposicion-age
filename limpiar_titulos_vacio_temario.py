"""
Limpia el marcador literal "VACIO" / "(VACIO)" que quedó pegado al final del
campo "titulo" de algunos temas (en las 3 colecciones de Temario), puesto
ahí como recordatorio manual antes de cargar contenido -- y que
listar_temas_vacios.py sacó a la luz al imprimir el titulo tal cual.

No toca subbloques ni contenido: solo corrige el texto del campo "titulo"
del documento de tema, quitando el sufijo " VACIO" / " (VACIO)" (con o sin
espacio/paréntesis, sin distinguir mayúsculas) donde aparezca, tenga o no
contenido real el tema ahora mismo.

USO:
  python limpiar_titulos_vacio_temario.py --preview
  python limpiar_titulos_vacio_temario.py --subir

Variables de entorno necesarias (solo para --subir):
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)
"""
import argparse
import json
import os
import re
import sys

COLECCIONES = ["Temario AGE", "Temario GACE", "Temario Auxiliar"]
PATRON_MARCADOR = re.compile(r"\s*\(?\s*vac[ií]o\s*\)?\s*$", re.IGNORECASE)


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


def encontrar_titulos_a_corregir(db):
    """Recorre las 3 colecciones y devuelve una lista de
    (coleccion, bloque_id, tema_id, titulo_actual, titulo_corregido) para
    cada tema cuyo titulo lleva el marcador."""
    encontrados = []
    for coleccion in COLECCIONES:
        for bloque in db.collection(coleccion).stream():
            temas_ref = db.collection(coleccion).document(bloque.id).collection("temas")
            for tema in temas_ref.stream():
                titulo = (tema.to_dict() or {}).get("titulo", "")
                if not titulo:
                    continue
                corregido = PATRON_MARCADOR.sub("", titulo).rstrip()
                if corregido != titulo:
                    encontrados.append((coleccion, bloque.id, tema.id, titulo, corregido))
    return encontrados


def guardar_preview(encontrados, ruta="preview_limpiar_titulos_vacio.json"):
    resumen = [
        {"coleccion": c, "bloque_id": b, "tema_id": t, "titulo_actual": ta, "titulo_corregido": tc}
        for c, b, t, ta, tc in encontrados
    ]
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    print(f"📋 Vista previa guardada en {ruta}")
    print(f"\n📊 {len(encontrados)} títulos con marcador a corregir:")
    for c, b, t, ta, tc in encontrados:
        print(f"   {c}/{b}/{t}:")
        print(f"      antes:   {ta!r}")
        print(f"      después: {tc!r}")


def corregir_en_firestore(db, encontrados):
    for coleccion, bloque_id, tema_id, _titulo_actual, titulo_corregido in encontrados:
        db.collection(coleccion).document(bloque_id).collection("temas").document(tema_id).update({
            "titulo": titulo_corregido
        })
    print(f"✅ Corregidos {len(encontrados)} títulos.")


def main():
    parser = argparse.ArgumentParser(description="Quitar el marcador 'VACIO'/'(VACIO)' de los títulos de tema en Firestore.")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--subir", action="store_true")
    args = parser.parse_args()

    if not args.preview and not args.subir:
        print("Indica --preview (para ver una vista previa) o --subir (para corregir de verdad).")
        sys.exit(1)

    db = conectar_firestore()
    encontrados = encontrar_titulos_a_corregir(db)
    guardar_preview(encontrados)

    if args.subir:
        corregir_en_firestore(db, encontrados)


if __name__ == "__main__":
    main()
