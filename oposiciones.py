"""Catálogo de oposiciones soportadas por la web.

Añadir una oposición nueva (tras subir su temario con cargar_temario_boe.py)
es solo cuestión de añadir una entrada aquí con el nombre de su colección de
Firestore -- todo el backend (rutas, generación de tests, chat, Stripe) usa
este catálogo en vez de tener "Temario AGE" escrito a fuego.
"""

OPOSICIONES = {
    "AGE": {
        "nombre": "Cuerpo General Administrativo del Estado (AGE, C1)",
        "coleccion_temario": "Temario AGE",
    },
    "GACE": {
        "nombre": "Cuerpo de Gestión de la Administración Civil del Estado (GACE, A2)",
        "coleccion_temario": "Temario GACE",
    },
}

OPOSICION_POR_DEFECTO = "AGE"


def oposicion_valida(oposicion):
    return oposicion in OPOSICIONES


def coleccion_temario(oposicion):
    datos = OPOSICIONES.get(oposicion) or OPOSICIONES[OPOSICION_POR_DEFECTO]
    return datos["coleccion_temario"]


def coleccion_examenes_oficiales(oposicion):
    if not oposicion_valida(oposicion):
        oposicion = OPOSICION_POR_DEFECTO
    return f"examenes_oficiales_{oposicion}"
