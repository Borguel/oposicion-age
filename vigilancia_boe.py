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
   examen...) -> aviso en avisos_oficiales. Revisa también días anteriores
   sin ejecución (backfill acotado, ver _DIAS_MAX_BACKFILL) y usa la IA como
   segunda pasada para títulos que no nombran ningún cuerpo literalmente
   pero sí términos genéricos de Administración/empleo público (ver
   _clasificar_relevancia_temario_con_ia) -- caso real que motivó esto: el
   RD 606/2026 modificó el temario de las 3 oposiciones sin nombrar ningún
   cuerpo en su título.

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
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timedelta

import requests

from deepseek_utils import call_deepseek_api
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
    "llamamiento extraordinario",
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
    # Visto en la práctica en una resolución de la Comisión Permanente de
    # Selección (llamamiento a un grupo reducido de aspirantes a un
    # examen de repesca) -- esa concreta se publica solo en el portal de
    # firma/validación del INAP (run.gob.es), no en el BOE, así que esta
    # palabra clave solo ayuda si algún día un caso similar sí llega a
    # publicarse en el sumario del BOE. Tipo propio (no "fecha_examen"):
    # ese se reserva para la fecha del ejercicio de la convocatoria
    # oficial, un llamamiento extraordinario es otra cosa (repesca).
    "llamamiento extraordinario": "llamamiento_extraordinario",
}

# Términos genéricos (sin nombrar ningún cuerpo) que pueden indicar que una
# disposición del BOE afecta igualmente al temario o a las convocatorias --
# visto en producción: el Real Decreto 606/2026, de 22 de julio (Estatuto de
# la Autoridad Independiente para la Igualdad de Trato y la No
# Discriminación) modificó el temario de Turno Libre de GACE/AGE/AUXILIAR
# sin mencionar ningún cuerpo en su título, así que PALABRAS_CLAVE_OPOSICION
# nunca lo habría detectado. Estas palabras NO clasifican nada por sí solas
# -- son deliberadamente genéricas y, usadas solas, darían decenas de falsos
# positivos al día (cualquier nombramiento o subvención menciona "sector
# público") -- solo sirven para preseleccionar del sumario del día un
# puñado de titulares candidatos que luego sí se le pasan a la IA (ver
# _clasificar_relevancia_temario_con_ia) para que decida con criterio real.
_PALABRAS_POSIBLE_RELEVANCIA_TEMARIO = (
    "empleado público", "empleados públicos", "función pública", "empleo público",
    "administración general del estado", "administración pública", "administraciones públicas",
    "sector público", "estatuto básico", "autoridad independiente", "organismo autónomo",
    "personal al servicio",
)

# Cuántos días hacia atrás se revisa como máximo si el ciclo diario se ha
# saltado alguno (cron caído, primer despliegue del workflow...) -- sin
# esto, detectar_avisos_oficiales solo miraba el sumario de "hoy" y
# cualquier publicación de un día sin ejecución se perdía para siempre, sin
# ninguna forma de recuperarla (así se perdió el RD 606/2026, publicado un
# día antes de que este workflow se activara por primera vez). Acotado (no
# "desde el principio de los tiempos") para no lanzar un backfill sin
# límite si el estado se resetea alguna vez o esto no se ha ejecutado nunca.
_DIAS_MAX_BACKFILL = 5

# Tope de títulos candidatos que se le pasan a _clasificar_relevancia_temario_con_ia
# en una sola ejecución -- control de coste: un día atípico con muchos
# títulos que rozan los términos genéricos de _PALABRAS_POSIBLE_RELEVANCIA_TEMARIO
# (o varios días de backfill acumulados) no debe traducirse en un prompt
# sin límite ni en una llamada desproporcionadamente cara.
_MAX_CANDIDATOS_RELEVANCIA_IA_POR_CICLO = 30


def _fechas_a_revisar(estado):
    """Normalmente devuelve solo [hoy]; si quedan días sin revisar desde la
    última ejecución (ver _DIAS_MAX_BACKFILL de arriba), los añade también,
    en orden cronológico. Siempre incluye HOY, aunque el estado diga que ya
    se revisó (p. ej. una segunda ejecución manual el mismo día) -- así
    "desde" nunca queda por delante de "hoy" y la lista jamás sale vacía;
    volver a mirar el sumario de hoy es idempotente gracias al deduplicado
    por avisos_ids_vistos."""
    hoy = datetime.utcnow().date()
    minimo = hoy - timedelta(days=_DIAS_MAX_BACKFILL - 1)
    desde = minimo
    ultima_str = estado.get("avisos_ultima_fecha_revisada")
    if ultima_str:
        try:
            desde = max(minimo, datetime.strptime(ultima_str, "%Y%m%d").date() + timedelta(days=1))
        except ValueError:
            pass
    desde = min(desde, hoy)
    fechas = []
    fecha = desde
    while fecha <= hoy:
        fechas.append(fecha.strftime("%Y%m%d"))
        fecha += timedelta(days=1)
    return fechas


def _prompt_relevancia_temario(titulos):
    listado = "\n".join(f"{i}: {t}" for i, t in enumerate(titulos))
    system = (
        "Eres un analista que vigila el BOE para una web de preparación de oposiciones a 3 cuerpos de "
        "la Administración General del Estado por turno libre: AGE (Cuerpo General Administrativo), "
        "GACE (Cuerpo de Gestión de la Administración Civil del Estado) y AUXILIAR (Cuerpo General "
        "Auxiliar). Te llega una lista de títulos de disposiciones publicadas en el BOE que mencionan "
        "de forma genérica la Administración o el empleo público, pero SIN nombrar literalmente ninguno "
        "de esos 3 cuerpos -- por eso no las ha detectado ya el filtro automático de palabras clave, y "
        "hace falta tu criterio.\n\n"
        "Para cada título, decide si es RAZONABLE PENSAR que puede afectar al TEMARIO o a las "
        "CONVOCATORIAS de esos 3 cuerpos -- por ejemplo, crea o reforma un organismo, ley o estatuto "
        "que se estudia en un temario de oposición a la Administración General del Estado, o afecta de "
        "forma directa a un proceso selectivo, aunque sea indirectamente. Sé conservador: NO marques "
        "como relevante una disposición que solo menciona la Administración Pública de pasada "
        "(nombramientos concretos, subvenciones puntuales, convenios de colaboración...) sin relación "
        "real con el contenido de un temario de oposición. Indica también a qué cuerpo(s) -- de AGE, "
        "GACE, AUXILIAR -- afecta probablemente; si no puedes distinguirlo, incluye los 3.\n\n"
        "Devuelve ÚNICAMENTE un JSON con esta forma exacta, con una entrada por cada título recibido "
        "(mismo índice que en el enunciado), sin texto adicional:\n"
        '{"resultados": [{"indice": 0, "relevante": true, "oposiciones": ["AGE"], "motivo": "una frase breve"}]}'
    )
    user = f"TÍTULOS:\n{listado}"
    return system, user


def _clasificar_relevancia_temario_con_ia(titulos):
    """Una sola llamada a DeepSeek para TODOS los títulos candidatos del
    ciclo (nunca una por título -- mismo principio de coste que
    test_generator._verificar_lote). Devuelve {indice: {"oposiciones": [...],
    "motivo": "..."}} solo para los índices que la IA considera relevantes;
    ante cualquier fallo (sin respuesta, JSON inválido) devuelve {} -- un
    ciclo sin esta clasificación extra no es peor que el comportamiento
    anterior a esta función, así que nunca merece romper el resto de
    detectar_avisos_oficiales."""
    if not titulos:
        return {}
    system, user = _prompt_relevancia_temario(titulos)
    raw = call_deepseek_api(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        max_tokens=min(4000, 200 + 150 * len(titulos)),
        response_format_json=True,
    )
    if not raw:
        return {}
    try:
        datos = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(datos, dict):
        return {}
    oposiciones_validas = set(PALABRAS_CLAVE_OPOSICION.keys())
    resultados = {}
    for entrada in (datos.get("resultados") or []):
        if not isinstance(entrada, dict) or entrada.get("relevante") is not True:
            continue
        try:
            indice = int(entrada.get("indice"))
        except (TypeError, ValueError):
            continue
        oposiciones = [o for o in (entrada.get("oposiciones") or []) if o in oposiciones_validas]
        resultados[indice] = {
            "oposiciones": oposiciones or list(oposiciones_validas),
            "motivo": str(entrada.get("motivo") or "").strip()[:300],
        }
    return resultados


# Antes se asumía que un fallo puntual "se reintenta al día siguiente" y
# no merecía reintentos agresivos -- pero eso ya no es del todo cierto
# desde que detectar_avisos_oficiales hace backfill: si el BOE devuelve un
# 502/503/504 transitorio (caída momentánea, no un día completo caído),
# unos pocos reintentos con espera evitan perder ese día del todo, sin
# tener que esperar a la siguiente ejecución. Solo se reintenta en esos
# códigos -- un 4xx (URL mal formada, recurso que no existe) no se arregla
# reintentando, así que falla directo como antes.
_REINTENTOS_TRANSITORIOS_BOE = 3
_CODIGOS_HTTP_REINTENTABLES_BOE = {502, 503, 504}


def _get_json(url):
    for intento in range(_REINTENTOS_TRANSITORIOS_BOE):
        try:
            resp = requests.get(url, headers={"Accept": "application/json"}, timeout=_TIMEOUT_SEGUNDOS)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            codigo = e.response.status_code if e.response is not None else None
            si_ultimo_intento = intento == _REINTENTOS_TRANSITORIOS_BOE - 1
            if codigo in _CODIGOS_HTTP_REINTENTABLES_BOE and not si_ultimo_intento:
                espera = (2 ** intento) + random.uniform(0, 1)
                logger.warning(
                    "BOE devolvió %s (intento %s/%s), reintentando en %.1fs: %s",
                    codigo, intento + 1, _REINTENTOS_TRANSITORIOS_BOE, espera, url,
                )
                time.sleep(espera)
                continue
            logger.warning("Fallo llamando a la API del BOE: %s", url, exc_info=True)
            return None
        except Exception:
            logger.warning("Fallo llamando a la API del BOE: %s", url, exc_info=True)
            return None
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
    """A diferencia de las demás funciones obtener_*, distingue "la consulta
    falló" (None) de "la consulta fue bien pero no hay items" ([]) -- lo
    necesita detectar_avisos_oficiales para no marcar como revisado un día
    cuyo sumario en realidad no se ha podido consultar (ver
    _DIAS_MAX_BACKFILL más abajo: si un fallo se tratara igual que "sin
    items", ese día se perdería para siempre en vez de reintentarse en la
    siguiente ejecución)."""
    dato = _get_json(f"{_BASE_URL}/boe/sumario/{fecha_aaaammdd}")
    if dato is None:
        return None
    return _buscar_lista(dato, "item")


def _doc_estado(db):
    return db.collection("config").document("vigilancia_boe")


def _clasificar_aviso(titulo):
    titulo_norm = (titulo or "").lower()
    for palabra in _PALABRAS_TIPO_AVISO:
        if palabra in titulo_norm:
            return _TIPO_POR_PALABRA_CLAVE[palabra]
    return "otro"


def _guardar_aviso_oficial(db, item, titulo, oposiciones, tipo, fecha_boe, motivo_ia=None):
    # Un único aviso con TODAS las oposiciones afectadas (p. ej. una
    # resolución que menciona a la vez al Cuerpo General Administrativo y
    # al de Gestión) -- así solo hace falta aprobarlo una vez y llega a las
    # páginas/usuarios de cada oposición, en vez de crear un documento
    # duplicado por oposición.
    resumen = titulo[:500]
    if motivo_ia:
        resumen = f"{titulo[:400]} — {motivo_ia}"[:500]
    db.collection("avisos_oficiales").document().set({
        "oposiciones": oposiciones,
        "tipo": tipo,
        "titulo": titulo[:300],
        "resumen": resumen,
        "url_boe": _buscar_clave(item, "url_html") or _buscar_clave(item, "url_pdf") or "",
        "fecha_boe": fecha_boe,
        "fecha_deteccion": datetime.utcnow().isoformat(),
        "estado": "pendiente",
    })


def detectar_avisos_oficiales(db):
    """Revisa el sumario del BOE de hoy (y de cualquier día sin revisar
    desde la última ejecución, ver _fechas_a_revisar) y crea un aviso
    pendiente de revisión por cada publicación relevante para AGE, GACE o
    Auxiliar que no se haya visto ya (deduplicado por id de la disposición
    en el BOE).

    Dos vías de detección, en este orden:
    1. Coincidencia literal del nombre de un cuerpo en el título (rápida,
       gratis, la de siempre) -- ver PALABRAS_CLAVE_OPOSICION.
    2. Para los títulos que NO mencionan ningún cuerpo pero sí un término
       genérico de Administración/empleo público (ver
       _PALABRAS_POSIBLE_RELEVANCIA_TEMARIO), una única llamada a la IA por
       ejecución que decide con más criterio si de verdad puede afectar al
       temario -- pensada para casos como el RD 606/2026, que modificó el
       temario de las 3 oposiciones sin nombrar ningún cuerpo en su
       título."""
    ref_estado = _doc_estado(db)
    estado = ref_estado.get().to_dict() or {}
    ids_ya_vistos = set(estado.get("avisos_ids_vistos") or [])
    fechas = _fechas_a_revisar(estado)

    creados = 0
    ids_nuevos = set()
    candidatos_relevancia = []  # [(item_id, titulo, item, fecha)]
    ultima_fecha_ok = None

    for fecha in fechas:
        items_dia = obtener_sumario_dia(fecha)
        if items_dia is None:
            # La consulta de este día falló (incluso tras los reintentos de
            # _get_json) -- se corta aquí SIN avanzar avisos_ultima_fecha_revisada
            # más allá del último día que sí se pudo consultar, para que la
            # siguiente ejecución reintente este día por el backfill en vez
            # de darlo por revisado sin haberlo mirado de verdad.
            logger.warning(
                "Vigilancia BOE: no se pudo obtener el sumario de %s tras los reintentos, se reintentará en la próxima ejecución",
                fecha,
            )
            break
        ultima_fecha_ok = fecha

        for item in items_dia:
            item_id = _buscar_clave(item, "identificador") or _buscar_clave(item, "id")
            titulo = _buscar_clave(item, "titulo") or ""
            if not item_id or item_id in ids_ya_vistos or item_id in ids_nuevos:
                continue

            oposiciones_afectadas = [
                op for op, nombre_cuerpo in PALABRAS_CLAVE_OPOSICION.items()
                if nombre_cuerpo.lower() in titulo.lower()
            ]
            if oposiciones_afectadas:
                tipo = _clasificar_aviso(titulo)
                if tipo == "otro":
                    continue  # menciona el cuerpo pero no parece un aviso de convocatoria/lista/examen
                _guardar_aviso_oficial(db, item, titulo, oposiciones_afectadas, tipo, fecha)
                creados += 1
                ids_nuevos.add(item_id)
                continue

            titulo_norm = titulo.lower()
            if any(palabra in titulo_norm for palabra in _PALABRAS_POSIBLE_RELEVANCIA_TEMARIO):
                candidatos_relevancia.append((item_id, titulo, item, fecha))

    if len(candidatos_relevancia) > _MAX_CANDIDATOS_RELEVANCIA_IA_POR_CICLO:
        # Tope de coste: un día con muchos títulos que rozan los términos
        # genéricos (ver _PALABRAS_POSIBLE_RELEVANCIA_TEMARIO) no debe
        # traducirse en un prompt sin límite -- se recorta sin más
        # (orden del sumario, no merece la complejidad de "priorizar").
        logger.warning(
            "Vigilancia BOE: %s candidatos para la IA de relevancia, se trunca a %s para controlar el coste",
            len(candidatos_relevancia), _MAX_CANDIDATOS_RELEVANCIA_IA_POR_CICLO,
        )
        candidatos_relevancia = candidatos_relevancia[:_MAX_CANDIDATOS_RELEVANCIA_IA_POR_CICLO]

    if candidatos_relevancia:
        resultados_ia = _clasificar_relevancia_temario_con_ia([c[1] for c in candidatos_relevancia])
        for indice, (item_id, titulo, item, fecha) in enumerate(candidatos_relevancia):
            resultado = resultados_ia.get(indice)
            if not resultado:
                continue
            _guardar_aviso_oficial(
                db, item, titulo, resultado["oposiciones"], "posible_relevancia_temario", fecha,
                motivo_ia=resultado["motivo"],
            )
            creados += 1
            ids_nuevos.add(item_id)

    if ultima_fecha_ok is None:
        # Ni siquiera el primer día de la ventana se pudo consultar --
        # nada que guardar, la próxima ejecución reintentará esta misma
        # ventana desde el estado actual (sin tocarlo).
        logger.info("Vigilancia BOE (avisos oficiales): 0 avisos nuevos creados (0 días revisados, fallo de consulta)")
        return 0

    if ids_nuevos:
        # Se guarda un histórico acotado (no crecer sin límite) de los
        # últimos IDs vistos, suficiente para deduplicar entre ejecuciones
        # diarias consecutivas.
        ids_ya_vistos = ids_ya_vistos | ids_nuevos
    # avisos_ultima_fecha_revisada avanza hasta el último día que SÍ se
    # pudo consultar (haya o no avisos nuevos en él) para que el backfill
    # de la próxima ejecución no vuelva a mirar estos mismos días -- si se
    # guardara solo dentro del "if ids_nuevos" de arriba, un día sin
    # ninguna novedad relevante se reintentaría cada día siguiente para
    # siempre.
    ref_estado.set({
        "avisos_ids_vistos": list(ids_ya_vistos)[-500:],
        "avisos_ultima_fecha_revisada": ultima_fecha_ok,
    }, merge=True)
    logger.info("Vigilancia BOE (avisos oficiales): %s avisos nuevos creados (hasta %s)", creados, ultima_fecha_ok)
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


# Ventana de deduplicación de _existe_propuesta_pendiente_reciente: si el
# workflow se dispara dos veces seguidas para el mismo cambio (p. ej. un
# reintento manual mientras la ejecución anterior sigue en curso, antes de
# que leyes_fecha_vista se actualice al final), la segunda pasada volvería
# a generar la MISMA propuesta -- 48h es margen de sobra para cualquier
# solape real sin arriesgarse a ocultar un cambio genuino y posterior del
# mismo artículo (fecha_version ya filtra eso por su cuenta; esto es solo
# para el solape entre dos ejecuciones del mismo ciclo).
_HORAS_DEDUP_PROPUESTA_TEMARIO = 48


def _existe_propuesta_pendiente_reciente(db, boe_id, subbloque_id):
    """True si ya hay una propuesta pendiente reciente para este mismo
    artículo (boe_id) y este mismo subbloque de temario -- para no crear un
    duplicado en cambios_temario_propuestos si dos ejecuciones se solapan.
    Requiere un índice compuesto en Firestore (boe_id Asc + subbloque_id
    Asc + estado Asc + fecha_deteccion Desc) que hay que crear a mano en la
    consola de Firebase -- ante CUALQUIER fallo de la consulta (incluido
    "falta el índice"), se asume que NO hay duplicado y se deja crear la
    propuesta igual: esta comprobación es una mejora sobre el
    comportamiento anterior, nunca debe poder romper el ciclo completo de
    vigilancia."""
    try:
        limite = (datetime.utcnow() - timedelta(hours=_HORAS_DEDUP_PROPUESTA_TEMARIO)).isoformat()
        coincidencias = list(
            db.collection("cambios_temario_propuestos")
            .where("boe_id", "==", boe_id)
            .where("subbloque_id", "==", subbloque_id)
            .where("estado", "==", "pendiente")
            .where("fecha_deteccion", ">", limite)
            .limit(1)
            .get()
        )
        return bool(coincidencias)
    except Exception:
        logger.warning(
            "No se pudo comprobar si ya existe una propuesta pendiente para boe_id=%s subbloque_id=%s "
            "(¿falta el índice compuesto en Firestore?) -- se crea la propuesta igual",
            boe_id, subbloque_id, exc_info=True,
        )
        return False


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
            texto_nuevo = (_buscar_clave(ultima_version, "texto") or "").strip()
            if not texto_nuevo:
                # or "" solo protege contra ausencia/None -- un texto que
                # sea solo espacios o saltos de línea (visto como
                # posibilidad real en una API cuyo formato exacto no se ha
                # podido verificar byte a byte, ver nota al principio del
                # módulo) pasaría ese filtro sin el strip().
                logger.warning("Bloque %s de %s sin texto útil en su última versión, se salta", id_bloque, boe_id)
                continue

            for oposicion, bloque_id, tema_id in config_ley["bloque_tema"]:
                subbloques = _subbloques_de_tema(db, coleccion_temario(oposicion), bloque_id, tema_id)
                if not subbloques:
                    continue
                propuesta = generar_propuesta_cambio(texto_nuevo, subbloques)
                if not propuesta:
                    continue
                if _existe_propuesta_pendiente_reciente(db, boe_id, propuesta["chunk_id_afectado"]):
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
