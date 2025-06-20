def validar_pregunta(p):
    if not isinstance(p, dict):
        return False

    if not p.get("pregunta") or not isinstance(p["pregunta"], str) or len(p["pregunta"].strip()) < 10:
        return False

    opciones = p.get("opciones", {})
    if not isinstance(opciones, dict) or len(opciones) != 4:
        return False

    for clave in ["A", "B", "C", "D"]:
        if clave not in opciones or not opciones[clave].strip():
            return False

    if p.get("respuesta_correcta") not in opciones:
        return False

    if not p.get("explicacion") or len(p["explicacion"].strip()) < 5:
        return False

    return True