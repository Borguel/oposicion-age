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

from utils import ejecutar_en_transaccion

MAX_PAGINAS_POR_PLAN = {"gratis": 50, "basico": 300, "premium": 500}

# Cada entrada es (periodo, límite). periodo: "dia" o "mes".
#
# Filosofía de cupos: en básico y premium todo cuenta POR DÍA (cupos
# generosos que se renuevan cada 24 h, no un tope mensual estrecho). Son
# topes anti-abuso, no el uso esperado: un usuario normal gasta una
# fracción. El coste real de IA es bajo (un test personalizado de 100
# preguntas ~0,10 € en el peor caso, y menos con la caché de DeepSeek), así
# que se prioriza que el usuario de pago no se choque con el límite en su
# uso diario real. El plan gratis se mantiene como muestra reducida.
LIMITES = {
    "pdf_ia": {
        "gratis": ("mes", 3),
        "basico": ("dia", 10),
        "premium": ("dia", 100),
    },
    "chat_pdf": {
        "gratis": ("mes", 0),
        "basico": ("dia", 25),
        "premium": ("dia", 80),
    },
    # Generación de esquemas/análisis a partir del TEMARIO (no de un PDF
    # subido) -- /generar-esquema, /generar-test-inteligente (hoy
    # desactivado en la web, pero la ruta sigue existiendo),
    # /analisis-rendimiento. Requieren plan básico como mínimo (ver
    # @requiere_plan de cada ruta), así que gratis queda en 0 solo por
    # coherencia con ese requisito.
    "generacion_ia": {
        "gratis": ("mes", 0),
        "basico": ("dia", 15),
        "premium": ("dia", 60),
    },
    # Test Personalizado con verificación jurídica (/generar-test-avanzado):
    # cada pregunta cuesta entre 2 y 8 llamadas a DeepSeek (generar +
    # verificar, con reintentos si no supera la verificación), muy por
    # encima del coste de una generación normal -- de ahí un cupo propio y
    # algo más ajustado que el resto, aunque también generoso.
    "test_avanzado_verificado": {
        "gratis": ("mes", 0),
        "basico": ("dia", 3),
        "premium": ("dia", 12),
    },
    # Chat conversacional "Tu Tutor" -- /tu-tutor.
    # Requiere plan premium (ver @requiere_plan de la ruta), por eso básico
    # se queda en 0 (la ruta ni siquiera deja entrar sin premium).
    "chat_temario": {
        "gratis": ("mes", 0),
        "basico": ("mes", 0),
        "premium": ("dia", 100),
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
    que fallan antes, p. ej. un PDF sin texto extraíble).

    Lectura (contador actual, con su posible reinicio de periodo) y
    escritura (contador+1) van dentro de la misma transacción de Firestore
    -- sin esto, dos peticiones concurrentes del mismo usuario (dos
    pestañas, un reintento del frontend) podían leer el mismo contador y
    perder un incremento, dejando que se superase la cuota."""
    config = LIMITES.get(tipo, {}).get(plan)
    if not config:
        return
    periodo, _limite = config
    clave = _clave_periodo(periodo)
    ref = db.collection("usuarios").document(uid)

    def _incrementar(transaction):
        doc = ref.get(transaction=transaction)
        datos = doc.to_dict() or {}
        uso = ((datos.get("limites_uso") or {}).get(tipo)) or {}
        usados = uso.get("contador", 0) if uso.get("periodo") == clave else 0
        transaction.update(ref, {f"limites_uso.{tipo}": {"periodo": clave, "contador": usados + 1}})

    ejecutar_en_transaccion(db, _incrementar)


def devolver_uso(db, uid, tipo, plan):
    """Resta 1 al contador del periodo actual (nunca por debajo de 0). Se usa
    en las rutas de streaming (SSE), donde el uso se cobra por ADELANTADO --
    antes de abrir el stream-- porque la generación corre en un hilo de fondo
    que sigue gastando en la API aunque el cliente corte la conexión, así que
    esperar al final para cobrar dejaba un hueco para saltarse la cuota
    abriendo y abortando la petición en bucle. Si esa generación acaba
    fallando de verdad (no produce nada), se devuelve el uso aquí.

    Ojo: NO se devuelve cuando el cliente simplemente corta la conexión a
    mitad -- en ese caso el trabajo (y el gasto real en la API) ya se ha
    hecho, así que el uso se mantiene consumido a propósito.

    Lectura y escritura van en la misma transacción, igual que registrar_uso,
    para no perder un decremento frente a otra petición concurrente."""
    config = LIMITES.get(tipo, {}).get(plan)
    if not config:
        return
    periodo, _limite = config
    clave = _clave_periodo(periodo)
    ref = db.collection("usuarios").document(uid)

    def _decrementar(transaction):
        doc = ref.get(transaction=transaction)
        datos = doc.to_dict() or {}
        uso = ((datos.get("limites_uso") or {}).get(tipo)) or {}
        # Si el periodo ya rotó (p. ej. cambió el día entre cobro y
        # devolución), no se toca: ese contador es de otro periodo.
        if uso.get("periodo") != clave:
            return
        usados = uso.get("contador", 0)
        transaction.update(ref, {f"limites_uso.{tipo}": {"periodo": clave, "contador": max(0, usados - 1)}})

    ejecutar_en_transaccion(db, _decrementar)
