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
    o edición manual) tiene prioridad sobre la genérica por oposición."""
    propia = (aviso.get("url_inap") or "").strip()
    if propia:
        return propia
    return URL_INAP_POR_OPOSICION.get(aviso.get("oposicion"), _URL_INAP_GENERAL)


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


def generar_html_avisos(avisos):
    if not avisos:
        return '<p class="guia-avisos-oficiales-vacio">Todavía no hay avisos recientes para esta oposición.</p>'
    partes = []
    for aviso in avisos:
        tipo_legible = etiqueta_tipo_aviso(aviso)
        url_inap = url_inap_aviso(aviso)
        # Sin URL no hay enlace que valga -- un href="" parece un botón
        # roto en vez de simplemente no estar.
        enlace_boe = (
            f'<a href="{aviso.get("url_boe")}" target="_blank" rel="noopener">Ver la resolución oficial ↗</a>'
            if aviso.get("url_boe") else ""
        )
        enlace_inap = (
            f'<a href="{url_inap}" target="_blank" rel="noopener">Ver en INAP ↗</a>'
            if url_inap else ""
        )
        partes.append(f"""      <div class="guia-avisos-oficiales-item">
        <span class="guia-avisos-oficiales-tipo">{tipo_legible}</span>
        <p class="guia-avisos-oficiales-titulo">{aviso.get("titulo", "")}</p>
        <div class="guia-avisos-oficiales-enlaces">
          {enlace_boe}
          {enlace_inap}
        </div>
      </div>""")
    return "\n".join(partes)


def _consultar_avisos_publicados(db, oposicion, tope=5):
    avisos = []
    consulta = (
        db.collection("avisos_oficiales")
        .where("oposicion", "==", oposicion)
        .where("estado", "==", "publicado")
    )
    for doc in consulta.stream():
        avisos.append(doc.to_dict() or {})
    avisos.sort(key=lambda a: a.get("fecha_boe", ""), reverse=True)
    return avisos[:tope]


def actualizar_pagina_estatica_avisos(db, oposicion):
    """Regenera la sección de avisos oficiales de la página pública de esa
    oposición a partir de lo que hay publicado en Firestore ahora mismo.
    Nunca lanza excepción -- ver docstring del módulo (incluye la propia
    consulta a Firestore, no solo las llamadas a GitHub)."""
    ruta = RUTA_PAGINA_POR_OPOSICION.get(oposicion)
    if not ruta:
        return False

    try:
        sha, html_actual = _leer_archivo_github(ruta)
        if sha is None:
            return False
        if _MARCADOR_INICIO not in html_actual or _MARCADOR_FIN not in html_actual:
            logger.warning("No se encontraron los marcadores de avisos oficiales en %s", ruta)
            return False

        avisos = _consultar_avisos_publicados(db, oposicion)
        bloque_nuevo = f"{_MARCADOR_INICIO}\n{generar_html_avisos(avisos)}\n      {_MARCADOR_FIN}"

        antes, resto = html_actual.split(_MARCADOR_INICIO, 1)
        _, despues = resto.split(_MARCADOR_FIN, 1)
        html_nuevo = antes + bloque_nuevo + despues

        if html_nuevo == html_actual:
            return True  # ya estaba al día, no hace falta commitear nada

        return _escribir_archivo_github(
            ruta, sha, html_nuevo,
            f"Actualizar avisos oficiales publicados ({oposicion}) [automático]",
        )
    except Exception:
        logger.warning("Fallo inesperado actualizando la página estática de %s", oposicion, exc_info=True)
        return False


def notificar_usuarios_aviso_oficial(db, aviso):
    """Manda el email de aviso oficial a cada usuario que tiene esta
    oposición entre sus suscripciones o su actividad ya registrada. Nunca
    lanza excepción -- ver docstring del módulo."""
    oposicion = aviso.get("oposicion")
    if not oposicion:
        return 0
    nombre_oposicion = OPOSICIONES.get(oposicion, {}).get("nombre", oposicion)
    url_inap = url_inap_aviso(aviso)
    tipo_legible = etiqueta_tipo_aviso(aviso)

    enviados = 0
    try:
        for doc in db.collection("usuarios").stream():
            datos = doc.to_dict() or {}
            email = datos.get("email")
            if not email:
                continue
            le_afecta = oposicion in (datos.get("suscripciones") or {}) or oposicion in (datos.get("estadisticas") or {})
            if not le_afecta:
                continue
            enviar_email_aviso_oficial(
                email, aviso.get("titulo", ""), tipo_legible, aviso.get("url_boe", ""), url_inap,
                nombre_oposicion, nombre=datos.get("nombre", ""),
            )
            enviados += 1
    except Exception:
        logger.warning("Fallo inesperado notificando el aviso oficial de %s", oposicion, exc_info=True)
    return enviados
