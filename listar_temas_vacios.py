"""
Diagnóstico de solo lectura: recorre las 3 colecciones de Temario (AGE, GACE,
Auxiliar) y lista qué bloques/temas todavía no tienen ningún subbloque con
contenido real (campo "texto" no vacío) -- para saber de un vistazo qué queda
por cargar, sin tener que ir mirando Firestore a mano tema por tema.

No escribe nada en Firestore, solo lee.

USO:
  python listar_temas_vacios.py

Variables de entorno necesarias:
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)
"""
import json
import os

COLECCIONES = ["Temario AGE", "Temario GACE", "Temario Auxiliar"]


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


def main():
    db = conectar_firestore()
    algun_vacio = False

    for coleccion in COLECCIONES:
        print(f"\n=== {coleccion} ===")
        bloques = list(db.collection(coleccion).stream())
        if not bloques:
            print("  (la colección no existe o está vacía)")
            continue
        for bloque in sorted(bloques, key=lambda b: b.id):
            bloque_titulo = (bloque.to_dict() or {}).get("titulo", bloque.id)
            temas = list(db.collection(coleccion).document(bloque.id).collection("temas").stream())
            print(f"  {bloque.id} ({bloque_titulo})")
            if not temas:
                print("    (sin temas creados)")
                continue
            for tema in sorted(temas, key=lambda t: t.id):
                tema_titulo = (tema.to_dict() or {}).get("titulo", tema.id)
                subbloques = list(
                    db.collection(coleccion).document(bloque.id).collection("temas")
                      .document(tema.id).collection("subbloques").stream()
                )
                con_texto = [s for s in subbloques if (s.to_dict() or {}).get("texto", "").strip()]
                marca = ""
                if not con_texto:
                    marca = "  ⚠️  VACÍO"
                    algun_vacio = True
                print(f"    {tema.id}: {len(con_texto)} subbloques con texto (de {len(subbloques)} documentos){marca} -- {tema_titulo[:80]}")

    print("\n" + ("⚠️  Hay temas vacíos (ver arriba)." if algun_vacio else "✅ Todos los temas tienen algún subbloque con contenido."))


if __name__ == "__main__":
    main()
