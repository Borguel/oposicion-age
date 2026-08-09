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
        # Ejercicio único (ambas partes, ver datos_examenes/datos_convocatoria_AUXILIAR.json):
        # 60 preguntas (1ª parte: 30 del bloque I + 30 psicotécnicas) + 50
        # preguntas (2ª parte, bloque II) = 110 preguntas, 90 minutos para las
        # dos partes juntas. El frontend deja elegir si se incluyen o no las
        # psicotécnicas (ver utils.tiene_preguntas_psicotecnicas) antes de
        # lanzar el simulacro.
        "simulacro_oficial": {"num_preguntas": 110, "minutos": 90},
    },
    "METRO": {
        "nombre": "Agente de Movilidad - Metro de Madrid",
        "coleccion_temario": "Temario Metro",
        # Sin exámenes oficiales pasados cargados todavía (a diferencia de
        # AGE/GACE/Auxiliar) -- sin datos verificados no se ofrece el botón
        # "Simulacro oficial" (ver frontend/test-oficial/script.js, que
        # oculta el botón si este campo es None).
        "simulacro_oficial": None,
        # Oposición dada de alta solo para un grupo cerrado de usuarios (no
        # es una de las oposiciones de Estado en las que se basa la web).
        # No aparece en el selector público (frontend/assets/oposicion.js)
        # ni en /oposiciones-disponibles salvo para quien ya tenga una
        # entrada en suscripciones.METRO -- se activa a mano por usuario
        # desde el panel admin (PATCH /admin/api/usuarios/<uid>/plan).
        "oculta": True,
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


def coleccion_psicotecnico(oposicion):
    """Colección de la prueba psicotécnica (razonamiento verbal/espacial) de
    una oposición -- hoy solo Metro (ver cargar_psicotecnico_metro.py). Vive
    aparte de examenes_oficiales_<oposicion> a propósito: en Metro el
    ejercicio aptitudinal se hace COMPLETO Y POR SEPARADO del resto del
    proceso (nunca mezclado con preguntas de temario, a diferencia de
    Auxiliar -- ver utils.tiene_preguntas_psicotecnicas), así que tiene su
    propia página (/test-psicotecnico/) en vez de ser un filtro dentro de
    Test Oficial."""
    if not oposicion_valida(oposicion):
        oposicion = OPOSICION_POR_DEFECTO
    return f"psicotecnico_{oposicion}"
