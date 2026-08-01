"""
Carga el Bloque II ("Unión Europea", 6 temas) de "Temario GACE" a partir de
los documentos aportados por el usuario en temario-examenes/GACE/union-europea/ -- hasta ahora
este bloque no tenía contenido real: los "Códigos electrónicos" del BOE
usados para el resto del temario (cargar_temario_boe.py) no incluyen los
Tratados de la UE, que no son normativa española.

Dos tipos de fuente, tratadas de forma distinta:

1) Los Tratados (TUE y TFUE), para los temas 1-5 (naturaleza jurídica,
   organización institucional (I) y (II), fuentes del derecho, presupuesto)
   Y también tema 6 en la parte de "Políticas y acciones internas" del TFUE:
     - document.pdf         = Tratado de la Unión Europea (TUE), DOUE C 202/1
     - CELEX_12016E_TXT_ES_TXT.pdf = Tratado de Funcionamiento de la UE (TFUE), DOUE C 202/47
   Cada Tratado se trocea por "Artículo N" (igual que dividir_en_subbloques
   de cargar_temario_boe.py, pero sin punto tras el número: en el texto de
   los Tratados el encabezado es "Artículo 1" en su propia línea, no
   "Artículo 1." como en las leyes del BOE) y cada subbloque se clasifica
   por IA entre los 6 temas del bloque (reutilizando
   cargar_temario_boe.clasificar_subbloque tal cual, con bloque_num=2).
   Solo se sube el articulado real: desde el primer "Artículo 1" hasta el
   primer protocolo ("PROTOCOLO (n. o 1)..."), dejando fuera protocolos,
   anexos y declaraciones (mucho volumen y poca relevancia para el
   temario, y además reintroducen su propia numeración "Artículo 1..."
   que ensuciaría el troceado por artículo).

2) Las 23 fichas temáticas oficiales del Parlamento Europeo (FTU_x.y.z.pdf,
   "Fichas temáticas sobre la Unión Europea", europarl.europa.eu/factsheets)
   van DIRECTAS al tema 6 ("Políticas de la Unión Europea"), sin
   clasificación por IA: cada una ya trata monográficamente una de las
   políticas que ese tema enumera explícitamente (mercado interior, UEM,
   PAC, pesca, espacio de libertad/seguridad/justicia, PESC), así que el
   mapeo fichero->tema ya se conoce de antemano (ver FTU_TEMA_06 más abajo).

USO:
  # 1) Vista previa (no escribe nada en Firestore, guarda un informe en JSON):
  python cargar_temario_gace_bloque2_ue.py --preview

  # 2) Revisa preview_temario_gace_bloque2_ue.json, y si está bien, sube:
  python cargar_temario_gace_bloque2_ue.py --subir

Variables de entorno necesarias:
  DEEPSEEK_API_KEY (para clasificar el articulado de los Tratados)
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)

Requiere: pypdf, firebase-admin (ya están en requirements.txt)
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from pypdf import PdfReader

from cargar_temario_boe import TEMARIO, extraer_paginas, clasificar_subbloque

COLECCION = "Temario GACE"
BLOQUE_ID = "bloque_02"
BLOQUE_NUM = 2  # índice (1-based) dentro de TEMARIO -- TEMARIO[BLOQUE_NUM - 1] == este bloque
BLOQUE_TITULO = TEMARIO[BLOQUE_NUM - 1]["bloque"]
TEMAS = TEMARIO[BLOQUE_NUM - 1]["temas"]
MAX_TOKENS_SUBBLOQUE = 1800

CARPETA_FUENTES = "temario-examenes/GACE/union-europea"

TRATADOS = [
    {"pdf": "document.pdf", "titulo": "Tratado de la Unión Europea (TUE)"},
    {"pdf": "CELEX_12016E_TXT_ES_TXT.pdf", "titulo": "Tratado de Funcionamiento de la Unión Europea (TFUE)"},
]

# Las 23 fichas del Parlamento Europeo -> todas al tema 6 ("Políticas de la
# Unión Europea"), con su título real (primera línea de contenido de cada
# PDF) para mostrarlo como "titulo" del subbloque en vez del nombre de archivo.
FTU_TEMA_06 = {
    "FTU_2.1.1": "El mercado interior: principios generales",
    "FTU_2.1.2": "La libre circulación de mercancías",
    "FTU_2.1.3": "La libre circulación de capitales",
    "FTU_2.1.4": "La libertad de establecimiento y la libre prestación de servicios",
    "FTU_2.1.5": "La libre circulación de trabajadores",
    "FTU_2.5.1": "La historia de la Unión Económica y Monetaria",
    "FTU_2.5.2": "Las instituciones de la Unión Económica y Monetaria",
    "FTU_2.5.3": "La política monetaria europea",
    "FTU_2.5.4": "La gobernanza económica",
    "FTU_2.5.12": "La política de competencia",
    "FTU_3.2.1": "La política agrícola común (PAC) y el Tratado",
    "FTU_3.2.3": "Los instrumentos de la política agrícola común y sus reformas",
    "FTU_3.3.1": "La política pesquera común: orígenes y evolución",
    "FTU_3.3.2": "La gestión de la pesca en la Unión Europea",
    "FTU_4.2.1": "Un espacio de libertad, seguridad y justicia: aspectos generales",
    "FTU_4.2.2": "La política de asilo",
    "FTU_4.2.3": "La política de inmigración",
    "FTU_4.2.4": "Gestión de las fronteras exteriores",
    "FTU_4.2.5": "La cooperación judicial en materia civil",
    "FTU_4.2.6": "La cooperación judicial en materia penal",
    "FTU_4.2.7": "La cooperación policial",
    "FTU_4.2.8": "La protección de los datos personales",
    "FTU_5.1.1": "Política exterior y de seguridad común",
}
TEMA_ID_POLITICAS = "tema_06"


# Estimación de tokens sin tiktoken (su diccionario se descarga de
# openaipublic.blob.core.windows.net, bloqueado por política de red en el
# entorno de desarrollo -- mismo motivo y mismo enfoque que
# cargar_temario_auxiliar_bloque2.py). No necesita ser exacta, solo
# consistente, para decidir dónde cortar los subbloques.
def _estimar_tokens(texto):
    return int(len(texto.split()) * 1.3)


def _trocear_por_parrafos_o_lineas(texto, max_tokens):
    unidades = [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]
    if len(unidades) <= 1:
        unidades = [l.strip() for l in texto.split("\n") if l.strip()]

    subbloques = []
    actual = []
    tokens_actual = 0
    for unidad in unidades:
        tokens_unidad = _estimar_tokens(unidad)
        if tokens_unidad > max_tokens:
            if actual:
                subbloques.append("\n\n".join(actual))
                actual, tokens_actual = [], 0
            paso = max_tokens * 4
            for i in range(0, len(unidad), paso):
                subbloques.append(unidad[i:i + paso])
            continue
        if tokens_actual + tokens_unidad > max_tokens and actual:
            subbloques.append("\n\n".join(actual))
            actual = []
            tokens_actual = 0
        actual.append(unidad)
        tokens_actual += tokens_unidad
    if actual:
        subbloques.append("\n\n".join(actual))
    return subbloques


# ---------------------------------------------------------------------------
# 1) Tratados: localizar el articulado real y trocear por "Artículo N"
# ---------------------------------------------------------------------------
PATRON_ARTICULO_TRATADO = re.compile(r"^Art[íi]culo\s+(\d+)\s*$", re.MULTILINE)
PATRON_PROTOCOLO = re.compile(r"PROTOCOLO\s*\(")


def _localizar_articulado(texto):
    """Devuelve (inicio, fin) del articulado real del Tratado: desde el
    primer 'Artículo 1' (línea con solo eso, para no confundirlo con
    referencias cruzadas como "conforme al artículo 5") hasta el primer
    "PROTOCOLO (n.o 1)..." posterior (los protocolos reinician su propia
    numeración de artículos, así que hay que dejarlos fuera del troceado)."""
    primero = PATRON_ARTICULO_TRATADO.search(texto)
    if not primero:
        raise RuntimeError("No se encontró ningún 'Artículo 1' en el documento.")
    fin_match = PATRON_PROTOCOLO.search(texto, pos=primero.start())
    fin = fin_match.start() if fin_match else len(texto)
    return primero.start(), fin


def dividir_tratado_en_subbloques(texto, max_tokens=MAX_TOKENS_SUBBLOQUE):
    """Igual que cargar_temario_boe.dividir_en_subbloques pero troceando por
    los encabezados de artículo propios de los Tratados ("Artículo N" en su
    propia línea, sin punto) en vez de "Artículo N." de las leyes del BOE."""
    coincidencias = list(PATRON_ARTICULO_TRATADO.finditer(texto))
    if not coincidencias:
        return [{"texto": sb, "rango_articulos": None} for sb in _trocear_por_parrafos_o_lineas(texto, max_tokens)]

    unidades = []
    preambulo = texto[:coincidencias[0].start()].strip()
    if preambulo:
        unidades.append((None, preambulo))
    for idx, m in enumerate(coincidencias):
        numero = int(m.group(1))
        fin = coincidencias[idx + 1].start() if idx + 1 < len(coincidencias) else len(texto)
        unidades.append((numero, texto[m.start():fin].strip()))

    subbloques = []
    actual = []
    tokens_actual = 0
    articulos_actual = []

    def cerrar_subbloque():
        if actual:
            numeros = [n for n in articulos_actual if n is not None]
            rango = f"{numeros[0]}-{numeros[-1]}" if numeros else None
            subbloques.append({"texto": "\n\n".join(actual), "rango_articulos": rango})

    for numero, unidad_texto in unidades:
        tokens_unidad = _estimar_tokens(unidad_texto)
        if tokens_unidad > max_tokens:
            cerrar_subbloque()
            actual, tokens_actual, articulos_actual = [], 0, []
            rango_unico = str(numero) if numero is not None else None
            for sb in _trocear_por_parrafos_o_lineas(unidad_texto, max_tokens):
                subbloques.append({"texto": sb, "rango_articulos": rango_unico})
            continue
        if tokens_actual + tokens_unidad > max_tokens and actual:
            cerrar_subbloque()
            actual, tokens_actual, articulos_actual = [], 0, []
        actual.append(unidad_texto)
        tokens_actual += tokens_unidad
        articulos_actual.append(numero)
    cerrar_subbloque()
    return subbloques


def procesar_tratado(pdf_path, titulo_norma):
    print(f"📄 {titulo_norma} ({pdf_path})")
    paginas = extraer_paginas(pdf_path)
    texto_completo = "\n".join(paginas)
    inicio, fin = _localizar_articulado(texto_completo)
    texto_articulado = texto_completo[inicio:fin]
    print(f"   Articulado: {len(texto_articulado)} caracteres (de {inicio} a {fin} del texto completo)")
    subbloques = dividir_tratado_en_subbloques(texto_articulado)
    print(f"   {len(subbloques)} subbloques (por artículo/token)")
    return subbloques


def clasificar_subbloques_tratado(subbloques, titulo_norma):
    resultados = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futuros = {
            executor.submit(clasificar_subbloque, sb["texto"], BLOQUE_NUM, titulo_norma, sb["rango_articulos"]): sb
            for sb in subbloques
        }
        completados = 0
        for futuro in as_completed(futuros):
            sb = futuros[futuro]
            tema_num = futuro.result()
            resultados.append({"tema_num": tema_num, "titulo": titulo_norma, "texto": sb["texto"]})
            completados += 1
            if completados % 25 == 0:
                print(f"   ...clasificados {completados}/{len(subbloques)}")

    pendientes = [r for r in resultados if not r["tema_num"]]
    if pendientes:
        votos = Counter(r["tema_num"] for r in resultados if r["tema_num"])
        tema_mayoritario = votos.most_common(1)[0][0] if votos else 1
        for r in pendientes:
            r["tema_num"] = tema_mayoritario
        print(f"🔧 {len(pendientes)} subbloques sin clasificar se asignaron al tema mayoritario de '{titulo_norma}'.")
    return resultados


# ---------------------------------------------------------------------------
# 2) Fichas temáticas del Parlamento Europeo -> directas a tema 6
# ---------------------------------------------------------------------------
PATRON_RUIDO_FTU = re.compile(
    r"^(FICHASTEM[ÁA]TICAS|Fichas tem[áa]ticas sobre la Uni[óo]n Europea.*|"
    r"www\.europarl\.europa\.eu/factsheets/es|\d{1,3})\s*$"
)


def extraer_texto_ftu(pdf_path):
    reader = PdfReader(pdf_path)
    lineas = []
    for pagina in reader.pages:
        for linea in (pagina.extract_text() or "").split("\n"):
            s = linea.strip()
            if not s or PATRON_RUIDO_FTU.match(s):
                continue
            lineas.append(linea)
    return "\n".join(lineas)


def procesar_ficha_ftu(codigo, ruta_pdf):
    titulo = FTU_TEMA_06[codigo]
    texto = extraer_texto_ftu(ruta_pdf)
    subbloques = _trocear_por_parrafos_o_lineas(texto, MAX_TOKENS_SUBBLOQUE)
    print(f"📄 tema_06 ← {codigo} ({titulo}): {len(subbloques)} subbloque(s)")
    return [{"tema_num": 6, "titulo": titulo, "texto": sb} for sb in subbloques]


def _localizar_fichas_ftu(carpeta):
    encontradas = {}
    for codigo in FTU_TEMA_06:
        ruta = os.path.join(carpeta, f"{codigo}.pdf")
        if os.path.exists(ruta):
            encontradas[codigo] = ruta
        else:
            print(f"⚠️  Falta el PDF de la ficha {codigo}")
    return encontradas


# ---------------------------------------------------------------------------
# 3) Vista previa / subida
# ---------------------------------------------------------------------------
def guardar_preview(resultados, ruta="preview_temario_gace_bloque2_ue.json"):
    resumen = {}
    for r in resultados:
        clave = f"tema_{r['tema_num']:02d}" if r["tema_num"] else "SIN CLASIFICAR"
        resumen.setdefault(clave, []).append({
            "titulo": r["titulo"],
            "primeras_palabras": " ".join(r["texto"].split()[:25]) + "…",
        })
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    print(f"📋 Vista previa guardada en {ruta}")
    for i, tema_titulo in enumerate(TEMAS, 1):
        clave = f"tema_{i:02d}"
        n = len(resumen.get(clave, []))
        print(f"   {clave} ({tema_titulo[:60]}): {n} subbloques")
    sin_clasificar = len(resumen.get("SIN CLASIFICAR", []))
    if sin_clasificar:
        print(f"⚠️  {sin_clasificar} subbloques sin clasificar.")


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

    # Aditivo respecto al resto del temario: solo toca bloque_02 (y, dentro
    # de él, borra y recrea sus propios subbloques -- nunca bloque_01 ni
    # ningún otro bloque ya cargado).
    db.collection(COLECCION).document(BLOQUE_ID).set({"titulo": BLOQUE_TITULO})
    for i, tema_titulo in enumerate(TEMAS, 1):
        tema_id = f"tema_{i:02d}"
        db.collection(COLECCION).document(BLOQUE_ID).collection("temas").document(tema_id).set({"titulo": tema_titulo})

    print("🗑️  Borrando subbloques existentes de bloque_02 antes de subir los nuevos...")
    borrados = 0
    for i in range(1, len(TEMAS) + 1):
        tema_id = f"tema_{i:02d}"
        ref = db.collection(COLECCION).document(BLOQUE_ID).collection("temas").document(tema_id).collection("subbloques")
        for doc in ref.stream():
            doc.reference.delete()
            borrados += 1
    print(f"🗑️  {borrados} subbloques antiguos borrados.")

    contadores = {}
    subidos = 0
    for r in resultados:
        if not r["tema_num"]:
            continue
        tema_id = f"tema_{r['tema_num']:02d}"
        contadores[tema_id] = contadores.get(tema_id, 0) + 1
        sub_id = f"sub_div_{contadores[tema_id]:03d}"
        db.collection(COLECCION).document(BLOQUE_ID).collection("temas").document(tema_id) \
          .collection("subbloques").document(sub_id).set({
              "titulo": r["titulo"][:120],
              "texto": r["texto"],
          })
        subidos += 1
    print(f"✅ Subidos {subidos} subbloques a '{COLECCION}/{BLOQUE_ID}'.")


def main():
    parser = argparse.ArgumentParser(
        description="Cargar el Bloque II (Unión Europea, 6 temas) de Temario GACE."
    )
    parser.add_argument("--carpeta", default=CARPETA_FUENTES, help="Carpeta con los PDF fuente")
    parser.add_argument("--preview", action="store_true", help="Solo procesar y guardar un informe, sin subir nada")
    parser.add_argument("--subir", action="store_true", help="Procesar y subir de verdad a Firestore")
    parser.add_argument("--solo-tratados", action="store_true", help="Procesar solo TUE/TFUE (pruebas rápidas, sin las fichas)")
    parser.add_argument("--solo-fichas", action="store_true", help="Procesar solo las fichas FTU (pruebas rápidas, sin los Tratados)")
    args = parser.parse_args()

    if not args.preview and not args.subir:
        print("Indica --preview (para ver una vista previa) o --subir (para subir de verdad).")
        sys.exit(1)

    resultados = []

    if not args.solo_fichas:
        for tratado in TRATADOS:
            ruta = os.path.join(args.carpeta, tratado["pdf"])
            if not os.path.exists(ruta):
                print(f"⚠️  No se encontró {ruta}, se omite.")
                continue
            subbloques = procesar_tratado(ruta, tratado["titulo"])
            resultados.extend(clasificar_subbloques_tratado(subbloques, tratado["titulo"]))

    if not args.solo_tratados:
        fichas = _localizar_fichas_ftu(args.carpeta)
        for codigo, ruta in fichas.items():
            resultados.extend(procesar_ficha_ftu(codigo, ruta))

    guardar_preview(resultados)

    if args.subir:
        subir_a_firestore(resultados)


if __name__ == "__main__":
    main()
