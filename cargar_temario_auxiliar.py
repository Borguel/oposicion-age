"""
Carga el Bloque I ("Organización Pública", 16 temas) de "Temario Auxiliar"
(Cuerpo General Auxiliar de la Administración del Estado, C2) a partir del
PDF BOE-435 (Normativa para ingreso en el Cuerpo General Auxiliar de la
Administración del Estado -- "Códigos electrónicos" del BOE, mismo formato
que BOE-442/443 ya usados para AGE y GACE).

Alcance: SOLO el Bloque I. El propio PDF se presenta como "Temario materias
jurídicas" y su SUMARIO no tiene ninguna sección más allá de las 16 que
cubren este bloque -- no incluye nada de "Actividad Administrativa y
Ofimática" (Bloque II: atención al ciudadano, cartas de servicio,
documentos administrativos, registro, informática básica, Windows,
Microsoft 365, redes/ciberseguridad), porque esos temas no son normativa
BOE. Ese bloque necesitará otra fuente que aporte el usuario más adelante;
este script no crea ningún documento de bloque_02.

Reutiliza las funciones de bajo nivel de cargar_temario_boe.py (extracción
de páginas, parseo del sumario, detección de offset, extracción de texto
por norma, troceado en subbloques por límites de artículo), pero define su
propia lista de temas y su propio clasificador -- igual que ya hace
completar_temario_age.py para el temario de AGE, que tampoco comparte el
TEMARIO de GACE.

Detalle importante ya verificado sobre este PDF en concreto: su SUMARIO
ocupa las páginas de índice 2 a 8 (inclusive) -- el rango por defecto de
parsear_sumario() (2 a 7) se queda corto y pierde las normas §64 a §72
(el tramo final de los temas 14 a 16), así que aquí se llama explícitamente
con un rango más amplio.

USO:
  # 1) Vista previa (no escribe nada en Firestore, guarda un informe en JSON):
  python cargar_temario_auxiliar.py --preview

  # 2) Revisa preview_temario_auxiliar.json, y si está bien, sube de verdad:
  python cargar_temario_auxiliar.py --subir

Variables de entorno necesarias:
  DEEPSEEK_API_KEY
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from cargar_temario_boe import (
    extraer_paginas,
    parsear_sumario,
    detectar_offset,
    extraer_texto_normas,
    dividir_en_subbloques,
)
from deepseek_utils import call_deepseek_api

PDF_FUENTE = (
    "temario-examenes/AUXILIAR/BOE-435_Normativa_para_ingreso_en_el_Cuerpo_General_Auxiliar_de_la_"
    "Administracion_del_Estado.pdf"
)

COLECCION = "Temario Auxiliar"
BLOQUE_ID = "bloque_01"
BLOQUE_TITULO = "Organización Pública"

# Los 16 temas del Bloque I, en el orden dado por el usuario -- coincide en
# número y orden con las 16 secciones romanas (I a XVI) del SUMARIO del PDF,
# aunque la clasificación real es por contenido de cada subbloque, no por
# posición, así que una norma que se reparta entre varias secciones romanas
# (p. ej. Ley 39/2015 y Ley 40/2015, que cubren buena parte de la sección XI
# pero también aportan fragmentos a otros temas) queda bien repartida entre
# los temas a los que de verdad corresponde cada fragmento.
TEMAS_BLOQUE_1 = [
    "Constitución Española de 1978.",
    "Tribunal Constitucional y la Corona.",
    "Las Cortes Generales: Congreso y Senado.",
    "El Poder Judicial y su organización.",
    "El Gobierno de España.",
    "Gobierno Abierto y Objetivos ODS.",
    "Transparencia y derecho de acceso.",
    "Administración General del Estado (AGE).",
    "Comunidades Autónomas y Administración Local.",
    "Unión Europea y sus instituciones.",
    "Funcionamiento electrónico del sector público.",
    "Protección de datos personales.",
    "Estatuto del Empleado Público (TREBEP).",
    "Derechos, deberes y carrera funcionarial.",
    "El Presupuesto del Estado.",
    "Políticas de Igualdad de Género.",
]

# El SUMARIO de este PDF concreto ocupa las páginas de índice 2 a 8
# (inclusive) -- el rango por defecto de parsear_sumario() (2 a 7) deja
# fuera las normas §64-§72 (temas 14 tardío, 15 y 16 enteros). La página 9
# está en blanco, incluirla no hace daño.
PAGINAS_SUMARIO = range(2, 10)


def clasificar_subbloque_auxiliar(texto_subbloque, norma_titulo=None, rango_articulos=None):
    """Igual que clasificar_subbloque_age de completar_temario_age.py, pero
    con los 16 temas del Bloque I de 'Temario Auxiliar'. Todo el PDF
    pertenece a este único bloque, así que no hace falta enrutar por
    sección romana primero."""
    lista_temas = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(TEMAS_BLOQUE_1))
    contexto_norma = f"Este fragmento pertenece a la norma: \"{norma_titulo}\".\n\n" if norma_titulo else ""
    contexto_articulos = (
        f"Este fragmento corresponde a los artículos {rango_articulos} de la norma.\n\n" if rango_articulos else ""
    )
    prompt = (
        f"Perteneces a un sistema que clasifica fragmentos de leyes españolas dentro del temario "
        f"oficial de una oposición. El bloque es \"{BLOQUE_TITULO}\", con estos temas:\n\n"
        f"{lista_temas}\n\n"
        f"{contexto_norma}"
        f"{contexto_articulos}"
        f"Lee este fragmento de texto legal y responde ÚNICAMENTE con el número del tema (1-{len(TEMAS_BLOQUE_1)}) "
        f"con el que más relación tenga, aunque no sea un encaje perfecto. Todo fragmento pertenece a algún "
        f"tema del bloque, así que elige siempre el más cercano. Responde solo el número.\n\n"
        f"FRAGMENTO:\n{texto_subbloque[:3000]}"
    )
    for _ in range(2):
        respuesta = call_deepseek_api(messages=[{"role": "user", "content": prompt}], temperature=0, max_tokens=10)
        if respuesta:
            m = re.search(r"\d+", respuesta)
            if m:
                num = int(m.group())
                if 1 <= num <= len(TEMAS_BLOQUE_1):
                    return num
    return None


def construir_subbloques_clasificados(paginas, sumario, offset, limite_chunks=None):
    textos_normas = extraer_texto_normas(paginas, sumario, offset)

    tareas = []  # (norma_numero, norma_titulo, texto, rango_articulos)
    for entrada in sumario:
        if entrada["pagina_impresa"] is None:
            continue
        texto_norma = textos_normas.get(entrada["numero"], "")
        if not texto_norma.strip():
            continue
        for sb in dividir_en_subbloques(texto_norma):
            tareas.append((entrada["numero"], entrada["titulo"], sb["texto"], sb["rango_articulos"]))

    if limite_chunks:
        tareas = tareas[:limite_chunks]

    print(f"🧩 {len(tareas)} subbloques a clasificar")

    resultados = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futuros = {
            executor.submit(clasificar_subbloque_auxiliar, texto, norma_titulo, rango): (norma_num, norma_titulo, texto)
            for norma_num, norma_titulo, texto, rango in tareas
        }
        completados = 0
        for futuro in as_completed(futuros):
            norma_num, norma_titulo, texto = futuros[futuro]
            tema_num = futuro.result()
            resultados.append({
                "tema_num": tema_num,
                "norma_numero": norma_num,
                "norma_titulo": norma_titulo,
                "texto": texto,
            })
            completados += 1
            if completados % 25 == 0:
                print(f"   ...clasificados {completados}/{len(tareas)}")

    # Red de seguridad: fragmentos sin clasificar (fallo puntual de red tras
    # los reintentos) se asignan por mayoría de su misma norma, nunca se
    # descartan.
    pendientes = [r for r in resultados if not r["tema_num"]]
    if pendientes:
        votos_por_norma = {}
        for r in resultados:
            if r["tema_num"]:
                votos_por_norma.setdefault(r["norma_numero"], Counter())[r["tema_num"]] += 1
        for r in pendientes:
            votos = votos_por_norma.get(r["norma_numero"])
            r["tema_num"] = votos.most_common(1)[0][0] if votos else 1
        print(f"🔧 {len(pendientes)} fragmentos sin clasificar por la IA se asignaron por mayoría de su misma norma.")

    return resultados


def guardar_preview(resultados, ruta="preview_temario_auxiliar.json"):
    resumen = {}
    for r in resultados:
        clave = f"tema_{r['tema_num']:02d}" if r["tema_num"] else "SIN CLASIFICAR"
        resumen.setdefault(clave, []).append({
            "norma": r["norma_titulo"],
            "primeras_palabras": " ".join(r["texto"].split()[:25]) + "…",
        })
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    print(f"📋 Vista previa guardada en {ruta} — revisa que los 16 temas tengan contenido razonable.")
    for i in range(1, len(TEMAS_BLOQUE_1) + 1):
        clave = f"tema_{i:02d}"
        n = len(resumen.get(clave, []))
        marca = "⚠️  VACÍO" if n == 0 else ""
        print(f"   tema_{i:02d} ({TEMAS_BLOQUE_1[i-1][:50]}): {n} subbloques {marca}")


def subir_a_firestore(resultados, coleccion=COLECCION):
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
    for j, titulo in enumerate(TEMAS_BLOQUE_1, 1):
        tema_id = f"tema_{j:02d}"
        db.collection(coleccion).document(BLOQUE_ID).collection("temas").document(tema_id).set({"titulo": titulo})

    print("🗑️  Borrando subbloques existentes de bloque_01 antes de subir los nuevos...")
    borrados = 0
    for j in range(1, len(TEMAS_BLOQUE_1) + 1):
        tema_id = f"tema_{j:02d}"
        subbloques_ref = db.collection(coleccion).document(BLOQUE_ID).collection("temas") \
            .document(tema_id).collection("subbloques")
        for doc in subbloques_ref.stream():
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
        db.collection(coleccion).document(BLOQUE_ID).collection("temas").document(tema_id) \
          .collection("subbloques").document(sub_id).set({
              "titulo": r["norma_titulo"][:120],
              "texto": r["texto"],
          })
        subidos += 1
    print(f"✅ Subidos {subidos} subbloques a '{coleccion}/{BLOQUE_ID}' (bloque_02 no se ha tocado).")


def main():
    parser = argparse.ArgumentParser(
        description="Cargar el Bloque I (16 temas) de Temario Auxiliar desde el PDF BOE-435."
    )
    parser.add_argument("--pdf", default=PDF_FUENTE, help="Ruta al PDF BOE-435 (por defecto, el del repo)")
    parser.add_argument("--preview", action="store_true", help="Solo clasificar y guardar un informe, sin subir nada")
    parser.add_argument("--subir", action="store_true", help="Clasificar y subir de verdad a Firestore")
    parser.add_argument("--limite", type=int, default=None, help="Procesar solo los N primeros subbloques (pruebas rápidas)")
    args = parser.parse_args()

    if not args.preview and not args.subir:
        print("Indica --preview (para ver una vista previa) o --subir (para subir de verdad).")
        sys.exit(1)

    paginas = extraer_paginas(args.pdf)
    sumario = parsear_sumario(paginas, paginas_sumario=PAGINAS_SUMARIO)
    print(f"📚 {len(sumario)} normas encontradas en el sumario")
    offset = detectar_offset(paginas, sumario)

    resultados = construir_subbloques_clasificados(paginas, sumario, offset, limite_chunks=args.limite)
    guardar_preview(resultados)

    if args.subir:
        subir_a_firestore(resultados)


if __name__ == "__main__":
    main()
