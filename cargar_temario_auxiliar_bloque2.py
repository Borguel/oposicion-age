"""
Carga el Bloque II ("Actividad Administrativa y Ofimática", 12 temas) de
"Temario Auxiliar" (Cuerpo General Auxiliar de la Administración del Estado,
C2) a partir de 12 PDFs (uno por tema) aportados por el usuario -- material
de la academia Persevera Oposiciones, con licencia confirmada por el usuario
para su uso en esta plataforma.

A diferencia del Bloque I (cargar_temario_auxiliar.py, BOE-435), este bloque
no es normativa BOE: es contenido de manual/apuntes (atención al ciudadano,
Windows, Word/Excel/Access/Outlook 365, Internet...), así que no hace falta
clasificar fragmentos por IA -- cada PDF ya es exactamente un tema. El
trabajo real aquí es:
  1) extraer el texto de cada PDF, descartando portada/intro/índice (3
     primeras páginas) y las 2 páginas finales de publicidad de la propia
     academia (siempre las mismas: "Tu oposición, en una app" y "Del mismo
     equipo"),
  2) localizar el inicio real del contenido buscando la ÚLTIMA aparición de
     "Epígrafe 1 —" (la primera aparición es la entrada del índice, que
     puede desbordar a la página 3 en temas con muchos epígrafes -- así que
     no basta con saltar un número fijo de páginas),
  3) limpiar cabeceras/pies de página repetidos y marcadores decorativos
     ("M A T I Z", "R E C U E R D A", etc.), y
  4) trocear por "Epígrafe N —" (igual que dividir_en_subbloques trocea por
     "Artículo N." en cargar_temario_boe.py) y pasar cada subbloque por
     DeepSeek para reparar el espaciado roto que introduce la fuente del PDF
     al extraer texto (p. ej. "nor mativo" en vez de "normativo") SIN
     resumir ni alterar el contenido.

USO:
  # 1) Vista previa (no escribe nada en Firestore, guarda un informe en JSON):
  python cargar_temario_auxiliar_bloque2.py --preview

  # 2) Revisa preview_temario_auxiliar_bloque2.json, y si está bien, sube:
  python cargar_temario_auxiliar_bloque2.py --subir

Variables de entorno necesarias:
  DEEPSEEK_API_KEY
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from pypdf import PdfReader

from deepseek_utils import call_deepseek_api

COLECCION = "Temario Auxiliar"
BLOQUE_ID = "bloque_02"
BLOQUE_TITULO = "Actividad Administrativa y Ofimática"
MAX_TOKENS_SUBBLOQUE = 1800

# Los 12 temas, en el mismo orden que los PDFs aportados por el usuario (cada
# PDF empieza por "01 - ", "02 - ", etc., así que se emparejan por ese
# prefijo numérico en vez de por nombre exacto de archivo -- evita líos de
# normalización Unicode NFC/NFD en nombres con tildes).
TEMAS_BLOQUE_2 = [
    "Atención al público",
    "Los servicios de información administrativa",
    "Documento, registro y archivo",
    "Administración electrónica y servicios al ciudadano",
    "Informática básica",
    "El entorno Windows",
    "El Explorador de Windows",
    "Procesadores de texto: Word 365",
    "Hojas de cálculo: Excel 365",
    "Bases de datos: Access 365",
    "Correo electrónico: Outlook 365",
    "Internet y navegadores web",
]

PATRON_EPIGRAFE = re.compile(r"Epígrafe\s+(\d+)\s*[—-]\s*")

# Líneas puramente decorativas (letras sueltas separadas por espacios, típico
# de cómo esta fuente en concreto extrae los títulos en versalitas/tracking
# ancho) que no aportan nada si ya se ha extraído el contenido real debajo.
PATRON_LINEA_DECORATIVA = re.compile(r"^(?:[A-ZÁÉÍÓÚÜÑ0-9]\s+){2,}[A-ZÁÉÍÓÚÜÑ0-9]?\s*$")
PATRON_PIE_PAGINA = re.compile(r"^\d{1,4}$")

MARCADORES = {
    re.compile(r"^M\s*A\s*T\s*I\s*Z$"): "Matiz:",
    re.compile(r"^R\s*E\s*C\s*U\s*E\s*R\s*D\s*A$"): "Recuerda:",
}


def _localizar_pdfs(carpeta="temario-examenes/AUXILIAR"):
    """Empareja cada uno de los 12 PDFs con su número de tema (1-12) por el
    prefijo del nombre de archivo -- usa os.listdir (no glob con literales
    acentuados) porque estos archivos llegaron con nombres en NFD (normal en
    subidas desde macOS) y comparar contra un literal NFC en el código nunca
    los encontraría."""
    encontrados = {}
    for nombre in os.listdir(carpeta):
        m = re.match(r"^(\d{2})\s*-\s*.+\.pdf$", nombre, re.IGNORECASE)
        if not m:
            continue
        num = int(m.group(1))
        if 1 <= num <= len(TEMAS_BLOQUE_2):
            encontrados[num] = os.path.join(carpeta, nombre)
    faltan = [i for i in range(1, len(TEMAS_BLOQUE_2) + 1) if i not in encontrados]
    if faltan:
        print(f"⚠️  Faltan los PDFs de los temas: {faltan}")
    return encontrados


def _limpiar_pagina(texto):
    lineas = []
    for linea in texto.split("\n"):
        s = linea.strip()
        if not s:
            continue
        # Cabecera repetida en cada página: "T E M A n · TÍTULO... perseveraoposiciones.com"
        if "oposiciones.com" in s.lower().replace(" ", ""):
            continue
        reemplazada = None
        for patron, texto_limpio in MARCADORES.items():
            if patron.match(s):
                reemplazada = texto_limpio
                break
        if reemplazada:
            lineas.append(reemplazada)
            continue
        if PATRON_PIE_PAGINA.match(s):
            continue
        if PATRON_LINEA_DECORATIVA.match(s):
            continue
        lineas.append(linea)
    return "\n".join(lineas)


def extraer_texto_tema(ruta_pdf):
    """Extrae y limpia el texto real de un tema (sin portada/intro/índice ni
    las 2 páginas de publicidad finales, siempre las mismas)."""
    reader = PdfReader(ruta_pdf)
    paginas = [p.extract_text() or "" for p in reader.pages]
    n = len(paginas)
    # Portada + "AL ALCANCE DE QUIEN ESTUDIA" (intro genérica) ocupan siempre
    # las 2 primeras páginas; las 2 últimas son siempre los anuncios de la
    # propia app "Persevera" y de "Eroodite" -- verificado en los 12 PDFs
    # independientemente de la longitud de cada tema.
    bruto = "\n".join(paginas[2:n - 2])
    limpio = _limpiar_pagina(bruto)

    # El índice (página con "Í N D I C E") repite "Epígrafe 1 —" antes de que
    # aparezca como encabezado real de contenido; puede desbordar a la
    # página siguiente en temas con muchos epígrafes, así que no basta con
    # saltar un número fijo de páginas -- se busca la ÚLTIMA aparición de
    # "Epígrafe 1" (la primera es siempre la entrada del índice).
    coincidencias = list(PATRON_EPIGRAFE.finditer(limpio))
    primeras = [m for m in coincidencias if m.group(1) == "1"]
    if primeras:
        return limpio[primeras[-1].start():]
    print("   ⚠️  No se encontró 'Epígrafe 1' -- se sube el texto completo sin recortar el índice.")
    return limpio


def _estimar_tokens(texto):
    """Estimación aproximada (sin tiktoken -- la descarga de su diccionario
    está bloqueada por política de red en este entorno) usada solo para
    decidir el tamaño de los trozos; no necesita ser exacta, basta con ser
    consistente. ~1.3 tokens por palabra es razonable para español."""
    return int(len(texto.split()) * 1.3)


def _trocear_por_parrafos_o_lineas(texto, max_tokens):
    """Igual que _trocear_por_parrafos_o_lineas de cargar_temario_boe.py
    pero con _estimar_tokens en vez de contar_tokens (tiktoken), para no
    depender de red en este script."""
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


def dividir_en_subbloques_por_epigrafe(texto, max_tokens=MAX_TOKENS_SUBBLOQUE):
    """Igual que dividir_en_subbloques de cargar_temario_boe.py pero
    troceando por límites de "Epígrafe N —" en vez de "Artículo N."."""
    coincidencias = list(PATRON_EPIGRAFE.finditer(texto))
    if not coincidencias:
        return [{"texto": sb, "epigrafes": None} for sb in _trocear_por_parrafos_o_lineas(texto, max_tokens)]

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
    epigrafes_actual = []

    def cerrar_subbloque():
        if actual:
            numeros = [n for n in epigrafes_actual if n is not None]
            rango = f"{numeros[0]}-{numeros[-1]}" if numeros else None
            subbloques.append({"texto": "\n\n".join(actual), "epigrafes": rango})

    for numero, unidad_texto in unidades:
        tokens_unidad = _estimar_tokens(unidad_texto)
        if tokens_unidad > max_tokens:
            cerrar_subbloque()
            actual, tokens_actual, epigrafes_actual = [], 0, []
            for trozo in _trocear_por_parrafos_o_lineas(unidad_texto, max_tokens):
                subbloques.append({"texto": trozo, "epigrafes": str(numero) if numero else None})
            continue
        if tokens_actual + tokens_unidad > max_tokens and actual:
            cerrar_subbloque()
            actual, tokens_actual, epigrafes_actual = [], 0, []
        actual.append(unidad_texto)
        tokens_actual += tokens_unidad
        epigrafes_actual.append(numero)
    cerrar_subbloque()
    return subbloques


def reparar_espaciado(texto_subbloque):
    """El PDF fuente usa una fuente con un tracking que pypdf extrae como
    espacios sueltos dentro de palabras (p. ej. "nor mativo", "R eal
    Decr eto"). DeepSeek corrige solo eso, sin resumir ni tocar el
    contenido."""
    prompt = (
        "El siguiente texto viene de extraer un PDF cuya fuente introduce espacios erróneos "
        "dentro de algunas palabras al extraerlo (p. ej. \"nor mativo\" en vez de \"normativo\", "
        "\"R eal Decr eto\" en vez de \"Real Decreto\"). Corrige ÚNICAMENTE esos espacios rotos "
        "dentro de palabras y saltos de línea sueltos a mitad de frase. NO resumas, NO elimines "
        "ni añadas ningún contenido, ejemplo, número de artículo, mnemotecnia o matiz. Devuelve "
        "el texto completo corregido, sin comentarios ni explicaciones adicionales, respetando "
        "los párrafos y las líneas \"Matiz:\"/\"Recuerda:\" tal cual aparezcan.\n\n"
        f"TEXTO:\n{texto_subbloque}"
    )
    respuesta = call_deepseek_api(
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=4000,
    )
    return (respuesta or "").strip() or texto_subbloque


def procesar_tema(num_tema, ruta_pdf, reparar=True):
    print(f"📄 Tema {num_tema}: {os.path.basename(ruta_pdf)}")
    texto = extraer_texto_tema(ruta_pdf)
    subbloques = dividir_en_subbloques_por_epigrafe(texto)
    print(f"   {len(subbloques)} subbloques (por epígrafe/token)")

    if not reparar:
        return subbloques

    resultados = [None] * len(subbloques)

    def _reparar(i):
        resultados[i] = reparar_espaciado(subbloques[i]["texto"])
        time.sleep(0.2)

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(_reparar, range(len(subbloques))))

    for sb, texto_reparado in zip(subbloques, resultados):
        sb["texto"] = texto_reparado
    return subbloques


def guardar_preview(resultados_por_tema, ruta="preview_temario_auxiliar_bloque2.json"):
    resumen = {}
    for num_tema, subbloques in resultados_por_tema.items():
        resumen[f"tema_{num_tema:02d}"] = {
            "titulo": TEMAS_BLOQUE_2[num_tema - 1],
            "num_subbloques": len(subbloques),
            "subbloques": [
                {"epigrafes": sb["epigrafes"], "primeras_palabras": " ".join(sb["texto"].split()[:40]) + "…"}
                for sb in subbloques
            ],
        }
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    print(f"📋 Vista previa guardada en {ruta}")
    for num_tema, subbloques in resultados_por_tema.items():
        print(f"   tema_{num_tema:02d} ({TEMAS_BLOQUE_2[num_tema-1][:40]}): {len(subbloques)} subbloques")


def subir_a_firestore(resultados_por_tema, coleccion=COLECCION):
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

    db.collection(coleccion).document(BLOQUE_ID).set({"titulo": BLOQUE_TITULO})

    for num_tema, subbloques in resultados_por_tema.items():
        tema_id = f"tema_{num_tema:02d}"
        titulo = TEMAS_BLOQUE_2[num_tema - 1]
        db.collection(coleccion).document(BLOQUE_ID).collection("temas").document(tema_id).set({"titulo": titulo})

        subbloques_ref = db.collection(coleccion).document(BLOQUE_ID).collection("temas") \
            .document(tema_id).collection("subbloques")
        for doc in subbloques_ref.stream():
            doc.reference.delete()

        for j, sb in enumerate(subbloques, 1):
            sub_id = f"sub_div_{j:03d}"
            etiqueta_titulo = f"Epígrafe {sb['epigrafes']}" if sb["epigrafes"] else titulo
            subbloques_ref.document(sub_id).set({
                "titulo": etiqueta_titulo[:120],
                "texto": sb["texto"],
            })
        print(f"✅ Subido tema_{num_tema:02d} ({titulo}): {len(subbloques)} subbloques")

    print(f"✅ Bloque II completo subido a '{coleccion}/{BLOQUE_ID}'.")


def main():
    parser = argparse.ArgumentParser(
        description="Cargar el Bloque II (12 temas) de Temario Auxiliar desde 12 PDFs propios."
    )
    parser.add_argument("--preview", action="store_true", help="Solo procesar y guardar un informe, sin subir nada")
    parser.add_argument("--subir", action="store_true", help="Procesar y subir de verdad a Firestore")
    parser.add_argument("--sin-reparar", action="store_true", help="No llamar a DeepSeek para reparar el espaciado (pruebas rápidas)")
    parser.add_argument("--solo-tema", type=int, default=None, help="Procesar solo el tema N (pruebas rápidas)")
    args = parser.parse_args()

    if not args.preview and not args.subir:
        print("Indica --preview (para ver una vista previa) o --subir (para subir de verdad).")
        sys.exit(1)

    pdfs = _localizar_pdfs()
    if args.solo_tema:
        pdfs = {args.solo_tema: pdfs[args.solo_tema]} if args.solo_tema in pdfs else {}

    resultados_por_tema = {}
    for num_tema in sorted(pdfs):
        resultados_por_tema[num_tema] = procesar_tema(num_tema, pdfs[num_tema], reparar=not args.sin_reparar)

    guardar_preview(resultados_por_tema)

    if args.subir:
        subir_a_firestore(resultados_por_tema)


if __name__ == "__main__":
    main()
