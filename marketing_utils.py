"""Sincronización de contactos con las listas de marketing de Brevo (Contactos
-> Listas), separada del envío de emails transaccionales (email_utils.py).

Etiqueta cada contacto con su oposición (AGE/GACE/Auxiliar) y con su fase
del embudo de suscripción (prueba, activo, pago fallido, sin suscripción),
para poder montar una campaña de marketing dirigida a un segmento concreto
desde el propio panel de Brevo sin tener que exportar nada a mano. Las
listas se crean solas en Brevo la primera vez que hacen falta.

Igual que en email_utils.py: si BREVO_API_KEY no está configurada, o la
sincronización falla (red, cuota, permisos), no se lanza ninguna excepción
hacia quien llama -- ninguna acción del usuario (registro, alta de
suscripción, impago...) debe romperse porque Brevo no esté disponible."""
import logging
import os

import requests

logger = logging.getLogger(__name__)

BREVO_CONTACTS_URL = "https://api.brevo.com/v3/contacts"
BREVO_LISTS_URL = "https://api.brevo.com/v3/contacts/lists"

# Nombre de la lista de Brevo por oposición -- coincide con las 3 soportadas
# en oposiciones.py.
LISTAS_OPOSICION = {
    "AGE": "Opositores · AGE (C1)",
    "GACE": "Opositores · GACE (A2)",
    "AUXILIAR": "Opositores · Auxiliar (C2)",
}

# Fases del embudo de suscripción. Un contacto pertenece como mucho a una de
# estas 4 listas a la vez (ver _listas_estado_a_quitar): entrar en una lo
# saca de las demás, para que una campaña dirigida a "sin_suscripcion" (p.ej.
# un win-back) no incluya por error a quien ya es suscriptor activo.
LISTAS_ESTADO = {
    "prueba": "Embudo · Prueba gratuita",
    "activo": "Embudo · Suscriptor activo",
    "pago_fallido": "Embudo · Pago fallido",
    "sin_suscripcion": "Embudo · Sin suscripción",
}

_cache_listas = {}  # nombre de lista de Brevo -> id numérico


def _id_carpeta():
    # Todas las listas de marketing viven en la misma carpeta de Brevo
    # (Contactos -> Listas). El id 1 es el de la carpeta por defecto que
    # Brevo crea sola en cualquier cuenta nueva; se puede sobrescribir con
    # BREVO_MARKETING_FOLDER_ID si en tu cuenta esa carpeta tiene otro id.
    return int(os.getenv("BREVO_MARKETING_FOLDER_ID", "1"))


def _headers():
    api_key = os.getenv("BREVO_API_KEY")
    if not api_key:
        return None
    return {"api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"}


def _id_lista(nombre, headers):
    """Id numérico de una lista de Brevo por su nombre, creándola en
    BREVO_MARKETING_FOLDER_ID si todavía no existe. Cachea el resultado en
    memoria del proceso -- las listas de marketing no cambian de nombre en
    caliente, así que no hace falta consultarlas en cada sincronización."""
    if nombre in _cache_listas:
        return _cache_listas[nombre]

    offset = 0
    while True:
        respuesta = requests.get(BREVO_LISTS_URL, headers=headers, params={"limit": 50, "offset": offset}, timeout=10)
        respuesta.raise_for_status()
        listas = respuesta.json().get("lists", [])
        for lista in listas:
            _cache_listas[lista["name"]] = lista["id"]
        if nombre in _cache_listas:
            return _cache_listas[nombre]
        if len(listas) < 50:
            break
        offset += 50

    creada = requests.post(BREVO_LISTS_URL, headers=headers, json={"name": nombre, "folderId": _id_carpeta()}, timeout=10)
    creada.raise_for_status()
    lista_id = creada.json()["id"]
    _cache_listas[nombre] = lista_id
    return lista_id


def sincronizar_contacto(email, *, nombre=None, oposicion=None, estado=None):
    """Da de alta o actualiza el contacto de marketing en Brevo.

    `oposicion` (AGE/GACE/AUXILIAR) lo añade a la lista de esa oposición sin
    tocar su fase del embudo. `estado` (una clave de LISTAS_ESTADO) lo mueve
    a la lista de esa fase y lo saca de las otras tres. Los dos parámetros
    son independientes entre sí y opcionales: se puede llamar solo con uno
    de los dos (p.ej. un cambio de fase sin oposición conocida)."""
    if not email:
        return
    headers = _headers()
    if not headers:
        logger.warning("BREVO_API_KEY no configurada: no se sincroniza el contacto de marketing")
        return

    try:
        listas_a_anadir = []
        listas_a_quitar = []

        if oposicion and oposicion in LISTAS_OPOSICION:
            listas_a_anadir.append(_id_lista(LISTAS_OPOSICION[oposicion], headers))

        if estado and estado in LISTAS_ESTADO:
            listas_a_anadir.append(_id_lista(LISTAS_ESTADO[estado], headers))
            for otro_estado, otro_nombre in LISTAS_ESTADO.items():
                if otro_estado != estado:
                    listas_a_quitar.append(_id_lista(otro_nombre, headers))

        atributos = {}
        if nombre:
            atributos["NOMBRE"] = nombre
        if oposicion:
            atributos["OPOSICION"] = oposicion
        if estado:
            atributos["ESTADO_MARKETING"] = estado

        payload = {"email": email, "updateEnabled": True}
        if atributos:
            payload["attributes"] = atributos
        if listas_a_anadir:
            payload["listIds"] = listas_a_anadir
        if listas_a_quitar:
            payload["unlinkListIds"] = listas_a_quitar

        respuesta = requests.post(BREVO_CONTACTS_URL, headers=headers, json=payload, timeout=10)
        if respuesta.status_code >= 300:
            logger.warning("Error sincronizando contacto de marketing (%s): %s", respuesta.status_code, respuesta.text[:300])
    except Exception:
        logger.exception("Excepción sincronizando el contacto de marketing %s", email)
