"""Vigilancia automática del BOE: dos cosas distintas que comparten la
misma API pública y el mismo ciclo diario (ver blueprints/tareas_programadas.py
-> POST /tareas/vigilar-boe), pero que generan colas de revisión separadas
en el panel de admin -- NUNCA se publica nada solo, el dueño siempre da el
OK desde /admin/ antes de que llegue a un usuario real o al temario:

1. detectar_cambios_leyes_vigiladas: leyes troncales del temario que el BOE
   ha modificado desde la última vez -> propuesta de "elimina este texto,
   añade este otro" en la colección cambios_temario_propuestos (ver
   generador_diff_temario.py para cómo se redacta esa propuesta).
2. detectar_avisos_oficiales: publicaciones del BOE relevantes para AGE,
   GACE o Auxiliar (convocatorias, listas de admitidos/excluidos, fechas de
   examen...) -> aviso en avisos_oficiales.

API usada, sin clave y solo GET (https://www.boe.es/datosabiertos/):
- legislacion-consolidada/id/{id}/metadatos -> fecha_actualizacion de la ley.
- legislacion-consolidada/id/{id}/texto/indice -> lista de bloques (~artículos).
- legislacion-consolidada/id/{id}/texto/bloque/{id_bloque} -> texto de ese
  bloque con su historial de versiones (fecha_publicacion + texto de cada una).
- boe/sumario/{AAAAMMDD} -> sumario diario (para los avisos oficiales).

IMPORTANTE (ver plan de esta entrega): esta API no se ha podido probar en
bruto desde el entorno de desarrollo de este proyecto (proxy que bloquea
boe.es). El formato exacto de la respuesta se ha documentado a partir de la
documentación pública del BOE, no de una llamada real verificada byte a
byte -- por eso _buscar_clave() busca las claves por NOMBRE en cualquier
nivel de anidamiento en vez de asumir una ruta fija, y por eso conviene una
llamada de humo real antes de fiarse del todo en producción."""
import logging
import os
from datetime import datetime

import requests

from oposiciones import OPOSICIONES

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.boe.es/datosabiertos/api"
_TIMEOUT_SEGUNDOS = 15

# Leyes troncales vigiladas para detectar cambios en el temario. Lista
# curada a mano a propósito (no hay forma fiable de deducir automáticamente
# a qué ley de BOE corresponde cada chunk de temario, que solo guarda un
# título libre) -- se amplía añadiendo una entrada nueva aquí, sin tocar
# nada de la lógica de abajo.
#
# bloque_tema: en qué sitios del temario (oposición, bloque_id, tema_id) se
# debe buscar el artículo afectado cuando esta ley cambia.
LEYES_VIGILADAS = {
    "BOE-A-2015-11719": {
        "nombre": "Real Decreto Legislativo 5/2015, Estatuto Básico del Empleado Público (TREBEP)",
        "bloque_tema": [
            ("AGE", "bloque_01", "tema_01"),
            ("GACE", "bloque_01", "tema_01"),
            ("AUXILIAR", "bloque_01", "tema_01"),
        ],
    },
}

# Nombres oficiales de los 3 cuerpos (ya usados en oposiciones.py), para
# filtrar el sumario diario del BOE y quedarnos solo con lo relevante para
# esta web.
PALABRAS_CLAVE_OPOSICION = {
    "AGE": "Cuerpo General Administrativo del Estado",
    "GACE": "Cuerpo de Gestión de la Administración Civil del Estado",
    "AUXILIAR": "Cuerpo General Auxiliar de la Administración del Estado",
}

# Palabras que, junto al nombre de un cuerpo, indican que una entrada del
# sumario es un aviso relevante (convocatoria, lista, fecha de examen...) y
# no una mención de paso del cuerpo en otro contexto.
_PALABRAS_TIPO_AVISO = (
    "convocatoria", "lista de admitidos", "lista provisional", "lista definitiva",
    "admitidos y excluidos", "tribunal calificador", "fecha del ejercicio",
    "fecha de examen", "relación de aprobados", "listas de aprobados",
)

_TIPO_POR_PALABRA_CLAVE = {
    "convocatoria": "convocatoria",
    "lista de admitidos": "lista_admitidos",
    "lista provisional": "lista_admitidos",
    "lista definitiva": "lista_admitidos",
    "admitidos y excluidos": "lista_admitidos",
    "tribunal calificador": "tribunal",
    "fecha del ejercicio": "fecha_examen",
    "fecha de examen": "fecha_examen",
    "relación de aprobados": "aprobados",
    "listas de aprobados": "aprobados",
}


def _get_json(url):
    """GET simple con timeout corto -- no es una ruta de usuario, un fallo
    puntual (red, BOE caído un rato) simplemente se reintenta al día
    siguiente, así que no merece reintentos agresivos aquí."""
    try:
        resp = requests.get(url, headers={"Accept": "application/json"}, timeout=_TIMEOUT_SEGUNDOS)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.warning("Fallo llamando a la API del BOE: %s", url, exc_info=True)
        return None


def _buscar_clave(dato, clave):
    """Busca la primera aparición de `clave` en cualquier nivel de un JSON
    anidado (dict/list), sin asumir una ruta fija -- ver nota al principio
    del módulo sobre por qué (formato de la API no verificado byte a
    byte). Devuelve None si no aparece en ningún sitio."""
    if isinstance(dato, dict):
        if clave in dato:
            return dato[clave]
        for valor in dato.values():
            encontrado = _buscar_clave(valor, clave)
            if encontrado is not None:
                return encontrado
    elif isinstance(dato, list):
        for item in dato:
            encontrado = _buscar_clave(item, clave)
            if encontrado is not None:
                return encontrado
    return None


def _buscar_lista(dato, clave):
    """Como _buscar_clave, pero garantiza devolver siempre una lista (vacía
    si no se encuentra o el valor encontrado no es una lista) -- para los
    campos que son colecciones (bloques, versiones, referencias, items del
    sumario)."""
    encontrado = _buscar_clave(dato, clave)
    if isinstance(encontrado, list):
        return encontrado
    return []


def obtener_metadatos_ley(boe_id):
    dato = _get_json(f"{_BASE_URL}/legislacion-consolidada/id/{boe_id}/metadatos")
    if dato is None:
        return None
    return {"fecha_actualizacion": _buscar_clave(dato, "fecha_actualizacion")}


def obtener_indice_texto_ley(boe_id):
    dato = _get_json(f"{_BASE_URL}/legislacion-consolidada/id/{boe_id}/texto/indice")
    if dato is None:
        return []
    return _buscar_lista(dato, "bloque")


def obtener_bloque_texto_ley(boe_id, id_bloque):
    """Texto (con su historial de versiones) de un bloque/artículo concreto
    de una ley. Cada versión trae su fecha_publicacion y el texto vigente
    desde esa fecha -- la versión más reciente es el "texto nuevo" a
    proponer para el temario."""
    dato = _get_json(f"{_BASE_URL}/legislacion-consolidada/id/{boe_id}/texto/bloque/{id_bloque}")
    if dato is None:
        return []
    versiones = _buscar_lista(dato, "version")
    return sorted(versiones, key=lambda v: _buscar_clave(v, "fecha_publicacion") or "", reverse=True)


def obtener_sumario_dia(fecha_aaaammdd):
    dato = _get_json(f"{_BASE_URL}/boe/sumario/{fecha_aaaammdd}")
    if dato is None:
        return []
    return _buscar_lista(dato, "item")


def _doc_estado(db):
    return db.collection("config").document("vigilancia_boe")


def _clasificar_aviso(titulo):
    titulo_norm = (titulo or "").lower()
    for palabra in _PALABRAS_TIPO_AVISO:
        if palabra in titulo_norm:
            return _TIPO_POR_PALABRA_CLAVE[palabra]
    return "otro"


def detectar_avisos_oficiales(db):
    """Revisa el sumario del BOE de hoy y crea un aviso pendiente de
    revisión por cada publicación relevante para AGE, GACE o Auxiliar que
    no se haya visto ya (deduplicado por id de la disposición en el
    BOE)."""
    hoy = datetime.utcnow().strftime("%Y%m%d")
    ref_estado = _doc_estado(db)
    estado = ref_estado.get().to_dict() or {}
    ids_ya_vistos = set(estado.get("avisos_ids_vistos") or [])

    items = obtener_sumario_dia(hoy)
    creados = 0
    ids_nuevos = set()
    for item in items:
        item_id = _buscar_clave(item, "identificador") or _buscar_clave(item, "id")
        titulo = _buscar_clave(item, "titulo") or ""
        if not item_id or item_id in ids_ya_vistos:
            continue

        oposiciones_afectadas = [
            op for op, nombre_cuerpo in PALABRAS_CLAVE_OPOSICION.items() if nombre_cuerpo.lower() in titulo.lower()
        ]
        if not oposiciones_afectadas:
            continue
        tipo = _clasificar_aviso(titulo)
        if tipo == "otro":
            continue  # menciona el cuerpo pero no parece un aviso de convocatoria/lista/examen

        for oposicion in oposiciones_afectadas:
            db.collection("avisos_oficiales").document().set({
                "oposicion": oposicion,
                "tipo": tipo,
                "titulo": titulo[:300],
                "resumen": titulo[:500],
                "url_boe": _buscar_clave(item, "url_html") or _buscar_clave(item, "url_pdf") or "",
                "fecha_boe": hoy,
                "fecha_deteccion": datetime.utcnow().isoformat(),
                "estado": "pendiente",
            })
            creados += 1
        ids_nuevos.add(item_id)

    if ids_nuevos:
        # Se guarda un histórico acotado (no crecer sin límite) de los
        # últimos IDs vistos, suficiente para deduplicar entre ejecuciones
        # diarias consecutivas.
        ref_estado.set(
            {"avisos_ids_vistos": list((ids_ya_vistos | ids_nuevos))[-500:]}, merge=True
        )
    logger.info("Vigilancia BOE (avisos oficiales): %s avisos nuevos creados", creados)
    return creados


def _subbloques_de_tema(db, coleccion, bloque_id, tema_id):
    """Como utils.obtener_subbloques_individuales, pero sin el recorte de
    texto a ~4000 caracteres que hace esa función -- aquí se necesita el
    texto COMPLETO y sin tocar del chunk, porque el guardarraíl de
    generador_diff_temario.py comprueba que el texto a eliminar aparece
    LITERAL en él; un recorte podría cortar justo el pasaje que cambió."""
    ref = db.collection(coleccion).document(bloque_id).collection("temas").document(tema_id).collection("subbloques")
    subbloques = []
    for doc in ref.stream():
        datos = doc.to_dict() or {}
        if not datos.get("texto"):
            continue
        subbloques.append({"chunk_id": doc.id, "titulo": datos.get("titulo", ""), "texto": datos["texto"]})
    return subbloques


def detectar_cambios_leyes_vigiladas(db):
    """Por cada ley en LEYES_VIGILADAS, comprueba si el BOE la ha
    modificado desde la última vez; si es así, por cada artículo cambiado
    genera (y verifica) una propuesta de cambio para cada tema del temario
    mapeado, y la deja pendiente de revisión en cambios_temario_propuestos.
    Nunca escribe directamente en el temario -- eso solo pasa cuando el
    dueño aprueba la propuesta desde el panel de admin."""
    from generador_diff_temario import generar_propuesta_cambio
    from oposiciones import coleccion_temario

    ref_estado = _doc_estado(db)
    estado = ref_estado.get().to_dict() or {}
    fechas_vistas = estado.get("leyes_fecha_vista") or {}

    propuestas_creadas = 0
    fechas_vistas_actualizadas = dict(fechas_vistas)

    for boe_id, config_ley in LEYES_VIGILADAS.items():
        metadatos = obtener_metadatos_ley(boe_id)
        if not metadatos or not metadatos.get("fecha_actualizacion"):
            continue
        fecha_actual = metadatos["fecha_actualizacion"]
        fecha_vista = fechas_vistas.get(boe_id)
        if fecha_vista and fecha_actual <= fecha_vista:
            continue  # sin cambios desde la última vez

        bloques_indice = obtener_indice_texto_ley(boe_id)
        for bloque in bloques_indice:
            id_bloque = _buscar_clave(bloque, "id")
            if not id_bloque:
                continue
            versiones = obtener_bloque_texto_ley(boe_id, id_bloque)
            if not versiones:
                continue
            ultima_version = versiones[0]
            fecha_version = _buscar_clave(ultima_version, "fecha_publicacion") or ""
            if fecha_vista and fecha_version <= fecha_vista:
                continue  # este bloque en concreto no cambió, aunque la ley sí
            texto_nuevo = _buscar_clave(ultima_version, "texto") or ""
            if not texto_nuevo:
                continue

            for oposicion, bloque_id, tema_id in config_ley["bloque_tema"]:
                subbloques = _subbloques_de_tema(db, coleccion_temario(oposicion), bloque_id, tema_id)
                if not subbloques:
                    continue
                propuesta = generar_propuesta_cambio(texto_nuevo, subbloques)
                if not propuesta:
                    continue
                db.collection("cambios_temario_propuestos").document().set({
                    "oposicion": oposicion,
                    "bloque_id": bloque_id,
                    "tema_id": tema_id,
                    "subbloque_id": propuesta["chunk_id_afectado"],
                    "ley_nombre": config_ley["nombre"],
                    "boe_id": boe_id,
                    "fecha_deteccion": datetime.utcnow().isoformat(),
                    "resumen": propuesta["resumen"],
                    "texto_eliminar": propuesta["texto_eliminar"],
                    "texto_anadir": propuesta["texto_anadir"],
                    "estado": "pendiente",
                })
                propuestas_creadas += 1

        fechas_vistas_actualizadas[boe_id] = fecha_actual

    if fechas_vistas_actualizadas != fechas_vistas:
        ref_estado.set({"leyes_fecha_vista": fechas_vistas_actualizadas}, merge=True)
    logger.info("Vigilancia BOE (cambios de temario): %s propuestas nuevas creadas", propuestas_creadas)
    return propuestas_creadas
