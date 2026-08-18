"""Publicación pública de los avisos oficiales aprobados (ver
vigilancia_boe.py + blueprints/admin.py): en cuanto el dueño aprueba un
aviso desde el panel, aquí se hacen las dos cosas que lo llevan a que la
gente que busca en Google (o que ya es usuaria) se entere:

1. actualizar_pagina_estatica_avisos: reescribe -- vía la API REST de
   GitHub, sin depender de git/SSH en el proceso en marcha del backend --
   la sección de avisos de la página pública de esa oposición
   (frontend/oposicion-*/index.html), para que el contenido sea HTML real
   ya en el propio repo (mejor para SEO y para vistas previas en redes
   sociales que un bloque que solo carga por JavaScript). Un commit en la
   rama de despliegue dispara el redeploy automático del sitio estático,
   igual que un `git push` normal -- no hace falta ningún paso aparte.
2. notificar_usuarios_aviso_oficial: manda un email (ver
   email_utils.enviar_email_aviso_oficial) a los usuarios que tienen esa
   oposición entre sus suscripciones o su actividad ya registrada.

Ninguna de las dos debe romper nunca la aprobación del aviso en Firestore
si falla -- mismo espíritu que email_utils._enviar (nunca lanzan excepción
hacia quien llama, solo registran un aviso en el log)."""
import base64
import html
import logging
import os

import requests

from email_utils import enviar_email_aviso_oficial
from oposiciones import OPOSICIONES

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_OWNER = "Borguel"
_REPO = "oposicion-age"
_RAMA = "claude/exam-prep-web-platform-07flxz"
_TIMEOUT_SEGUNDOS = 15

_MARCADOR_INICIO = "<!-- AVISOS_OFICIALES_INICIO -->"
_MARCADOR_FIN = "<!-- AVISOS_OFICIALES_FIN -->"

# A qué página estática (ruta dentro del repo) corresponde cada oposición.
RUTA_PAGINA_POR_OPOSICION = {
    "AGE": "frontend/oposicion-administrativo-estado-c1/index.html",
    "GACE": "frontend/oposicion-gace/index.html",
    "AUXILIAR": "frontend/oposicion-auxiliar-administrativo-estado/index.html",
}

# Página común a las 3 oposiciones, con el histórico completo (resumen
# entero, no solo el título) -- para que un aviso no se "pierda" dentro de
# la página de una sola oposición, sobre todo los que afectan a varias.
RUTA_PAGINA_AVISOS_GENERAL = "frontend/avisos-oficiales/index.html"


def _oposiciones_de(aviso):
    """Oposiciones a las que afecta un aviso. Un aviso puede afectar a
    varias a la vez (p. ej. un llamamiente extraordinario que menciona al
    Cuerpo General Administrativo Y al de Gestión) -- se guarda como lista
    en "oposiciones". Los documentos antiguos, de antes de que existiera
    ese campo, solo tienen "oposicion" (una sola, en singular): se siguen
    leyendo igual de bien envolviéndola en una lista de un elemento."""
    lista = aviso.get("oposiciones")
    if lista:
        return list(lista)
    oposicion = aviso.get("oposicion")
    return [oposicion] if oposicion else []

# INAP no tiene API ni un esquema de URL estable por convocatoria concreta
# -- se enlaza a su página general de procesos selectivos como "ver en
# INAP", no a un enlace específico de este aviso.
_URL_INAP_GENERAL = "https://www.inap.es/es/seleccion/procesos-selectivos-de-cuerposescalas-generales"
URL_INAP_POR_OPOSICION = {op: _URL_INAP_GENERAL for op in RUTA_PAGINA_POR_OPOSICION}

ETIQUETA_TIPO_AVISO = {
    "convocatoria": "Convocatoria",
    "lista_admitidos": "Lista de admitidos",
    "tribunal": "Tribunal calificador",
    "fecha_examen": "Fecha de examen",
    # Distinto de "fecha_examen" a propósito: ese se reserva para la fecha
    # del ejercicio de la convocatoria oficial, mientras que un llamamiento
    # extraordinario es una repesca para un grupo reducido de aspirantes
    # concretos (ver el caso real que motivó esto: resolución de la
    # Comisión Permanente de Selección publicada solo en el INAP, no en el
    # BOE).
    "llamamiento_extraordinario": "Llamamiento extraordinario",
    "aprobados": "Relación de aprobados",
    # A diferencia de los demás tipos (detectados por el nombre literal del
    # cuerpo en el título), este lo genera la IA a partir de un título que
    # NO menciona ningún cuerpo pero sí términos genéricos de Administración
    # / empleo público (ver vigilancia_boe._clasificar_relevancia_temario_con_ia)
    # -- se etiqueta distinto para que el dueño sepa que necesita más
    # revisión que un aviso detectado por palabra clave exacta.
    "posible_relevancia_temario": "Posible novedad (revisar)",
    "otro": "Aviso oficial",
}


def etiqueta_tipo_aviso(aviso):
    """Texto a mostrar como "tipo" del aviso: si se rellenó un tipo
    personalizado a mano (alta manual, cuando ninguna de las opciones fijas
    encajaba) tiene prioridad sobre la etiqueta fija de ETIQUETA_TIPO_AVISO."""
    personalizado = (aviso.get("tipo_personalizado") or "").strip()
    if personalizado:
        return personalizado
    return ETIQUETA_TIPO_AVISO.get(aviso.get("tipo"), ETIQUETA_TIPO_AVISO["otro"])


def url_inap_aviso(aviso):
    """URL de "ver en INAP" para este aviso: si se indicó una a mano (alta
    o edición manual) tiene prioridad sobre la genérica por oposición (que
    hoy es la misma para las 3, así que da igual cuál de las oposiciones
    afectadas se use para mirarla)."""
    propia = (aviso.get("url_inap") or "").strip()
    if propia:
        return propia
    oposiciones = _oposiciones_de(aviso)
    primera = oposiciones[0] if oposiciones else None
    return URL_INAP_POR_OPOSICION.get(primera, _URL_INAP_GENERAL)


def etiquetas_oposiciones_aviso(aviso):
    """Siglas ("AGE", "GACE"...) de las oposiciones a las que afecta el
    aviso, para mostrar como etiquetas -- solo hace falta en la página
    común a las 3 (en la página de una sola oposición ya es obvio en qué
    oposición estás)."""
    return _oposiciones_de(aviso)


def _cabeceras():
    token = os.getenv("GITHUB_TOKEN")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


def _leer_archivo_github(ruta):
    """Devuelve (sha, texto) del archivo en la rama de despliegue, o
    (None, None) si algo falla (sin token, red, 404...)."""
    if not os.getenv("GITHUB_TOKEN"):
        logger.warning("GITHUB_TOKEN no configurado: no se puede leer/actualizar %s", ruta)
        return None, None
    try:
        resp = requests.get(
            f"{_GITHUB_API}/repos/{_OWNER}/{_REPO}/contents/{ruta}",
            headers=_cabeceras(), params={"ref": _RAMA}, timeout=_TIMEOUT_SEGUNDOS,
        )
        resp.raise_for_status()
        datos = resp.json()
        texto = base64.b64decode(datos["content"]).decode("utf-8")
        return datos["sha"], texto
    except Exception:
        logger.warning("No se pudo leer %s desde GitHub", ruta, exc_info=True)
        return None, None


def _escribir_archivo_github(ruta, sha, contenido, mensaje):
    """Intenta el commit; nunca lanza excepción. True si se hizo, False si
    no (sin token, red, o 409 por conflicto de sha con otro commit
    mientras tanto -- se reintentará solo la próxima vez que se apruebe
    algo para esa oposición)."""
    if not os.getenv("GITHUB_TOKEN"):
        return False
    try:
        payload = {
            "message": mensaje,
            "content": base64.b64encode(contenido.encode("utf-8")).decode("ascii"),
            "sha": sha,
            "branch": _RAMA,
        }
        resp = requests.put(
            f"{_GITHUB_API}/repos/{_OWNER}/{_REPO}/contents/{ruta}",
            headers=_cabeceras(), json=payload, timeout=_TIMEOUT_SEGUNDOS,
        )
        resp.raise_for_status()
        return True
    except Exception:
        logger.warning("No se pudo escribir %s en GitHub", ruta, exc_info=True)
        return False


def _tarjeta_aviso_html(aviso, mostrar_etiquetas_oposicion=False, mostrar_resumen=False):
    # Este HTML se comitea tal cual a páginas ESTÁTICAS públicas (ver
    # actualizar_pagina_estatica_avisos/actualizar_pagina_avisos_general),
    # servidas a cualquier visitante -- titulo/resumen/tipo_personalizado
    # los puede escribir cualquier cuenta con el permiso "reportes" (no
    # hace falta ser super-admin, ver requiere_permiso("reportes") en
    # blueprints/admin.py), y url_boe/url_inap pueden venir de una alta
    # manual. html.escape() en cada valor evita que ese texto libre inyecte
    # HTML/rompa un atributo -- quote=True (por defecto) escapa también las
    # comillas, necesario para los que van dentro de href="..."/data-...="...".
    tipo_legible = html.escape(etiqueta_tipo_aviso(aviso))
    url_inap = html.escape(url_inap_aviso(aviso))
    url_boe = html.escape(aviso.get("url_boe") or "")
    # Sin URL no hay enlace que valga -- un href="" parece un botón roto
    # en vez de simplemente no estar.
    enlace_boe = (
        f'<a href="{url_boe}" target="_blank" rel="noopener">Ver la resolución oficial ↗</a>'
        if url_boe else ""
    )
    enlace_inap = (
        f'<a href="{url_inap}" target="_blank" rel="noopener">Ver en INAP ↗</a>'
        if url_inap else ""
    )
    etiquetas_op = ""
    if mostrar_etiquetas_oposicion:
        etiquetas_op = "".join(
            f'<span class="guia-avisos-oficiales-op">{html.escape(op)}</span>' for op in etiquetas_oposiciones_aviso(aviso)
        )
    resumen_html = ""
    if mostrar_resumen:
        resumen = (aviso.get("resumen") or "").strip()
        titulo = (aviso.get("titulo") or "").strip()
        # Si el resumen es literalmente el título (lo por defecto cuando no
        # se rellenó ninguno propio) no aporta nada repetirlo aparte.
        if resumen and resumen != titulo:
            resumen_html = f'<p class="guia-avisos-oficiales-resumen">{html.escape(resumen)}</p>'
    # data-oposiciones: para el filtro por oposición de la página común
    # (ver /avisos-oficiales/) -- en las páginas de una sola oposición no
    # se usa, pero no estorba tenerlo siempre.
    oposiciones_dato = html.escape(" ".join(_oposiciones_de(aviso)))
    titulo_html = html.escape(aviso.get("titulo") or "")
    return f"""      <div class="guia-avisos-oficiales-item" data-oposiciones="{oposiciones_dato}">
        <div class="guia-avisos-oficiales-cab">
          <span class="guia-avisos-oficiales-tipo">{tipo_legible}</span>
          {etiquetas_op}
        </div>
        <p class="guia-avisos-oficiales-titulo">{titulo_html}</p>
        {resumen_html}
        <div class="guia-avisos-oficiales-enlaces">
          {enlace_boe}
          {enlace_inap}
        </div>
      </div>"""


def generar_html_avisos(avisos):
    """Sección de avisos dentro de la página de UNA oposición concreta:
    solo título + enlaces (el resumen completo y las etiquetas de qué
    oposiciones afecta viven en la página común, ver
    generar_html_avisos_hub) y un enlace a esa página común al final."""
    cuerpo = (
        "\n".join(_tarjeta_aviso_html(a) for a in avisos)
        if avisos
        else '<p class="guia-avisos-oficiales-vacio">Todavía no hay avisos recientes para esta oposición.</p>'
    )
    enlace_hub = (
        '<p class="guia-avisos-oficiales-vertodos">'
        '<a href="/avisos-oficiales/">Ver todos los avisos oficiales ↗</a></p>'
    )
    return f"{cuerpo}\n      {enlace_hub}"


def generar_html_avisos_hub(avisos):
    """Página común a las 3 oposiciones: mismas tarjetas pero con el
    resumen completo y una etiqueta por cada oposición afectada (aquí sí
    hace falta, a diferencia de la página de una sola oposición)."""
    if not avisos:
        return '<p class="guia-avisos-oficiales-vacio">Todavía no hay avisos oficiales publicados.</p>'
    return "\n".join(
        _tarjeta_aviso_html(a, mostrar_etiquetas_oposicion=True, mostrar_resumen=True) for a in avisos
    )


def _consultar_avisos_publicados(db, oposicion, tope=5):
    """Los "publicado" en Firestore no se pueden filtrar por oposición en
    la propia consulta (no hay índice de array-contains configurado, y la
    colección es pequeña) -- se trae todo lo publicado y se filtra aquí."""
    avisos = [
        d for d in (
            (doc.to_dict() or {}) for doc in db.collection("avisos_oficiales").where("estado", "==", "publicado").stream()
        )
        if oposicion in _oposiciones_de(d)
    ]
    avisos.sort(key=lambda a: a.get("fecha_boe", ""), reverse=True)
    return avisos[:tope]


def _consultar_avisos_publicados_todos(db, tope=30):
    avisos = [doc.to_dict() or {} for doc in db.collection("avisos_oficiales").where("estado", "==", "publicado").stream()]
    avisos.sort(key=lambda a: a.get("fecha_boe", ""), reverse=True)
    return avisos[:tope]


def _regenerar_pagina(ruta, avisos, generador_html, mensaje):
    """Lee, sustituye entre marcadores y comitea si hace falta -- usado
    tanto por la página de una oposición como por la página común. Nunca
    lanza excepción -- ver docstring del módulo."""
    try:
        sha, html_actual = _leer_archivo_github(ruta)
        if sha is None:
            return False
        if _MARCADOR_INICIO not in html_actual or _MARCADOR_FIN not in html_actual:
            logger.warning("No se encontraron los marcadores de avisos oficiales en %s", ruta)
            return False

        bloque_nuevo = f"{_MARCADOR_INICIO}\n{generador_html(avisos)}\n      {_MARCADOR_FIN}"
        antes, resto = html_actual.split(_MARCADOR_INICIO, 1)
        _, despues = resto.split(_MARCADOR_FIN, 1)
        html_nuevo = antes + bloque_nuevo + despues

        if html_nuevo == html_actual:
            return True  # ya estaba al día, no hace falta commitear nada

        return _escribir_archivo_github(ruta, sha, html_nuevo, mensaje)
    except Exception:
        logger.warning("Fallo inesperado actualizando la página estática %s", ruta, exc_info=True)
        return False


def actualizar_pagina_estatica_avisos(db, oposicion):
    """Regenera la sección de avisos oficiales de la página pública de esa
    oposición a partir de lo que hay publicado en Firestore ahora mismo."""
    ruta = RUTA_PAGINA_POR_OPOSICION.get(oposicion)
    if not ruta:
        return False
    avisos = _consultar_avisos_publicados(db, oposicion)
    return _regenerar_pagina(
        ruta, avisos, generar_html_avisos,
        f"Actualizar avisos oficiales publicados ({oposicion}) [automático]",
    )


def actualizar_pagina_avisos_general(db):
    """Regenera la página común a las 3 oposiciones (histórico completo,
    con el resumen entero de cada aviso) -- se llama junto a
    actualizar_pagina_estatica_avisos cada vez que se publica o corrige un
    aviso, para que nunca se quede desactualizada respecto a las 3
    páginas por oposición."""
    avisos = _consultar_avisos_publicados_todos(db)
    return _regenerar_pagina(
        RUTA_PAGINA_AVISOS_GENERAL, avisos, generar_html_avisos_hub,
        "Actualizar página de avisos oficiales [automático]",
    )


def notificar_usuarios_aviso_oficial(db, aviso):
    """Manda el email de aviso oficial a cada usuario que tiene CUALQUIERA
    de las oposiciones afectadas entre sus suscripciones o su actividad ya
    registrada (una sola vez por usuario, aunque coincida en varias).
    Nunca lanza excepción -- ver docstring del módulo."""
    oposiciones = _oposiciones_de(aviso)
    if not oposiciones:
        return 0
    nombre_oposicion = " y ".join(OPOSICIONES.get(op, {}).get("nombre", op) for op in oposiciones)
    url_inap = url_inap_aviso(aviso)
    tipo_legible = etiqueta_tipo_aviso(aviso)

    enviados = 0
    try:
        for doc in db.collection("usuarios").stream():
            datos = doc.to_dict() or {}
            email = datos.get("email")
            if not email:
                continue
            le_afecta = any(
                op in (datos.get("suscripciones") or {}) or op in (datos.get("estadisticas") or {})
                for op in oposiciones
            )
            if not le_afecta:
                continue
            enviar_email_aviso_oficial(
                email, aviso.get("titulo", ""), tipo_legible, aviso.get("url_boe", ""), url_inap,
                nombre_oposicion, nombre=datos.get("nombre", ""),
            )
            enviados += 1
    except Exception:
        logger.warning("Fallo inesperado notificando el aviso oficial de %s", oposiciones, exc_info=True)
    return enviados
