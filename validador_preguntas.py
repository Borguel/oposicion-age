
def es_pregunta_valida(pregunta):
    if not isinstance(pregunta, dict):
        return False

    claves = ["pregunta", "opciones", "respuesta_correcta", "explicacion"]
    if not all(clave in pregunta for clave in claves):
        return False

    if not isinstance(pregunta["opciones"], dict):
        return False

    opciones = pregunta["opciones"]
    if not all(opcion in opciones for opcion in ["A", "B", "C", "D"]):
        return False

    return True
