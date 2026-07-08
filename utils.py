import random
import tiktoken
from typing import List, Dict

# ✅ Cuenta los tokens de un texto
def contar_tokens(texto: str, modelo="gpt-3.5-turbo") -> int:
    try:
        encoding = tiktoken.encoding_for_model(modelo)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(texto))

# ✅ Agrupa subbloques por tema para prompts largos (estructura anterior, por si la usas aún)
def agrupar_subbloques_por_tema(db, temas: List[str], limite_tokens=3000, coleccion="Temario AGE") -> Dict[str, List[List[dict]]]:
    resultado = {}
    for tema_completo in temas:
        if "-" not in tema_completo:
            continue
        bloque_id, tema_id = tema_completo.split("-", 1)
        subbloques_ref = db.collection(coleccion).document(bloque_id).collection("temas").document(tema_id).collection("subbloques").stream()
        grupo_actual = []
        total_tokens = 0
        todos_grupos = []

        for sub in subbloques_ref:
            datos = sub.to_dict()
            if not datos:
                continue
            texto = datos.get("texto", "").strip()
            titulo = datos.get("titulo", "")
            etiqueta = f"{bloque_id}-{tema_id}-{sub.id}"
            tokens = contar_tokens(texto)

            if tokens > limite_tokens:
                todos_grupos.append([{"etiqueta": etiqueta, "titulo": titulo, "texto": texto}])
                continue

            if total_tokens + tokens > limite_tokens:
                todos_grupos.append(grupo_actual)
                grupo_actual = []
                total_tokens = 0

            grupo_actual.append({"etiqueta": etiqueta, "titulo": titulo, "texto": texto})
            total_tokens += tokens

        if grupo_actual:
            todos_grupos.append(grupo_actual)
        resultado[tema_completo] = todos_grupos
    return resultado

# ✅ Obtiene el contexto completo de varios temas para usarlo en respuestas IA
def obtener_contexto_por_temas(db, temas, token_limit=3000, coleccion="Temario AGE"):
    contexto_total = ""
    usados = set()

    bloques = db.collection(coleccion).list_documents()

    for bloque_doc in bloques:
        temas_ref = bloque_doc.collection("temas")
        for tema in temas:
            tema_doc = temas_ref.document(tema).get()
            if not tema_doc.exists:
                continue
            subbloques_ref = temas_ref.document(tema).collection("subbloques")
            subbloques = subbloques_ref.stream()

            for sub in subbloques:
                sub_id = f"{bloque_doc.id}-{tema}-{sub.id}"
                if sub_id in usados:
                    continue
                usados.add(sub_id)

                texto = sub.to_dict().get("texto", "")
                titulo = sub.to_dict().get("titulo", "")
                fragmento = f"[{sub_id}]\n{titulo}\n{texto.strip()}\n"
                if contar_tokens(contexto_total + fragmento) > token_limit:
                    return contexto_total.strip()
                contexto_total += fragmento

    return contexto_total.strip()

# ✅ Catálogo (bloque + tema, con sus títulos) de una oposición, para poder
# detectar si un mensaje del usuario menciona un tema concreto sin tener
# que descargar el contenido completo del temario.
def obtener_catalogo_temas(db, coleccion="Temario AGE") -> List[dict]:
    catalogo = []
    for bloque in db.collection(coleccion).stream():
        bloque_titulo = (bloque.to_dict() or {}).get("titulo", bloque.id)
        temas_ref = db.collection(coleccion).document(bloque.id).collection("temas").stream()
        for tema in temas_ref:
            titulo = (tema.to_dict() or {}).get("titulo", tema.id)
            catalogo.append({"id": f"{bloque.id}-{tema.id}", "titulo": titulo, "bloque_titulo": bloque_titulo})
    return catalogo

# ✅ Datos oficiales de la convocatoria vigente (plazas, estructura de los
# ejercicios, tiempos, penalización, calificación), transcritos a mano de las
# normas específicas publicadas en el BOE -- para que Tu Tutor no tenga que
# adivinar estas cifras ni inventarlas. Un único documento por oposición en
# la colección "datos_convocatoria", con un campo "texto" ya redactado para
# inyectar tal cual en el prompt (ver cargar_datos_convocatoria.py).
def obtener_datos_convocatoria(db, oposicion):
    doc = db.collection("datos_convocatoria").document(oposicion).get()
    if not doc.exists:
        return None
    return (doc.to_dict() or {}).get("texto")

_NUMEROS_ROMANOS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]

# ✅ Estructura REAL del temario (bloques y temas tal y como están cargados en
# Firestore), en texto listo para inyectar en el prompt de Tu Tutor -- para
# que describa el temario a partir de los datos reales en vez de un resumen
# escrito a mano que puede quedar desactualizado. Se agrupa por bloque y se
# ordena por el id del documento (bloque_01, bloque_02... / tema_01, tema_02...)
# ya que stream() no garantiza ningún orden.
def obtener_resumen_temario(db, coleccion="Temario AGE"):
    bloques = {}
    for bloque in db.collection(coleccion).stream():
        bloque_titulo = (bloque.to_dict() or {}).get("titulo", bloque.id)
        temas = []
        for tema in db.collection(coleccion).document(bloque.id).collection("temas").stream():
            titulo = (tema.to_dict() or {}).get("titulo", tema.id)
            temas.append((tema.id, titulo))
        if not temas:
            continue
        temas.sort(key=lambda t: t[0])
        bloques[bloque.id] = (bloque_titulo, temas)

    if not bloques:
        return None

    lineas = []
    for indice, bloque_id in enumerate(sorted(bloques.keys())):
        bloque_titulo, temas = bloques[bloque_id]
        numero_romano = _NUMEROS_ROMANOS[indice] if indice < len(_NUMEROS_ROMANOS) else str(indice + 1)
        lineas.append(f"Bloque {numero_romano}. {bloque_titulo} ({len(temas)} temas)")
        for numero, (_tema_id, titulo) in enumerate(temas, start=1):
            lineas.append(f"  {numero}. {titulo}")
    return "\n".join(lineas)

# ✅ Contexto de temas identificados por su id combinado "bloque_id-tema_id"
# (a diferencia de obtener_contexto_por_temas, que solo recibe el tema_id y
# por tanto no distingue entre bloques distintos que reutilicen el mismo
# tema_id). La usa el detector de temas mencionados de Tu Tutor.
def obtener_contexto_por_temas_exactos(db, temas_combinados: List[str], token_limit=3000, coleccion="Temario AGE") -> str:
    contexto_total = ""
    for tema_completo in temas_combinados:
        if "-" not in tema_completo:
            continue
        bloque_id, tema_id = tema_completo.split("-", 1)
        subbloques = db.collection(coleccion).document(bloque_id).collection("temas") \
                       .document(tema_id).collection("subbloques").stream()
        for sub in subbloques:
            datos = sub.to_dict() or {}
            texto = datos.get("texto", "").strip()
            titulo = datos.get("titulo", "")
            fragmento = f"[{tema_completo}-{sub.id}]\n{titulo}\n{texto}\n"
            if contar_tokens(contexto_total + fragmento) > token_limit:
                return contexto_total.strip()
            contexto_total += fragmento
    return contexto_total.strip()

    return contexto_total.strip()

# ✅ NUEVA: Extrae todos los subbloques de todos los temas sin límite de tokens acumulados
def obtener_subbloques_individuales(db, temas: List[str], coleccion="Temario AGE") -> List[dict]:
    subbloques_utilizados = []

    for tema_completo in temas:
        if "-" not in tema_completo:
            continue

        bloque_id, tema_id = tema_completo.split("-", 1)
        temas_ref = db.collection(coleccion).document(bloque_id).collection("temas")
        subbloques_ref = temas_ref.document(tema_id).collection("subbloques").stream()

        for sub in subbloques_ref:
            datos = sub.to_dict()
            if not datos:
                continue
            texto = datos.get("texto", "").strip()
            if len(texto.split()) < 30:
                continue
            if contar_tokens(texto) > 3000:
                texto = texto[:4000]  # recorte de seguridad

            subbloques_utilizados.append({
                "etiqueta": f"{bloque_id}-{tema_id}-{sub.id}",
                "titulo": datos.get("titulo", ""),
                "texto": texto
            })

    return subbloques_utilizados


    return contexto_total.strip()


def calcular_resultado_test(aciertos, fallos, blancos):
    """Único criterio de "aprobado/suspendido" de toda la web, replicando
    la tipología oficial de corrección de los exámenes (aciertos menos
    fallos/3, sobre el total de preguntas -- las respuestas en blanco no
    penalizan, pero sí cuentan en el total). Antes existían 3 versiones
    distintas de este cálculo (guardar_resultado.py, resultados-test.js y
    registro_progreso_usuario.py) que no siempre coincidían entre sí."""
    puntuacion = round(aciertos - (fallos / 3), 2)
    total = aciertos + fallos + blancos
    nota_sobre_10 = round((puntuacion / total) * 10, 2) if total else 0.0
    resultado = "aprobado" if nota_sobre_10 >= 5 else "suspendido"
    return puntuacion, nota_sobre_10, resultado


def repartir_cupos_por_tema(temas_ids, cantidad):
    """Reparte 'cantidad' unidades lo más equitativamente posible entre
    temas_ids (división entera + resto). Se baraja el orden antes de asignar
    el resto para que este no recaiga siempre sobre los mismos temas.
    Compartido por la generación del test personalizado (test_generator.py)
    y la selección de preguntas oficiales por tema (ver
    seleccionar_preguntas_con_cuota más abajo), para que elegir varios temas
    reparta el test entre ellos en vez de dejar que gane el que más
    contenido tenga cargado."""
    ids = list(temas_ids)
    if not ids:
        return {}
    random.shuffle(ids)
    base, resto = divmod(cantidad, len(ids))
    return {tid: base + (1 if i < resto else 0) for i, tid in enumerate(ids)}


def seleccionar_preguntas_con_cuota(preguntas, num_preguntas, temas_filtro=None):
    """Selecciona num_preguntas de una lista ya completa de preguntas (cada
    una con su propio campo 'tema_id'), repartiendo en cuotas equitativas
    entre los temas de temas_filtro que sí tengan preguntas disponibles. Si
    temas_filtro es None/vacío, se comporta como el muestreo aleatorio simple
    de siempre (sin tema elegido = sin filtrar). Usado por
    /generar-test-oficial."""
    if not temas_filtro:
        return random.sample(preguntas, min(num_preguntas, len(preguntas)))

    filtro = set(temas_filtro)
    pendientes_por_tema = {}
    for p in preguntas:
        tid = p.get("tema_id")
        if tid in filtro:
            pendientes_por_tema.setdefault(tid, []).append(p)
    for lista in pendientes_por_tema.values():
        random.shuffle(lista)

    seleccionadas = []
    candidatos = list(pendientes_por_tema.keys())
    restante = num_preguntas
    while restante > 0 and candidatos:
        cupos = repartir_cupos_por_tema(candidatos, restante)
        avance = 0
        for tid, cupo in cupos.items():
            tomadas = pendientes_por_tema[tid][:cupo]
            del pendientes_por_tema[tid][:cupo]
            seleccionadas.extend(tomadas)
            avance += len(tomadas)
        restante -= avance
        if avance == 0:
            break
        candidatos = [tid for tid in candidatos if pendientes_por_tema[tid]]

    random.shuffle(seleccionadas)  # no dejar el orden agrupado por tema
    return seleccionadas


def obtener_titulos_temas_reales(db, coleccion, lista_codigos):
    """Traduce códigos "bloque-tema" (p. ej. "bloque_01-tema_02") a sus
    títulos reales guardados en Firestore -- la misma fuente que usa
    /temas-disponibles -- en vez de una lista fija en el código que solo
    cubría los temas de AGE y no servía para el resto de oposiciones."""
    titulos = []
    for codigo in lista_codigos:
        partes = codigo.split("-", 1)
        if len(partes) < 2:
            titulos.append(codigo)
            continue
        bloque_id, tema_id = partes
        doc = db.collection(coleccion).document(bloque_id).collection("temas").document(tema_id).get()
        titulos.append(doc.to_dict().get("titulo", codigo) if doc.exists else codigo)
    return titulos

