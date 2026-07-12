"""
Sustituye el Bloque de informática básica y ofimática (8 temas) de Temario
AGE (bloque_06, C1) y Temario Auxiliar (bloque_02, temas 5-12, C2) por
contenido generado desde cero con DeepSeek a partir ÚNICAMENTE de los
títulos/subtítulos (epígrafes) de los 8 PDF originales de Persevera
Oposiciones -- nunca desde su texto de desarrollo, que no tenía licencia
confirmada para usarse en esta plataforma.

GACE (A2) no tiene bloque de ofimática en su temario: este script no lo
toca ni lo referencia en ningún paso.

El contenido se genera UNA sola vez por tema (8 llamadas a DeepSeek en
total, no 16) y el mismo texto se sube a los dos cuerpos que comparten
este bloque -- decisión tomada con el usuario: duplicar el texto en vez de
crear referencias cruzadas, porque el coste real a minimizar es el de
tokens de DeepSeek (el de almacenamiento en Firestore es insignificante) y
una arquitectura de punteros obligaría a tocar los ~6 sitios del código
que leen subbloques directamente (utils.py, blueprints/temario.py,
blueprints/pdf_ia.py, rutas_progreso.py, gestion_cuenta.py...).

PASOS (cada uno se dispara por separado y a mano):

  1) --paso0
     Extrae SOLO el índice (títulos de epígrafe + numeración de
     subtítulos, tal como aparecen en la página de índice de cada PDF,
     ANTES del texto de desarrollo) de los 8 PDF de Persevera. Guarda el
     resultado en indices-ofimatica.json y lo imprime en consola. No toca
     Firestore. No borra nada todavía.

  2) --paso1 --preview / --subir
     Borra de "Temario Auxiliar"/bloque_02 los subbloques existentes de
     los temas 5 a 12 (el contenido Persevera a reemplazar). No toca los
     temas 1-4 (Atención al público, etc. -- fuera del alcance de esta
     tarea) ni GACE.

  3) --generar --preview
     Para cada uno de los 8 temas, UNA llamada a DeepSeek usando solo el
     índice de indices-ofimatica.json (nunca el texto original). Guarda el
     resultado en contenido-generado-ofimatica.json (cache, para no
     volver a llamar a DeepSeek en el paso --subir) e imprime en consola
     un resumen de tokens usados. No toca Firestore.

  3b) --generar --subir
     Reutiliza contenido-generado-ofimatica.json (si ya existe, no vuelve
     a llamar a DeepSeek) y sube el mismo texto a Temario AGE/bloque_06
     (temas 1-8) y Temario Auxiliar/bloque_02 (temas 5-12).

Tras confirmar --paso0, borra a mano (git rm) los 8 PDF de Persevera del
repo -- no lo hace este script porque es una operación de control de
versiones, no de datos.

Variables de entorno necesarias:
  DEEPSEEK_API_KEY (para --generar)
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON) (para --paso1/--generar --subir)
"""
import argparse
import json
import os
import re
import sys

from PyPDF2 import PdfReader

from cargar_temario_auxiliar_bloque2 import (
    _limpiar_pagina, PATRON_EPIGRAFE, dividir_en_subbloques_por_epigrafe, _estimar_tokens,
)
from deepseek_utils import generar_con_continuacion

INDICES_JSON = "indices-ofimatica.json"
GENERADO_JSON = "contenido-generado-ofimatica.json"

# Los 8 temas de informática básica y ofimática, en orden, tal como
# aparecen numerados en los PDF de Persevera (05-12) -- y su
# correspondencia exacta con los temas ya existentes (con título propio,
# distinto en cada cuerpo) en Temario AGE/bloque_06 y Temario
# Auxiliar/bloque_02. GACE no tiene equivalente y no aparece aquí.
MAPEO_TEMAS = [
    {"pdf_prefijo": "05", "age_tema": "tema_01", "aux_tema": "tema_05", "titulo_generico": "Informática básica"},
    {"pdf_prefijo": "06", "age_tema": "tema_02", "aux_tema": "tema_06", "titulo_generico": "El entorno Windows / sistema operativo"},
    {"pdf_prefijo": "07", "age_tema": "tema_03", "aux_tema": "tema_07", "titulo_generico": "El Explorador de Windows"},
    {"pdf_prefijo": "08", "age_tema": "tema_04", "aux_tema": "tema_08", "titulo_generico": "Procesadores de texto: Word 365"},
    {"pdf_prefijo": "09", "age_tema": "tema_05", "aux_tema": "tema_09", "titulo_generico": "Hojas de cálculo: Excel 365"},
    {"pdf_prefijo": "10", "age_tema": "tema_06", "aux_tema": "tema_10", "titulo_generico": "Bases de datos: Access 365"},
    {"pdf_prefijo": "11", "age_tema": "tema_07", "aux_tema": "tema_11", "titulo_generico": "Correo electrónico: Outlook 365"},
    {"pdf_prefijo": "12", "age_tema": "tema_08", "aux_tema": "tema_12", "titulo_generico": "Internet y navegadores web"},
]

AGE_COLECCION = "Temario AGE"
AGE_BLOQUE = "bloque_06"
AUX_COLECCION = "Temario Auxiliar"
AUX_BLOQUE = "bloque_02"

SYSTEM_PROMPT = (
    "Eres un redactor de temario de oposiciones españolas para el Cuerpo General "
    "de la Administración del Estado (aplicable a Auxiliar C2 y Administrativo C1, "
    "que comparten este mismo bloque de informática y ofimática). Se te da "
    "ÚNICAMENTE una lista de títulos y subtítulos de un tema. Escribe el contenido "
    "completo desde cero, sin haber visto texto previo de desarrollo. Formato "
    "requerido:\n"
    "- Usa como cabecera literal de cada sección \"Epígrafe N — <título>\" (igual "
    "que en la lista que se te da), seguido del desarrollo de esa sección.\n"
    "- Tablas comparativas cuando aplique\n"
    "- Recuadro 'MATIZ' señalando confusiones típicas de examen tipo test\n"
    "- Recuadro 'RECUERDA' con mnemotecnias\n"
    "- Versiones, fechas y cifras concretas y verificables\n"
    "- Nivel alto, orientado a examen tipo test de oposición"
)


def _localizar_pdf(prefijo, carpeta="."):
    for nombre in os.listdir(carpeta):
        if nombre.startswith(f"{prefijo} -") and nombre.lower().endswith(".pdf"):
            return os.path.join(carpeta, nombre)
    return None


def _extraer_texto_limpio(ruta_pdf):
    reader = PdfReader(ruta_pdf)
    paginas = [p.extract_text() or "" for p in reader.pages]
    n = len(paginas)
    bruto = "\n".join(paginas[2:n - 2])
    return _limpiar_pagina(bruto), n


def _separar_pagina(linea, total_paginas):
    """La maquetación en 2 columnas del PDF hace que, en la página de
    índice, el número de página de cada entrada quede pegado sin espacio
    al final del texto (p. ej. 'Windows 1113' = título '...Windows 11' +
    página 13). No se puede asumir un nº fijo de dígitos de página: prueba
    desde el sufijo más largo posible hacia el más corto, aceptando el
    primero que sea una página plausible (<= total de páginas del propio
    PDF) -- así no corta dígitos que en realidad son parte del título
    (versiones, cifras: 'Windows 11', '365', etc.)."""
    m = re.search(r"(\d+)\s*$", linea)
    if not m:
        return linea.strip(), None
    digitos = m.group(1)
    inicio_digitos = m.start(1)
    for longitud in range(len(digitos), 0, -1):
        candidato = digitos[-longitud:]
        if 1 <= int(candidato) <= total_paginas:
            resto = linea[:inicio_digitos + len(digitos) - longitud].rstrip()
            return resto, int(candidato)
    return linea.strip(), None


def _extraer_indice(texto_limpio, total_paginas):
    """El PDF repite 'Epígrafe 1 —' dos veces: la 1ª como entrada de la
    página de índice, la 2ª como cabecera real del desarrollo (verificado:
    las 8 PDF de ofimática tienen exactamente 2 ocurrencias). Todo lo que
    hay ENTRE esas dos ocurrencias es la página de índice completa (todos
    los epígrafes con su numeración de subtítulos), con el número de
    página de cada entrada pegado al final de la línea."""
    # Localiza específicamente las ocurrencias de "Epígrafe 1 —" (no de
    # cualquier epígrafe) para acotar el rango índice/desarrollo.
    epi1 = list(re.finditer(r"Ep[ií]grafe\s+1\s*[—-]\s*", texto_limpio))
    if len(epi1) < 2:
        raise RuntimeError("No se encontraron las 2 ocurrencias esperadas de 'Epígrafe 1' (índice + desarrollo).")
    indice_texto = texto_limpio[epi1[0].start():epi1[-1].start()]

    epigrafes = []
    matches = list(PATRON_EPIGRAFE.finditer(indice_texto))
    for idx, m in enumerate(matches):
        numero = int(m.group(1))
        fin = matches[idx + 1].start() if idx + 1 < len(matches) else len(indice_texto)
        chunk = indice_texto[m.end():fin]
        lineas = [l.strip() for l in chunk.split("\n") if l.strip()]

        i = 0
        titulo_lineas = []
        while i < len(lineas) and not re.match(r"^\d+\.\s", lineas[i]):
            titulo_lineas.append(lineas[i])
            i += 1
        titulo, _ = _separar_pagina(" ".join(titulo_lineas), total_paginas)

        subtitulos = []
        for linea in lineas[i:]:
            mm = re.match(r"^\d+\.\s*(.+)$", linea)
            texto_subtitulo = mm.group(1) if mm else linea
            texto_subtitulo, _ = _separar_pagina(texto_subtitulo, total_paginas)
            subtitulos.append(texto_subtitulo)

        epigrafes.append({"numero": numero, "titulo": titulo, "subtitulos": subtitulos})
    return epigrafes


def paso0():
    resultado = {}
    for entrada in MAPEO_TEMAS:
        ruta = _localizar_pdf(entrada["pdf_prefijo"])
        if not ruta:
            print(f"⚠️  No se encontró el PDF con prefijo '{entrada['pdf_prefijo']}'.")
            continue
        print(f"📄 {ruta}")
        texto_limpio, total_paginas = _extraer_texto_limpio(ruta)
        epigrafes = _extraer_indice(texto_limpio, total_paginas)
        resultado[entrada["age_tema"]] = {
            "titulo_generico": entrada["titulo_generico"],
            "age_tema": entrada["age_tema"],
            "aux_tema": entrada["aux_tema"],
            "epigrafes": epigrafes,
        }
        print(f"   {len(epigrafes)} epígrafes:")
        for epi in epigrafes:
            print(f"   - Epígrafe {epi['numero']} — {epi['titulo']}")
            for st in epi["subtitulos"]:
                print(f"       · {st}")

    with open(INDICES_JSON, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    print(f"\n📋 Índices guardados en {INDICES_JSON} ({len(resultado)} temas).")
    print("Revisa la lista de arriba. Si está bien, borra a mano (git rm) los 8 PDF de Persevera y continúa con --paso1.")


def _formatear_indice_para_prompt(entrada):
    lineas = [f"Tema: {entrada['titulo_generico']}", ""]
    for epi in entrada["epigrafes"]:
        lineas.append(f"Epígrafe {epi['numero']} — {epi['titulo']}")
        for st in epi["subtitulos"]:
            lineas.append(f"  {st}")
    return "\n".join(lineas)


def generar(solo_preview):
    if not os.path.exists(INDICES_JSON):
        print(f"⚠️  No existe {INDICES_JSON}. Ejecuta antes --paso0.")
        sys.exit(1)
    with open(INDICES_JSON, encoding="utf-8") as f:
        indices = json.load(f)

    generado = {}
    if os.path.exists(GENERADO_JSON):
        with open(GENERADO_JSON, encoding="utf-8") as f:
            generado = json.load(f)

    total_tokens_entrada = 0
    total_tokens_salida = 0

    for age_tema, entrada in indices.items():
        if age_tema in generado:
            print(f"⏭️  {age_tema} ({entrada['titulo_generico']}): ya generado en caché, no se vuelve a llamar a DeepSeek.")
            continue
        mensaje = _formatear_indice_para_prompt(entrada)
        print(f"🧠 Generando {age_tema} ({entrada['titulo_generico']}) con DeepSeek...")
        texto = generar_con_continuacion(SYSTEM_PROMPT, mensaje, max_tokens=4096, temperature=0.3, max_continuaciones=3)
        if not texto:
            print(f"❌ DeepSeek no devolvió contenido para {age_tema}.")
            continue
        tokens_entrada = _estimar_tokens(SYSTEM_PROMPT + mensaje)
        tokens_salida = _estimar_tokens(texto)
        total_tokens_entrada += tokens_entrada
        total_tokens_salida += tokens_salida
        generado[age_tema] = {
            "titulo_generico": entrada["titulo_generico"],
            "age_tema": entrada["age_tema"],
            "aux_tema": entrada["aux_tema"],
            "texto": texto,
            "tokens_entrada_aprox": tokens_entrada,
            "tokens_salida_aprox": tokens_salida,
        }
        print(f"   ✅ {tokens_salida} tokens aprox. generados.")
        with open(GENERADO_JSON, "w", encoding="utf-8") as f:
            json.dump(generado, f, ensure_ascii=False, indent=2)

    print(f"\n📊 {len(generado)}/8 temas generados en total (cache: {GENERADO_JSON}).")
    if total_tokens_entrada or total_tokens_salida:
        print(f"   Esta ejecución: ~{total_tokens_entrada} tokens de entrada, ~{total_tokens_salida} tokens de salida.")

    if not solo_preview:
        subir_generado(generado)


def mostrar(num_caracteres):
    if not os.path.exists(GENERADO_JSON):
        print(f"⚠️  No existe {GENERADO_JSON}. Ejecuta antes --generar --preview.")
        sys.exit(1)
    with open(GENERADO_JSON, encoding="utf-8") as f:
        generado = json.load(f)
    for age_tema in sorted(generado):
        datos = generado[age_tema]
        print(f"\n{'=' * 70}\n{age_tema} ({datos['titulo_generico']}) -- {datos.get('tokens_salida_aprox', '?')} tokens aprox.\n{'=' * 70}")
        print(datos["texto"][:num_caracteres])
        if len(datos["texto"]) > num_caracteres:
            print(f"\n   […truncado, {len(datos['texto'])} caracteres en total…]")


def subir_generado(generado):
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

    for age_tema, datos in generado.items():
        subbloques = dividir_en_subbloques_por_epigrafe(datos["texto"])
        for coleccion, bloque_id, tema_id in (
            (AGE_COLECCION, AGE_BLOQUE, datos["age_tema"]),
            (AUX_COLECCION, AUX_BLOQUE, datos["aux_tema"]),
        ):
            subbloques_ref = (
                db.collection(coleccion).document(bloque_id).collection("temas")
                  .document(tema_id).collection("subbloques")
            )
            existentes = list(subbloques_ref.stream())
            for doc in existentes:
                doc.reference.delete()
            for j, sb in enumerate(subbloques, 1):
                titulo_sb = f"Epígrafe {sb['epigrafes']}" if sb["epigrafes"] else datos["titulo_generico"]
                subbloques_ref.document(f"sub_div_{j:03d}").set({
                    "titulo": titulo_sb[:120],
                    "texto": sb["texto"],
                })
            print(f"✅ {coleccion}/{bloque_id}/{tema_id}: {len(subbloques)} subbloques subidos (borrados {len(existentes)} anteriores).")

    print(f"\n✅ {len(generado)} temas subidos a Temario AGE/{AGE_BLOQUE} y Temario Auxiliar/{AUX_BLOQUE}. GACE no se ha tocado.")


def paso1(solo_preview):
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

    total = 0
    for entrada in MAPEO_TEMAS:
        tema_id = entrada["aux_tema"]
        subbloques_ref = (
            db.collection(AUX_COLECCION).document(AUX_BLOQUE).collection("temas")
              .document(tema_id).collection("subbloques")
        )
        existentes = list(subbloques_ref.stream())
        print(f"{AUX_COLECCION}/{AUX_BLOQUE}/{tema_id}: {len(existentes)} subbloques existentes (Persevera).")
        total += len(existentes)
        if not solo_preview:
            for doc in existentes:
                doc.reference.delete()

    if solo_preview:
        print(f"\n📋 Vista previa: se borrarían {total} subbloques en total (temas 5-12). No se ha tocado Firestore.")
    else:
        print(f"\n✅ Borrados {total} subbloques en total de {AUX_COLECCION}/{AUX_BLOQUE} (temas 5-12).")
    print("No se ha tocado bloque_02/tema_01-04 ni ninguna colección de GACE.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--paso0", action="store_true")
    parser.add_argument("--paso1", action="store_true")
    parser.add_argument("--generar", action="store_true")
    parser.add_argument("--mostrar", action="store_true", help="Imprime un extracto del contenido ya cacheado, sin llamar a DeepSeek")
    parser.add_argument("--caracteres", type=int, default=1200, help="Caracteres a mostrar por tema con --mostrar")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--subir", action="store_true")
    args = parser.parse_args()

    if args.paso0:
        paso0()
        return

    if args.mostrar:
        mostrar(args.caracteres)
        return

    if args.paso1:
        if not args.preview and not args.subir:
            print("Indica --preview o --subir junto con --paso1.")
            sys.exit(1)
        paso1(solo_preview=args.preview)
        return

    if args.generar:
        if not args.preview and not args.subir:
            print("Indica --preview o --subir junto con --generar.")
            sys.exit(1)
        generar(solo_preview=args.preview)
        return

    print("Indica --paso0, --paso1 (--preview/--subir) o --generar (--preview/--subir).")
    sys.exit(1)


if __name__ == "__main__":
    main()
