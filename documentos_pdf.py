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
        "tiene_resumen": False,
        "tiene_esquema": False,
        "num_tarjetas": 0,
        "num_tests": 0,
        "ultima_actividad": datetime.utcnow().isoformat(),
    }
    nuevo_ref = docs_ref.document()
    nuevo_ref.set(datos)
    return nuevo_ref.id, datos


def obtener_documento(db, uid, documento_id):
    doc = db.collection("usuarios").document(uid).collection("documentos").document(documento_id).get()
    if not doc.exists:
        return None
    datos = doc.to_dict()
    datos["id"] = doc.id
    return datos


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
            "tiene_resumen": datos.get("tiene_resumen", False),
            "tiene_esquema": datos.get("tiene_esquema", False),
            "num_tarjetas": datos.get("num_tarjetas", 0),
            "num_tests": datos.get("num_tests", 0),
            "ultima_actividad": datos.get("ultima_actividad"),
        })
    resultado.sort(key=lambda d: d.get("ultima_actividad") or "", reverse=True)
    return resultado
