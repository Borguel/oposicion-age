"""Límites de uso de las herramientas de IA (PDF -> resumen/esquema/test/
tarjetas/chat), para que un usuario no pueda disparar el gasto en la API de
IA subiendo documentos enormes o llamando a las herramientas sin parar.

Dos capas de protección:
1. Un límite "duro" por documento (páginas / tamaño de fichero), igual para
   todo el mundo, para que nadie pueda subir p.ej. un PDF de 3000 páginas.
2. Una cuota diaria de usos por usuario, según su plan, guardada en
   Firestore (usuarios/{uid}.limites_uso.{tipo} = {fecha, contador}).
"""
from datetime import date

# Un tema/capítulo normal de oposición ronda las 10-40 páginas. 60 da margen
# de sobra para documentos largos legítimos sin permitir subir manuales
# enteros (y con ellos, un gasto de IA desproporcionado) de una sentada.
MAX_PAGINAS_PDF = 60

# Cuota diaria de generaciones (resumen/esquema/test/tarjetas desde PDF),
# por plan. Solo Premium tiene acceso a estas herramientas hoy (ver
# @requiere_plan en app.py), pero el límite ya queda listo por plan para
# cuando cambie esa regla.
LIMITES_DIARIOS = {
    "pdf_ia": {"gratis": 0, "basico": 0, "premium": 15},
    "chat_pdf": {"gratis": 0, "basico": 0, "premium": 40},
}


def limite_diario_para_plan(tipo, plan):
    return LIMITES_DIARIOS.get(tipo, {}).get(plan, 0)


def verificar_limite_uso(db, uid, plan, tipo):
    """Comprueba si el usuario puede usar hoy la herramienta `tipo` sin
    incrementar todavía el contador (eso se hace en registrar_uso, solo si
    la llamada a la IA se llega a realizar). Devuelve
    (permitido, mensaje_error_o_None, usados_hoy, limite_diario)."""
    limite = limite_diario_para_plan(tipo, plan)
    if limite <= 0:
        return False, "Tu plan actual no incluye esta herramienta.", 0, 0

    hoy = date.today().isoformat()
    doc = db.collection("usuarios").document(uid).get()
    datos = doc.to_dict() or {}
    uso = ((datos.get("limites_uso") or {}).get(tipo)) or {}
    usados_hoy = uso.get("contador", 0) if uso.get("fecha") == hoy else 0

    if usados_hoy >= limite:
        return (
            False,
            f"Has alcanzado el límite diario de {limite} usos para esta herramienta. "
            "Podrás volver a usarla mañana.",
            usados_hoy,
            limite,
        )
    return True, None, usados_hoy, limite


def registrar_uso(db, uid, tipo):
    """Suma 1 al contador de uso de hoy. Se llama solo cuando la llamada a
    la IA se ha realizado de verdad (para no penalizar intentos que fallan
    antes, p. ej. un PDF sin texto extraíble)."""
    hoy = date.today().isoformat()
    ref = db.collection("usuarios").document(uid)
    doc = ref.get()
    datos = doc.to_dict() or {}
    uso = ((datos.get("limites_uso") or {}).get(tipo)) or {}
    usados_hoy = uso.get("contador", 0) if uso.get("fecha") == hoy else 0
    ref.update({f"limites_uso.{tipo}": {"fecha": hoy, "contador": usados_hoy + 1}})
