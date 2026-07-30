"""
Rellena los 2 temas de "Temario AGE" que estaban vacíos en Firestore (ver
listar_temas_vacios.py), a partir de los 2 Códigos BOE consolidados aportados
por el usuario en Continuacion-temario-AGE/:

  - bloque_04/tema_09 "El régimen de la Seguridad Social del personal
    laboral." <- BOE-A-2015-11724-consolidado.pdf (Real Decreto Legislativo
    8/2015, texto refundido de la Ley General de la Seguridad Social).
  - bloque_05/tema_06 "Gestión económica y financiera de los contratos del
    sector público." <- BOE-A-2003-21614-consolidado.pdf (Ley 47/2003,
    General Presupuestaria).

A diferencia de cargar_temario_boe.py (que reparte un Código BOE ENTERO
entre varios temas clasificando cada fragmento por IA), aquí no hace falta
clasificar nada: cada PDF es exactamente la norma completa de un único tema,
así que solo se trocea por "Artículo N." (reutilizando
cargar_temario_boe.dividir_en_subbloques tal cual) y se sube entero a su
tema correspondiente.

Aditivo: solo toca esos dos temas concretos de "Temario AGE", nunca borra ni
sobrescribe ningún otro bloque/tema ya cargado.

USO:
  # 1) Vista previa (no escribe nada en Firestore, guarda un informe en JSON):
  python completar_temario_age_bloques_4_5.py --preview

  # 2) Revisa preview_temario_age_bloques_4_5.json, y si está bien, sube:
  python completar_temario_age_bloques_4_5.py --subir

Variables de entorno necesarias:
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)

Requiere: pypdf, tiktoken, firebase-admin (ya están en requirements.txt)
"""
import argparse
import json
import os
import sys

from cargar_temario_boe import extraer_paginas, dividir_en_subbloques

COLECCION = "Temario AGE"
CARPETA_FUENTES = "Continuacion-temario-AGE"

OBJETIVOS = [
    {
        "pdf": "BOE-A-2015-11724-consolidado.pdf",
        "bloque_id": "bloque_04",
        "tema_id": "tema_09",
        "titulo_norma": (
            "Real Decreto Legislativo 8/2015, de 30 de octubre, por el que se "
            "aprueba el texto refundido de la Ley General de la Seguridad Social"
        ),
    },
    {
        "pdf": "BOE-A-2003-21614-consolidado.pdf",
        "bloque_id": "bloque_05",
        "tema_id": "tema_06",
        "titulo_norma": "Ley 47/2003, de 26 de noviembre, General Presupuestaria",
    },
]


def procesar_objetivo(objetivo, carpeta):
    ruta_pdf = os.path.join(carpeta, objetivo["pdf"])
    print(f"📄 {objetivo['bloque_id']}/{objetivo['tema_id']} ← {objetivo['titulo_norma']} ({ruta_pdf})")
    paginas = extraer_paginas(ruta_pdf)
    texto = "\n".join(paginas)
    subbloques = dividir_en_subbloques(texto)
    print(f"   {len(subbloques)} subbloques (por artículo/token)")
    return subbloques


def guardar_preview(resultados_por_objetivo, ruta="preview_temario_age_bloques_4_5.json"):
    resumen = {}
    for clave, subbloques in resultados_por_objetivo.items():
        resumen[clave] = [
            {"rango_articulos": sb["rango_articulos"], "primeras_palabras": " ".join(sb["texto"].split()[:25]) + "…"}
            for sb in subbloques
        ]
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    print(f"📋 Vista previa guardada en {ruta}")
    for clave, subbloques in resumen.items():
        print(f"   {clave}: {len(subbloques)} subbloques")


def subir_a_firestore(resultados_por_objetivo):
    import firebase_admin
    from firebase_admin import credentials, firestore

    if not firebase_admin._apps:
        cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
        if cred_json:
            cred = credentials.Certificate(json.loads(cred_json))
        else:
            cred = credentials.Certificate(os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json"))
        firebase_admin.initialize_app(cred)
    db = firestore.client()

    for objetivo in OBJETIVOS:
        clave = f"{objetivo['bloque_id']}/{objetivo['tema_id']}"
        subbloques = resultados_por_objetivo[clave]

        subbloques_ref = (
            db.collection(COLECCION).document(objetivo["bloque_id"]).collection("temas")
              .document(objetivo["tema_id"]).collection("subbloques")
        )
        existentes = list(subbloques_ref.stream())
        if existentes:
            print(f"🗑️  {clave} ya tenía {len(existentes)} subbloques -- se borran antes de subir los nuevos.")
            for doc in existentes:
                doc.reference.delete()

        for i, sb in enumerate(subbloques, 1):
            sub_id = f"sub_div_{i:03d}"
            subbloques_ref.document(sub_id).set({
                "titulo": objetivo["titulo_norma"][:120],
                "texto": sb["texto"],
            })
        print(f"✅ Subidos {len(subbloques)} subbloques a '{COLECCION}/{clave}'.")


def main():
    parser = argparse.ArgumentParser(
        description="Rellenar bloque_04/tema_09 y bloque_05/tema_06 de Temario AGE."
    )
    parser.add_argument("--carpeta", default=CARPETA_FUENTES, help="Carpeta con los PDF fuente")
    parser.add_argument("--preview", action="store_true", help="Solo procesar y guardar un informe, sin subir nada")
    parser.add_argument("--subir", action="store_true", help="Procesar y subir de verdad a Firestore")
    args = parser.parse_args()

    if not args.preview and not args.subir:
        print("Indica --preview (para ver una vista previa) o --subir (para subir de verdad).")
        sys.exit(1)

    resultados_por_objetivo = {}
    for objetivo in OBJETIVOS:
        ruta = os.path.join(args.carpeta, objetivo["pdf"])
        if not os.path.exists(ruta):
            print(f"⚠️  No se encontró {ruta}, se omite.")
            continue
        clave = f"{objetivo['bloque_id']}/{objetivo['tema_id']}"
        resultados_por_objetivo[clave] = procesar_objetivo(objetivo, args.carpeta)

    guardar_preview(resultados_por_objetivo)

    if args.subir:
        subir_a_firestore(resultados_por_objetivo)


if __name__ == "__main__":
    main()
