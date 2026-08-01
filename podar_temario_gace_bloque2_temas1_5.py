"""
Poda el TUE y el TFUE ya cargados en Temario GACE/bloque_02 (temas 1-5) a
solo los artículos realmente relevantes para cada uno de esos temas.

cargar_temario_gace_bloque2_ue.py subió el articulado COMPLETO de ambos
Tratados (11 + 46 = 57 subbloques, arts. 1-55 TUE y 1-358 TFUE) clasificado
por IA entre los 6 temas del bloque. Eso metió en los temas 1-5 mucho
contenido que en realidad pertenece a "políticas" (mercado interior, PAC,
pesca, acción exterior detallada, etc. -- ya cubierto aparte por las fichas
FTU del tema 6) y a materias que ni siquiera están en el temario (cooperación
reforzada, disposiciones finales...). Cada tema del temario AGE/GACE se lee
en Firestore sin más filtro que su propio path
("Temario GACE/bloque_02/temas/tema_0N/subbloques"), así que todo ese exceso
se usaba igual que el contenido relevante al generar tests/resúmenes.

Este script relee los PDF originales, localiza los artículos concretos que
sí corresponden a cada tema (verificado contra el propio texto e índice de
los Tratados, no de memoria) y sustituye los subbloques de los temas 1-5 por
solo esos. NO clasifica nada por IA: el mapeo artículo -> tema es
determinista, verificado a mano contra la estructura real de TUE/TFUE.
El tema 6 (fichas FTU) no se toca.

Artículos incluidos por tema (verificados contra el índice/texto real):
  tema_01 (antecedentes, objetivos y naturaleza jurídica):
    - TUE arts. 1-8 (Título I "Disposiciones comunes", incluye el art. 5
      donde se enuncia el principio de subsidiariedad/proporcionalidad).
  tema_02 (organización I: Consejo Europeo, Consejo, Comisión):
    - TUE art. 13 (marco institucional general), 15 (Consejo Europeo),
      16 (Consejo), 17 (Comisión), 18 (Alto Representante -- añadido por ir
      ligado al nombramiento por el Consejo Europeo/Comisión en el propio
      art. 17-18, aunque no es una "institución" de las 7 del art. 13).
    - TFUE arts. 235-236 (Consejo Europeo), 237-243 (Consejo),
      244-250 (Comisión) -- Sexta Parte, Tít. I, Cap. 1, secciones 2.ª-4.ª.
  tema_03 (organización II: Parlamento, TJUE, Tribunal de Cuentas, BCE):
    - TUE art. 14 (Parlamento Europeo), 19 (TJUE).
    - TFUE arts. 223-234 (Parlamento, sección 1.ª), 251-281 (TJUE,
      sección 5.ª), 282-284 (BCE, sección 6.ª), 285-287 (Tribunal de
      Cuentas, sección 7.ª).
  tema_04 (fuentes del Derecho de la UE + relación con el derecho nacional):
    - TFUE arts. 288-299 (Cap. 2 "Actos jurídicos de la Unión": reglamentos,
      directivas, decisiones, procedimientos de adopción).
    - Protocolo (n.º 2) del TUE "sobre la aplicación de los principios de
      subsidiariedad y proporcionalidad", arts. 1-9 (numeración propia del
      protocolo, reinicia en 1) -- el mecanismo de control por los
      Parlamentos nacionales es justo la "relación Derecho UE/nacional" de
      este tema. No estaba subido antes (el primer script solo llegaba
      hasta el primer protocolo y los dejaba todos fuera a propósito).
  tema_05 (presupuesto comunitario, fondos europeos, cohesión):
    - Ningún artículo de TUE/TFUE pedido para este tema: queda SIN
      contenido tras la poda (el presupuesto se regula en la Sexta Parte,
      Tít. II TFUE, arts. 310-325 aprox., fuera del alcance pedido aquí).
      Revisar aparte si se quiere cargar ese tema.

Aditivo: solo borra y recrea los subbloques de bloque_02/temas 1-5. No toca
tema_06 (fichas FTU, ya bien acotado) ni ningún otro bloque.

USO:
  python podar_temario_gace_bloque2_temas1_5.py --preview
  python podar_temario_gace_bloque2_temas1_5.py --subir

Variables de entorno necesarias (solo para --subir):
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)
"""
import argparse
import json
import os
import re
import sys

from cargar_temario_boe import extraer_paginas, TEMARIO
from cargar_temario_gace_bloque2_ue import (
    PATRON_ARTICULO_TRATADO, PATRON_PROTOCOLO, _estimar_tokens, dividir_tratado_en_subbloques,
)

COLECCION = "Temario GACE"
BLOQUE_ID = "bloque_02"
BLOQUE_NUM = 2
TEMAS = TEMARIO[BLOQUE_NUM - 1]["temas"]
CARPETA_FUENTES = "temario-examenes/GACE/union-europea"

TUE_PDF = os.path.join(CARPETA_FUENTES, "document.pdf")
TFUE_PDF = os.path.join(CARPETA_FUENTES, "CELEX_12016E_TXT_ES_TXT.pdf")
TUE_TITULO = "Tratado de la Unión Europea (TUE)"
TFUE_TITULO = "Tratado de Funcionamiento de la Unión Europea (TFUE)"
PROTOCOLO2_TITULO = "Protocolo (n.º 2) sobre la aplicación de los principios de subsidiariedad y proporcionalidad (TUE)"

# (documento, art_inicio, art_fin, tema_num, descripción) -- ambos límites
# de artículo inclusive. "documento" es una clave de RANGOS_DOCUMENTO.
RANGOS_INCLUIR = [
    ("TUE", 1, 8, 1, "Arts. 1-8 TUE (Tít. I) - Objetivos y naturaleza jurídica de la Unión"),
    ("TUE", 13, 13, 2, "Art. 13 TUE - Marco institucional general"),
    ("TUE", 15, 15, 2, "Art. 15 TUE - El Consejo Europeo"),
    ("TUE", 16, 16, 2, "Art. 16 TUE - El Consejo"),
    ("TUE", 17, 17, 2, "Art. 17 TUE - La Comisión"),
    ("TUE", 18, 18, 2, "Art. 18 TUE - El Alto Representante"),
    ("TFUE", 235, 236, 2, "Arts. 235-236 TFUE - El Consejo Europeo"),
    ("TFUE", 237, 243, 2, "Arts. 237-243 TFUE - El Consejo"),
    ("TFUE", 244, 250, 2, "Arts. 244-250 TFUE - La Comisión"),
    ("TUE", 14, 14, 3, "Art. 14 TUE - El Parlamento Europeo"),
    ("TUE", 19, 19, 3, "Art. 19 TUE - El Tribunal de Justicia de la Unión Europea"),
    ("TFUE", 223, 234, 3, "Arts. 223-234 TFUE - El Parlamento Europeo"),
    ("TFUE", 251, 281, 3, "Arts. 251-281 TFUE - El Tribunal de Justicia de la Unión Europea"),
    ("TFUE", 282, 284, 3, "Arts. 282-284 TFUE - El Banco Central Europeo"),
    ("TFUE", 285, 287, 3, "Arts. 285-287 TFUE - El Tribunal de Cuentas"),
    ("TFUE", 288, 299, 4, "Arts. 288-299 TFUE - Actos jurídicos de la Unión (fuentes del Derecho)"),
    ("PROTOCOLO2", 1, 9, 4, "Protocolo n.º 2 TUE, arts. 1-9 - Subsidiariedad y proporcionalidad"),
]

PATRON_PROTOCOLO_NUM = re.compile(r"PROTOCOLO\s*\(\s*N\s*[ºo°]?\s*(\d+)\s*\)", re.IGNORECASE)


def _localizar_articulado_principal(texto):
    """(offsets, fin) del articulado real del Tratado -- ver
    cargar_temario_gace_bloque2_ue._localizar_articulado."""
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
    return offsets, fin


def _localizar_protocolo(texto, numero, fin_articulado_principal):
    """(offsets, fin) del articulado propio (numeración reiniciada en 1) del
    protocolo numerado indicado, buscando su cabecera real después del
    articulado principal del Tratado (para no confundirla con la entrada
    del índice, que enumera todos los protocolos al principio del PDF)."""
    cabeceras = [
        (int(m.group(1)), m.start())
        for m in PATRON_PROTOCOLO_NUM.finditer(texto)
        if m.start() > fin_articulado_principal
    ]
    cabeceras.sort(key=lambda t: t[1])
    inicio = next((off for num, off in cabeceras if num == numero), None)
    if inicio is None:
        raise RuntimeError(f"No se encontró el Protocolo n.º {numero}.")
    posteriores = [off for num, off in cabeceras if off > inicio]
    fin = min(posteriores) if posteriores else len(texto)
    fragmento = texto[inicio:fin]
    offsets = {int(m.group(1)): m.start() for m in PATRON_ARTICULO_TRATADO.finditer(fragmento)}
    return offsets, fragmento


def _extraer_rango(texto, offsets, ini, fin):
    if ini not in offsets:
        raise RuntimeError(f"No se encontró el Artículo {ini} en el rango esperado.")
    posteriores = sorted(n for n in offsets if n > fin)
    off_fin = offsets[posteriores[0]] if posteriores else len(texto)
    return texto[offsets[ini]:off_fin].strip()


def procesar():
    textos = {}
    for pdf_path in (TUE_PDF, TFUE_PDF):
        paginas = extraer_paginas(pdf_path)
        textos[pdf_path] = "\n".join(paginas)

    texto_tue = textos[TUE_PDF]
    texto_tfue = textos[TFUE_PDF]
    offsets_tue, fin_tue = _localizar_articulado_principal(texto_tue)
    offsets_tfue, fin_tfue = _localizar_articulado_principal(texto_tfue)
    offsets_prot2, fragmento_prot2 = _localizar_protocolo(texto_tue, 2, fin_tue)

    documentos = {
        "TUE": (texto_tue, offsets_tue, TUE_TITULO),
        "TFUE": (texto_tfue, offsets_tfue, TFUE_TITULO),
        "PROTOCOLO2": (fragmento_prot2, offsets_prot2, PROTOCOLO2_TITULO),
    }

    resultados_por_tema = {i: [] for i in range(1, len(TEMAS) + 1)}
    articulos_incluidos = {"TUE": set(), "TFUE": set(), "PROTOCOLO2": set()}

    for doc_clave, ini, fin, tema_num, descripcion in RANGOS_INCLUIR:
        texto, offsets, titulo_norma = documentos[doc_clave]
        fragmento = _extraer_rango(texto, offsets, ini, fin)
        for sb in dividir_tratado_en_subbloques(fragmento):
            resultados_por_tema[tema_num].append({
                "titulo": titulo_norma,
                "texto": sb["texto"],
                "descripcion": descripcion,
            })
        articulos_incluidos[doc_clave].update(range(ini, fin + 1))

    excluidos = {
        "TUE": sorted(n for n in offsets_tue if n not in articulos_incluidos["TUE"]),
        "TFUE": sorted(n for n in offsets_tfue if n not in articulos_incluidos["TFUE"]),
        "PROTOCOLO2": sorted(n for n in offsets_prot2 if n not in articulos_incluidos["PROTOCOLO2"]),
    }
    totales = {"TUE": sorted(offsets_tue), "TFUE": sorted(offsets_tfue), "PROTOCOLO2": sorted(offsets_prot2)}
    return resultados_por_tema, totales, excluidos


def _resumen_rangos(numeros):
    if not numeros:
        return "(ninguno)"
    numeros = sorted(numeros)
    rangos = []
    ini = fin = numeros[0]
    for n in numeros[1:]:
        if n == fin + 1:
            fin = n
        else:
            rangos.append(f"{ini}" if ini == fin else f"{ini}-{fin}")
            ini = fin = n
    rangos.append(f"{ini}" if ini == fin else f"{ini}-{fin}")
    return ", ".join(rangos)


def guardar_preview(resultados_por_tema, totales, excluidos, ruta="preview_podar_gace_bloque2_temas1_5.json"):
    resumen = {}
    for tema_num, items in resultados_por_tema.items():
        tema_id = f"tema_{tema_num:02d}"
        resumen[tema_id] = [
            {"descripcion": it["descripcion"], "titulo": it["titulo"], "primeras_palabras": " ".join(it["texto"].split()[:20]) + "…"}
            for it in items
        ]
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    print(f"📋 Vista previa guardada en {ruta}")
    print(f"\n📊 Resumen -- {COLECCION}/{BLOQUE_ID} (temas 1-5, tema_06 no se toca)")
    for i, tema_titulo in enumerate(TEMAS, 1):
        if i == 6:
            continue
        tema_id = f"tema_{i:02d}"
        n = len(resumen.get(tema_id, []))
        marca = "  ⚠️  SIN artículos (queda vacío tras la poda)" if n == 0 else ""
        print(f"   {tema_id} ({tema_titulo[:65]}): {n} subbloques{marca}")

    for doc_clave in ("TUE", "TFUE", "PROTOCOLO2"):
        print(f"\n   {doc_clave}: {len(totales[doc_clave])} artículos en el articulado.")
        print(f"      ✅ Incluidos: {_resumen_rangos(sorted(set(totales[doc_clave]) - set(excluidos[doc_clave])))}")
        print(f"      ❌ Excluidos ({len(excluidos[doc_clave])}): {_resumen_rangos(excluidos[doc_clave])}")


def subir_a_firestore(resultados_por_tema):
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

    for tema_num in range(1, 6):  # 1-5, nunca tema_06
        tema_id = f"tema_{tema_num:02d}"
        subbloques_ref = (
            db.collection(COLECCION).document(BLOQUE_ID).collection("temas")
              .document(tema_id).collection("subbloques")
        )
        existentes = list(subbloques_ref.stream())
        if existentes:
            print(f"🗑️  {COLECCION}/{BLOQUE_ID}/{tema_id} tenía {len(existentes)} subbloques -- se borran antes de subir los podados.")
            for doc in existentes:
                doc.reference.delete()

        items = resultados_por_tema.get(tema_num, [])
        for i, it in enumerate(items, 1):
            subbloques_ref.document(f"sub_div_{i:03d}").set({
                "titulo": it["titulo"][:120],
                "texto": it["texto"],
            })
        print(f"✅ Subidos {len(items)} subbloques podados a '{COLECCION}/{BLOQUE_ID}/{tema_id}'.")


def main():
    parser = argparse.ArgumentParser(description="Podar TUE/TFUE en Temario GACE/bloque_02 (temas 1-5) a solo los artículos relevantes.")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--subir", action="store_true")
    args = parser.parse_args()

    if not args.preview and not args.subir:
        print("Indica --preview (para ver una vista previa) o --subir (para subir de verdad).")
        sys.exit(1)

    for pdf_path in (TUE_PDF, TFUE_PDF):
        if not os.path.exists(pdf_path):
            print(f"⚠️  No se encontró {pdf_path}.")
            sys.exit(1)

    resultados_por_tema, totales, excluidos = procesar()
    guardar_preview(resultados_por_tema, totales, excluidos)

    if args.subir:
        subir_a_firestore(resultados_por_tema)


if __name__ == "__main__":
    main()
