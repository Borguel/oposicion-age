"""
Carga automática de un "Código electrónico" del BOE (una recopilación de leyes
completas, con su propio índice/sumario con páginas exactas) a Firestore,
repartiendo cada ley en subbloques y usando DeepSeek para clasificar cada
subbloque bajo el tema del temario oficial al que corresponde.

Pensado para documentos como "BOE-443 Normativa para ingreso en el Cuerpo de
Gestión de la Administración Civil del Estado", pero sirve para cualquier
Código electrónico del BOE con la misma estructura (SUMARIO con "§ N. Título
....... página").

USO:
  # 1) Vista previa (no escribe nada en Firestore, guarda un informe en JSON):
  python cargar_temario_boe.py --pdf "mi_temario.pdf" --preview

  # 2) Revisa scratch/preview_temario.json, y si está bien, sube de verdad:
  python cargar_temario_boe.py --pdf "mi_temario.pdf" --subir

Variables de entorno necesarias (las mismas que usa el resto del proyecto):
  DEEPSEEK_API_KEY
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)

Requiere: PyPDF2, tiktoken, requests, firebase-admin (ya están en requirements.txt)
"""

import argparse
import json
import os
import pickle
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyPDF2 import PdfReader

from utils import contar_tokens
from deepseek_utils import call_deepseek_api

# ---------------------------------------------------------------------------
# 1) TEMARIO OFICIAL (bloques y temas). Edita esta estructura para otra
#    oposición: es lo único que hay que cambiar para "escalar" a otro temario.
# ---------------------------------------------------------------------------
TEMARIO = [
    {
        "bloque": "Organización del Estado y de la Administración Pública",
        "temas": [
            "La Constitución Española de 1978: estructura y contenido. La reforma de la Constitución.",
            "Derechos y deberes fundamentales. Su garantía y suspensión. El Defensor del Pueblo.",
            "El Tribunal Constitucional: organización, composición y atribuciones.",
            "La Corona: funciones constitucionales del Rey. Sucesión y regencia. El refrendo.",
            "El poder legislativo: las Cortes Generales. Composición y atribuciones del Congreso de los Diputados y del Senado.",
            "El poder ejecutivo: el Presidente del Gobierno y el Consejo de Ministros. Relaciones entre el Gobierno y las Cortes Generales. Designación, causas de cese y responsabilidad del Gobierno. El Consejo de Estado.",
            "El Poder Judicial: el principio de unidad jurisdiccional. El Consejo General del Poder Judicial. La organización judicial española.",
            "La Administración General del Estado: principios de organización y funcionamiento. Órganos centrales. Órganos superiores y órganos directivos. Servicios comunes de los ministerios. Órganos territoriales. La Administración del Estado en el exterior.",
            "El sector público institucional: entidades que lo integran y régimen jurídico.",
            "Organización territorial (I): las Comunidades Autónomas. Estatutos de Autonomía. Organización política y administrativa. Distribución de competencias entre el Estado y las Comunidades Autónomas.",
            "Organización territorial (II): la Administración local. Autonomía local. El municipio y la provincia: organización y competencias.",
        ],
    },
    {
        "bloque": "Unión Europea",
        "temas": [
            "La Unión Europea: antecedentes, objetivos y naturaleza jurídica. Tratados originarios y modificativos. El Tratado de la Unión Europea y el Tratado de Funcionamiento de la Unión Europea. Proceso de ampliación. Cooperaciones reforzadas.",
            "La organización de la Unión Europea (I): el Consejo Europeo, el Consejo y la Comisión Europea. Composición y funciones. Procedimiento decisorio. Participación de los Estados miembros.",
            "La organización de la Unión Europea (II): el Parlamento Europeo. El Tribunal de Justicia de la Unión Europea. El Tribunal de Cuentas. El Banco Central Europeo.",
            "Las fuentes del Derecho de la Unión Europea: Derecho originario y Derecho derivado. Reglamentos, directivas y decisiones. Otras fuentes. Relación entre el Derecho de la Unión Europea y el ordenamiento jurídico de los Estados miembros.",
            "El presupuesto comunitario. Los fondos europeos. La cohesión económica y social.",
            "Políticas de la Unión Europea: mercado interior, política económica y monetaria, política exterior y de seguridad común, espacio de seguridad, libertad y justicia, defensa de la competencia, política agrícola y pesquera.",
        ],
    },
    {
        "bloque": "Políticas públicas",
        "temas": [
            "Políticas de modernización de la Administración General del Estado. Administración electrónica. Acceso electrónico de los ciudadanos a los servicios públicos. Agenda Digital para España. Calidad de los servicios públicos. Mejora regulatoria y análisis de impacto normativo.",
            "Política económica actual. Política presupuestaria. Evolución y distribución del gasto público. Política fiscal. Unidad de mercado.",
            "Política ambiental: distribución de competencias. Conservación de la biodiversidad. Prevención de la contaminación y del cambio climático.",
            "La Seguridad Social: estructura y financiación. Problemas actuales y líneas de actuación. Régimen general y regímenes especiales. Acción protectora. Prestaciones.",
            "Evolución del empleo en España. Servicios públicos de empleo. Régimen de prestaciones y políticas de empleo.",
            "Política de inmigración. Régimen de los extranjeros en España. Derecho de asilo y condición de refugiado.",
            "Gobierno Abierto: concepto y principios. Planes de acción. Ley 19/2013, de transparencia, acceso a la información pública y buen gobierno.",
            "Protección de datos personales y su régimen jurídico: principios, derechos, responsable y encargado del tratamiento, delegado y autoridades de protección de datos. Derechos digitales.",
            "Políticas de igualdad y contra la violencia de género. Igualdad de trato y no discriminación de las personas LGTBI. Discapacidad y dependencia.",
            "Otras políticas públicas: sistema sanitario, política exterior y cooperación al desarrollo, telecomunicaciones y sociedad de la información. Agenda 2030 y Objetivos de Desarrollo Sostenible.",
        ],
    },
    {
        "bloque": "Derecho administrativo general",
        "temas": [
            "Las fuentes del Derecho administrativo: concepto, clases y jerarquía.",
            "La ley: tipos de leyes y reserva de ley. Disposiciones del Gobierno con fuerza de ley: decreto-ley y decreto legislativo.",
            "El reglamento: concepto, clases y límites. Principios generales del Derecho. Tratados internacionales.",
            "El acto administrativo: concepto, clases y elementos. Eficacia y validez. Motivación y notificación.",
            "Los contratos del sector público (I): concepto, clases y elementos. Preparación, adjudicación, efectos, cumplimiento y extinción. Revisión de precios. Régimen de invalidez y recursos.",
            "Los contratos regulados por la Ley de Contratos del Sector Público (II): tipos y características generales.",
            "Procedimientos y formas de la actividad administrativa. Actividad de intervención, arbitral, de servicio público y de fomento. Formas de gestión de los servicios públicos. Ayudas y subvenciones públicas.",
            "La expropiación forzosa: concepto, naturaleza y elementos. Procedimientos y garantías jurisdiccionales.",
            "Régimen patrimonial de las Administraciones públicas. Dominio público y bienes patrimoniales del Estado. Patrimonio Nacional. Bienes comunales.",
            "Responsabilidad patrimonial de las Administraciones públicas. Procedimiento de responsabilidad patrimonial.",
            "Procedimiento administrativo común: iniciación, ordenación, instrucción y terminación. Obligación de resolver. Silencio administrativo.",
            "Derechos de los ciudadanos en el procedimiento administrativo. Garantías procedimentales. Revisión de oficio y recursos administrativos.",
            "Jurisdicción contencioso-administrativa: funciones, órganos y competencias. Recurso contencioso-administrativo. Actividad impugnable. Partes procesales.",
        ],
    },
    {
        "bloque": "Administración de recursos humanos",
        "temas": [
            "Personal al servicio de las Administraciones públicas: concepto y clases. Adquisición y pérdida de la relación de servicio.",
            "Derechos y deberes del personal. Régimen disciplinario.",
            "Planificación de recursos humanos. Ofertas de empleo público. Selección de personal. Competencias en materia de personal.",
            "Provisión de puestos de trabajo y movilidad. Promoción interna y carrera profesional.",
            "Situaciones administrativas. Incompatibilidades.",
            "Sistema de retribuciones: retribuciones básicas y complementarias. Indemnizaciones por razón del servicio.",
            "Personal laboral al servicio de las Administraciones públicas. Régimen jurídico. IV Convenio Único del personal laboral de la AGE.",
            "Negociación colectiva, representación y participación institucional. Derecho de huelga.",
            "Régimen especial de la Seguridad Social de los funcionarios civiles del Estado. MUFACE y clases pasivas.",
            "Acceso al empleo público y provisión de puestos de trabajo de las personas con discapacidad.",
        ],
    },
    {
        "bloque": "Gestión financiera y Seguridad Social",
        "temas": [
            "El presupuesto: concepto y clases. Ley General Presupuestaria. Principios generales y estructura. Leyes de estabilidad presupuestaria.",
            "Las leyes anuales de presupuestos. Contenido. Presupuesto del Estado: elaboración, estructura y desglose de aplicaciones presupuestarias.",
            "Gastos plurianuales y modificaciones de crédito: transferencias, créditos extraordinarios, suplementos, ampliaciones, incorporaciones y generaciones de crédito.",
            "Control del gasto público: Intervención General de la Administración del Estado. Función interventora, control financiero permanente y auditoría pública. Tribunal de Cuentas.",
            "Ejecución del presupuesto de gastos. Órganos competentes. Fases del procedimiento. Relación con la contratación administrativa y la gestión de subvenciones. Documentos contables. Tesorería del Estado.",
            "Gastos de bienes y servicios, gastos de inversión y transferencias. Anticipos de caja fija. Pagos a justificar.",
            "Ingresos públicos: concepto y clasificación. Sistema tributario español. Tasas y precios públicos.",
            "Retribuciones de los funcionarios públicos. Nóminas: estructura y normas de confección. Altas y bajas. Devengo y liquidación de derechos económicos.",
        ],
    },
]

MAX_TOKENS_SUBBLOQUE = 1800
CACHE_PAGINAS = "cache_paginas_pdf.pkl"


# ---------------------------------------------------------------------------
# 2) Extracción del PDF (con caché en disco para no repetirlo cada vez)
# ---------------------------------------------------------------------------
def extraer_paginas(pdf_path):
    if os.path.exists(CACHE_PAGINAS):
        print(f"📄 Usando texto ya extraído de {CACHE_PAGINAS} (bórralo si el PDF cambió)")
        with open(CACHE_PAGINAS, "rb") as f:
            return pickle.load(f)

    print(f"📄 Extrayendo texto de {pdf_path} (puede tardar uno o dos minutos)...")
    reader = PdfReader(pdf_path)
    paginas = []
    for i, pagina in enumerate(reader.pages):
        paginas.append(pagina.extract_text() or "")
        if i % 500 == 0:
            print(f"   ...página {i}/{len(reader.pages)}")
    with open(CACHE_PAGINAS, "wb") as f:
        pickle.dump(paginas, f)
    print(f"✅ {len(paginas)} páginas extraídas")
    return paginas


# ---------------------------------------------------------------------------
# 3) Parseo del SUMARIO: lista de (numero, titulo, pagina_impresa) + secciones
#    romanas que delimitan cada bloque.
# ---------------------------------------------------------------------------
def parsear_sumario(paginas, paginas_sumario=range(2, 8)):
    texto = "\n".join(paginas[i] for i in paginas_sumario if i < len(paginas))

    # Posiciones de los encabezados de sección romana ("II. ORGANIZACIÓN...")
    patron_roman = re.compile(r"\n([IVX]{1,4})\.\s+([A-ZÁÉÍÓÚÑ][^\n]{3,90})\n")
    secciones = [(m.start(), m.group(1)) for m in patron_roman.finditer(texto)]

    # Se usan las posiciones exactas de cada "§ N." (via finditer) en vez de
    # reconstruirlas sumando longitudes de fragmentos de un re.split: ese
    # segundo método acumula una pequeña deriva en cada entrada (pierde el
    # texto exacto del separador) que, tras ~10 entradas, puede desplazar el
    # "pos" de una entrada lo suficiente como para caer del lado equivocado
    # de un encabezado de sección cercano.
    patron_norma = re.compile(r"§\s*(\d+)\.\s*")
    coincidencias = list(patron_norma.finditer(texto))
    entradas = []
    for idx, m in enumerate(coincidencias):
        numero = int(m.group(1))
        inicio_contenido = m.end()
        fin_contenido = coincidencias[idx + 1].start() if idx + 1 < len(coincidencias) else len(texto)
        contenido = texto[inicio_contenido:fin_contenido]
        mm = re.search(r"\.{2,}\s*(\d+)\s*\Z", contenido.strip())
        if not mm:
            mm = re.search(r"\.{2,}\s*(\d+)", contenido)
        pagina = int(mm.group(1)) if mm else None
        titulo = contenido[: mm.start()] if mm else contenido
        titulo = " ".join(titulo.split())
        entradas.append({"numero": numero, "titulo": titulo, "pagina_impresa": pagina, "pos": m.start()})

    # Asignar a cada entrada la sección romana bajo la que cae (por posición en el texto)
    for entrada in entradas:
        seccion_actual = None
        for pos_seccion, numero_romano in secciones:
            if pos_seccion <= entrada["pos"]:
                seccion_actual = numero_romano
            else:
                break
        entrada["seccion_romana"] = seccion_actual

    return entradas


ROMANOS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]


def seccion_a_bloque(numero_romano):
    """La sección romana N del SUMARIO (que incluye 'I. INTRODUCCIÓN') es el
    bloque N-1 del temario oficial (que no incluye la introducción)."""
    if numero_romano not in ROMANOS:
        return None
    indice = ROMANOS.index(numero_romano)  # I=0, II=1, III=2...
    bloque_num = indice  # II(1) -> bloque 1, III(2) -> bloque 2, ...
    if 1 <= bloque_num <= len(TEMARIO):
        return bloque_num
    return None


# ---------------------------------------------------------------------------
# 4) Offset de páginas: la página "impresa" N del sumario corresponde a qué
#    índice real dentro de reader.pages. Se detecta buscando el encabezado
#    real de la norma 1 ("§ 1" solo en su línea) y comparando con su página
#    impresa (1).
# ---------------------------------------------------------------------------
def detectar_offset(paginas, sumario):
    patron_heading = re.compile(r"^\s*§\s*(\d+)\s*$", re.MULTILINE)
    primera_norma = min(e["numero"] for e in sumario if e["pagina_impresa"])
    pagina_impresa_objetivo = next(e["pagina_impresa"] for e in sumario if e["numero"] == primera_norma)
    for i, texto in enumerate(paginas):
        m = patron_heading.search(texto)
        if m and int(m.group(1)) == primera_norma:
            offset = i - pagina_impresa_objetivo
            print(f"✅ Offset de páginas detectado: {offset} (página impresa {pagina_impresa_objetivo} = índice real {i})")
            return offset
    raise RuntimeError("No se pudo detectar el offset de páginas automáticamente.")


# ---------------------------------------------------------------------------
# 5) Extraer el texto real de cada norma (de su página de inicio a la
#    siguiente), y trocearlo en subbloques por tokens sin cortar frases.
# ---------------------------------------------------------------------------
def extraer_texto_normas(paginas, sumario, offset):
    entradas_validas = [e for e in sumario if e["pagina_impresa"] is not None]
    entradas_validas.sort(key=lambda e: e["pagina_impresa"])

    textos = {}
    for idx, entrada in enumerate(entradas_validas):
        inicio = entrada["pagina_impresa"] + offset
        if idx + 1 < len(entradas_validas):
            fin = entradas_validas[idx + 1]["pagina_impresa"] + offset
        else:
            fin = len(paginas)
        inicio = max(0, min(inicio, len(paginas)))
        fin = max(inicio, min(fin, len(paginas)))
        texto = "\n".join(paginas[inicio:fin])
        textos[entrada["numero"]] = texto
    return textos


def dividir_en_subbloques(texto, max_tokens=MAX_TOKENS_SUBBLOQUE):
    parrafos = [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]
    subbloques = []
    actual = []
    tokens_actual = 0
    for parrafo in parrafos:
        tokens_parrafo = contar_tokens(parrafo)
        if tokens_actual + tokens_parrafo > max_tokens and actual:
            subbloques.append("\n\n".join(actual))
            actual = []
            tokens_actual = 0
        actual.append(parrafo)
        tokens_actual += tokens_parrafo
    if actual:
        subbloques.append("\n\n".join(actual))
    return subbloques


# ---------------------------------------------------------------------------
# 6) Clasificación de cada subbloque bajo el tema del bloque al que pertenece
# ---------------------------------------------------------------------------
def clasificar_subbloque(texto_subbloque, bloque_num):
    temas = TEMARIO[bloque_num - 1]["temas"]
    lista_temas = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(temas))
    prompt = (
        f"Perteneces a un sistema que clasifica fragmentos de leyes españolas dentro del temario "
        f"oficial de una oposición. El bloque es \"{TEMARIO[bloque_num - 1]['bloque']}\", con estos temas:\n\n"
        f"{lista_temas}\n\n"
        f"Lee este fragmento de texto legal y responde ÚNICAMENTE con el número del tema (1-{len(temas)}) "
        f"al que pertenece mayoritariamente. Si de verdad no encaja en ninguno, responde 0.\n\n"
        f"FRAGMENTO:\n{texto_subbloque[:3000]}"
    )
    respuesta = call_deepseek_api(
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=10
    )
    if not respuesta:
        return None
    m = re.search(r"\d+", respuesta)
    if not m:
        return None
    num = int(m.group())
    if 1 <= num <= len(temas):
        return num
    return None


# ---------------------------------------------------------------------------
# 7) Orquestación
# ---------------------------------------------------------------------------
def construir_subbloques_clasificados(paginas, sumario, offset, limite_chunks=None):
    textos_normas = extraer_texto_normas(paginas, sumario, offset)

    tareas = []  # (bloque_num, norma_numero, indice_subbloque, texto)
    for entrada in sumario:
        bloque_num = seccion_a_bloque(entrada["seccion_romana"])
        if not bloque_num:
            continue
        texto_norma = textos_normas.get(entrada["numero"], "")
        if not texto_norma.strip():
            continue
        subbloques = dividir_en_subbloques(texto_norma)
        for i, sb in enumerate(subbloques):
            tareas.append((bloque_num, entrada["numero"], entrada["titulo"], i, sb))

    if limite_chunks:
        tareas = tareas[:limite_chunks]

    print(f"🧩 {len(tareas)} subbloques a clasificar (bloques con contenido: "
          f"{sorted(set(t[0] for t in tareas))})")

    resultados = []  # (bloque_num, tema_num, norma_titulo, texto)
    with ThreadPoolExecutor(max_workers=12) as executor:
        futuros = {
            executor.submit(clasificar_subbloque, texto, bloque_num): (bloque_num, norma_num, norma_titulo, i, texto)
            for bloque_num, norma_num, norma_titulo, i, texto in tareas
        }
        completados = 0
        for futuro in as_completed(futuros):
            bloque_num, norma_num, norma_titulo, i, texto = futuros[futuro]
            tema_num = futuro.result()
            resultados.append({
                "bloque_num": bloque_num,
                "tema_num": tema_num,
                "norma_numero": norma_num,
                "norma_titulo": norma_titulo,
                "texto": texto,
            })
            completados += 1
            if completados % 25 == 0:
                print(f"   ...clasificados {completados}/{len(tareas)}")

    return resultados


def guardar_preview(resultados, ruta="preview_temario.json"):
    resumen = {}
    for r in resultados:
        clave = f"bloque_{r['bloque_num']:02d} / tema_{r['tema_num']:02d}" if r["tema_num"] else f"bloque_{r['bloque_num']:02d} / SIN CLASIFICAR"
        resumen.setdefault(clave, []).append({
            "norma": r["norma_titulo"],
            "primeras_palabras": " ".join(r["texto"].split()[:25]) + "…"
        })
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    print(f"📋 Vista previa guardada en {ruta} — ábrelo y revisa que la clasificación tenga sentido.")
    total_sin_clasificar = sum(len(v) for k, v in resumen.items() if "SIN CLASIFICAR" in k)
    if total_sin_clasificar:
        print(f"⚠️  {total_sin_clasificar} subbloques no se pudieron clasificar en ningún tema.")


def subir_a_firestore(resultados, coleccion):
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

    # Crear bloques y temas (títulos) primero
    for i, bloque in enumerate(TEMARIO, 1):
        bloque_id = f"bloque_{i:02d}"
        db.collection(coleccion).document(bloque_id).set({"titulo": bloque["bloque"]})
        for j, tema_titulo in enumerate(bloque["temas"], 1):
            tema_id = f"tema_{j:02d}"
            db.collection(coleccion).document(bloque_id).collection("temas").document(tema_id).set({"titulo": tema_titulo})

    # Contador de subbloques por (bloque, tema) para numerarlos
    contadores = {}
    subidos = 0
    for r in resultados:
        if not r["tema_num"]:
            continue
        clave = (r["bloque_num"], r["tema_num"])
        contadores[clave] = contadores.get(clave, 0) + 1
        sub_id = f"sub_div_{contadores[clave]:03d}"
        bloque_id = f"bloque_{r['bloque_num']:02d}"
        tema_id = f"tema_{r['tema_num']:02d}"
        db.collection(coleccion).document(bloque_id).collection("temas").document(tema_id) \
          .collection("subbloques").document(sub_id).set({
              "titulo": r["norma_titulo"][:120],
              "texto": r["texto"],
          })
        subidos += 1
    print(f"✅ Subidos {subidos} subbloques a Firestore, colección '{coleccion}'")


def main():
    parser = argparse.ArgumentParser(description="Cargar un Código BOE a Firestore, repartido por temas.")
    parser.add_argument("--pdf", required=True, help="Ruta al PDF del Código BOE")
    parser.add_argument("--coleccion", default="Temario GACE", help="Colección de Firestore donde subirlo")
    parser.add_argument("--preview", action="store_true", help="Solo clasificar y guardar un informe, sin subir nada")
    parser.add_argument("--subir", action="store_true", help="Clasificar y subir de verdad a Firestore")
    parser.add_argument("--limite", type=int, default=None, help="Procesar solo los N primeros subbloques (pruebas rápidas)")
    args = parser.parse_args()

    if not args.preview and not args.subir:
        print("Indica --preview (para ver una vista previa) o --subir (para subir de verdad).")
        sys.exit(1)

    paginas = extraer_paginas(args.pdf)
    sumario = parsear_sumario(paginas)
    print(f"📚 {len(sumario)} normas encontradas en el sumario")
    offset = detectar_offset(paginas, sumario)

    resultados = construir_subbloques_clasificados(paginas, sumario, offset, limite_chunks=args.limite)
    guardar_preview(resultados)

    if args.subir:
        subir_a_firestore(resultados, args.coleccion)


if __name__ == "__main__":
    main()
