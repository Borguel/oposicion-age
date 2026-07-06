"""
Rellena ÚNICAMENTE los temas vacíos de "Temario AGE" (Bloque IV temas 6-9,
Bloque V completo) a partir del PDF BOE-442 (Normativa para ingreso en el
Cuerpo General Administrativo de la Administración del Estado).

A diferencia de cargar_temario_boe.py (pensado para subir/resubir un
temario entero desde cero, borrando y recreando todos sus subbloques), este
script es deliberadamente ADITIVO: el resto de "Temario AGE" (Bloques I-III
y los temas 1-5 del Bloque IV) ya lo subió el usuario a mano y NO se debe
tocar. Si algún fragmento se clasifica en un tema que no está en la lista
de vacíos (TEMAS_VACIOS), se descarta en vez de subirse -- nunca se borra
ni se sobrescribe nada ya existente.

USO:
  # 1) Vista previa (no escribe nada en Firestore, guarda un informe en JSON):
  python completar_temario_age.py --pdf "BOE-442_...pdf" --preview

  # 2) Revisa preview_temario_age.json, y si está bien, sube de verdad:
  python completar_temario_age.py --pdf "BOE-442_...pdf" --subir

Variables de entorno necesarias:
  DEEPSEEK_API_KEY
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)
"""
import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

from cargar_temario_boe import (
    extraer_paginas,
    parsear_sumario,
    detectar_offset,
    extraer_texto_normas,
    dividir_en_subbloques,
)
from deepseek_utils import call_deepseek_api

# Solo se definen los bloques que se van a tocar, con los títulos EXACTOS
# ya guardados en Firestore (confirmados por el usuario) -- así nunca se
# crea un bloque/tema con un nombre distinto al que ya existe.
TEMARIO_AGE = {
    4: {
        "titulo": "Gestión de personal",
        "temas": [
            "El personal al servicio de las Administraciones públicas.",
            "Selección de personal.",
            "El personal funcionario al servicio de las Administraciones públicas.",
            "Adquisición y pérdida de la condición de funcionario.",
            "Provisión de puestos de trabajo en la función pública.",
            "Las incompatibilidades. Régimen disciplinario: faltas, sanciones y procedimiento.",
            "El régimen de la Seguridad Social de los funcionarios.",
            "El personal laboral al servicio de las Administraciones públicas.",
            "El régimen de la Seguridad Social del personal laboral.",
        ],
    },
    5: {
        "titulo": "Gestión financiera",
        "temas": [
            "El presupuesto.",
            "El presupuesto del Estado en España.",
            "El procedimiento administrativo de ejecución del presupuesto de gasto.",
            "Las retribuciones e indemnizaciones de los funcionarios públicos y del personal laboral al servicio de la Administración pública.",
            "Gastos para la compra de bienes y servicios.",
            "Gestión económica y financiera de los contratos del sector público.",
        ],
    },
}

# Secciones romanas del sumario de este PDF concreto (BOE-442) que
# corresponden a los bloques de arriba -- confirmado leyendo el propio PDF:
# "V. GESTIÓN DE PERSONAL" -> Bloque 4, "VI. GESTIÓN FINANCIERA" -> Bloque 5.
# Cualquier otra sección (I-IV) se ignora: ya está completa en Firestore.
SECCION_A_BLOQUE = {"V": 4, "VI": 5}

# Únicos (bloque, tema) donde de verdad hace falta contenido. Todo lo demás
# de "Temario AGE" ya está subido a mano y jamás se toca.
TEMAS_VACIOS = {
    (4, 6), (4, 7), (4, 8), (4, 9),
    (5, 1), (5, 2), (5, 3), (5, 4), (5, 5), (5, 6),
}


def clasificar_subbloque_age(texto_subbloque, bloque_num, norma_titulo=None, rango_articulos=None):
    """Igual que clasificar_subbloque de cargar_temario_boe.py, pero usando
    los temas de TEMARIO_AGE (los de GACE no aplican aquí)."""
    temas = TEMARIO_AGE[bloque_num]["temas"]
    lista_temas = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(temas))
    contexto_norma = f"Este fragmento pertenece a la norma: \"{norma_titulo}\".\n\n" if norma_titulo else ""
    contexto_articulos = (
        f"Este fragmento corresponde a los artículos {rango_articulos} de la norma.\n\n" if rango_articulos else ""
    )
    prompt = (
        f"Perteneces a un sistema que clasifica fragmentos de leyes españolas dentro del temario "
        f"oficial de una oposición. El bloque es \"{TEMARIO_AGE[bloque_num]['titulo']}\", con estos temas:\n\n"
        f"{lista_temas}\n\n"
        f"{contexto_norma}"
        f"{contexto_articulos}"
        f"Lee este fragmento de texto legal y responde ÚNICAMENTE con el número del tema (1-{len(temas)}) "
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
                if 1 <= num <= len(temas):
                    return num
    return None


def construir_subbloques_clasificados(paginas, sumario, offset, limite_chunks=None):
    textos_normas = extraer_texto_normas(paginas, sumario, offset)

    tareas = []  # (bloque_num, norma_numero, norma_titulo, indice, texto, rango_articulos)
    for entrada in sumario:
        bloque_num = SECCION_A_BLOQUE.get(entrada["seccion_romana"])
        if not bloque_num:
            continue
        texto_norma = textos_normas.get(entrada["numero"], "")
        if not texto_norma.strip():
            continue
        subbloques = dividir_en_subbloques(texto_norma)
        for i, sb in enumerate(subbloques):
            tareas.append((bloque_num, entrada["numero"], entrada["titulo"], i, sb["texto"], sb["rango_articulos"]))

    if limite_chunks:
        tareas = tareas[:limite_chunks]

    print(f"🧩 {len(tareas)} subbloques a clasificar (bloques: {sorted(set(t[0] for t in tareas))})")

    resultados = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futuros = {
            executor.submit(clasificar_subbloque_age, texto, bloque_num, norma_titulo, rango): (bloque_num, norma_num, norma_titulo, texto)
            for bloque_num, norma_num, norma_titulo, i, texto, rango in tareas
        }
        completados = 0
        for futuro in as_completed(futuros):
            bloque_num, norma_num, norma_titulo, texto = futuros[futuro]
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

    pendientes = [r for r in resultados if not r["tema_num"]]
    if pendientes:
        votos_por_norma = {}
        for r in resultados:
            if r["tema_num"]:
                votos_por_norma.setdefault(r["norma_numero"], Counter())[r["tema_num"]] += 1
        for r in pendientes:
            votos = votos_por_norma.get(r["norma_numero"])
            r["tema_num"] = votos.most_common(1)[0][0] if votos else None
        print(f"🔧 {len(pendientes)} fragmentos sin clasificar por la IA se asignaron por mayoría de su misma norma.")

    return resultados


def guardar_preview(resultados, ruta="preview_temario_age.json"):
    resumen = {}
    descartados = 0
    for r in resultados:
        clave_tema = (r["bloque_num"], r["tema_num"]) if r["tema_num"] else None
        if clave_tema not in TEMAS_VACIOS:
            descartados += 1
            continue
        clave = f"bloque_{r['bloque_num']:02d} / tema_{r['tema_num']:02d}"
        resumen.setdefault(clave, []).append({
            "norma": r["norma_titulo"],
            "primeras_palabras": " ".join(r["texto"].split()[:25]) + "…",
        })
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    print(f"📋 Vista previa guardada en {ruta} — ábrelo y revisa que los 10 temas vacíos queden con contenido razonable.")
    print(f"⚠️  {descartados} fragmentos descartados (cayeron en un tema que ya tiene contenido, fuera de TEMAS_VACIOS).")


def subir_a_firestore(resultados, coleccion="Temario AGE"):
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

    # Se cuenta cuántos subbloques ya existen en cada tema vacío para
    # continuar la numeración sin pisar ninguno -- en la práctica deberían
    # ser 0 (por eso están en TEMAS_VACIOS), pero se comprueba en vez de
    # asumirlo. Deliberadamente NO se borra nada en ningún momento.
    contadores = {}
    for bloque_num, tema_num in TEMAS_VACIOS:
        bloque_id = f"bloque_{bloque_num:02d}"
        tema_id = f"tema_{tema_num:02d}"
        existentes = list(
            db.collection(coleccion).document(bloque_id).collection("temas")
              .document(tema_id).collection("subbloques").stream()
        )
        contadores[(bloque_num, tema_num)] = len(existentes)
        if existentes:
            print(f"⚠️  {bloque_id}/{tema_id} ya tenía {len(existentes)} subbloques -- se numera a continuación, no se borra nada.")

    subidos = 0
    descartados = 0
    for r in resultados:
        clave = (r["bloque_num"], r["tema_num"]) if r["tema_num"] else None
        if clave not in TEMAS_VACIOS:
            descartados += 1
            continue
        contadores[clave] += 1
        sub_id = f"sub_div_{contadores[clave]:03d}"
        bloque_id = f"bloque_{r['bloque_num']:02d}"
        tema_id = f"tema_{r['tema_num']:02d}"
        db.collection(coleccion).document(bloque_id).collection("temas").document(tema_id) \
          .collection("subbloques").document(sub_id).set({
              "titulo": r["norma_titulo"][:120],
              "texto": r["texto"],
          })
        subidos += 1
    print(f"✅ Subidos {subidos} subbloques nuevos a '{coleccion}' (ningún subbloque existente fue tocado ni borrado).")
    print(f"⚠️  {descartados} fragmentos descartados (fuera de los temas vacíos).")


def main():
    parser = argparse.ArgumentParser(
        description="Rellena los temas vacíos de Temario AGE (Bloque IV temas 6-9 y Bloque V completo) desde el PDF BOE-442."
    )
    parser.add_argument("--pdf", required=True, help="Ruta al PDF BOE-442")
    parser.add_argument("--coleccion", default="Temario AGE")
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
