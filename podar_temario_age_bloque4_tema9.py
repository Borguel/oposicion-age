"""
Poda el TRLGSS (RDL 8/2015) ya cargado en Temario AGE/bloque_04/tema_09
("El régimen de la Seguridad Social del personal laboral") a solo los
artículos realmente relevantes para ese tema concreto.

completar_temario_age_bloques_4_5.py subió la norma COMPLETA (202 subbloques,
más de 370 artículos) porque, al ser un único PDF = un único tema, no
clasificaba nada por IA. Pero ese tema en realidad solo trata dos puntos:
campo de aplicación del sistema y encuadramiento del personal laboral en el
Régimen General -- el resto de la LGSS (cotización, prestaciones,
incapacidad, jubilación, muerte y supervivencia, desempleo, etc.) no
corresponde a este tema y solo añade ruido al generador de tests/resúmenes,
que lee todo el contenido de "Temario AGE/bloque_04/tema_09/subbloques" sin
más filtro que ese path.

Artículos verificados contra el propio texto del PDF (no de memoria):
  - Artículo 7. Extensión del campo de aplicación (Título I, Capítulo II).
  - Artículos 136-140: Título II "Régimen General de la Seguridad Social",
    Capítulo I "Campo de aplicación" (136 Extensión, 137 Exclusiones) +
    Sección 1.ª del Capítulo II "Inscripción de empresas y afiliación de
    trabajadores" (138 Inscripción de empresas, 139 Afiliación/altas/bajas,
    140 Procedimiento y plazos) -- el bloque de encuadramiento propiamente
    dicho. El artículo 141 ya abre la Sección 2.ª "Cotización" (materia
    distinta, no es encuadramiento) y por eso queda fuera.

Aditivo: solo toca bloque_04/tema_09, nunca ningún otro bloque/tema.

USO:
  python podar_temario_age_bloque4_tema9.py --preview
  python podar_temario_age_bloque4_tema9.py --subir

Variables de entorno necesarias (solo para --subir):
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)
"""
import argparse
import json
import os
import re
import sys

from cargar_temario_boe import extraer_paginas, PATRON_ARTICULO

COLECCION = "Temario AGE"
BLOQUE_ID = "bloque_04"
TEMA_ID = "tema_09"
PDF = "temario-examenes/AGE/BOE-A-2015-11724-consolidado.pdf"
TITULO_NORMA = (
    "Real Decreto Legislativo 8/2015, de 30 de octubre, por el que se "
    "aprueba el texto refundido de la Ley General de la Seguridad Social"
)

# (artículo_inicio, artículo_fin, descripción) -- ambos límites inclusive.
RANGOS_INCLUIR = [
    (7, 7, "Art. 7 - Extensión del campo de aplicación del sistema de la Seguridad Social"),
    (136, 140, "Arts. 136-140 - Tít. II Cap. I Campo de aplicación + Secc. 1.ª Afiliación/altas-bajas del Régimen General"),
]

MAX_TOKENS_SUBBLOQUE = 1800


# Estimación de tokens sin tiktoken (bloqueado por red en el sandbox de
# desarrollo): no necesita ser exacta, solo consistente para decidir el
# corte -- mismo enfoque que cargar_temario_gace_bloque2_ue.py.
def _estimar_tokens(texto):
    return int(len(texto.split()) * 1.3)


def _localizar_articulos(texto):
    """num_articulo -> offset de inicio de su cabecera "Artículo N." real
    (mayúscula + punto, así que no confunde con referencias cruzadas en
    minúscula tipo "conforme al artículo 5.")."""
    offsets = {}
    for m in PATRON_ARTICULO.finditer(texto):
        num = int(m.group(1))
        if num not in offsets:  # primera aparición = la cabecera real
            offsets[num] = m.start()
    return offsets


def _extraer_rango(texto, offsets, ini, fin):
    if ini not in offsets:
        raise RuntimeError(f"No se encontró el Artículo {ini} en el texto del PDF.")
    posteriores = sorted(n for n in offsets if n > fin)
    off_fin = offsets[posteriores[0]] if posteriores else len(texto)
    return texto[offsets[ini]:off_fin].strip()


def _trocear(texto, max_tokens=MAX_TOKENS_SUBBLOQUE):
    coincidencias = list(PATRON_ARTICULO.finditer(texto))
    unidades = []
    if coincidencias:
        for idx, m in enumerate(coincidencias):
            fin = coincidencias[idx + 1].start() if idx + 1 < len(coincidencias) else len(texto)
            unidades.append(texto[m.start():fin].strip())
    else:
        unidades = [texto]

    subbloques = []
    actual = []
    tokens_actual = 0
    for unidad in unidades:
        tokens_unidad = _estimar_tokens(unidad)
        if tokens_actual + tokens_unidad > max_tokens and actual:
            subbloques.append("\n\n".join(actual))
            actual, tokens_actual = [], 0
        actual.append(unidad)
        tokens_actual += tokens_unidad
    if actual:
        subbloques.append("\n\n".join(actual))
    return subbloques


def procesar(pdf_path):
    paginas = extraer_paginas(pdf_path)
    texto = "\n".join(paginas)
    offsets = _localizar_articulos(texto)

    incluidos = []
    for ini, fin, descripcion in RANGOS_INCLUIR:
        fragmento = _extraer_rango(texto, offsets, ini, fin)
        for sb in _trocear(fragmento):
            incluidos.append({"texto": sb, "rango": descripcion})

    todos_los_articulos = sorted(offsets.keys())
    incluidos_nums = set()
    for ini, fin, _ in RANGOS_INCLUIR:
        incluidos_nums.update(range(ini, fin + 1))
    excluidos_nums = [n for n in todos_los_articulos if n not in incluidos_nums]

    return incluidos, todos_los_articulos, excluidos_nums


def _resumen_rangos(numeros):
    """Comprime una lista de números de artículo en rangos legibles, p.ej.
    [1,2,3,5,6] -> '1-3, 5-6', para no imprimir 370 números sueltos."""
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


def guardar_preview(incluidos, todos_los_articulos, excluidos_nums, ruta="preview_podar_age_bloque4_tema9.json"):
    resumen = {
        "coleccion": COLECCION,
        "bloque_id": BLOQUE_ID,
        "tema_id": TEMA_ID,
        "pdf": PDF,
        "subbloques_incluidos": [
            {"rango": sb["rango"], "primeras_palabras": " ".join(sb["texto"].split()[:25]) + "…"}
            for sb in incluidos
        ],
        "total_articulos_en_pdf": len(todos_los_articulos),
        "articulos_incluidos": _resumen_rangos([n for ini, fin, _ in RANGOS_INCLUIR for n in range(ini, fin + 1)]),
        "articulos_excluidos": _resumen_rangos(excluidos_nums),
    }
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    print(f"📋 Vista previa guardada en {ruta}")
    print(f"\n📊 Resumen -- {COLECCION}/{BLOQUE_ID}/{TEMA_ID}")
    print(f"   PDF completo: {len(todos_los_articulos)} artículos.")
    print(f"   ✅ Incluidos ({len(incluidos)} subbloques): {resumen['articulos_incluidos']}")
    print(f"   ❌ Excluidos ({len(excluidos_nums)} artículos): {resumen['articulos_excluidos']}")


def subir_a_firestore(incluidos):
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
    print(f"🗑️  {COLECCION}/{BLOQUE_ID}/{TEMA_ID} tenía {len(existentes)} subbloques -- se borran antes de subir los podados.")
    for doc in existentes:
        doc.reference.delete()

    for i, sb in enumerate(incluidos, 1):
        subbloques_ref.document(f"sub_div_{i:03d}").set({
            "titulo": TITULO_NORMA[:120],
            "texto": sb["texto"],
        })
    print(f"✅ Subidos {len(incluidos)} subbloques podados a '{COLECCION}/{BLOQUE_ID}/{TEMA_ID}'.")


def main():
    parser = argparse.ArgumentParser(description="Podar TRLGSS en Temario AGE/bloque_04/tema_09 a solo los artículos relevantes.")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--subir", action="store_true")
    args = parser.parse_args()

    if not args.preview and not args.subir:
        print("Indica --preview (para ver una vista previa) o --subir (para subir de verdad).")
        sys.exit(1)

    if not os.path.exists(PDF):
        print(f"⚠️  No se encontró {PDF}.")
        sys.exit(1)

    incluidos, todos_los_articulos, excluidos_nums = procesar(PDF)
    guardar_preview(incluidos, todos_los_articulos, excluidos_nums)

    if args.subir:
        subir_a_firestore(incluidos)


if __name__ == "__main__":
    main()
