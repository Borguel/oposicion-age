"""
Completa Temario GACE/bloque_02/tema_05 ("El presupuesto comunitario. Los
fondos europeos. La cohesión económica y social."), que quedó sin contenido
tras la poda de podar_temario_gace_bloque2_temas1_5.py (no se pidieron
artículos de TUE/TFUE para él en esa tanda).

Dos fuentes, igual que en cargar_temario_gace_bloque2_ue.py:

1) TFUE, Sexta Parte, Título II "Disposiciones financieras" (verificado
   contra el propio texto: comienza en el Art. 310, justo tras el Título I
   de instituciones, y termina en el Art. 325, justo antes del Título VI
   "Cooperaciones reforzadas" que arranca en el Art. 326) -- recursos
   propios de la Unión (Cap. 1), marco financiero plurianual (Cap. 2),
   presupuesto anual (Cap. 3), ejecución del presupuesto y descarga
   (Cap. 4), disposiciones comunes (Cap. 5) y lucha contra el fraude
   (Cap. 6): exactamente recursos propios + procedimiento presupuestario
   anual + marco financiero plurianual + control presupuestario.

2) 4 fichas temáticas del Parlamento Europeo, directas a tema_05 (todas
   encajan, ninguna se descarta): FTU_3.1.1 (cohesión económica, social y
   territorial), FTU_3.1.2 (FEDER), FTU_3.1.3 (Fondo de Cohesión) y
   FTU_3.1.4 (Fondo de Solidaridad).

Aditivo: solo toca bloque_02/tema_05 (que estaba vacío), nunca ningún otro
bloque/tema ya cargado.

USO:
  python completar_temario_gace_bloque2_tema5.py --preview
  python completar_temario_gace_bloque2_tema5.py --subir

Variables de entorno necesarias (solo para --subir):
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)
"""
import argparse
import json
import os
import sys

from cargar_temario_boe import extraer_paginas, TEMARIO
from cargar_temario_gace_bloque2_ue import (
    PATRON_ARTICULO_TRATADO, PATRON_PROTOCOLO, dividir_tratado_en_subbloques, extraer_texto_ftu,
    _trocear_por_parrafos_o_lineas,
)

COLECCION = "Temario GACE"
BLOQUE_ID = "bloque_02"
BLOQUE_NUM = 2
TEMA_ID = "tema_05"
TEMA_TITULO = TEMARIO[BLOQUE_NUM - 1]["temas"][4]
CARPETA_FUENTES = "temario-fuentes"

TFUE_PDF = os.path.join(CARPETA_FUENTES, "CELEX_12016E_TXT_ES_TXT.pdf")
TFUE_TITULO = "Tratado de Funcionamiento de la Unión Europea (TFUE)"
TFUE_RANGO = (310, 325, "Arts. 310-325 TFUE (Sexta Parte, Tít. II) - Disposiciones financieras: recursos propios, marco financiero plurianual, presupuesto anual, control presupuestario")

FTU_TEMA_05 = {
    "FTU_3.1.1": "La cohesión económica, social y territorial",
    "FTU_3.1.2": "El Fondo Europeo de Desarrollo Regional (FEDER)",
    "FTU_3.1.3": "Fondo de Cohesión",
    "FTU_3.1.4": "Fondo de Solidaridad",
}

MAX_TOKENS_SUBBLOQUE = 1800


def _localizar_articulado_principal(texto):
    primero = PATRON_ARTICULO_TRATADO.search(texto)
    if not primero:
        raise RuntimeError("No se encontró ningún 'Artículo 1' en el documento.")
    fin_match = PATRON_PROTOCOLO.search(texto, pos=primero.start())
    fin = fin_match.start() if fin_match else len(texto)
    offsets = {}
    for m in PATRON_ARTICULO_TRATADO.finditer(texto):
        if m.start() >= fin:
            break
        num = int(m.group(1))
        if num not in offsets:
            offsets[num] = m.start()
    return offsets


def _extraer_rango(texto, offsets, ini, fin):
    if ini not in offsets:
        raise RuntimeError(f"No se encontró el Artículo {ini} en el rango esperado.")
    posteriores = sorted(n for n in offsets if n > fin)
    off_fin = offsets[posteriores[0]] if posteriores else len(texto)
    return texto[offsets[ini]:off_fin].strip()


def procesar_tfue():
    paginas = extraer_paginas(TFUE_PDF)
    texto = "\n".join(paginas)
    offsets = _localizar_articulado_principal(texto)
    ini, fin, descripcion = TFUE_RANGO
    fragmento = _extraer_rango(texto, offsets, ini, fin)
    resultados = []
    for sb in dividir_tratado_en_subbloques(fragmento, MAX_TOKENS_SUBBLOQUE):
        resultados.append({"titulo": TFUE_TITULO, "texto": sb["texto"], "origen": descripcion})
    return resultados


def procesar_fichas_ftu(carpeta):
    resultados = []
    for codigo, titulo in FTU_TEMA_05.items():
        ruta = os.path.join(carpeta, f"{codigo}.pdf")
        if not os.path.exists(ruta):
            print(f"⚠️  Falta el PDF de la ficha {codigo}, se omite.")
            continue
        texto = extraer_texto_ftu(ruta)
        subbloques = _trocear_por_parrafos_o_lineas(texto, MAX_TOKENS_SUBBLOQUE)
        for sb in subbloques:
            resultados.append({"titulo": titulo, "texto": sb, "origen": f"Ficha {codigo}"})
        print(f"📄 tema_05 ← {codigo} ({titulo}): {len(subbloques)} subbloque(s)")
    return resultados


def guardar_preview(resultados, ruta="preview_completar_gace_bloque2_tema5.json"):
    resumen = [
        {"origen": r["origen"], "titulo": r["titulo"], "primeras_palabras": " ".join(r["texto"].split()[:20]) + "…"}
        for r in resultados
    ]
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    print(f"📋 Vista previa guardada en {ruta}")
    print(f"\n📊 Resumen -- {COLECCION}/{BLOQUE_ID}/{TEMA_ID} ({TEMA_TITULO[:70]})")
    por_origen = {}
    for r in resultados:
        por_origen.setdefault(r["origen"], 0)
        por_origen[r["origen"]] += 1
    for origen, n in por_origen.items():
        print(f"   + {origen}: {n} subbloques")
    print(f"   Total: {len(resultados)} subbloques nuevos.")


def subir_a_firestore(resultados):
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

    subbloques_ref = (
        db.collection(COLECCION).document(BLOQUE_ID).collection("temas")
          .document(TEMA_ID).collection("subbloques")
    )
    existentes = list(subbloques_ref.stream())
    if existentes:
        print(f"🗑️  {COLECCION}/{BLOQUE_ID}/{TEMA_ID} tenía {len(existentes)} subbloques -- se borran antes de subir los nuevos.")
        for doc in existentes:
            doc.reference.delete()

    for i, r in enumerate(resultados, 1):
        subbloques_ref.document(f"sub_div_{i:03d}").set({
            "titulo": r["titulo"][:120],
            "texto": r["texto"],
        })
    print(f"✅ Subidos {len(resultados)} subbloques a '{COLECCION}/{BLOQUE_ID}/{TEMA_ID}'.")


def main():
    parser = argparse.ArgumentParser(description="Completar Temario GACE/bloque_02/tema_05 (presupuesto, fondos, cohesión).")
    parser.add_argument("--carpeta", default=CARPETA_FUENTES, help="Carpeta con los PDF fuente")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--subir", action="store_true")
    args = parser.parse_args()

    if not args.preview and not args.subir:
        print("Indica --preview (para ver una vista previa) o --subir (para subir de verdad).")
        sys.exit(1)

    if not os.path.exists(TFUE_PDF):
        print(f"⚠️  No se encontró {TFUE_PDF}.")
        sys.exit(1)

    resultados = procesar_tfue()
    resultados += procesar_fichas_ftu(args.carpeta)

    guardar_preview(resultados)

    if args.subir:
        subir_a_firestore(resultados)


if __name__ == "__main__":
    main()
