"""Límites de uso de las herramientas de IA (PDF -> resumen/esquema/test/
tarjetas/chat), para que un usuario no pueda disparar el gasto en la API de
IA subiendo documentos enormes o llamando a las herramientas sin parar.

Dos capas de protección:
1. Un límite "duro" de páginas por documento, según el plan (para que nadie
   suba p. ej. un PDF de 3000 páginas), independiente del gasto de IA en sí
   (ese ya está acotado aparte truncando el texto que se manda al modelo).
2. Una cuota de usos por usuario y por plan, guardada en Firestore
   (usuarios/{uid}.limites_uso.{tipo} = {periodo, contador}). El periodo de
   la cuota (día o mes) depende del plan: Gratis/Básico tienen cuotas
   mensuales (fáciles de anunciar, tipo "20 documentos/mes"); Premium es
   "prácticamente ilimitado" de cara al cliente pero con un tope de
   seguridad diario para que un solo mal uso no dispare el gasto de golpe.
"""
from datetime import date

MAX_PAGINAS_POR_PLAN = {"gratis": 40, "basico": 200, "premium": 200}

# Cada entrada es (periodo, límite). periodo: "dia" o "mes".
LIMITES = {
    "pdf_ia": {
        "gratis": ("mes", 2),
        "basico": ("mes", 15),
        "premium": ("dia", 60),
    },
    "chat_pdf": {
        "gratis": ("mes", 0),
        "basico": ("mes", 30),
        "premium": ("dia", 40),
    },
    # Generación de tests/esquemas/análisis a partir del TEMARIO (no de un
    # PDF subido) -- /generar-test-avanzado, /generar-esquema,
    # /generar-test-inteligente, /analisis-rendimiento. Requieren plan
    # básico como mínimo (ver @requiere_plan de cada ruta), así que gratis
    # queda en 0 solo por coherencia con ese requisito.
    "generacion_ia": {
        "gratis": ("mes", 0),
        "basico": ("mes", 60),
        "premium": ("dia", 40),
    },
    # Chat conversacional "Tu Tutor" -- /tu-tutor.
    # Requiere plan premium (ver @requiere_plan de la ruta).
    "chat_temario": {
        "gratis": ("mes", 0),
        "basico": ("mes", 0),
        "premium": ("dia", 60),
    },
}


def max_paginas_para_plan(plan):
    return MAX_PAGINAS_POR_PLAN.get(plan, MAX_PAGINAS_POR_PLAN["gratis"])


def _clave_periodo(periodo):
    hoy = date.today()
    return hoy.strftime("%Y-%m") if periodo == "mes" else hoy.isoformat()


def verificar_limite_uso(db, uid, plan, tipo):
    """Comprueba si el usuario puede usar ahora mismo la herramienta `tipo`,
    sin incrementar todavía el contador (eso se hace en registrar_uso, solo
    si la llamada a la IA se llega a realizar). Devuelve
    (permitido, mensaje_error_o_None, usados, limite)."""
    config = LIMITES.get(tipo, {}).get(plan)
    if not config or config[1] <= 0:
        return False, "Tu plan actual no incluye esta herramienta.", 0, 0
    periodo, limite = config

    clave = _clave_periodo(periodo)
    doc = db.collection("usuarios").document(uid).get()
    datos = doc.to_dict() or {}
    uso = ((datos.get("limites_uso") or {}).get(tipo)) or {}
    usados = uso.get("contador", 0) if uso.get("periodo") == clave else 0

    if usados >= limite:
        if periodo == "dia":
            mensaje = f"Has alcanzado el límite de {limite} usos diarios para esta herramienta. Podrás volver a usarla mañana."
        else:
            mensaje = f"Has alcanzado el límite de {limite} usos mensuales para esta herramienta. Se renueva el próximo mes."
        return False, mensaje, usados, limite
    return True, None, usados, limite


def registrar_uso(db, uid, tipo, plan):
    """Suma 1 al contador del periodo actual. Se llama solo cuando la
    llamada a la IA se ha realizado de verdad (para no penalizar intentos
    que fallan antes, p. ej. un PDF sin texto extraíble)."""
    config = LIMITES.get(tipo, {}).get(plan)
    if not config:
        return
    periodo, _limite = config
    clave = _clave_periodo(periodo)
    ref = db.collection("usuarios").document(uid)
    doc = ref.get()
    datos = doc.to_dict() or {}
    uso = ((datos.get("limites_uso") or {}).get(tipo)) or {}
    usados = uso.get("contador", 0) if uso.get("periodo") == clave else 0
    ref.update({f"limites_uso.{tipo}": {"periodo": clave, "contador": usados + 1}})
