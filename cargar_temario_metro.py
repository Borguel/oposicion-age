"""
Carga los 7 temas de "Temario Metro" (oposición de Agente de Movilidad de
Metro de Madrid -- oposición oculta, ver oposiciones.py) a partir de los 7
PDFs aportados por el usuario en metro/ (manuales internos y normativa de
Metro de Madrid, con licencia de uso confirmada por el usuario para esta
plataforma). Los 7 forman un único bloque (bloque_01), un PDF = un tema.

Como en cargar_temario_auxiliar_bloque2.py, no hace falta clasificar
fragmentos por IA: cada PDF es exactamente un tema, así que el trabajo real
es trocear cada uno en subbloques razonables. A diferencia de aquel script
(un solo proveedor, con cabeceras/patrón conocidos de antemano), aquí hay 7
documentos de origen distinto (Metro de Madrid, Comunidad de Madrid...),
cada uno con su propio formato:
  - Con patrón de artículo/capítulo reconocible (Normativa Interna de
    Circulación, Reglamento de Viajeros, Código Ético, Normas Internas de
    Seguridad, Conocimientos específicos) se trocea por esos límites --
    ver _trocear_por_patron, la misma idea que dividir_en_subbloques_por_epigrafe
    de cargar_temario_auxiliar_bloque2.py pero parametrizada por regex en
    vez de fija a "Epígrafe N".
  - Sin patrón reconocible (Manual PRL, Conocimientos CRTM: manuales
    corridos sin numeración de artículo/capítulo) se trocea genéricamente
    por párrafo/token.

Los PDFs de origen tienen (todos, no solo uno) el mismo defecto de
extracción que ya se veía en el material de cargar_temario_auxiliar_bloque2.py:
espacios sueltos dentro de palabras (p. ej. "si empre" en vez de "siempre")
-- se corrige igual, con DeepSeek, sin resumir ni tocar contenido.

No se ha replicado la limpieza de cabeceras/pies de página línea a línea de
aquel script (pensada para un único proveedor con cabeceras conocidas de
antemano): con 7 documentos de origen distinto no compensa teclear a mano
el texto exacto de cada cabecera, así que aquí solo se descartan las líneas
de pie de página que son un número suelto -- el resto de ruido de cabecera
(nombre del documento repetido, etc.) queda dentro del texto como ruido
menor, sin afectar a la generación de preguntas.

USO:
  # 1) Vista previa (no escribe nada en Firestore, guarda un informe en JSON):
  python cargar_temario_metro.py --preview

  # 2) Revisa preview_temario_metro.json, y si está bien, sube:
  python cargar_temario_metro.py --subir

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

from dotenv import load_dotenv
from pypdf import PdfReader

from deepseek_utils import call_deepseek_api

# A diferencia de los demás cargar_temario_*.py (que exigen exportar
# DEEPSEEK_API_KEY/FIREBASE_KEY_PATH a mano en cada sesión de terminal),
# aquí se cargan también desde un archivo .env en la raíz del repo si
# existe -- igual que ya hacen cargar_datos_convocatoria.py y
# cargar_examen_oficial_*.py -- para no tener que volver a escribirlas cada
# vez que se abre una terminal nueva.
load_dotenv()

COLECCION = "Temario Metro"
BLOQUE_ID = "bloque_01"
BLOQUE_TITULO = "Temario completo"
MAX_TOKENS_SUBBLOQUE = 1800

PATRON_CAPITULO = re.compile(r"CAP[ÍI]TULO\s+(\d+)")
PATRON_ARTICULO = re.compile(r"Art[íi]culo\s+(\d+)\b")
PATRON_ARTICULO_PUNTEADO = re.compile(r"Art\.\s*(\d+(?:\.\d+)+)\s*\.?\s*-")

# Los 7 temas, cada uno un PDF completo (el prefijo numérico del nombre de
# archivo, p. ej. "1." o "2.", identifica cuál es cuál -- igual que
# _localizar_pdfs en cargar_temario_auxiliar_bloque2.py, por si acaso llegan
# con distinta normalización Unicode en el nombre). "patron"/"etiqueta" en
# None significa "sin numeración de artículo/capítulo reconocible": se
# trocea genéricamente por párrafo/token en vez de por ese límite.
TEMAS_METRO = [
    {
        "num": 1, "prefijo": "1.",
        "titulo": "Conocimientos específicos sobre Metro de Madrid",
        "patron": PATRON_CAPITULO, "primer_valor": "1", "etiqueta": "Capítulo {n}",
    },
    {
        "num": 2, "prefijo": "2.",
        "titulo": "Normas internas para la seguridad de los agentes en relación con la circulación",
        "patron": PATRON_CAPITULO, "primer_valor": "1", "etiqueta": "Capítulo {n}",
    },
    {
        "num": 3, "prefijo": "3.",
        "titulo": "Normativa interna de circulación",
        "patron": PATRON_ARTICULO_PUNTEADO, "primer_valor": "1.1.1", "etiqueta": "Art. {n}",
    },
    {
        "num": 4, "prefijo": "4.",
        "titulo": "Reglamento de viajeros del Ferrocarril Metropolitano de Madrid",
        "patron": PATRON_ARTICULO, "primer_valor": "1", "etiqueta": "Artículo {n}",
    },
    {
        "num": 5, "prefijo": "5.",
        "titulo": "Código Ético en Metro de Madrid",
        "patron": PATRON_ARTICULO, "primer_valor": "1", "etiqueta": "Artículo {n}",
    },
    {
        "num": 6, "prefijo": "6.",
        "titulo": "Prevención de Riesgos Laborales",
        "patron": None, "primer_valor": None, "etiqueta": None,
    },
    {
        "num": 7, "prefijo": "7.",
        "titulo": "Conocimientos generales sobre el Consorcio Regional de Transportes de Madrid (CRTM)",
        "patron": None, "primer_valor": None, "etiqueta": None,
    },
]


def _localizar_pdfs(carpeta="metro"):
    """Empareja cada uno de los 7 PDFs con su tema por el prefijo numérico
    del nombre de archivo -- usa os.listdir (no glob con literales
    acentuados) por si llegan con nombres en NFD (normal en subidas desde
    macOS), igual que _localizar_pdfs en cargar_temario_auxiliar_bloque2.py."""
    encontrados = {}
    for nombre in os.listdir(carpeta):
        if not nombre.lower().endswith(".pdf"):
            continue
        for tema in TEMAS_METRO:
            if nombre.startswith(tema["prefijo"]):
                encontrados[tema["num"]] = os.path.join(carpeta, nombre)
                break
    faltan = [t["num"] for t in TEMAS_METRO if t["num"] not in encontrados]
    if faltan:
        print(f"⚠️  Faltan los PDFs de los temas: {faltan}")
    return encontrados


def _limpiar_pagina(texto):
    """Descarta líneas vacías y de pie de página que son solo un número
    suelto -- el resto de ruido de cabecera (nombre del documento repetido,
    etc.) se deja tal cual, ver nota en la cabecera del módulo."""
    lineas = []
    for linea in texto.split("\n"):
        s = linea.strip()
        if not s or re.fullmatch(r"\d{1,4}", s):
            continue
        lineas.append(s)
    return "\n".join(lineas)


def extraer_texto_tema(ruta_pdf):
    reader = PdfReader(ruta_pdf)
    return "\n".join(_limpiar_pagina(p.extract_text() or "") for p in reader.pages)


def _recortar_indice(texto, patron, primer_valor):
    """Si el primer valor esperado (p. ej. "Capítulo 1") aparece más de una
    vez, la primera es casi siempre la entrada del índice y la última el
    encabezado real -- se recorta el texto para empezar ahí, igual que
    extraer_texto_tema hacía con "Epígrafe 1" en
    cargar_temario_auxiliar_bloque2.py. Con 0 o 1 apariciones (sin índice
    detectable, o documentos como el Reglamento de Viajeros que no tienen
    índice separado) se deja el texto tal cual."""
    coincidencias = [m for m in patron.finditer(texto) if m.group(1) == primer_valor]
    if len(coincidencias) >= 2:
        return texto[coincidencias[-1].start():]
    return texto


def _estimar_tokens(texto):
    """Estimación aproximada (sin tiktoken -- ver la misma nota en
    cargar_temario_auxiliar_bloque2.py), suficiente para decidir el tamaño
    de los trozos sin depender de red."""
    return int(len(texto.split()) * 1.3)


def _contar_palabras(texto):
    return len(texto.split())


def _dividir_en_unidades(texto):
    """Intenta dividir en unidades cada vez más finas: por párrafo (línea en
    blanco), si no hay, por línea suelta -- nunca por debajo de una línea,
    para no cortar nunca una palabra por la mitad. Con len(unidades) <= 1
    (nada por lo que dividir con ese criterio) se devuelve tal cual, para
    que el llamador decida qué hacer."""
    unidades = [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]
    if len(unidades) > 1:
        return unidades
    unidades = [l.strip() for l in texto.split("\n") if l.strip()]
    return unidades if unidades else [texto]


def _trocear_por_parrafos_o_lineas(texto, max_tokens):
    """Agrupa unidades (párrafos, o líneas si el texto no tiene párrafos
    separados por línea en blanco -- ver _limpiar_pagina, que ya descarta
    esas líneas en blanco al extraer) sin pasar de max_tokens por grupo.

    Acumula PALABRAS, no la estimación de tokens de cada unidad por
    separado: sumar `_estimar_tokens(unidad)` unidad a unidad trunca
    (int()) en cada paso y puede quedarse corto frente al token real del
    grupo ya unido -- con textos de muchas líneas cortas (línea a línea, no
    por párrafo) esa deriva llegó a colar grupos de hasta ~2000 tokens
    reales con el límite puesto en 1800. Contar palabras y convertir a
    tokens una sola vez, al comparar, evita la deriva por acumular
    redondeos.

    Una unidad (un párrafo entero, o -- caso real visto en el Manual PRL --
    prácticamente el documento entero cuando casi no hay líneas en blanco
    internas) puede en sí misma superar max_tokens: en ese caso se
    subdivide recursivamente por línea en vez de cortarla por un número
    fijo de caracteres, para no partir palabras por la mitad."""
    unidades = _dividir_en_unidades(texto)

    subbloques = []
    actual, palabras_actual = [], 0
    for unidad in unidades:
        palabras_unidad = _contar_palabras(unidad)
        if int(palabras_unidad * 1.3) > max_tokens:
            if actual:
                subbloques.append("\n\n".join(actual))
                actual, palabras_actual = [], 0
            sub_unidades = _dividir_en_unidades(unidad)
            if len(sub_unidades) > 1:
                subbloques.extend(_trocear_por_parrafos_o_lineas(unidad, max_tokens))
            else:
                # Unidad indivisible por línea (una única línea gigantesca
                # sin espacios internos que la partan) -- no visto en
                # ninguno de los 7 PDFs, pero se sube entera antes que
                # cortarla a mitad de palabra.
                subbloques.append(unidad)
            continue
        if int((palabras_actual + palabras_unidad) * 1.3) > max_tokens and actual:
            subbloques.append("\n\n".join(actual))
            actual, palabras_actual = [], 0
        actual.append(unidad)
        palabras_actual += palabras_unidad
    if actual:
        subbloques.append("\n\n".join(actual))
    return subbloques


def _trocear_por_patron(texto, patron, etiqueta_formato, max_tokens=MAX_TOKENS_SUBBLOQUE):
    """Trocea por los límites que marca `patron` (p. ej. "Capítulo N" o
    "Artículo N"), agrupando hasta `max_tokens` sin partir nunca un
    capítulo/artículo a mitad -- igual que dividir_en_subbloques_por_epigrafe
    de cargar_temario_auxiliar_bloque2.py, parametrizado por regex/etiqueta
    en vez de fijo a "Epígrafe N"."""
    coincidencias = list(patron.finditer(texto))
    if not coincidencias:
        return [{"texto": sb, "etiqueta": None} for sb in _trocear_por_parrafos_o_lineas(texto, max_tokens)]

    unidades = []
    preambulo = texto[:coincidencias[0].start()].strip()
    if preambulo:
        unidades.append((None, preambulo))
    for idx, m in enumerate(coincidencias):
        numero = m.group(1)
        fin = coincidencias[idx + 1].start() if idx + 1 < len(coincidencias) else len(texto)
        unidades.append((numero, texto[m.start():fin].strip()))

    subbloques = []
    # Acumula palabras, no tokens ya redondeados por unidad -- misma razón
    # que en _trocear_por_parrafos_o_lineas.
    actual, palabras_actual, numeros_actual = [], 0, []

    def cerrar():
        if not actual:
            return
        numeros = [n for n in numeros_actual if n is not None]
        etiqueta = None
        if numeros:
            etiqueta = etiqueta_formato.format(n=numeros[0])
            if numeros[-1] != numeros[0]:
                etiqueta += f"-{numeros[-1]}"
        subbloques.append({"texto": "\n\n".join(actual), "etiqueta": etiqueta})

    for numero, unidad_texto in unidades:
        palabras_unidad = _contar_palabras(unidad_texto)
        if int(palabras_unidad * 1.3) > max_tokens:
            cerrar()
            actual, palabras_actual, numeros_actual = [], 0, []
            for trozo in _trocear_por_parrafos_o_lineas(unidad_texto, max_tokens):
                subbloques.append({"texto": trozo, "etiqueta": etiqueta_formato.format(n=numero) if numero else None})
            continue
        if int((palabras_actual + palabras_unidad) * 1.3) > max_tokens and actual:
            cerrar()
            actual, palabras_actual, numeros_actual = [], 0, []
        actual.append(unidad_texto)
        palabras_actual += palabras_unidad
        numeros_actual.append(numero)
    cerrar()
    return subbloques


# Si la respuesta de DeepSeek tiene menos palabras que este porcentaje del
# original, se descarta y se sube el texto sin reparar -- de vez en cuando
# el propio "si empre" queda en el texto final, pero eso es un defecto
# cosmético menor; perder contenido real (un corte a mitad de artículo por
# una respuesta truncada, o que el modelo decida "resumir" pese a la
# instrucción) sería mucho peor y pasaría desapercibido, ya que la llamada
# no falla -- simplemente devuelve menos texto del que se le pasó.
UMBRAL_PALABRAS_REPARACION = 0.85


def reparar_espaciado(texto_subbloque):
    """Los PDFs de origen introducen espacios erróneos dentro de algunas
    palabras al extraer el texto (p. ej. "si empre" en vez de "siempre").
    DeepSeek corrige solo eso, sin resumir ni tocar el contenido -- mismo
    prompt que cargar_temario_auxiliar_bloque2.py."""
    prompt = (
        "El siguiente texto viene de extraer un PDF cuya fuente introduce espacios erróneos "
        "dentro de algunas palabras al extraerlo (p. ej. \"nor mativo\" en vez de \"normativo\", "
        "\"si empre\" en vez de \"siempre\"). Corrige ÚNICAMENTE esos espacios rotos dentro de "
        "palabras y saltos de línea sueltos a mitad de frase. NO resumas, NO elimines ni añadas "
        "ningún contenido, ejemplo ni número de artículo/capítulo. Devuelve el texto completo "
        "corregido, sin comentarios ni explicaciones adicionales, respetando los párrafos tal "
        "cual aparezcan.\n\n"
        f"TEXTO:\n{texto_subbloque}"
    )
    respuesta = call_deepseek_api(
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=4000,
    )
    respuesta = (respuesta or "").strip()
    if not respuesta:
        return texto_subbloque
    palabras_originales = _contar_palabras(texto_subbloque)
    if palabras_originales and _contar_palabras(respuesta) < palabras_originales * UMBRAL_PALABRAS_REPARACION:
        print(f"   ⚠️  Respuesta de DeepSeek sospechosamente corta ({_contar_palabras(respuesta)} "
              f"palabras vs {palabras_originales} originales) -- se descarta, se sube sin reparar.")
        return texto_subbloque
    return respuesta


def procesar_tema(config, ruta_pdf, reparar=True):
    print(f"📄 Tema {config['num']}: {os.path.basename(ruta_pdf)}")
    texto = extraer_texto_tema(ruta_pdf)

    if config["patron"] and config["primer_valor"]:
        texto = _recortar_indice(texto, config["patron"], config["primer_valor"])

    if config["patron"]:
        subbloques = _trocear_por_patron(texto, config["patron"], config["etiqueta"])
    else:
        subbloques = [{"texto": sb, "etiqueta": None} for sb in _trocear_por_parrafos_o_lineas(texto, MAX_TOKENS_SUBBLOQUE)]
    print(f"   {len(subbloques)} subbloques")

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


def guardar_preview(resultados_por_tema, ruta="preview_temario_metro.json"):
    resumen = {}
    for num_tema, subbloques in resultados_por_tema.items():
        titulo = next(t["titulo"] for t in TEMAS_METRO if t["num"] == num_tema)
        resumen[f"tema_{num_tema:02d}"] = {
            "titulo": titulo,
            "num_subbloques": len(subbloques),
            "subbloques": [
                {"etiqueta": sb["etiqueta"], "primeras_palabras": " ".join(sb["texto"].split()[:40]) + "…"}
                for sb in subbloques
            ],
        }
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    print(f"📋 Vista previa guardada en {ruta}")
    for num_tema, subbloques in resultados_por_tema.items():
        titulo = next(t["titulo"] for t in TEMAS_METRO if t["num"] == num_tema)
        print(f"   tema_{num_tema:02d} ({titulo[:50]}): {len(subbloques)} subbloques")


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
        titulo = next(t["titulo"] for t in TEMAS_METRO if t["num"] == num_tema)
        db.collection(coleccion).document(BLOQUE_ID).collection("temas").document(tema_id).set({"titulo": titulo})

        subbloques_ref = db.collection(coleccion).document(BLOQUE_ID).collection("temas") \
            .document(tema_id).collection("subbloques")
        for doc in subbloques_ref.stream():
            doc.reference.delete()

        for j, sb in enumerate(subbloques, 1):
            sub_id = f"sub_div_{j:03d}"
            etiqueta_titulo = sb["etiqueta"] or titulo
            subbloques_ref.document(sub_id).set({
                "titulo": etiqueta_titulo[:120],
                "texto": sb["texto"],
            })
        print(f"✅ Subido tema_{num_tema:02d} ({titulo}): {len(subbloques)} subbloques")

    print(f"✅ Temario Metro completo subido a '{coleccion}/{BLOQUE_ID}'.")


def main():
    parser = argparse.ArgumentParser(
        description="Cargar los 7 temas de Temario Metro desde los PDFs propios en metro/."
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
        config = next(t for t in TEMAS_METRO if t["num"] == num_tema)
        resultados_por_tema[num_tema] = procesar_tema(config, pdfs[num_tema], reparar=not args.sin_reparar)

    guardar_preview(resultados_por_tema)

    if args.subir:
        subir_a_firestore(resultados_por_tema)


if __name__ == "__main__":
    main()
