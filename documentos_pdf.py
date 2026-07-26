"""Librería de documentos subidos por el usuario ("Mis documentos"): agrupa
en una sola entidad todo el contenido de IA generado (resumen, esquema,
tarjetas, test) a partir de un mismo PDF, para poder repasarlo más tarde sin
tener que volver a subir el archivo ni volver a generarlo.

Un "documento" vive en usuarios/{uid}/documentos/{id} y es solo metadatos +
el texto extraído (para poder generar más contenido desde él sin re-subir el
PDF). El contenido en sí (resumen/esquema/tarjetas/test) se sigue guardando
en las subcolecciones ya existentes (resumenes_pdf, esquemas_pdf, etc.),
cada entrada etiquetada con su documento_id."""
import hashlib
from datetime import datetime

# Se guarda un extracto generoso del texto (bastante más que en el chat con
# PDF, donde se reenvía en cada mensaje y sí conviene recortarlo mucho): aquí
# solo se usa para volver a generar contenido más tarde sin re-subir el PDF,
# así que interesa mantener la misma calidad de origen que una subida nueva,
# sin disparar el tamaño del documento en Firestore (bien dentro del límite
# de 1 MB por documento).
MAX_CARACTERES_DOCUMENTO = 150000


def _hash_texto(texto):
    return hashlib.sha256(texto.encode("utf-8", "ignore")).hexdigest()


def extraer_titulo(texto, nombre_archivo):
    """Heurística barata (sin gastar IA) para sacar un título legible: la
    primera línea del documento que parezca un título de verdad, o si no,
    el nombre de archivo limpiado."""
    for linea in (texto or "").splitlines():
        linea = linea.strip()
        if 8 <= len(linea) <= 120 and any(c.isalpha() for c in linea):
            return linea
    base = (nombre_archivo or "documento.pdf").rsplit(".", 1)[0]
    limpio = base.replace("_", " ").replace("-", " ").strip()
    return limpio[:1].upper() + limpio[1:] if limpio else "Documento sin título"


def obtener_o_crear_documento(db, uid, texto, nombre_archivo, num_paginas):
    """Si el usuario ya había subido este mismo documento antes (mismo
    texto), reutiliza esa entrada en vez de crear una duplicada -- así, si
    sube el mismo PDF a dos herramientas distintas, todo queda agrupado bajo
    un único documento en su biblioteca."""
    hash_texto = _hash_texto(texto)
    docs_ref = db.collection("usuarios").document(uid).collection("documentos")
    existentes = list(docs_ref.where("hash_texto", "==", hash_texto).limit(1).stream())
    if existentes:
        return existentes[0].id, existentes[0].to_dict()

    datos = {
        "titulo": extraer_titulo(texto, nombre_archivo),
        "nombre_archivo": nombre_archivo,
        "fecha_subida": datetime.utcnow().isoformat(),
        "num_paginas": num_paginas,
        "texto": texto[:MAX_CARACTERES_DOCUMENTO],
        "hash_texto": hash_texto,
        "carpeta": "",
        "tiene_resumen": False,
        "tiene_esquema": False,
        "num_tarjetas": 0,
        "num_tests": 0,
        "ultima_actividad": datetime.utcnow().isoformat(),
    }
    nuevo_ref = docs_ref.document()
    nuevo_ref.set(datos)
    # Se suma aquí, no en las rutas /guardar-*-pdf: este punto solo se
    # alcanza una vez por documento realmente nuevo (el "if existentes"
    # de arriba evita pasar por aquí si el usuario reutiliza el mismo PDF
    # en varias herramientas), así que las páginas no se cuentan varias
    # veces por un mismo archivo.
    from firebase_admin import firestore
    db.collection("usuarios").document(uid).update({
        "paginas_analizadas": firestore.Increment(num_paginas),
    })
    return nuevo_ref.id, datos


def obtener_preguntas_previas(db, uid, documento_id, limite=60):
    """Preguntas (con su respuesta correcta) de tests ANTERIORES ya
    generados para este mismo documento (colección tests_pdf, ver
    guardar_resultado.py) -- se usan para que una nueva generación desde
    la biblioteca ("generar test" otra vez sobre el mismo documento) no
    repita el mismo dato ya preguntado, aunque lo redacte con otras
    palabras (ver test_generator.py, preguntas_a_evitar). Sin esto, cada
    generación parte de cero: la deduplicación existente (fragmentar el
    documento por lote, relleno de huecos evitando "lo ya cubierto en
    este test") solo actúa DENTRO de una misma llamada, así que dos tests
    sucesivos del mismo PDF podían acabar compartiendo preguntas."""
    if not documento_id:
        return []
    docs = (
        db.collection("usuarios").document(uid).collection("tests_pdf")
        .where("documento_id", "==", documento_id)
        .stream()
    )
    formateadas = []
    for doc in docs:
        for p in (doc.to_dict() or {}).get("preguntas", []):
            texto = (p or {}).get("pregunta")
            if not texto:
                continue
            opciones = (p or {}).get("opciones") or {}
            letra = str((p or {}).get("respuesta_correcta", "")).upper()
            respuesta = opciones.get(letra, "")
            formateadas.append(f"{texto} (respuesta: {respuesta})" if respuesta else str(texto))
    return formateadas[:limite]


def obtener_documento(db, uid, documento_id):
    doc = db.collection("usuarios").document(uid).collection("documentos").document(documento_id).get()
    if not doc.exists:
        return None
    datos = doc.to_dict()
    datos["id"] = doc.id
    return datos


def obtener_tests_en_progreso_por_documento(db, uid):
    """{documento_id: test_id} de los tests desde PDF que quedaron
    "en_progreso" (autoguardados sin terminar, ver rutas_progreso.py
    autosave_test) -- para que "Mis documentos" pueda ofrecer "Continuar"
    en vez de solo "Ver"/"Generar más" (que antes solo aparecían cuando ya
    había al menos un test FINALIZADO, ver marcar_generado/num_tests: un
    test empezado y no acabado no incrementa num_tests, así que no tenía
    ninguna forma de retomarse desde la biblioteca). Si un documento tiene
    más de un test en_progreso a la vez, se queda con el más reciente."""
    docs = (
        db.collection("usuarios").document(uid).collection("tests")
        .where("estado", "==", "en_progreso")
        .stream()
    )
    por_documento = {}
    for doc in docs:
        datos = doc.to_dict() or {}
        if datos.get("tipo") != "test_pdf":
            continue
        documento_id = datos.get("documento_id")
        if not documento_id:
            continue
        fecha = datos.get("fecha") or ""
        actual = por_documento.get(documento_id)
        if not actual or fecha > actual[1]:
            por_documento[documento_id] = (doc.id, fecha)
    return {documento_id: test_id for documento_id, (test_id, _fecha) in por_documento.items()}


def marcar_generado(db, uid, documento_id, tipo, num_tarjetas_nuevas=0):
    """Actualiza los indicadores del documento tras guardar contenido nuevo
    generado a partir de él (se llama desde las rutas /guardar-*-pdf)."""
    ref = db.collection("usuarios").document(uid).collection("documentos").document(documento_id)
    actualizacion = {"ultima_actividad": datetime.utcnow().isoformat()}
    if tipo == "resumen_pdf":
        actualizacion["tiene_resumen"] = True
    elif tipo == "esquema_pdf":
        actualizacion["tiene_esquema"] = True
    elif tipo == "tarjetas_pdf":
        from firebase_admin import firestore
        actualizacion["num_tarjetas"] = firestore.Increment(num_tarjetas_nuevas)
    elif tipo == "test_pdf":
        from firebase_admin import firestore
        actualizacion["num_tests"] = firestore.Increment(1)
    ref.update(actualizacion)


def listar_documentos(db, uid):
    docs_ref = db.collection("usuarios").document(uid).collection("documentos")
    resultado = []
    for doc in docs_ref.stream():
        datos = doc.to_dict()
        resultado.append({
            "id": doc.id,
            "titulo": datos.get("titulo"),
            "nombre_archivo": datos.get("nombre_archivo"),
            "fecha_subida": datos.get("fecha_subida"),
            "num_paginas": datos.get("num_paginas"),
            "carpeta": datos.get("carpeta", ""),
            "tiene_resumen": datos.get("tiene_resumen", False),
            "tiene_esquema": datos.get("tiene_esquema", False),
            "num_tarjetas": datos.get("num_tarjetas", 0),
            "num_tests": datos.get("num_tests", 0),
            "ultima_actividad": datos.get("ultima_actividad"),
        })
    resultado.sort(key=lambda d: d.get("ultima_actividad") or "", reverse=True)
    return resultado


def actualizar_carpeta(db, uid, documento_id, carpeta):
    ref = db.collection("usuarios").document(uid).collection("documentos").document(documento_id)
    if not ref.get().exists:
        return False
    ref.update({"carpeta": (carpeta or "").strip()[:60]})
    return True


def actualizar_titulo(db, uid, documento_id, titulo):
    """Deja que el usuario le ponga a un documento un nombre distinto del
    que se extrajo automáticamente al subirlo (ver extraer_titulo)."""
    ref = db.collection("usuarios").document(uid).collection("documentos").document(documento_id)
    if not ref.get().exists:
        return False
    titulo = (titulo or "").strip()[:120]
    if not titulo:
        return False
    ref.update({"titulo": titulo})
    return True


def listar_carpetas(db, uid):
    """Catálogo de carpetas del usuario: las creadas explícitamente con
    crear_carpeta() más cualquier nombre que ya tuviera asignado algún
    documento antes de que existiera este catálogo (para no perder carpetas
    de usuarios que ya las usaban con el sistema anterior)."""
    usuario = db.collection("usuarios").document(uid).get().to_dict() or {}
    explicitas = set(usuario.get("carpetas_documentos") or [])
    de_documentos = {
        (doc.to_dict() or {}).get("carpeta")
        for doc in db.collection("usuarios").document(uid).collection("documentos").stream()
    }
    de_documentos.discard("")
    de_documentos.discard(None)
    return sorted(explicitas | de_documentos)


def crear_carpeta(db, uid, nombre):
    nombre = (nombre or "").strip()[:60]
    if not nombre:
        return None
    from firebase_admin import firestore
    db.collection("usuarios").document(uid).update({
        "carpetas_documentos": firestore.ArrayUnion([nombre])
    })
    return nombre


def eliminar_carpeta(db, uid, nombre):
    """Borra la carpeta del catálogo y deja "sin carpeta" a los documentos
    que estuvieran dentro, en vez de borrarlos."""
    from firebase_admin import firestore
    nombre = (nombre or "").strip()
    if not nombre:
        return
    docs_ref = db.collection("usuarios").document(uid).collection("documentos")
    for doc in docs_ref.where("carpeta", "==", nombre).stream():
        doc.reference.update({"carpeta": ""})
    db.collection("usuarios").document(uid).update({
        "carpetas_documentos": firestore.ArrayRemove([nombre])
    })
