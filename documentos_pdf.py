"""Librería de documentos subidos por el usuario ("Mis documentos"): agrupa
en una sola entidad todo el contenido de IA generado (resumen, esquema,
tarjetas, test) a partir de un mismo PDF, para poder repasarlo más tarde sin
tener que volver a subir el archivo ni volver a generarlo.

Un "documento" vive en usuarios/{uid}/documentos/{id} y es solo metadatos +
el texto extraído (para poder generar más contenido desde él sin re-subir el
PDF). El contenido en sí (resumen/esquema/tarjetas/test) se sigue guardando
en las subcolecciones ya existentes (resumenes_pdf, esquemas_pdf, etc.),
cada entrada etiquetada con su documento_id."""
import hashlib
from datetime import datetime, timedelta

from deepseek_utils import detectar_texto_legal

# Se guarda un extracto generoso del texto (bastante más que en el chat con
# PDF, donde se reenvía en cada mensaje y sí conviene recortarlo mucho): aquí
# solo se usa para volver a generar contenido más tarde sin re-subir el PDF,
# así que interesa mantener la misma calidad de origen que una subida nueva,
# sin disparar el tamaño del documento en Firestore (que admite hasta 1 MiB
# = 1.048.576 bytes por documento, contando TODOS sus campos).
#
# El recorte se hace en BYTES de UTF-8, no en nº de caracteres: el español
# (con tildes, ñ, viñetas...) mide en la práctica ~1,02 bytes/carácter
# (medido sobre un documento real de esta app), así que limitar por
# caracteres sin más deja mucho margen sin usar Y, al reves, no protege de
# verdad frente a texto con muchos caracteres multibyte. El resto de campos
# del documento (título, nombre de archivo, fechas, contadores, el hash) no
# llegan a un par de KB en total, así que el presupuesto de abajo deja de
# sobra 148 KB de margen sobre el límite real de 1 MiB.
LIMITE_BYTES_TEXTO_DOCUMENTO = 900_000


def _recortar_a_bytes_utf8(texto, limite_bytes):
    """Recorta `texto` para que no supere `limite_bytes` una vez codificado
    en UTF-8, sin dejar a medias el último carácter multibyte del corte."""
    codificado = texto.encode("utf-8")
    if len(codificado) <= limite_bytes:
        return texto
    return codificado[:limite_bytes].decode("utf-8", errors="ignore")


def _hash_texto(texto):
    return hashlib.sha256(texto.encode("utf-8", "ignore")).hexdigest()


def extraer_titulo(texto, nombre_archivo):
    """Heurística barata (sin gastar IA) para sacar un título legible: la
    primera línea del documento que parezca un título de verdad, o si no,
    el nombre de archivo limpiado."""
    for linea in (texto or "").splitlines():
        linea = linea.strip()
        if 8 <= len(linea) <= 120 and any(c.isalpha() for c in linea):
            return linea
    base = (nombre_archivo or "documento.pdf").rsplit(".", 1)[0]
    limpio = base.replace("_", " ").replace("-", " ").strip()
    return limpio[:1].upper() + limpio[1:] if limpio else "Documento sin título"


def obtener_o_crear_documento(db, uid, texto, nombre_archivo, num_paginas):
    """Si el usuario ya había subido este mismo documento antes (mismo
    texto), reutiliza esa entrada en vez de crear una duplicada -- así, si
    sube el mismo PDF a dos herramientas distintas, todo queda agrupado bajo
    un único documento en su biblioteca."""
    hash_texto = _hash_texto(texto)
    docs_ref = db.collection("usuarios").document(uid).collection("documentos")
    existentes = list(docs_ref.where("hash_texto", "==", hash_texto).limit(1).stream())
    if existentes:
        return existentes[0].id, existentes[0].to_dict()

    datos = {
        "titulo": extraer_titulo(texto, nombre_archivo),
        "nombre_archivo": nombre_archivo,
        "fecha_subida": datetime.utcnow().isoformat(),
        "num_paginas": num_paginas,
        "texto": _recortar_a_bytes_utf8(texto, LIMITE_BYTES_TEXTO_DOCUMENTO),
        "hash_texto": hash_texto,
        "carpeta": "",
        "tiene_resumen": False,
        "tiene_esquema": False,
        "num_tarjetas": 0,
        "num_tests": 0,
        "ultima_actividad": datetime.utcnow().isoformat(),
        # tipo_contenido (05/08/2026, ver detectar_texto_legal en
        # deepseek_utils.py): auto-detectado UNA vez, al crear el
        # documento -- así no se re-analiza cada vez que el usuario
        # regenera resumen/esquema/tarjetas/test desde el mismo
        # documento_id. Un override manual posterior (ver
        # resolver_tipo_contenido) lo sobrescribe y persiste igual.
        "tipo_contenido": "legal" if detectar_texto_legal(texto) else "general",
    }
    nuevo_ref = docs_ref.document()
    nuevo_ref.set(datos)
    # Se suma aquí, no en las rutas /guardar-*-pdf: este punto solo se
    # alcanza una vez por documento realmente nuevo (el "if existentes"
    # de arriba evita pasar por aquí si el usuario reutiliza el mismo PDF
    # en varias herramientas), así que las páginas no se cuentan varias
    # veces por un mismo archivo.
    from firebase_admin import firestore
    db.collection("usuarios").document(uid).update({
        "paginas_analizadas": firestore.Increment(num_paginas),
    })
    return nuevo_ref.id, datos


def obtener_preguntas_previas(db, uid, documento_id, limite=60):
    """Preguntas (con su respuesta correcta) de tests ANTERIORES ya
    generados para este mismo documento (colección tests_pdf, ver
    guardar_resultado.py) -- se usan para que una nueva generación desde
    la biblioteca ("generar test" otra vez sobre el mismo documento) no
    repita el mismo dato ya preguntado, aunque lo redacte con otras
    palabras (ver test_generator.py, preguntas_a_evitar). Sin esto, cada
    generación parte de cero: la deduplicación existente (fragmentar el
    documento por lote, relleno de huecos evitando "lo ya cubierto en
    este test") solo actúa DENTRO de una misma llamada, así que dos tests
    sucesivos del mismo PDF podían acabar compartiendo preguntas."""
    if not documento_id:
        return []
    # .limit(...) (12/08/2026, bug real: sin límite, un documento con
    # muchos tests generados traía TODOS sus tests_pdf enteros para acabar
    # recortando la lista final de preguntas a `limite` -- se acota
    # directamente la propia consulta, con un margen generoso sobre
    # `limite` (cada test trae varias preguntas) en vez de sobre el número
    # final de preguntas.
    docs = (
        db.collection("usuarios").document(uid).collection("tests_pdf")
        .where("documento_id", "==", documento_id)
        .limit(max(limite, 1) * 3)
        .stream()
    )
    formateadas = []
    for doc in docs:
        for p in (doc.to_dict() or {}).get("preguntas", []):
            texto = (p or {}).get("pregunta")
            if not texto:
                continue
            opciones = (p or {}).get("opciones") or {}
            letra = str((p or {}).get("respuesta_correcta", "")).upper()
            respuesta = opciones.get(letra, "")
            formateadas.append(f"{texto} (respuesta: {respuesta})" if respuesta else str(texto))
    return formateadas[:limite]


def obtener_documento(db, uid, documento_id):
    doc = db.collection("usuarios").document(uid).collection("documentos").document(documento_id).get()
    if not doc.exists:
        return None
    datos = doc.to_dict()
    datos["id"] = doc.id
    return datos


def actualizar_tipo_contenido(db, uid, documento_id, tipo_contenido):
    """Persiste un override manual de tipo_contenido ("legal"/"general",
    ver resolver_tipo_contenido) para que sobreviva a la próxima
    regeneración de resumen/esquema/tarjetas/test desde el mismo
    documento_id -- sin esto, el override solo valdría para la petición en
    curso y la siguiente volvería a caer en la auto-detección de
    obtener_o_crear_documento (calculada la primera vez que se subió el
    documento, antes de que el usuario pudiera decir nada)."""
    ref = db.collection("usuarios").document(uid).collection("documentos").document(documento_id)
    if not ref.get().exists:
        return False
    ref.update({"tipo_contenido": tipo_contenido})
    return True


def resolver_tipo_contenido(db, uid, documento_id, documento, texto, es_legal_override=None):
    """Decide "legal" o "general" para ESTA generación de resumen/esquema
    (ver /resumir-pdf, /generar-esquema-desde-pdf en blueprints/pdf_ia.py),
    en este orden de prioridad:

    1. Override manual explícito del usuario en la propia petición
       (es_legal_override True/False) -- si viene, además se PERSISTE en
       el documento (ver actualizar_tipo_contenido) para que las próximas
       generaciones sobre el mismo documento_id ya no necesiten que el
       usuario lo repita.
    2. tipo_contenido ya guardado en el documento (auto-detectado al
       subirlo, ver obtener_o_crear_documento, o un override anterior).
    3. Si no hay ninguno de los dos -- típicamente un documento creado
       ANTES de que este campo existiera -- detecta sobre la marcha con
       detectar_texto_legal y lo persiste igual que un override, para que
       quede cacheado y la siguiente regeneración de este mismo
       documento_id ya no vuelva a pasar por aquí.

    Devuelve "legal" o "general"."""
    if es_legal_override is not None:
        tipo = "legal" if es_legal_override else "general"
        if documento_id:
            actualizar_tipo_contenido(db, uid, documento_id, tipo)
        return tipo
    tipo_guardado = (documento or {}).get("tipo_contenido")
    if tipo_guardado in ("legal", "general"):
        return tipo_guardado
    tipo = "legal" if detectar_texto_legal(texto) else "general"
    if documento_id:
        actualizar_tipo_contenido(db, uid, documento_id, tipo)
    return tipo


def obtener_tests_en_progreso_por_documento(db, uid):
    """{documento_id: test_id} de los tests desde PDF que quedaron
    "en_progreso" (autoguardados sin terminar, ver rutas_progreso.py
    autosave_test) -- para que "Mis documentos" pueda ofrecer "Continuar"
    en vez de solo "Ver"/"Generar más" (que antes solo aparecían cuando ya
    había al menos un test FINALIZADO, ver marcar_generado/num_tests: un
    test empezado y no acabado no incrementa num_tests, así que no tenía
    ninguna forma de retomarse desde la biblioteca). Si un documento tiene
    más de un test en_progreso a la vez, se queda con el más reciente."""
    docs = (
        db.collection("usuarios").document(uid).collection("tests")
        .where("estado", "==", "en_progreso")
        .stream()
    )
    por_documento = {}
    for doc in docs:
        datos = doc.to_dict() or {}
        if datos.get("tipo") != "test_pdf":
            continue
        documento_id = datos.get("documento_id")
        if not documento_id:
            continue
        fecha = datos.get("fecha") or ""
        actual = por_documento.get(documento_id)
        if not actual or fecha > actual[1]:
            por_documento[documento_id] = (doc.id, fecha)
    return {documento_id: test_id for documento_id, (test_id, _fecha) in por_documento.items()}


def _banco_ref(db, uid, documento_id, tipo):
    coleccion = "banco_preguntas_pdf" if tipo == "preguntas" else "banco_tarjetas_pdf"
    return db.collection("usuarios").document(uid).collection(coleccion).document(documento_id)


# Minutos sin ninguna actualización (ver anadir_al_banco/finalizar_banco)
# a partir de los cuales un banco en estado "generando" se considera
# abandonado, no en curso (03/08/2026, bug real reportado: documentos que
# se quedaban mostrando "Generando..." para siempre). El hilo de fondo que
# rellena el banco puede morir sin llegar a llamar nunca a finalizar_banco
# -- el caso típico es un despliegue/reinicio del servidor a mitad de
# generación (Render mata los procesos en marcha al desplegar una versión
# nueva, y esta app se redespliega a menudo). Sin este chequeo, ese
# documento se quedaba "generando" para siempre Y además el propio botón
# de disparo lo bloqueaba con 409 "ya se está generando", sin ninguna
# forma de reintentar salvo tocar Firestore a mano.
_BANCO_ATASCADO_MINUTOS = 10


def _banco_atascado(datos):
    if datos.get("estado") != "generando":
        return False
    actualizado = datos.get("actualizado")
    if not actualizado:
        return True
    try:
        momento = datetime.fromisoformat(actualizado)
    except (TypeError, ValueError):
        return True
    return (datetime.utcnow() - momento) > timedelta(minutes=_BANCO_ATASCADO_MINUTOS)


def obtener_banco(db, uid, documento_id, tipo):
    """Devuelve el banco tal cual está en Firestore, salvo que lleve
    "generando" más de _BANCO_ATASCADO_MINUTOS sin ninguna actualización
    -- en ese caso se presenta como "atascado" (nunca se reescribe aquí,
    solo en la copia devuelta) para que tanto la UI como el chequeo de "ya
    hay una generación en curso" de las rutas /generar-banco-*-desde-pdf
    dejen de tratarlo como si siguiera vivo."""
    doc = _banco_ref(db, uid, documento_id, tipo).get()
    if not doc.exists:
        return None
    datos = doc.to_dict()
    if _banco_atascado(datos):
        datos = dict(datos)
        datos["estado"] = "atascado"
    return datos


def iniciar_banco(db, uid, documento_id, tipo, objetivo, nombre_archivo):
    """Crea (o reinicia) el banco de preguntas/tarjetas de un documento antes
    de arrancar la generación adaptativa en segundo plano (ver
    generar_banco_preguntas_adaptativo / generar_banco_tarjetas_adaptativo),
    para que "Mis documentos" pueda mostrar "Generando..." desde el primer
    momento y anadir_al_banco tenga un documento donde ir acumulando."""
    ahora = datetime.utcnow().isoformat()
    campo_items = "preguntas" if tipo == "preguntas" else "tarjetas"
    _banco_ref(db, uid, documento_id, tipo).set({
        "documento_id": documento_id,
        "nombre_archivo": nombre_archivo,
        campo_items: [],
        "estado": "generando",
        "objetivo": objetivo,
        "total": 0,
        "iniciado": ahora,
        "actualizado": ahora,
    })


def anadir_al_banco(db, uid, documento_id, tipo, item):
    """Persiste una pregunta/tarjeta aceptada en cuanto se genera (on_progreso
    de la generación adaptativa), en vez de esperar al final: así un banco a
    medio generar sigue siendo utilizable aunque el proceso se corte a
    mitad (reinicio del dyno, error de DeepSeek, etc.)."""
    from firebase_admin import firestore
    campo_items = "preguntas" if tipo == "preguntas" else "tarjetas"
    _banco_ref(db, uid, documento_id, tipo).update({
        campo_items: firestore.ArrayUnion([item]),
        "total": firestore.Increment(1),
        "actualizado": datetime.utcnow().isoformat(),
    })


def finalizar_banco(db, uid, documento_id, tipo, estado="completo", mensaje_error=None):
    actualizacion = {"estado": estado, "actualizado": datetime.utcnow().isoformat()}
    if mensaje_error:
        actualizacion["mensaje_error"] = mensaje_error
    _banco_ref(db, uid, documento_id, tipo).update(actualizacion)


def _resumen_bancos(db, uid, tipo):
    """{documento_id: {estado, total, objetivo}} de todos los bancos de un
    tipo (preguntas o tarjetas) del usuario, para listar_documentos: una
    sola lectura de colección en vez de una por documento."""
    coleccion = "banco_preguntas_pdf" if tipo == "preguntas" else "banco_tarjetas_pdf"
    resultado = {}
    for doc in db.collection("usuarios").document(uid).collection(coleccion).stream():
        datos = doc.to_dict() or {}
        estado = "atascado" if _banco_atascado(datos) else datos.get("estado", "sin_generar")
        resultado[doc.id] = {
            "estado": estado,
            "total": datos.get("total", 0),
            "objetivo": datos.get("objetivo", 0),
        }
    return resultado


def marcar_generado(db, uid, documento_id, tipo, num_tarjetas_nuevas=0):
    """Actualiza los indicadores del documento tras guardar contenido nuevo
    generado a partir de él (se llama desde las rutas /guardar-*-pdf)."""
    ref = db.collection("usuarios").document(uid).collection("documentos").document(documento_id)
    actualizacion = {"ultima_actividad": datetime.utcnow().isoformat()}
    if tipo == "resumen_pdf":
        actualizacion["tiene_resumen"] = True
    elif tipo == "esquema_pdf":
        actualizacion["tiene_esquema"] = True
    elif tipo == "tarjetas_pdf":
        from firebase_admin import firestore
        actualizacion["num_tarjetas"] = firestore.Increment(num_tarjetas_nuevas)
    elif tipo == "test_pdf":
        from firebase_admin import firestore
        actualizacion["num_tests"] = firestore.Increment(1)
    ref.update(actualizacion)


# Progreso real de una generación de resumen/esquema en curso (10/08/2026,
# a petición del usuario: quejarse de que "no sé qué está pasando, pon una
# barra o un contador" mientras espera). resumir-pdf/generar-esquema-desde-
# pdf redirigen a "Mis documentos" antes de terminar (ver el comentario
# largo en blueprints/pdf_ia), así que el único sitio donde el usuario
# puede seguir el progreso es sondeando GET /mis-documentos -- pero ese
# progreso solo existe de verdad dentro del propio proceso de generación
# (on_progreso de generar_documento_largo_por_partes), que corre en un
# hilo de fondo sin conexión abierta con el cliente. Guardarlo aquí, en el
# propio documento, es lo que permite que el sondeo lo lea.
def actualizar_progreso_generacion(db, uid, documento_id, tipo, completadas, total, fase):
    ref = db.collection("usuarios").document(uid).collection("documentos").document(documento_id)
    ref.update({
        f"progreso_{tipo}": {
            "completadas": completadas, "total": total, "fase": fase,
            # "actualizado" (10/08/2026, mismo motivo y mismo criterio que
            # _banco_atascado más arriba): sin marca de tiempo no hay forma
            # de distinguir "sigue generando de verdad" de "el hilo de
            # fondo murió a mitad -- p. ej. un redeploy de Render -- y este
            # progreso se quedó pegado en Firestore para siempre". Ver
            # _progreso_atascado/listar_documentos.
            "actualizado": datetime.utcnow().isoformat(),
        },
    })


def _progreso_atascado(progreso):
    """Igual que _banco_atascado, pero para progreso_resumen/progreso_
    esquema (10/08/2026): protege contra exactamente el mismo caso -- el
    hilo de fondo muere a mitad de generación (un redeploy de Render, por
    ejemplo) sin llegar a llamar a limpiar_progreso_generacion, y el
    documento se quedaría mostrando "Generando..." para siempre."""
    if not progreso:
        return False
    actualizado = progreso.get("actualizado")
    if not actualizado:
        return True
    try:
        momento = datetime.fromisoformat(actualizado)
    except (TypeError, ValueError):
        return True
    return (datetime.utcnow() - momento) > timedelta(minutes=_BANCO_ATASCADO_MINUTOS)


def limpiar_progreso_generacion(db, uid, documento_id, tipo):
    """Se llama SIEMPRE al terminar una generación (con éxito o sin él) --
    sin esto, el último progreso guardado (p. ej. "3 de 7") se quedaría
    pegado indefinidamente la próxima vez que alguien mire este documento,
    aunque la generación ya hubiera terminado hace rato."""
    ref = db.collection("usuarios").document(uid).collection("documentos").document(documento_id)
    ref.update({f"progreso_{tipo}": None})


# error_resumen/error_esquema (10/08/2026, a petición del usuario: "cuando
# le das al botón de regenerar que regenere de verdad, no que cargue datos
# antiguos"): cuando una generación falla, el resumen/esquema ANTERIOR (si
# lo había) se queda intacto sin que nada lo sustituya -- correcto para no
# perder lo que ya había, pero antes no había NINGUNA señal de que el
# intento de regenerar hubiera fallado, así que al ver el de siempre daba
# la sensación de que "regenerar no hace nada". Se marca al fallar y se
# limpia al empezar un intento nuevo o al conseguir uno con éxito.
def marcar_error_generacion(db, uid, documento_id, tipo, mensaje):
    ref = db.collection("usuarios").document(uid).collection("documentos").document(documento_id)
    ref.update({f"error_{tipo}": {"mensaje": mensaje, "fecha": datetime.utcnow().isoformat()}})


def limpiar_error_generacion(db, uid, documento_id, tipo):
    ref = db.collection("usuarios").document(uid).collection("documentos").document(documento_id)
    ref.update({f"error_{tipo}": None})


_LIMITE_DOCUMENTOS_LISTADOS = 200


def listar_documentos(db, uid):
    # .limit(...) (12/08/2026, bug real: sin límite, un usuario con muchos
    # documentos subidos traía la colección entera en cada carga de "Mis
    # Documentos" -- el tope es generoso a propósito, esto no sustituye a
    # paginación real si algún día hiciera falta, solo evita una lectura sin
    # fin.
    docs_ref = (
        db.collection("usuarios").document(uid).collection("documentos")
        .limit(_LIMITE_DOCUMENTOS_LISTADOS)
    )
    bancos_preguntas = _resumen_bancos(db, uid, "preguntas")
    bancos_tarjetas = _resumen_bancos(db, uid, "tarjetas")
    resultado = []
    for doc in docs_ref.stream():
        datos = doc.to_dict()
        banco_preguntas = bancos_preguntas.get(doc.id, {})
        banco_tarjetas = bancos_tarjetas.get(doc.id, {})
        # progreso_resumen/progreso_esquema atascados (10/08/2026, ver
        # _progreso_atascado): se presentan como si la generación hubiera
        # terminado con error -- nunca se muestra "Generando..." para
        # siempre, y el usuario ve una señal clara de que hay que
        # regenerar, en vez de un dato de Firestore sucio sin ninguna
        # explicación visible.
        progreso_resumen = datos.get("progreso_resumen")
        error_resumen = datos.get("error_resumen")
        if _progreso_atascado(progreso_resumen):
            progreso_resumen = None
            error_resumen = {
                "mensaje": "La generación se interrumpió antes de terminar.",
                "fecha": datetime.utcnow().isoformat(),
            }
        progreso_esquema = datos.get("progreso_esquema")
        error_esquema = datos.get("error_esquema")
        if _progreso_atascado(progreso_esquema):
            progreso_esquema = None
            error_esquema = {
                "mensaje": "La generación se interrumpió antes de terminar.",
                "fecha": datetime.utcnow().isoformat(),
            }
        resultado.append({
            "id": doc.id,
            "titulo": datos.get("titulo"),
            "nombre_archivo": datos.get("nombre_archivo"),
            "fecha_subida": datos.get("fecha_subida"),
            "num_paginas": datos.get("num_paginas"),
            "carpeta": datos.get("carpeta", ""),
            # tipo_contenido (05/08/2026): "legal"/"general", ver
            # detectar_texto_legal/resolver_tipo_contenido -- documentos
            # creados antes de este cambio no lo tienen guardado, de ahí
            # el "general" por defecto (el más neutro: si en realidad es
            # legal, la próxima generación de resumen/esquema lo
            # auto-detectará y lo guardará).
            "tipo_contenido": datos.get("tipo_contenido", "general"),
            "tiene_resumen": datos.get("tiene_resumen", False),
            "tiene_esquema": datos.get("tiene_esquema", False),
            # progreso_resumen/progreso_esquema (10/08/2026): None si no hay
            # ninguna generación en curso -- ver actualizar_progreso_generacion
            # (y _progreso_atascado si lleva demasiado sin actualizarse).
            "progreso_resumen": progreso_resumen,
            "progreso_esquema": progreso_esquema,
            # error_resumen/error_esquema (10/08/2026): último intento de
            # generar que falló, ver marcar_error_generacion. None si el
            # último intento (o el único que ha habido) fue bien.
            "error_resumen": error_resumen,
            "error_esquema": error_esquema,
            "num_tarjetas": datos.get("num_tarjetas", 0),
            "num_tests": datos.get("num_tests", 0),
            "ultima_actividad": datos.get("ultima_actividad"),
            # Banco de preguntas/tarjetas pre-generado (03/08/2026, ver el
            # comentario largo junto a iniciar_banco): estado="sin_generar"
            # cuando nunca se ha pedido, para que el frontend pueda decidir
            # entre "Generar banco" y "Generando.../N disponibles".
            "banco_preguntas_estado": banco_preguntas.get("estado", "sin_generar"),
            "banco_preguntas_total": banco_preguntas.get("total", 0),
            "banco_preguntas_objetivo": banco_preguntas.get("objetivo", 0),
            "banco_tarjetas_estado": banco_tarjetas.get("estado", "sin_generar"),
            "banco_tarjetas_total": banco_tarjetas.get("total", 0),
            "banco_tarjetas_objetivo": banco_tarjetas.get("objetivo", 0),
        })
    resultado.sort(key=lambda d: d.get("ultima_actividad") or "", reverse=True)
    return resultado


def actualizar_carpeta(db, uid, documento_id, carpeta):
    ref = db.collection("usuarios").document(uid).collection("documentos").document(documento_id)
    if not ref.get().exists:
        return False
    ref.update({"carpeta": (carpeta or "").strip()[:60]})
    return True


def actualizar_titulo(db, uid, documento_id, titulo):
    """Deja que el usuario le ponga a un documento un nombre distinto del
    que se extrajo automáticamente al subirlo (ver extraer_titulo)."""
    ref = db.collection("usuarios").document(uid).collection("documentos").document(documento_id)
    if not ref.get().exists:
        return False
    titulo = (titulo or "").strip()[:120]
    if not titulo:
        return False
    ref.update({"titulo": titulo})
    return True


def eliminar_documento(db, uid, documento_id):
    """Borra un documento de la biblioteca -- pensado sobre todo para poder
    quitar una subida duplicada o ya no deseada. Descuenta del contador
    paginas_analizadas del usuario las páginas que había aportado al
    crearse (ver obtener_o_crear_documento), para que ese contador siga
    reflejando la realidad tras el borrado.

    NO borra el contenido ya generado a partir de él (resúmenes/esquemas/
    tarjetas/tests en sus propias colecciones, cada uno etiquetado con este
    documento_id) -- sigue accesible donde ya estuviera (p. ej. "Mis
    Tests"), solo deja de aparecer como documento de origen en la
    biblioteca. Borrar en cascada todo lo generado sería mucho más
    destructivo de lo que pide "quitar un duplicado de la lista", y esos
    contenidos no dependen de que el documento siga existiendo."""
    ref = db.collection("usuarios").document(uid).collection("documentos").document(documento_id)
    doc = ref.get()
    if not doc.exists:
        return False
    num_paginas = (doc.to_dict() or {}).get("num_paginas") or 0
    ref.delete()
    if num_paginas:
        from firebase_admin import firestore
        db.collection("usuarios").document(uid).update({
            "paginas_analizadas": firestore.Increment(-num_paginas),
        })
    return True


def listar_carpetas(db, uid):
    """Catálogo de carpetas del usuario: las creadas explícitamente con
    crear_carpeta() más cualquier nombre que ya tuviera asignado algún
    documento antes de que existiera este catálogo (para no perder carpetas
    de usuarios que ya las usaban con el sistema anterior)."""
    usuario = db.collection("usuarios").document(uid).get().to_dict() or {}
    explicitas = set(usuario.get("carpetas_documentos") or [])
    de_documentos = {
        (doc.to_dict() or {}).get("carpeta")
        for doc in db.collection("usuarios").document(uid).collection("documentos").stream()
    }
    de_documentos.discard("")
    de_documentos.discard(None)
    return sorted(explicitas | de_documentos)


def crear_carpeta(db, uid, nombre):
    nombre = (nombre or "").strip()[:60]
    if not nombre:
        return None
    from firebase_admin import firestore
    db.collection("usuarios").document(uid).update({
        "carpetas_documentos": firestore.ArrayUnion([nombre])
    })
    return nombre


def eliminar_carpeta(db, uid, nombre):
    """Borra la carpeta del catálogo y deja "sin carpeta" a los documentos
    que estuvieran dentro, en vez de borrarlos."""
    from firebase_admin import firestore
    nombre = (nombre or "").strip()
    if not nombre:
        return
    docs_ref = db.collection("usuarios").document(uid).collection("documentos")
    for doc in docs_ref.where("carpeta", "==", nombre).stream():
        doc.reference.update({"carpeta": ""})
    db.collection("usuarios").document(uid).update({
        "carpetas_documentos": firestore.ArrayRemove([nombre])
    })
