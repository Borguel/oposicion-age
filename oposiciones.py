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
        # Formato real de la 1ª parte (cuestionario test) del ejercicio único,
        # según el Anexo III de la convocatoria 2025 (ver
        # datos_examenes/datos_convocatoria_AGE.json) -- usado para el botón
        # "Simulacro oficial" de un clic en /test-oficial/. La convocatoria no
        # fija un tiempo específico para esta primera parte por separado (el
        # límite de 100 minutos publicado es solo de la 2ª parte, el supuesto
        # práctico, que esta web no genera), así que "minutos" queda sin
        # valor real documentado en vez de inventarse uno.
        "simulacro_oficial": {"num_preguntas": 70, "minutos": None},
    },
    "GACE": {
        "nombre": "Cuerpo de Gestión de la Administración Civil del Estado (GACE, A2)",
        "coleccion_temario": "Temario GACE",
        # 1er ejercicio (test) según el Anexo VII de la convocatoria 2025
        # (ver datos_examenes/datos_convocatoria_GACE.json): 100 preguntas,
        # 90 minutos.
        "simulacro_oficial": {"num_preguntas": 100, "minutos": 90},
    },
    "AUXILIAR": {
        "nombre": "Cuerpo General Auxiliar de la Administración del Estado (Auxiliar, C2)",
        "coleccion_temario": "Temario Auxiliar",
        # Sin examen oficial cargado todavía (ver cargar_temario_auxiliar.py)
        # -- sin datos de convocatoria verificados, no se ofrece el botón.
        "simulacro_oficial": None,
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
