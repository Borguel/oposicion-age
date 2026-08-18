"""Límites de uso de las herramientas de IA (PDF -> resumen/esquema/test/
tarjetas/chat), para que un usuario no pueda disparar el gasto en la API de
IA subiendo documentos enormes o llamando a las herramientas sin parar.

Dos capas de protección:
1. Un límite "duro" de páginas por documento, según el plan (para que nadie
   suba p. ej. un PDF de 3000 páginas), independiente del gasto de IA en sí
   (ese ya está acotado aparte truncando el texto que se manda al modelo).
2. Una cuota de usos por usuario y por plan, guardada en Firestore
   (usuarios/{uid}.limites_uso.{tipo} = {periodo, contador}).

Ya no existe un plan "gratis" permanente (sustituido por una prueba de
Premium de 7 días, ver planes.py) -- ninguna ruta puede resolver ya a ese
plan sin ser bloqueada antes por requiere_plan, así que estos diccionarios
solo tienen "basico"/"premium".
"""
import time
from datetime import date

from utils import ejecutar_en_transaccion

MAX_PAGINAS_POR_PLAN = {"basico": 200, "premium": 200}

# Cada entrada es (periodo, límite). periodo: "dia" o "mes".
#
# Filosofía de cupos: Básico se queda deliberadamente corto y VISIBLE (el
# frontend sí enseña estos números, a diferencia de antes) para que se note
# la limitación frente a Premium, presentado de cara al usuario como
# "ilimitado" aunque internamente siga topado por seguridad de coste (el
# coste real de IA es bajo -- un test personalizado de 100 preguntas ~0,10 €
# en el peor caso -- así que el tope de premium es solo anti-abuso, no el
# uso esperado).
LIMITES = {
    # Herramientas de PDF propio y chat -- exclusivas de Premium (ver
    # @requiere_plan de cada ruta en pdf_ia.py), básico se queda a 0 por
    # coherencia con eso.
    "pdf_ia": {
        "basico": ("dia", 0),
        "premium": ("dia", 100),
    },
    "chat_pdf": {
        "basico": ("dia", 0),
        "premium": ("dia", 80),
    },
    # Análisis de rendimiento con IA a partir del TEMARIO (/analisis-rendimiento).
    # Básico se mide en MES (no en día): un cupo bajo pero de uso ocasional,
    # no algo que se consulte a diario.
    "analisis_ia": {
        "basico": ("mes", 20),
        "premium": ("dia", 60),
    },
    # Test Oficial (/generar-test-oficial): no llama a ninguna IA (lee del
    # banco de preguntas ya cargado), pero igualmente se topa por día para
    # que no se generen tests en bucle sin límite. Premium se deja con un
    # techo alto (no es un cupo real, es anti-abuso).
    "test_oficial": {
        "basico": ("dia", 50),
        "premium": ("dia", 1000),
    },
    # Test Personalizado con verificación jurídica (/generar-test-avanzado):
    # cada pregunta cuesta entre 2 y 8 llamadas a DeepSeek. A DIFERENCIA del
    # resto, el cupo aquí se mide en PREGUNTAS/día, no en "número de tests":
    # así un test de 100 preguntas gasta 100 y uno de 10 gasta 10, y no es lo
    # mismo (antes ambos contaban como "1 uso", lo cual era injusto).
    "test_avanzado_verificado": {
        "basico": ("dia", 50),
        "premium": ("dia", 1500),
    },
    # Tope MENSUAL adicional para el mismo Test Personalizado -- se
    # comprueba y se cobra en paralelo al cupo diario de arriba (ver
    # blueprints/test_ia.py), como una segunda cuenta independiente sobre
    # el mismo consumo en preguntas. El de premium es simplemente su cupo
    # diario x30 (nunca supone una restricción real, igual que el resto de
    # topes de premium).
    "test_avanzado_verificado_mensual": {
        "basico": ("mes", 400),
        "premium": ("mes", 45000),
    },
    # Chat conversacional "Tu Tutor" -- /tu-tutor.
    # Requiere plan premium (ver @requiere_plan de la ruta), por eso básico
    # se queda en 0 (la ruta ni siquiera deja entrar sin premium).
    "chat_temario": {
        "basico": ("dia", 0),
        "premium": ("dia", 100),
    },
    # Tope MENSUAL de documentos NUEVOS SUBIDOS (no de usos de herramienta:
    # ver el comentario largo en blueprints/pdf_ia._resolver_texto_documento,
    # a petición explícita del usuario 17/08/2026 -- "lo que quiero limitar
    # es la subida del documento, no cada herramienta que uses sobre él").
    # Se comprueba y se cobra SOLO cuando un PDF resulta ser un documento
    # que el usuario nunca había subido antes (mismo hash de texto);
    # generar resumen, esquema, banco de preguntas o banco de tarjetas
    # sobre un documento YA subido no lo toca, por muchas veces que se use.
    # Nombre histórico "banco_pdf_mensual" (antes solo cubría banco de
    # preguntas/tarjetas por-uso, cambiado el mismo día a por-subida) --
    # se mantiene para no romper documentos ya guardados en Firestore con
    # este campo. Como red de seguridad de margen frente a la subida de
    # precio de DeepSeek del 16/08/2026; es el número (20) que se anuncia
    # en /planes como "20 documentos al mes".
    "banco_pdf_mensual": {
        "basico": ("mes", 0),
        "premium": ("mes", 20),
    },
}


# Etiquetas legibles de cada herramienta, para pintarlas en el panel de
# administración (pestaña "Límites"). El orden es el de la interfaz.
TIPOS_META = [
    {"id": "test_oficial", "nombre": "Test Oficial", "unidad": "preguntas",
     "descripcion": "Se mide en PREGUNTAS al día, igual que el Test Personalizado."},
    {"id": "test_avanzado_verificado", "nombre": "Test Personalizado (cupo diario)", "unidad": "preguntas",
     "descripcion": "Se mide en PREGUNTAS al día (no en nº de tests): un test de 100 gasta 100 y uno de 10 gasta 10, así el consumo es justo. El usuario no ve este contador."},
    {"id": "test_avanzado_verificado_mensual", "nombre": "Test Personalizado (tope mensual)", "unidad": "preguntas",
     "descripcion": "Tope adicional en preguntas AL MES, aparte del cupo diario de arriba -- ambos se comprueban a la vez."},
    {"id": "analisis_ia", "nombre": "Análisis de rendimiento con IA", "unidad": "usos",
     "descripcion": "Análisis de fortalezas/debilidades por tema, generado con IA, a partir del temario."},
    {"id": "pdf_ia", "nombre": "Subir PDF (resumen / esquema / tarjetas / test)", "unidad": "usos",
     "descripcion": "Herramientas de IA sobre un PDF que sube el propio usuario."},
    {"id": "banco_pdf_mensual", "nombre": "Documentos nuevos subidos (tope mensual)", "unidad": "documentos",
     "descripcion": "Tope AL MES de documentos NUEVOS subidos (no de usos de herramienta) -- reutilizar un documento ya subido en resumen/esquema/banco de preguntas/banco de tarjetas no lo consume, por muchas veces que se use. Es el \"20 documentos al mes\" que se anuncia en /planes."},
    {"id": "chat_pdf", "nombre": "Chat con PDF", "unidad": "usos",
     "descripcion": "Conversar con la IA sobre un PDF subido."},
    {"id": "chat_temario", "nombre": "Tu Tutor (chat del temario)", "unidad": "usos",
     "descripcion": "Chat conversacional del temario. Solo disponible en premium."},
]
_PLANES = ("basico", "premium")

# ---------------------------------------------------------------------------
# Límites efectivos: los valores de arriba (LIMITES / MAX_PAGINAS_POR_PLAN)
# son los DEFECTO; el panel admin puede sobrescribirlos guardándolos en
# config/limites. Se cachean unos segundos para no leer Firestore en cada
# comprobación de cuota.
# ---------------------------------------------------------------------------
_TTL_CACHE_S = 30
_cache_limites = {"data": None, "ts": 0.0}


def invalidar_cache_limites():
    """Fuerza recargar los límites de Firestore en la próxima consulta (se
    llama tras guardarlos desde el panel)."""
    _cache_limites["data"] = None


def _estructura_defecto():
    tools = {
        tipo: {plan: {"periodo": cfg[plan][0], "limite": cfg[plan][1]} for plan in _PLANES}
        for tipo, cfg in LIMITES.items()
    }
    return {"tools": tools, "max_paginas": dict(MAX_PAGINAS_POR_PLAN)}


def _fusionar_overrides(guardado):
    """Parte de los defaults y superpone SOLO valores válidos y conocidos del
    documento guardado -- así, si en el código se añade una herramienta nueva,
    aparece aunque el doc guardado sea antiguo, y valores raros se ignoran."""
    base = _estructura_defecto()
    if not guardado:
        return base
    for tipo, planes in (guardado.get("tools") or {}).items():
        if tipo not in base["tools"]:
            continue
        for plan, cfg in (planes or {}).items():
            if plan not in base["tools"][tipo]:
                continue
            per = (cfg or {}).get("periodo")
            lim = (cfg or {}).get("limite")
            if per in ("dia", "mes") and isinstance(lim, (int, float)) and not isinstance(lim, bool):
                base["tools"][tipo][plan] = {"periodo": per, "limite": max(0, min(100000, int(lim)))}
    for plan, val in (guardado.get("max_paginas") or {}).items():
        if plan in base["max_paginas"] and isinstance(val, (int, float)) and not isinstance(val, bool):
            base["max_paginas"][plan] = max(1, min(100000, int(val)))
    return base


def limites_efectivos(db):
    """Devuelve {'tools': {...}, 'max_paginas': {...}} efectivos (defaults +
    overrides de config/limites), cacheado unos segundos."""
    ahora = time.time()
    if _cache_limites["data"] is not None and ahora - _cache_limites["ts"] < _TTL_CACHE_S:
        return _cache_limites["data"]
    guardado = None
    try:
        doc = db.collection("config").document("limites").get()
        if doc.exists:
            guardado = doc.to_dict()
    except Exception:
        guardado = None
    data = _fusionar_overrides(guardado)
    _cache_limites["data"] = data
    _cache_limites["ts"] = ahora
    return data


def _config_tool(db, tipo, plan):
    cfg = limites_efectivos(db)["tools"].get(tipo, {}).get(plan)
    return (cfg["periodo"], cfg["limite"]) if cfg else None


def cargar_limites_config(db):
    """Config completa para el panel admin (GET)."""
    return limites_efectivos(db)


def guardar_limites_config(db, data):
    """Valida y guarda los límites editados desde el panel (PUT). Devuelve la
    config efectiva ya saneada."""
    limpio = _fusionar_overrides(data)
    db.collection("config").document("limites").set(limpio)
    invalidar_cache_limites()
    return limpio


def max_paginas_para_plan(plan, db=None):
    if db is not None:
        mp = limites_efectivos(db)["max_paginas"]
        return mp.get(plan, mp.get("basico"))
    return MAX_PAGINAS_POR_PLAN.get(plan, MAX_PAGINAS_POR_PLAN["basico"])


def _clave_periodo(periodo):
    hoy = date.today()
    return hoy.strftime("%Y-%m") if periodo == "mes" else hoy.isoformat()


def verificar_limite_uso(db, uid, plan, tipo):
    """Comprueba si el usuario puede usar ahora mismo la herramienta `tipo`,
    sin incrementar todavía el contador (eso se hace en registrar_uso, solo
    si la llamada a la IA se llega a realizar). Devuelve
    (permitido, mensaje_error_o_None, usados, limite)."""
    config = _config_tool(db, tipo, plan)
    if not config or config[1] <= 0:
        return False, "Tu plan actual no incluye esta herramienta.", 0, 0
    periodo, limite = config

    clave = _clave_periodo(periodo)
    doc = db.collection("usuarios").document(uid).get()
    datos = doc.to_dict() or {}
    uso = ((datos.get("limites_uso") or {}).get(tipo)) or {}
    usados = uso.get("contador", 0) if uso.get("periodo") == clave else 0

    if usados >= limite:
        # Mensaje sin cifra concreta: para el Test Personalizado el contador va
        # en preguntas (no en "usos"), y en general se prefiere que el cupo se
        # perciba como generoso/ilimitado en vez de exponer el número interno.
        if periodo == "dia":
            mensaje = "Has alcanzado el límite de uso diario de esta herramienta. Podrás volver a usarla mañana."
        else:
            mensaje = "Has alcanzado el límite de uso mensual de esta herramienta. Se renueva el próximo mes."
        return False, mensaje, usados, limite
    return True, None, usados, limite


def reservar_uso(db, uid, tipo, plan, cantidad=1):
    """Como verificar_limite_uso + registrar_uso, pero en una ÚNICA
    transacción atómica: la comprobación del límite y el incremento del
    contador ocurren en la misma lectura-escritura de Firestore.

    verificar_limite_uso lee el contador SIN transacción, y registrar_uso
    se llama aparte, normalmente después de la llamada a la IA (que puede
    tardar varios segundos) -- entre esas dos cosas hay una ventana real
    en la que dos peticiones concurrentes del mismo usuario pueden pasar
    la comprobación a la vez, viendo las dos cupo libre antes de que
    ninguna haya llegado a registrar_uso (TOCTOU). Fusionar comprobación
    e incremento en la misma transacción cierra ese hueco: la segunda
    petición concurrente ve ya el contador actualizado por la primera.

    Solo vale cuando `cantidad` se conoce ANTES de hacer el trabajo (aquí
    se cobra por adelantado, como ya hacían las rutas de streaming con
    registrar_uso + devolver_uso). Para los casos donde la cantidad real
    solo se sabe DESPUÉS del trabajo (p. ej. Test Oficial, que cobra
    según cuántas preguntas había realmente disponibles en el banco),
    seguir usando verificar_limite_uso + registrar_uso por separado --
    esas rutas no llaman a ninguna IA (leen de un banco ya cargado), así
    que el coste real en juego por ese hueco concreto es bajo.

    Devuelve (permitido, mensaje_error_o_None, usados, limite), mismo
    formato que verificar_limite_uso. Si `permitido` es True, el contador
    YA ha sido incrementado -- si el trabajo posterior acaba fallando,
    llamar a devolver_uso(cantidad) para reembolsarlo, igual que ya hacían
    las rutas de streaming."""
    cantidad = max(1, int(cantidad or 1))
    config = _config_tool(db, tipo, plan)
    if not config or config[1] <= 0:
        return False, "Tu plan actual no incluye esta herramienta.", 0, 0
    periodo, limite = config
    clave = _clave_periodo(periodo)
    ref = db.collection("usuarios").document(uid)

    def _verificar_y_reservar(transaction):
        doc = ref.get(transaction=transaction)
        datos = doc.to_dict() or {}
        uso = ((datos.get("limites_uso") or {}).get(tipo)) or {}
        usados = uso.get("contador", 0) if uso.get("periodo") == clave else 0
        if usados + cantidad > limite:
            return False, usados
        transaction.update(ref, {f"limites_uso.{tipo}": {"periodo": clave, "contador": usados + cantidad}})
        return True, usados + cantidad

    permitido, usados = ejecutar_en_transaccion(db, _verificar_y_reservar)
    if not permitido:
        # Mismo mensaje que verificar_limite_uso, sin cifra concreta (ver
        # ese docstring).
        if periodo == "dia":
            mensaje = "Has alcanzado el límite de uso diario de esta herramienta. Podrás volver a usarla mañana."
        else:
            mensaje = "Has alcanzado el límite de uso mensual de esta herramienta. Se renueva el próximo mes."
        return False, mensaje, usados, limite
    return True, None, usados, limite


def reservar_uso_multiple(db, uid, tipos, plan, cantidad=1):
    """Como reservar_uso, pero para varios `tipos` que se comprueban y
    cobran JUNTOS (p. ej. TIPOS_CUOTA_TEST_PERSONALIZADO: cupo diario +
    tope mensual sobre el mismo consumo) -- los dos viven en el MISMO
    documento usuarios/{uid}, así que se leen y se actualizan en una única
    transacción: si CUALQUIERA de los tipos está al límite, no se
    incrementa NINGUNO (mismo comportamiento que antes, cuando se
    verificaban todos primero y solo si todos pasaban se registraban
    todos) -- y al ir en una sola transacción, tampoco hay ventana entre
    comprobar un tipo y comprobar el siguiente.

    Devuelve (permitido, mensaje_error_o_None). Si `permitido` es True,
    los contadores de TODOS los tipos ya han sido incrementados -- si el
    trabajo posterior falla, reembolsar con devolver_uso para cada tipo."""
    cantidad = max(1, int(cantidad or 1))
    configs = {}
    for tipo in tipos:
        config = _config_tool(db, tipo, plan)
        if not config or config[1] <= 0:
            return False, "Tu plan actual no incluye esta herramienta."
        configs[tipo] = config
    ref = db.collection("usuarios").document(uid)

    def _verificar_y_reservar_todos(transaction):
        doc = ref.get(transaction=transaction)
        datos = doc.to_dict() or {}
        limites_uso_actual = datos.get("limites_uso") or {}
        actualizaciones = {}
        for tipo, (periodo, limite) in configs.items():
            clave = _clave_periodo(periodo)
            uso = limites_uso_actual.get(tipo) or {}
            usados = uso.get("contador", 0) if uso.get("periodo") == clave else 0
            if usados + cantidad > limite:
                return False
            actualizaciones[f"limites_uso.{tipo}"] = {"periodo": clave, "contador": usados + cantidad}
        transaction.update(ref, actualizaciones)
        return True

    permitido = ejecutar_en_transaccion(db, _verificar_y_reservar_todos)
    if not permitido:
        # Al menos uno de los periodos es "dia" siempre que haya un tope
        # diario en el grupo -- se prioriza ese mensaje (más frecuente de
        # tocar) sobre el mensual si ambos coexisten en `tipos`.
        periodos = {p for p, _l in configs.values()}
        if "dia" in periodos:
            mensaje = "Has alcanzado el límite de uso diario de esta herramienta. Podrás volver a usarla mañana."
        else:
            mensaje = "Has alcanzado el límite de uso mensual de esta herramienta. Se renueva el próximo mes."
        return False, mensaje
    return True, None


def registrar_uso(db, uid, tipo, plan, cantidad=1):
    """Suma `cantidad` al contador del periodo actual (por defecto 1). Se llama
    solo cuando la llamada a la IA se ha realizado de verdad (para no penalizar
    intentos que fallan antes, p. ej. un PDF sin texto extraíble). `cantidad`
    permite cobrar por consumo real: el Test Personalizado carga tantas
    unidades como preguntas se piden, no 1 fija.

    Lectura (contador actual, con su posible reinicio de periodo) y
    escritura (contador+1) van dentro de la misma transacción de Firestore
    -- sin esto, dos peticiones concurrentes del mismo usuario (dos
    pestañas, un reintento del frontend) podían leer el mismo contador y
    perder un incremento, dejando que se superase la cuota."""
    config = _config_tool(db, tipo, plan)
    if not config:
        return
    periodo, _limite = config
    clave = _clave_periodo(periodo)
    ref = db.collection("usuarios").document(uid)

    cantidad = max(1, int(cantidad or 1))

    def _incrementar(transaction):
        doc = ref.get(transaction=transaction)
        datos = doc.to_dict() or {}
        uso = ((datos.get("limites_uso") or {}).get(tipo)) or {}
        usados = uso.get("contador", 0) if uso.get("periodo") == clave else 0
        transaction.update(ref, {f"limites_uso.{tipo}": {"periodo": clave, "contador": usados + cantidad}})

    ejecutar_en_transaccion(db, _incrementar)


def devolver_uso(db, uid, tipo, plan, cantidad=1):
    """Resta `cantidad` al contador del periodo actual (nunca por debajo de 0,
    por defecto 1; debe cuadrar con lo que se cobró en registrar_uso). Se usa
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
    config = _config_tool(db, tipo, plan)
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
        transaction.update(ref, {f"limites_uso.{tipo}": {"periodo": clave, "contador": max(0, usados - max(1, int(cantidad or 1)))}})

    ejecutar_en_transaccion(db, _decrementar)
