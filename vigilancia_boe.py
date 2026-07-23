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
import re
from datetime import datetime

import requests

from oposiciones import OPOSICIONES

logger = logging.getLogger(__name__)

# El índice de una ley trae bloques de artículo ("a1", "a2"...) MEZCLADOS con
# disposiciones (transitorias "dt*", derogatorias "dd*", finales "df*",
# preámbulo "pr"...). Confirmado en producción: /texto/bloque/{id} devuelve
# 400 para esos ids de disposición -- y da igual, porque el temario nunca
# está anclado a una "disposición", solo a "Artículo N." (ver
# generador_preguntas_verificado._PATRON_ARTICULO), así que no hace falta
# pedirlas: se descartan aquí, antes de llamar a la API por cada una.
_PATRON_ID_BLOQUE_ARTICULO = re.compile(r"^a\d")

_BASE_URL = "https://www.boe.es/datosabiertos/api"
_TIMEOUT_SEGUNDOS = 15

# Leyes troncales vigiladas para detectar cambios en el temario. Lista
# curada a mano a propósito (no hay forma fiable de deducir automáticamente
# a qué ley de BOE corresponde cada chunk de temario, que solo guarda un
# título libre) -- se amplía añadiendo una entrada nueva aquí, sin tocar
# nada de la lógica de abajo.
#
# bloque_tema: en qué sitios del temario (oposición, bloque_id, tema_id) se
# debe buscar el artículo afectado cuando esta ley cambia -- confirmado
# contra los títulos reales de Firestore (workflow "Listar temas vacíos del
# temario", que además de temas vacíos imprime bloque_id/tema_id + título de
# las 3 colecciones). ¡Ojo! Hasta esta revisión, el TREBEP estaba mal
# ubicado en bloque_01/tema_01 en las 3 oposiciones -- ese tema es en
# realidad "la Constitución Española", no el TREBEP -- así que llevaba
# tiempo vigilando el tema equivocado. Ya corregido abajo.
#
# Todos los BOE-A de esta lista están verificados contra los "Códigos
# electrónicos" oficiales del BOE -- "Normativa para ingreso en el Cuerpo
# de Gestión de la Administración Civil del Estado" (código 443, GACE),
# "...en el Cuerpo General Administrativo..." (código 442, AGE) y "...en el
# Cuerpo General Auxiliar..." (código 435, Auxiliar; este último ya se
# había usado antes para cargar el Bloque I de Auxiliar). Los 3 PDF están
# en la raíz del repo, edición actualizada entre mayo y junio de 2026. Cada
# uno trae el sumario oficial completo de las normas del temario de esa
# oposición y el texto consolidado de cada una con su propia "Referencia:
# BOE-A-..." -- de ahí se han extraído y contrastado uno a uno los BOE-A de
# abajo (no de memoria, como en una revisión anterior de este archivo).
# Aun así, esta lista NO agota el temario entero: cubre las leyes troncales
# de mayor peso identificadas hasta ahora, no cada Orden/Resolución menor
# que también aparece en el código. Si alguna referencia fuera incorrecta
# de todos modos, el efecto sigue siendo inofensivo: obtener_metadatos_ley()
# simplemente no encuentra la ley y esa entrada no genera nunca ninguna
# propuesta (nunca lanza excepción ni rompe el resto).
LEYES_VIGILADAS = {
    "BOE-A-2015-11719": {
        "nombre": "Real Decreto Legislativo 5/2015, Estatuto Básico del Empleado Público (TREBEP)",
        "bloque_tema": [
            ("AGE", "bloque_04", "tema_01"), ("AGE", "bloque_04", "tema_02"),
            ("AGE", "bloque_04", "tema_03"), ("AGE", "bloque_04", "tema_04"),
            ("AGE", "bloque_04", "tema_05"), ("AGE", "bloque_04", "tema_06"),
            ("AGE", "bloque_04", "tema_08"),
            ("GACE", "bloque_05", "tema_01"), ("GACE", "bloque_05", "tema_02"),
            ("GACE", "bloque_05", "tema_03"), ("GACE", "bloque_05", "tema_04"),
            ("GACE", "bloque_05", "tema_05"), ("GACE", "bloque_05", "tema_06"),
            ("GACE", "bloque_05", "tema_07"), ("GACE", "bloque_05", "tema_08"),
            ("AUXILIAR", "bloque_01", "tema_13"),
        ],
    },
    "BOE-A-2015-10566": {
        "nombre": "Ley 40/2015, de Régimen Jurídico del Sector Público (LRJSP)",
        "bloque_tema": [
            ("AGE", "bloque_01", "tema_08"), ("AGE", "bloque_03", "tema_06"),
            ("GACE", "bloque_01", "tema_08"), ("GACE", "bloque_01", "tema_09"),
            ("AUXILIAR", "bloque_01", "tema_08"), ("AUXILIAR", "bloque_01", "tema_11"),
        ],
    },
    "BOE-A-2015-10565": {
        "nombre": "Ley 39/2015, del Procedimiento Administrativo Común de las Administraciones Públicas (LPACAP)",
        "bloque_tema": [
            ("AGE", "bloque_03", "tema_03"),
            ("GACE", "bloque_04", "tema_11"),
            ("AUXILIAR", "bloque_01", "tema_11"),
        ],
    },
    "BOE-A-2017-12902": {
        "nombre": "Ley 9/2017, de Contratos del Sector Público (LCSP)",
        "bloque_tema": [
            ("AGE", "bloque_03", "tema_04"),
            ("GACE", "bloque_04", "tema_05"), ("GACE", "bloque_04", "tema_06"),
        ],
    },
    "BOE-A-2013-12887": {
        "nombre": "Ley 19/2013, de transparencia, acceso a la información pública y buen gobierno",
        "bloque_tema": [
            ("AGE", "bloque_01", "tema_07"),
            ("AUXILIAR", "bloque_01", "tema_07"),
        ],
    },
    "BOE-A-1981-10325": {
        "nombre": "Ley Orgánica 3/1981, del Defensor del Pueblo",
        "bloque_tema": [
            ("GACE", "bloque_01", "tema_02"),
        ],
    },
    "BOE-A-1979-23709": {
        "nombre": "Ley Orgánica 2/1979, del Tribunal Constitucional",
        "bloque_tema": [
            ("GACE", "bloque_01", "tema_03"),
            ("AUXILIAR", "bloque_01", "tema_02"),
        ],
    },
    "BOE-A-1997-25336": {
        "nombre": "Ley 50/1997, del Gobierno",
        "bloque_tema": [
            ("AGE", "bloque_01", "tema_05"),
            ("GACE", "bloque_01", "tema_06"),
            ("AUXILIAR", "bloque_01", "tema_05"),
        ],
    },
    "BOE-A-1985-12666": {
        "nombre": "Ley Orgánica 6/1985, del Poder Judicial",
        "bloque_tema": [
            ("AGE", "bloque_01", "tema_04"),
            ("GACE", "bloque_01", "tema_07"),
            ("AUXILIAR", "bloque_01", "tema_04"),
        ],
    },
    "BOE-A-1985-5392": {
        "nombre": "Ley 7/1985, Reguladora de las Bases del Régimen Local (LRBRL)",
        "bloque_tema": [
            ("AGE", "bloque_01", "tema_10"),
            ("GACE", "bloque_01", "tema_11"),
            ("AUXILIAR", "bloque_01", "tema_09"),
        ],
    },
    "BOE-A-2000-544": {
        "nombre": "Ley Orgánica 4/2000, sobre derechos y libertades de los extranjeros en España",
        "bloque_tema": [
            ("GACE", "bloque_03", "tema_06"),
        ],
    },
    "BOE-A-2018-16673": {
        "nombre": "Ley Orgánica 3/2018, de Protección de Datos Personales y garantía de los derechos digitales (LOPDGDD)",
        "bloque_tema": [
            ("AGE", "bloque_02", "tema_04"),
            ("GACE", "bloque_03", "tema_08"),
            ("AUXILIAR", "bloque_01", "tema_12"),
        ],
    },
    "BOE-A-2007-6115": {
        "nombre": "Ley Orgánica 3/2007, para la igualdad efectiva de mujeres y hombres",
        "bloque_tema": [
            ("AGE", "bloque_03", "tema_07"),
            ("GACE", "bloque_03", "tema_09"),
            ("AUXILIAR", "bloque_01", "tema_16"),
        ],
    },
    "BOE-A-2004-21760": {
        "nombre": "Ley Orgánica 1/2004, de Medidas de Protección Integral contra la Violencia de Género",
        "bloque_tema": [
            ("AGE", "bloque_03", "tema_07"),
            ("GACE", "bloque_03", "tema_09"),
        ],
    },
    "BOE-A-1954-15431": {
        "nombre": "Ley de Expropiación Forzosa, de 16 de diciembre de 1954",
        "bloque_tema": [
            ("GACE", "bloque_04", "tema_08"),
        ],
    },
    "BOE-A-2003-20254": {
        "nombre": "Ley 33/2003, del Patrimonio de las Administraciones Públicas",
        "bloque_tema": [
            ("GACE", "bloque_04", "tema_09"),
        ],
    },
    "BOE-A-1998-16718": {
        "nombre": "Ley 29/1998, reguladora de la Jurisdicción Contencioso-Administrativa",
        "bloque_tema": [
            ("GACE", "bloque_04", "tema_13"),
        ],
    },
    "BOE-A-2007-19814": {
        "nombre": "Ley 37/2007, sobre reutilización de la información del sector público",
        "bloque_tema": [
            ("AGE", "bloque_01", "tema_06"),
            ("AUXILIAR", "bloque_01", "tema_06"),
        ],
    },
    "BOE-A-1985-151": {
        "nombre": "Ley 53/1984, de Incompatibilidades del personal al servicio de las Administraciones Públicas",
        "bloque_tema": [
            ("AGE", "bloque_04", "tema_06"),
        ],
    },
    "BOE-A-2000-12140": {
        "nombre": "Real Decreto Legislativo 4/2000, texto refundido de la Ley sobre Seguridad Social de los Funcionarios Civiles del Estado (MUFACE)",
        "bloque_tema": [
            ("AGE", "bloque_04", "tema_07"),
            ("GACE", "bloque_05", "tema_09"),
        ],
    },
    "BOE-A-2012-5730": {
        "nombre": "Ley Orgánica 2/2012, de Estabilidad Presupuestaria y Sostenibilidad Financiera",
        "bloque_tema": [
            ("AGE", "bloque_05", "tema_01"),
        ],
    },
    "BOE-A-1982-11584": {
        "nombre": "Ley Orgánica 2/1982, del Tribunal de Cuentas",
        "bloque_tema": [
            ("GACE", "bloque_06", "tema_04"),
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
            if not id_bloque or not _PATRON_ID_BLOQUE_ARTICULO.match(id_bloque):
                continue  # disposición u otro bloque que no es un artículo -- ver nota arriba
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


def verificar_bloque_temas_referenciados(db):
    """Chequeo de salud de LEYES_VIGILADAS: comprueba que cada
    (oposicion, bloque_id, tema_id) referenciado sigue existiendo en el
    temario con contenido real. Si algún día se reestructura el temario
    (se renumeran o se borran bloques/temas) esas entradas dejarían de
    generar propuestas para siempre sin que nadie se entere -- no fallan,
    simplemente `_subbloques_de_tema` empieza a devolver una lista vacía y
    `detectar_cambios_leyes_vigiladas` las salta en silencio. Este chequeo
    lo detecta y lo deja guardado para poder avisar desde el panel de
    admin, sin tener que repetir la comprobación en cada carga de esa
    pestaña. No modifica el temario ni LEYES_VIGILADAS, solo lee."""
    from oposiciones import coleccion_temario

    faltantes = []
    vistos = set()
    for config_ley in LEYES_VIGILADAS.values():
        for oposicion, bloque_id, tema_id in config_ley["bloque_tema"]:
            clave = (oposicion, bloque_id, tema_id)
            if clave in vistos:
                continue
            vistos.add(clave)
            subbloques = _subbloques_de_tema(db, coleccion_temario(oposicion), bloque_id, tema_id)
            if not subbloques:
                faltantes.append({"oposicion": oposicion, "bloque_id": bloque_id, "tema_id": tema_id})

    _doc_estado(db).set({
        "temas_faltantes": faltantes,
        "temas_faltantes_fecha": datetime.utcnow().isoformat(),
    }, merge=True)
    if faltantes:
        logger.warning("Vigilancia BOE: %s temas referenciados en LEYES_VIGILADAS ya no existen: %s", len(faltantes), faltantes)
    return faltantes
