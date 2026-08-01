"""
Rellena ÚNICAMENTE el tema 9 del bloque 1 de "Temario GACE" ("El sector público
institucional: entidades que lo integran y régimen jurídico."), que está vacío en
Firestore pese a que el contenido SÍ existe en el PDF ya usado para cargar el resto
del temario.

Diagnóstico (ver detalle en el plan de esta sesión): el PDF "BOE-443 Normativa para
ingreso en el Cuerpo de Gestión de la Administración Civil del Estado" incluye la Ley
40/2015, de Régimen Jurídico del Sector Público, DOS veces:
  - § 7 (página impresa 343): marcada "[Inclusión parcial]", solo trae el Título I
    (Administración General del Estado -> tema 8).
  - § 45 (página impresa 2051): inclusión mucho más completa, SIN esa marca, que sí
    trae el Título II (Organización y funcionamiento del sector público institucional
    -> tema 9, arts. 81 a 136) antes de pasar al Título III (Relaciones
    interadministrativas, art. 140).

El pipeline original de carga (cargar_temario_boe.py) probablemente clasificó mal los
fragmentos de esta segunda inclusión -- al compartir el mismo norma_titulo que el
Título I, es fácil que el clasificador por IA los metiera todos en tema 8 en vez de
distinguir por contenido. Este script no reintenta esa clasificación: ya sabemos
exactamente qué texto corresponde a tema 9 (delimitado por los propios encabezados
"TÍTULO II" / "TÍTULO III" del documento), así que lo extrae directamente y lo sube.

A diferencia de cargar_temario_boe.py (que resube un temario entero borrando y
recreando subbloques), este script es deliberadamente ADITIVO: solo toca
bloque_01/tema_09 de "Temario GACE", nunca borra ni sobrescribe ningún otro
tema/bloque ya existente.

USO:
  # 1) Vista previa (no escribe nada en Firestore, guarda un informe en JSON):
  python completar_tema_gace_sector_publico.py --preview

  # 2) Revisa preview_tema_gace_09.json, y si está bien, sube de verdad:
  python completar_tema_gace_sector_publico.py --subir

Variables de entorno necesarias:
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)

Requiere: pypdf, firebase-admin (ya están en requirements.txt)
"""
import argparse
import json
import os
import re
import sys

from cargar_temario_boe import extraer_paginas, dividir_en_subbloques

PDF_FUENTE = (
    "BOE-443_Normativa_para_ingreso_en_el_Cuerpo_de_Gestion_de_la_Administracion_"
    "Civil_del_Estado (1).pdf"
)

BLOQUE_ID = "bloque_01"
TEMA_ID = "tema_09"
COLECCION = "Temario GACE"

TITULO_NORMA = (
    "Ley 40/2015, de 1 de octubre, de Régimen Jurídico del Sector Público "
    "(Título II. Organización y funcionamiento del sector público institucional)"
)[:120]

# Encabezados literales del propio documento que delimitan el Título II -- se busca
# por contenido, no por número de página fijo, para que siga funcionando aunque
# pypdf extraiga el texto con un salto de línea ligeramente distinto a como se vio
# al investigar el documento con PyMuPDF. Ancla en el título exacto del Título II
# ("Organización y funcionamiento del sector público institucional") para no
# confundirlo con un "TÍTULO II" de cualquier otra norma del documento (3792
# páginas, con muchas leyes que también tienen su propio Título II).
PATRON_INICIO = re.compile(
    r"TÍTULO\s+II\s*\n\s*Organización\s+y\s+funcionamiento\s+del\s+sector\s+público\s+institucional",
    re.IGNORECASE,
)
PATRON_FIN = re.compile(r"TÍTULO\s+III\b")


def extraer_texto_titulo_ii(pdf_path):
    paginas = extraer_paginas(pdf_path)
    texto_completo = "\n".join(paginas)

    inicio = PATRON_INICIO.search(texto_completo)
    if not inicio:
        print("❌ No se encontró el encabezado del Título II en el documento.")
        sys.exit(1)

    fin = PATRON_FIN.search(texto_completo, pos=inicio.end())
    if not fin:
        print("❌ Se encontró el inicio del Título II pero no el Título III que lo cierra.")
        sys.exit(1)

    texto_titulo_ii = texto_completo[inicio.start():fin.start()].strip()
    print(f"✅ Título II localizado: {len(texto_titulo_ii)} caracteres "
          f"(de la posición {inicio.start()} a {fin.start()} del texto completo).")
    return texto_titulo_ii


def guardar_preview(subbloques, ruta="preview_tema_gace_09.json"):
    resumen = [
        {
            "indice": i + 1,
            "rango_articulos": sb["rango_articulos"],
            "primeras_palabras": " ".join(sb["texto"].split()[:25]) + "…",
        }
        for i, sb in enumerate(subbloques)
    ]
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    print(f"📋 Vista previa guardada en {ruta} — revisa que el primer subbloque "
          f"empiece en el art. 81 y el último termine antes del art. 140.")


def subir_a_firestore(subbloques):
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

    ref_subbloques = (
        db.collection(COLECCION).document(BLOQUE_ID).collection("temas")
          .document(TEMA_ID).collection("subbloques")
    )
    existentes = list(ref_subbloques.stream())
    contador = len(existentes)
    if existentes:
        print(f"⚠️  {COLECCION}/{BLOQUE_ID}/{TEMA_ID} ya tenía {contador} subbloques "
              f"-- se numera a continuación, no se borra nada.")

    subidos = 0
    for sb in subbloques:
        contador += 1
        sub_id = f"sub_div_{contador:03d}"
        ref_subbloques.document(sub_id).set({
            "titulo": TITULO_NORMA,
            "texto": sb["texto"],
        })
        subidos += 1
    print(f"✅ Subidos {subidos} subbloques nuevos a '{COLECCION}/{BLOQUE_ID}/{TEMA_ID}' "
          f"(ningún subbloque existente fue tocado ni borrado).")


def main():
    parser = argparse.ArgumentParser(
        description="Rellena bloque_01/tema_09 de Temario GACE con el Título II de la Ley 40/2015."
    )
    parser.add_argument("--pdf", default=PDF_FUENTE, help="Ruta al PDF BOE-443 (por defecto, el del repo)")
    parser.add_argument("--preview", action="store_true", help="Solo extraer y guardar un informe, sin subir nada")
    parser.add_argument("--subir", action="store_true", help="Extraer y subir de verdad a Firestore")
    args = parser.parse_args()

    if not args.preview and not args.subir:
        print("Indica --preview (para ver una vista previa) o --subir (para subir de verdad).")
        sys.exit(1)

    texto_titulo_ii = extraer_texto_titulo_ii(args.pdf)
    subbloques = dividir_en_subbloques(texto_titulo_ii)
    print(f"🧩 {len(subbloques)} subbloques generados.")

    guardar_preview(subbloques)

    if args.subir:
        subir_a_firestore(subbloques)


if __name__ == "__main__":
    main()
