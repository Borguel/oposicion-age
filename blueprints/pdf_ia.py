"""Herramientas de IA sobre un PDF subido por el propio usuario: resumen,
esquema, test, tarjetas y chat sobre el documento, más "Mis documentos"
(la biblioteca de lo ya generado)."""
import json
import logging
import os
import queue
import random
import threading
from datetime import datetime
from io import BytesIO

from flask import Blueprint, Response, g, jsonify, request, stream_with_context
from google.api_core import exceptions as google_exceptions
from pypdf import PdfReader

from firebase_setup import db
from auth_utils import requiere_plan, requiere_admin, obtener_oposicion_solicitada
from limites_uso import max_paginas_para_plan, verificar_limite_uso, devolver_uso, reservar_uso
from rate_limiter import limiter
from documentos_pdf import (
    obtener_documento, listar_documentos, actualizar_carpeta,
    listar_carpetas, crear_carpeta, eliminar_carpeta, actualizar_titulo, obtener_preguntas_previas,
    obtener_tests_en_progreso_por_documento, eliminar_documento,
    iniciar_banco, anadir_al_banco, finalizar_banco, obtener_banco,
    resolver_tipo_contenido, actualizar_progreso_generacion, limpiar_progreso_generacion,
    marcar_error_generacion, limpiar_error_generacion,
    buscar_documento_por_texto, crear_documento,
    limite_regeneraciones_alcanzado, LIMITE_GENERACIONES_POR_DOCUMENTO,
)
from guardar_resultado import guardar_resultado_en_firestore
from test_generator import (
    generar_preguntas_ia_en_lotes, generar_banco_preguntas_adaptativo, TOPE_BANCO_PREGUNTAS,
)
from coste_ia import AcumuladorTokens
from deepseek_utils import (
    TAMANO_CHUNK_CARACTERES, TAMANO_CHUNK_ESQUEMA, FRACCION_MINIMA_MAP_ESQUEMA, FRACCION_MINIMA_FUSION_ESQUEMA,
    generar_documento_largo_por_partes, call_deepseek_api, call_deepseek_api_stream,
)
from tarjetas_generator import (
    generar_tarjetas_verificadas, generar_banco_tarjetas_adaptativo, TOPE_BANCO_TARJETAS,
)
from utils import barajar_opciones_pregunta
import generacion_control

logger = logging.getLogger(__name__)

bp = Blueprint("pdf_ia", __name__)


# Cláusula de fidelidad compartida por los prompts de resumen/esquema (los
# 3 modos: narrativo general, narrativo legal-mapa-de-artículos, esquema) --
# factorizada aquí el 05/08/2026 al añadir el modo legal para no
# cuadruplicar el mismo párrafo palabra por palabra en el archivo.
_CLAUSULA_FIDELIDAD_DOCUMENTO = (
    "IMPORTANTE -- fidelidad al documento: basa tu respuesta ÚNICAMENTE en el "
    "contenido del documento proporcionado. No añadas información externa, no "
    "completes huecos con conocimiento propio, y no inventes datos, fechas, "
    "artículos, cifras o nombres que no aparezcan literalmente en el texto. Si el "
    "documento no aporta un dato que normalmente se esperaría, no lo inventes: "
    "sencillamente no lo incluyas. Antes de dar tu respuesta por buena, revisa "
    "mentalmente que cada dato concreto que has escrito (fecha, cifra, ley, "
    "artículo, plazo) aparezca efectivamente en el documento que se te ha dado."
)


def _resolver_texto_documento(plan_actual):
    """Punto de entrada común de TODAS las rutas que trabajan sobre un PDF
    del usuario: o bien viene un 'documento_id' (contenido ya subido antes,
    de la biblioteca de "Mis documentos"), o bien viene un archivo 'pdf'
    nuevo -- en ese caso, y solo si resulta ser un documento que este
    usuario nunca había subido, se comprueba y se cobra el cupo mensual de
    SUBIDAS (banco_pdf_mensual, ver el comentario largo más abajo). Devuelve
    (texto, documento_id, nombre_archivo, respuesta_error_o_None); si el
    último elemento no es None, la ruta debe devolverlo tal cual."""
    documento_id = request.form.get("documento_id")
    if documento_id:
        documento = obtener_documento(db, g.uid, documento_id)
        if not documento:
            return None, None, None, (jsonify({"error": "No se encontró el documento indicado."}), 404)
        return documento["texto"], documento_id, documento.get("nombre_archivo", "documento.pdf"), None

    if 'pdf' not in request.files:
        return None, None, None, (jsonify({"error": "No se encontró archivo PDF"}), 400)
    pdf_file = request.files['pdf']
    if pdf_file.filename == '':
        return None, None, None, (jsonify({"error": "Nombre de archivo inválido"}), 400)
    try:
        pdf_reader = PdfReader(BytesIO(pdf_file.read()))
        numero_paginas = len(pdf_reader.pages)
    except Exception:
        return None, None, None, (jsonify({"error": "El archivo no es un PDF válido o está dañado. Comprueba que sea un PDF real e inténtalo de nuevo."}), 400)
    limite_paginas = max_paginas_para_plan(plan_actual, db)
    if numero_paginas > limite_paginas:
        return None, None, None, (jsonify({"error": f"El PDF tiene demasiadas páginas para tu plan (máx. {limite_paginas}). Divide el documento en partes más pequeñas o mejora de plan."}), 400)
    # La extracción también va protegida: un PDF estructuralmente válido puede
    # tener páginas con contenido corrupto que revientan extract_text().
    try:
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    except Exception:
        return None, None, None, (jsonify({"error": "El archivo no es un PDF válido o está dañado. Comprueba que sea un PDF real e inténtalo de nuevo."}), 400)
    if not text.strip():
        return None, None, None, (jsonify({"error": "El PDF no contiene texto extraíble (puede ser una imagen)"}), 400)
    # Cupo mensual de SUBIDAS (17/08/2026, ver banco_pdf_mensual en
    # limites_uso.py, a petición explícita del usuario: "lo que quiero
    # limitar es la subida del documento, no cada herramienta que uses
    # sobre él"): se comprueba SOLO si este texto es realmente nuevo para
    # este usuario (buscar_documento_por_texto no encuentra nada) -- si el
    # usuario ya lo había subido antes (mismo hash), reutilizar ese
    # documento en cualquier herramienta NUNCA cuenta como una subida
    # nueva, por muchas veces que se use.
    documento_id, documento = buscar_documento_por_texto(db, g.uid, text)
    if not documento_id:
        # reservar_uso comprueba Y cobra en una única transacción atómica,
        # ANTES de crear el documento -- así dos subidas concurrentes de
        # documentos NUEVOS y distintos no pueden pasar la comprobación las
        # dos a la vez viendo cupo libre (verificar_limite_uso, sin
        # transacción, dejaba esa ventana abierta). Si crear_documento
        # falla, se devuelve el uso ya reservado.
        permitido, mensaje_error, _usados, _limite = reservar_uso(db, g.uid, "banco_pdf_mensual", plan_actual)
        if not permitido:
            return None, None, None, (jsonify({"error": mensaje_error}), 429)
        try:
            documento_id, documento = crear_documento(db, g.uid, text, pdf_file.filename, numero_paginas)
        except Exception:
            devolver_uso(db, g.uid, "banco_pdf_mensual", plan_actual)
            raise
    return text, documento_id, pdf_file.filename, None


def _leer_override_texto_legal():
    """Override manual de tipo_contenido para /resumir-pdf y
    /generar-esquema-desde-pdf (ver resolver_tipo_contenido en
    documentos_pdf.py): "true"/"false" fuerza legal/general, cualquier
    otro valor (incluido ausente) deja la decisión en automático."""
    valor = request.form.get("es_texto_legal")
    if valor is None:
        return None
    return valor.strip().lower() == "true"


def _parece_documento_generado_valido(texto):
    """Filtro barato (sin gastar IA) contra un fallo real reportado por un
    usuario (06/08/2026): al pedir un esquema, el modelo devolvió UNA sola
    frase de METACOMENTARIO sobre el propio resultado ("El esquema ya está
    completo: cubre todas las secciones del documento... No hay ningún
    epígrafe pendiente de desarrollo...") en vez del esquema en Markdown
    pedido -- y esa frase se guardó y se mostró tal cual, sin ningún aviso
    de que la generación había fallado.

    Los CUATRO system_prompt de /resumir-pdf y /generar-esquema-desde-pdf
    (narrativo y mapa de artículos, resumen y esquema) exigen SIEMPRE al
    menos un encabezado de nivel 1 ("# ") como parte del formato -- su
    ausencia es una señal barata y fiable de que la respuesta no es el
    documento pedido, sea cual sea la causa exacta (metacomentario,
    respuesta vacía, texto cortado de forma rara). No hace falta detectar
    la frase de metacomentario en sí -- eso sería frágil ante la próxima
    reformulación distinta del mismo problema -- basta con comprobar que
    se cumplió el contrato de formato que el propio prompt exige."""
    if not texto:
        return False
    return any(linea.strip().startswith("# ") for linea in texto.splitlines())


def _generar_documento_validado(*args, **kwargs):
    """Envoltorio de generar_documento_largo_por_partes que, si el resultado
    no supera _parece_documento_generado_valido (ver el comentario largo de
    esa función), lo devuelve de todas formas con un aviso visible en vez de
    regenerarlo entero.

    Hasta el 10/08/2026 esto reintentaba la generación COMPLETA una segunda
    vez (todos los fragmentos + fusión) -- el multiplicador ×2 más caro de
    todo el pipeline, para un fallo (metacomentario del modelo en vez del
    documento pedido) que en la práctica es raro. Cambiado a petición
    explícita del usuario ("no tiene que consumir muchas llamadas... calidad
    media, no alta"): se acepta el resultado tal cual, con el mismo tipo de
    aviso ya usado en generar_documento_largo_por_partes para fragmentos
    perdidos, y el usuario puede pulsar «Regenerar» si de verdad hace falta
    -- mismo criterio que la degradación parcial ya establecida, sin pagar
    una segunda generación entera por adelantado en cada intento."""
    resultado = generar_documento_largo_por_partes(*args, **kwargs)
    if resultado and not _parece_documento_generado_valido(resultado):
        logger.warning(
            "generar_documento_largo_por_partes devolvió una respuesta sin encabezado "
            "Markdown válido, se devuelve con aviso en vez de regenerar: %r", resultado[:200],
        )
        resultado = (
            "> **Aviso:** la IA no ha devuelto el documento en el formato esperado. Pulsa "
            "«Regenerar» para intentarlo de nuevo.\n\n"
        ) + resultado
    return resultado


def _normalizar_pregunta_pdf(p):
    """Deja una pregunta cruda de generar_preguntas_ia_en_lotes/
    generar_banco_preguntas_adaptativo lista para mostrarse o guardarse:
    rellena campos opcionales que falten, homogeneiza tipos y baraja las
    opciones (para que la correcta no caiga siempre en la misma letra).
    Devuelve None si la pregunta no trae lo mínimo imprescindible."""
    if not all(k in p for k in ["pregunta", "opciones", "respuesta_correcta"]):
        return None
    if "explicacion" not in p:
        p["explicacion"] = "Explicación no disponible."
    p["pregunta"] = str(p["pregunta"]).strip() if p["pregunta"] else "Pregunta no disponible"
    p["explicacion"] = str(p["explicacion"]).strip() if p["explicacion"] else "Explicación no disponible"
    if not isinstance(p["opciones"], dict):
        p["opciones"] = {}
    for key in list(p["opciones"].keys()):
        p["opciones"][key] = str(p["opciones"][key]).strip() if p["opciones"][key] else "Opción no disponible"
    p["respuesta_correcta"] = str(p["respuesta_correcta"]).upper() if p["respuesta_correcta"] else "A"
    return barajar_opciones_pregunta(p)


def _extraer_json_array(texto):
    """Extrae y parsea el array JSON que debería devolver la IA, tolerando
    que venga envuelto en texto explicativo alrededor (el LLM a veces
    añade una frase antes o después pese a que el prompt le pide "SOLO el
    JSON") y que use comillas simples en vez de dobles (JSON inválido
    estricto, pero un fallo común de generación). Lanza ValueError si no
    se puede recuperar un array JSON válido de ninguna de las dos formas."""
    start_index = texto.find("[")
    end_index = texto.rfind("]") + 1
    if start_index == -1 or end_index <= start_index:
        raise ValueError("No se encontró un array JSON en la respuesta.")
    json_str = texto[start_index:end_index]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(json_str.replace("'", '"'))
    except json.JSONDecodeError as e:
        raise ValueError("El texto entre corchetes no es un JSON válido.") from e


def _ultimo_por_documento(coleccion, documento_id, uid):
    """Última entrada guardada de una subcolección de contenido generado
    (resumenes_pdf/esquemas_pdf/tests_pdf) para un documento -- usada por
    los GET /documento/<id>/resumen|esquema|test de cada módulo de
    herramienta correspondiente."""
    docs = list(
        db.collection("usuarios").document(uid).collection(coleccion)
        .where("documento_id", "==", documento_id)
        .stream()
    )
    if not docs:
        return None
    docs.sort(key=lambda d: d.to_dict().get("fecha") or "", reverse=True)
    return docs[0].to_dict()


@bp.route('/resumir-pdf', methods=['POST'])
@limiter.limit("5 per minute")
@requiere_plan(db, "premium", global_check=True)
def resumir_pdf():
    # En streaming (SSE, mismo patrón que /generar-test-desde-pdf) para dar
    # progreso real por fragmento en vez de los mensajes rotativos
    # cosméticos que tenía antes.
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "pdf_ia")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    text, documento_id, nombre_archivo, error = _resolver_texto_documento(g.plan_actual)
    if error:
        return error
    if not os.getenv("DEEPSEEK_API_KEY"):
        return jsonify({"error": "API key de DeepSeek no configurada"}), 500

    max_length = 300000
    # texto_truncado_por_longitud (12/08/2026, bug real: hasta ahora este
    # truncado era completamente silencioso -- ni la subida ni el resultado
    # avisaban de que el documento se había cortado, así que un usuario con
    # un documento de 150+ páginas se quedaba con un resumen incompleto sin
    # saberlo). Se guarda el aviso para anteponerlo al resultado más abajo.
    texto_truncado_por_longitud = len(text) > max_length
    if texto_truncado_por_longitud:
        text = text[:max_length]

    # tipo_contenido (05/08/2026, ver resolver_tipo_contenido en
    # documentos_pdf.py): documento_id ya viene resuelto/creado por
    # _resolver_texto_documento, así que aquí solo hace falta releerlo para
    # saber si ya tiene tipo_contenido guardado (auto-detectado la primera
    # vez que se subió) u override de una generación anterior.
    documento_actual = obtener_documento(db, g.uid, documento_id) if documento_id else None
    # Límite de regeneraciones por documento (17/08/2026, ver
    # LIMITE_GENERACIONES_POR_DOCUMENTO en documentos_pdf.py): se comprueba
    # ANTES de gastar ninguna cuota ni llamar a DeepSeek.
    if documento_id and limite_regeneraciones_alcanzado(documento_actual, "resumen"):
        return jsonify({
            "error": f"Has alcanzado el límite de {LIMITE_GENERACIONES_POR_DOCUMENTO} generaciones de "
                     "resumen para este documento (incluida la primera). Sube el documento de nuevo "
                     "para poder generar un resumen distinto.",
        }), 429
    tipo_contenido = resolver_tipo_contenido(
        db, g.uid, documento_id, documento_actual, text, _leer_override_texto_legal(),
    )
    es_legal = tipo_contenido == "legal"

    if es_legal:
        # Mapa de artículos (05/08/2026): un resumen NARRATIVO de una ley
        # pierde justo lo que un opositor necesita para el examen -- número
        # de artículo, plazos, excepciones, mayorías, órganos competentes.
        # Aquí no se pide prosa conectada entre artículos, sino una entrada
        # breve y autocontenida por cada uno, en el mismo orden del
        # documento y sin omitir ninguno.
        system_prompt = (
            "Eres un experto en oposiciones especializado en textos legales (leyes, "
            "reglamentos, BOE). El documento que se te da es un texto legal: en vez de un "
            "resumen narrativo, crea un MAPA DE ARTÍCULOS que recorra el documento "
            "artículo por artículo, EN ORDEN y SIN OMITIR NINGUNO. Usa EXACTAMENTE este "
            "formato Markdown, sin desviarte de él:\n"
            "- Encabezados de nivel 1 con \"# \" para cada título/capítulo del documento, "
            "en el orden en que aparecen (si el documento no tiene esa división, usa un "
            "único encabezado con su nombre).\n"
            "- Por cada artículo, una viñeta \"- \" que empiece con su número EXACTO tal "
            "como aparece en el documento en **negrita** (p. ej. \"**Artículo 14.**\" o "
            "\"**Artículo 26.9.**\" si el documento ya lo numera así), seguido de 1-2 "
            "líneas -- nunca más -- con el concepto clave de ese artículo y los términos "
            "concretos que suelen preguntarse en examen: plazos exactos, mayorías, "
            "excepciones, órganos competentes, cifras. Nada de narrativa que conecte un "
            "artículo con el siguiente: cada uno es una entrada independiente y "
            "autocontenida.\n"
            "- Si un artículo tiene apartados numerados relevantes para el examen (a, b, "
            "c... o 1, 2, 3...), anídalos como sub-viñetas debajo, indentadas 2 espacios, "
            "con el mismo criterio de brevedad.\n"
            "- Las disposiciones adicionales, transitorias o finales se tratan igual que "
            "un artículo más (mismo formato de viñeta con su número/nombre en negrita), "
            "agrupadas bajo su propio encabezado de nivel 1 si el documento tiene varias.\n"
            "No uses tablas, bloques de código, ni HTML. No resumas varios artículos "
            "juntos en una sola viñeta ni te saltes ninguno aunque parezca poco "
            "relevante -- el mapa debe permitir comprobar de un vistazo que no falta "
            "ningún artículo del documento.\n" + _CLAUSULA_FIDELIDAD_DOCUMENTO
        )
    else:
        system_prompt = (
            "Eres un experto en oposiciones. Crea un resumen de estudio claro y bien "
            "estructurado a partir del siguiente documento, destacando conceptos "
            "fundamentales, leyes importantes y fechas relevantes. Usa EXACTAMENTE este "
            "formato Markdown, sin desviarte de él:\n"
            "- Encabezados de nivel 1 con \"# \" para los bloques temáticos principales.\n"
            "- Encabezados de nivel 2 con \"## \" para subapartados.\n"
            "- Texto en **negrita** para términos clave, leyes, artículos o fechas, la "
            "primera vez que aparecen.\n"
            "- Listas con \"- \" para viñetas normales.\n"
            "- Listas numeradas con \"1. \", \"2. \", etc. cuando el orden importe (por "
            "ejemplo, fases de un procedimiento).\n"
            "- Cuando definas formalmente un concepto clave, usa el prefijo \"> \" para esa "
            "línea, de forma que se pueda destacar como una caja de definición aparte.\n"
            "No uses tablas, bloques de código, ni HTML. Cada línea de texto debe ir en su "
            "propio párrafo o viñeta, sin mezclar varias ideas en una misma línea larga. El "
            "resumen debe ser útil para un opositor.\n" + _CLAUSULA_FIDELIDAD_DOCUMENTO
        )

    uid = g.uid
    plan_actual = g.plan_actual
    # La comprobación de arriba (verificar_limite_uso) es solo un filtro
    # rápido para no perder tiempo resolviendo/parseando el documento si el
    # usuario ya está claramente al límite -- la que de verdad cuenta es
    # esta de aquí: reservar_uso comprueba Y cobra en una única transacción
    # atómica justo antes de arrancar el hilo de fondo, así dos peticiones
    # concurrentes no pueden colarse las dos a la vez viendo cupo libre. Se
    # cobra por adelantado (no al llegar "fin"): el hilo de fondo sigue
    # generando y gastando en DeepSeek aunque el cliente corte la conexión
    # SSE (mismo motivo que /generar-test-desde-pdf).
    permitido, mensaje_error, _usados, _limite = reservar_uso(db, uid, "pdf_ia", plan_actual)
    if not permitido:
        return jsonify({"error": mensaje_error}), 429

    def generar():
        eventos = queue.Queue()
        acumulador_tokens = AcumuladorTokens()

        def _en_hilo_de_fondo():
            # evento_parada (10/08/2026, a petición explícita del usuario:
            # "quiero un botón para parar una generación mía en curso, no
            # quiero consumir tokens de más haciendo pruebas") -- ver
            # generacion_control.py. Solo tiene sentido con documento_id
            # (es la clave que usa la ruta de detener para encontrarla).
            evento_parada = generacion_control.registrar(uid, documento_id, "resumen") if documento_id else None

            def on_progreso(evento_progreso):
                eventos.put({"tipo": "progreso", **evento_progreso})
                # Progreso real persistido (10/08/2026, a petición del
                # usuario: "no sé qué está pasando, pon una barra o un
                # contador") -- el evento SSE de arriba no le sirve a nadie
                # porque el frontend ya redirigió a "Mis documentos" y
                # cortó la conexión; esto sí lo puede leer el sondeo de esa
                # página (ver actualizar_progreso_generacion).
                if documento_id:
                    try:
                        actualizar_progreso_generacion(db, uid, documento_id, "resumen", **evento_progreso)
                    except Exception:
                        logger.exception("No se pudo guardar el progreso de /resumir-pdf")
            # Error del intento ANTERIOR limpiado al empezar uno nuevo
            # (10/08/2026, a petición del usuario: "que regenere de verdad,
            # no que cargue datos antiguos") -- si no, un "Regenerar" que sí
            # funciona podría quedarse mostrando el aviso de fallo de la
            # vez anterior.
            if documento_id:
                try:
                    limpiar_error_generacion(db, uid, documento_id, "resumen")
                except Exception:
                    logger.exception("No se pudo limpiar el error previo de /resumir-pdf")
            try:
                resumen = _generar_documento_validado(
                    system_prompt, text, etiqueta_documento="Documento para resumir",
                    evento_parada=evento_parada,
                    # max_tokens más alto en modo legal: el prompt de "mapa
                    # de artículos" exige cubrir cada artículo, un listón
                    # más exigente que el resumen narrativo general, así que
                    # necesita más presupuesto de salida por llamada.
                    #
                    # tamano_chunk NO se reduce en modo legal (10/08/2026, a
                    # petición explícita del usuario: "si hay que bajar un
                    # poco de calidad no pasa nada... rápido, barato, calidad
                    # media"). Antes se bajaba a 8000/12000 para que el
                    # modelo cubriera mejor CADA artículo -- pero eso
                    # multiplicaba el número de llamadas a DeepSeek (hasta 7
                    # para un documento de ~51.000 caracteres), cada una un
                    # punto más de fallo, más lento y con el system_prompt
                    # pagado una vez por fragmento. Con el
                    # TAMANO_CHUNK_CARACTERES general (22000, ver
                    # deepseek_utils.py) ese mismo documento ya baja a 3
                    # fragmentos sin necesidad de un valor propio para legal.
                    max_tokens=8192 if es_legal else 4096,
                    on_usage=acumulador_tokens.add, on_progreso=on_progreso,
                )
                if resumen:
                    if texto_truncado_por_longitud:
                        resumen = (
                            "> **Aviso:** este documento supera la longitud que esta herramienta "
                            "puede analizar de una vez, así que el resumen se ha generado solo a "
                            "partir de la primera parte. Para cubrirlo entero, divide el documento "
                            "en partes más cortas y súbelas por separado.\n\n"
                        ) + resumen
                    resultado = {
                        "resumen": resumen, "documento_id": documento_id, "nombre_archivo": nombre_archivo,
                        "tipo_contenido_detectado": tipo_contenido,
                    }
                    # Guardado en Firestore DESDE EL PROPIO hilo de fondo
                    # (05/08/2026, a petición del usuario: quiere poder irse a
                    # "Mis documentos" nada más pedir el resumen, sin quedarse
                    # esperando aquí, igual que ya podía con el banco de
                    # tarjetas/preguntas). Antes este guardado dependía de que
                    # el FRONTEND recibiera el evento "fin" y llamara aparte a
                    # /guardar-resumen-pdf -- si el usuario navegaba fuera de
                    # esta página antes de que el stream terminara, el
                    # resumen se generaba y se pagaba igual pero se perdía
                    # sin guardar. Guardarlo aquí lo hace depender solo de
                    # que la generación termine, no de que alguien siga
                    # escuchando el SSE.
                    if documento_id:
                        guardar_resultado_en_firestore(
                            db=db, tipo="resumen_pdf", contenido=resumen, usuario_id=uid,
                            metadatos={
                                "nombre_archivo": nombre_archivo,
                                "documento_id": documento_id,
                                "longitud": len(resumen),
                                "fecha_procesamiento": datetime.utcnow().isoformat(),
                            },
                        )
                else:
                    resultado = {"error": "Error en DeepSeek API"}
            except Exception:
                logger.exception("Error en /resumir-pdf")
                resultado = {"error": "Error al procesar el PDF."}
            if not resultado.get("resumen"):
                devolver_uso(db, uid, "pdf_ia", plan_actual)
                # Fallo visible en "Mis documentos" (10/08/2026) -- sin
                # esto, un intento de regenerar que falla es indistinguible
                # de uno que nunca se pidió: el resumen anterior (si lo
                # había) se queda tal cual, sin ninguna señal de que el
                # intento nuevo no funcionó.
                if documento_id:
                    try:
                        marcar_error_generacion(db, uid, documento_id, "resumen", resultado.get("error", "Error desconocido"))
                    except Exception:
                        logger.exception("No se pudo marcar el error de /resumir-pdf")
            acumulador_tokens.volcar_directo(db, uid)
            # Progreso limpiado SIEMPRE al terminar, con éxito o sin él
            # (10/08/2026) -- si no, el último "3 de 7" guardado se
            # quedaría pegado indefinidamente para la próxima vez que se
            # mire este documento, aunque la generación ya hubiera acabado.
            if documento_id:
                try:
                    limpiar_progreso_generacion(db, uid, documento_id, "resumen")
                except Exception:
                    logger.exception("No se pudo limpiar el progreso de /resumir-pdf")
            if documento_id:
                generacion_control.desregistrar(uid, documento_id, "resumen")
            eventos.put({"tipo": "fin", **resultado})

        hilo = threading.Thread(target=_en_hilo_de_fondo, daemon=True)
        hilo.start()

        # "inicio" (05/08/2026): se manda ANTES de esperar nada del hilo de
        # fondo -- documento_id ya se conoce en cuanto se resolvió el PDF,
        # sin necesidad de esperar a que termine la generación. El frontend
        # puede leer solo este evento, cancelar la conexión y llevar al
        # usuario a "Mis documentos" sin esperar más, mismo patrón que
        # /generar-banco-tarjetas-desde-pdf.
        yield f"data: {json.dumps({'tipo': 'inicio', 'documento_id': documento_id}, ensure_ascii=False)}\n\n"

        while True:
            evento = eventos.get()
            yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
            if evento["tipo"] == "fin":
                break

    return Response(
        stream_with_context(generar()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
    )


# ✅ NUEVA RUTA: alias para compatibilidad con frontend
@bp.route('/resumir-documento', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def resumir_documento():
    return resumir_pdf()


@bp.route('/generar-esquema-desde-pdf', methods=['POST'])
@limiter.limit("5 per minute")
@requiere_plan(db, "premium", global_check=True)
def generar_esquema_desde_pdf():
    # En streaming (SSE, mismo patrón que /generar-test-desde-pdf/
    # /resumir-pdf) para dar progreso real por fragmento.
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "pdf_ia")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    text, documento_id, nombre_archivo, error = _resolver_texto_documento(g.plan_actual)
    if error:
        return error
    if not os.getenv("DEEPSEEK_API_KEY"):
        return jsonify({"error": "API key de DeepSeek no configurada"}), 500

    max_length = 300000
    # texto_truncado_por_longitud: mismo motivo que en /resumir-pdf (ver el
    # comentario largo ahí) -- se avisa más abajo si el resultado final se
    # generó a partir de un documento truncado.
    texto_truncado_por_longitud = len(text) > max_length
    if texto_truncado_por_longitud:
        text = text[:max_length]

    # tipo_contenido (05/08/2026, ver resolver_tipo_contenido en
    # documentos_pdf.py): mismo criterio que /resumir-pdf.
    documento_actual = obtener_documento(db, g.uid, documento_id) if documento_id else None
    # Límite de regeneraciones por documento: mismo motivo que en
    # /resumir-pdf (ver el comentario largo ahí).
    if documento_id and limite_regeneraciones_alcanzado(documento_actual, "esquema"):
        return jsonify({
            "error": f"Has alcanzado el límite de {LIMITE_GENERACIONES_POR_DOCUMENTO} generaciones de "
                     "esquema para este documento (incluida la primera). Sube el documento de nuevo "
                     "para poder generar un esquema distinto.",
        }), 429
    tipo_contenido = resolver_tipo_contenido(
        db, g.uid, documento_id, documento_actual, text, _leer_override_texto_legal(),
    )
    es_legal = tipo_contenido == "legal"

    system_prompt = (
        "Eres un experto en oposiciones. Crea un ESQUEMA de estudio: no es un resumen "
        "en prosa, es un árbol jerárquico de epígrafes y sub-epígrafes que refleje la "
        "estructura real del documento (título > capítulo > artículo > apartado, o el "
        "equivalente en el documento dado), pensado para repasar de un vistazo. Usa "
        "EXACTAMENTE este formato Markdown, sin desviarte de él:\n"
        "- Encabezados de nivel 1 con \"# \" para las secciones principales del temario "
        "(p. ej. cada título o bloque grande).\n"
        "- Encabezados de nivel 2 con \"## \" para subsecciones dentro de cada sección "
        "(p. ej. cada capítulo o epígrafe).\n"
        "- Encabezados de nivel 3 con \"### \" cuando dentro de una subsección haya que "
        "bajar un nivel más (p. ej. cada artículo o punto concreto dentro de un "
        "capítulo). Usa este tercer nivel siempre que el documento tenga esa "
        "profundidad real: NO lo omitas ni lo aplanes al nivel 2 de forma artificial.\n"
        "- Texto en **negrita** para términos clave, nombres de leyes o artículos, la "
        "primera vez que aparecen.\n"
        "- Listas con \"- \" para viñetas normales. IMPORTANTE: anida las viñetas todo lo "
        "que haga falta para reflejar la jerarquía real (una idea que detalla o depende "
        "de la viñeta anterior va debajo de ella, indentada con 2 espacios más por cada "
        "nivel de profundidad, exactamente igual que una lista anidada de Markdown). Un "
        "esquema con viñetas anidadas es MEJOR que uno plano: no limites la profundidad "
        "de anidación.\n"
        "- Listas numeradas con \"1. \", \"2. \", etc. cuando el orden importe (por "
        "ejemplo, pasos de un procedimiento o fases de un proceso). También pueden "
        "anidarse igual que las viñetas.\n"
        "- Cuando definas formalmente un concepto, usa el prefijo \"> \" para esa línea, "
        "de forma que se pueda destacar como una caja de definición aparte.\n"
        "REGLA CLAVE contra la duplicación: cada tema o epígrafe del documento debe "
        "aparecer UNA SOLA VEZ en el esquema, en el nivel de profundidad que le "
        "corresponda. Si el documento vuelve a tratar el mismo epígrafe más adelante con "
        "más detalle (por ejemplo, un índice o resumen inicial y luego un desarrollo "
        "artículo por artículo del mismo título), NO crees una segunda sección "
        "independiente para ese mismo epígrafe: integra ese detalle como sub-viñetas "
        "anidadas bajo el encabezado ya existente de ese epígrafe. Todas las secciones "
        "del esquema deben acabar con un nivel de detalle similar entre sí -- evita que "
        "una sección quede muy desarrollada y las demás apenas esbozadas.\n"
        "No uses tablas, bloques de código, ni HTML. Cada línea de texto debe ir en su "
        "propio párrafo o viñeta, sin mezclar varias ideas en una misma línea larga.\n"
        + _CLAUSULA_FIDELIDAD_DOCUMENTO
    )
    instrucciones_fusion_esquema = (
        "Al fusionar los fragmentos, presta especial atención a que un mismo epígrafe o "
        "sección del documento no aparezca dos veces a distinta profundidad (por "
        "ejemplo, una versión breve tipo índice en un fragmento y luego un desarrollo "
        "mucho más detallado del MISMO epígrafe en otro fragmento): en ese caso, fusiona "
        "ambas versiones en una única sección, usando la más detallada como base y "
        "anidando el resto como sub-viñetas, en vez de dejar las dos como secciones "
        "independientes. Vigila también que la profundidad de detalle quede equilibrada "
        "entre secciones -- si una sección terminó mucho más desarrollada que el resto "
        "por venir de un fragmento distinto, resúmela ligeramente para igualar el nivel "
        "de detalle general del esquema."
    )
    if es_legal:
        # Reforzado, no sustituido (05/08/2026): la regla de arriba contra
        # duplicar un mismo epígrafe a distinta profundidad sigue haciendo
        # falta en un texto legal (un índice + desarrollo del mismo título
        # es un patrón habitual también en leyes) -- esto se SUMA, pidiendo
        # además que la numeración de artículos sea el eje del esquema y
        # que dos artículos distintos nunca se fusionen bajo un mismo
        # epígrafe aunque traten un tema parecido.
        instrucciones_fusion_esquema += (
            "\n\nAdemás, al ser un documento legal: la numeración de artículos debe ser "
            "el eje del esquema -- cada artículo mantiene su propio epígrafe con su "
            "número exacto, y NUNCA se fusionan dos artículos distintos bajo un mismo "
            "epígrafe aunque traten un tema similar, ni siquiera para simplificar. Si dos "
            "fragmentos citan el mismo artículo (por repetirse en el documento), fusiona "
            "esas dos versiones en una sola entrada para ESE artículo, pero mantenlo "
            "separado de cualquier otro artículo distinto."
        )

    uid = g.uid
    plan_actual = g.plan_actual
    # Ver el comentario largo en /resumir-pdf: la comprobación de arriba es
    # solo un filtro rápido, reservar_uso (comprueba + cobra en una única
    # transacción atómica) es la que de verdad cierra la ventana de carrera.
    permitido, mensaje_error, _usados, _limite = reservar_uso(db, uid, "pdf_ia", plan_actual)
    if not permitido:
        return jsonify({"error": mensaje_error}), 429

    def generar():
        eventos = queue.Queue()
        acumulador_tokens = AcumuladorTokens()

        def _en_hilo_de_fondo():
            evento_parada = generacion_control.registrar(uid, documento_id, "esquema") if documento_id else None

            def on_progreso(evento_progreso):
                eventos.put({"tipo": "progreso", **evento_progreso})
                if documento_id:
                    try:
                        actualizar_progreso_generacion(db, uid, documento_id, "esquema", **evento_progreso)
                    except Exception:
                        logger.exception("No se pudo guardar el progreso de /generar-esquema-desde-pdf")
            if documento_id:
                try:
                    limpiar_error_generacion(db, uid, documento_id, "esquema")
                except Exception:
                    logger.exception("No se pudo limpiar el error previo de /generar-esquema-desde-pdf")
            try:
                esquema = _generar_documento_validado(
                    system_prompt,
                    text,
                    etiqueta_documento="Documento para crear esquema",
                    instrucciones_fusion_extra=instrucciones_fusion_esquema,
                    evento_parada=evento_parada,
                    # max_tokens más alto en modo legal -- ver el comentario
                    # largo en resumir_pdf, mismo motivo (el esquema legal
                    # también exige que cada artículo mantenga su propio
                    # epígrafe).
                    max_tokens=8192 if es_legal else 4096,
                    # tamano_chunk propio, más bajo que el general
                    # (TAMANO_CHUNK_ESQUEMA, ver el comentario largo junto a
                    # su definición en deepseek_utils.py): un esquema
                    # reproduce la estructura completa en viñetas anidadas en
                    # vez de condensarla en prosa, así que necesita mucho más
                    # presupuesto de salida por carácter de entrada que un
                    # resumen -- bug real (10/08/2026): con el umbral
                    # general, un documento de ~20-24.000 caracteres se
                    # generaba en una sola llamada y el esquema se cortaba
                    # antes de cubrir ni la mitad del documento, mientras que
                    # el resumen del mismo documento (mismo umbral, mucho más
                    # compacto de por sí) llegaba mucho más lejos.
                    tamano_chunk=TAMANO_CHUNK_ESQUEMA,
                    on_usage=acumulador_tokens.add,
                    on_progreso=on_progreso,
                    # Umbrales de colapso propios del esquema (10/08/2026,
                    # bug real: fallaba mientras el resumen del mismo
                    # documento no) -- ver el comentario largo junto a
                    # FRACCION_MINIMA_MAP_ESQUEMA en deepseek_utils.py: un
                    # árbol de epígrafes en viñetas es, por diseño, mucho
                    # más compacto que su fuente incluso estando completo,
                    # así que los umbrales generales (pensados para prosa)
                    # lo marcaban como "colapsado" sin estarlo.
                    fraccion_minima_map=FRACCION_MINIMA_MAP_ESQUEMA,
                    fraccion_minima_fusion=FRACCION_MINIMA_FUSION_ESQUEMA,
                )
                if esquema:
                    if texto_truncado_por_longitud:
                        esquema = (
                            "> **Aviso:** este documento supera la longitud que esta herramienta "
                            "puede analizar de una vez, así que el esquema se ha generado solo a "
                            "partir de la primera parte. Para cubrirlo entero, divide el documento "
                            "en partes más cortas y súbelas por separado.\n\n"
                        ) + esquema
                    resultado = {
                        "esquema": esquema, "documento_id": documento_id, "nombre_archivo": nombre_archivo,
                        "tipo_contenido_detectado": tipo_contenido,
                    }
                    # Guardado desde el propio hilo de fondo -- mismo motivo
                    # que en /resumir-pdf (ver el comentario largo ahí).
                    if documento_id:
                        guardar_resultado_en_firestore(
                            db=db, tipo="esquema_pdf", contenido=esquema, usuario_id=uid,
                            metadatos={
                                "nombre_archivo": nombre_archivo,
                                "documento_id": documento_id,
                                "longitud": len(esquema),
                                "fecha_procesamiento": datetime.utcnow().isoformat(),
                            },
                        )
                else:
                    resultado = {"error": "Error en DeepSeek API"}
            except Exception:
                logger.exception("Error en /generar-esquema-desde-pdf")
                resultado = {"error": "Error al procesar el PDF."}
            if not resultado.get("esquema"):
                devolver_uso(db, uid, "pdf_ia", plan_actual)
                if documento_id:
                    try:
                        marcar_error_generacion(db, uid, documento_id, "esquema", resultado.get("error", "Error desconocido"))
                    except Exception:
                        logger.exception("No se pudo marcar el error de /generar-esquema-desde-pdf")
            acumulador_tokens.volcar_directo(db, uid)
            if documento_id:
                try:
                    limpiar_progreso_generacion(db, uid, documento_id, "esquema")
                except Exception:
                    logger.exception("No se pudo limpiar el progreso de /generar-esquema-desde-pdf")
            if documento_id:
                generacion_control.desregistrar(uid, documento_id, "esquema")
            eventos.put({"tipo": "fin", **resultado})

        hilo = threading.Thread(target=_en_hilo_de_fondo, daemon=True)
        hilo.start()

        yield f"data: {json.dumps({'tipo': 'inicio', 'documento_id': documento_id}, ensure_ascii=False)}\n\n"

        while True:
            evento = eventos.get()
            yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
            if evento["tipo"] == "fin":
                break

    return Response(
        stream_with_context(generar()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
    )


@bp.route('/generar-test-desde-pdf', methods=['POST'])
@limiter.limit("5 per minute")
@requiere_plan(db, "premium", global_check=True)
def generar_test_desde_pdf():
    # En streaming (SSE, mismo patrón que /generar-test-avanzado en
    # blueprints/test_ia.py) para poder retransmitir progreso real por lote
    # en vez de los mensajes rotativos cosméticos que tenía antes -- generar
    # varios lotes en paralelo con IA tarda bastante más que una respuesta
    # instantánea, sobre todo con num_preguntas alto.
    try:
        num_preguntas = int(request.form.get("num_preguntas", 10))
        if num_preguntas < 1 or num_preguntas > 100:
            num_preguntas = 10
    except (ValueError, TypeError):
        num_preguntas = 10
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "pdf_ia")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    text, documento_id, nombre_archivo, error = _resolver_texto_documento(g.plan_actual)
    if error:
        return error

    # max_length=800000 (subido de 150000 el 02/08/2026): el límite de
    # páginas por plan (ver limites_uso.MAX_PAGINAS_POR_PLAN, 200 páginas
    # como tope, igualando a la competencia) permite subir PDFs de hasta
    # 200 páginas -- con 150000 caracteres, un documento de texto legal
    # denso (~2000-4000 caracteres/página) se cortaba ya a partir de ~40-75
    # páginas, y todo lo posterior se descartaba en silencio ANTES incluso
    # de llegar al reparto en lotes (ver _fragmentos_por_lote en
    # test_generator.py): por muy bien que se reparta el texto que SÍ
    # llega, el resto del documento nunca se llega a ver. 800000
    # caracteres cubre con margen 200 páginas incluso en el caso más denso,
    # y sigue siendo una fracción pequeña de la ventana de contexto de
    # deepseek-v4-flash (1M tokens, varios millones de caracteres).
    max_length = 800000
    if len(text) > max_length:
        text = text[:max_length]

    # Al pulsar "generar test" otra vez sobre un documento ya subido antes
    # (viene con documento_id), se recuperan las preguntas de sus tests
    # anteriores para que el nuevo test no vuelva a preguntar por los
    # mismos datos -- la deduplicación existente (fragmentar el documento
    # por lote, relleno evitando "lo ya cubierto en este test") solo actúa
    # dentro de una misma llamada (ver test_generator.py, preguntas_a_evitar).
    preguntas_previas = obtener_preguntas_previas(db, g.uid, documento_id)

    def construir_prompt(n, fragmento=None):
        documento = fragmento if fragmento is not None else text
        system_prompt = (
            f"Eres un experto en la elaboración de preguntas tipo test para oposiciones oficiales en España. "
            f"Tu tarea es generar EXACTAMENTE {n} preguntas de opción múltiple de alta calidad, "
            f"basadas únicamente en el documento proporcionado. Cada pregunta debe cumplir lo siguiente:\n"
            f"1. **Formato**: pregunta clara y directa, seguida de cuatro opciones (A, B, C, D).\n"
            f"2. **Precisión**: si el documento menciona leyes, artículos, plazos, funciones, definiciones, principios o procedimientos, la pregunta debe reflejarlos con exactitud. Si citas un número de artículo, di TAMBIÉN en la misma frase el nombre de la ley o norma a la que pertenece (tal como aparece en el documento) -- un artículo mencionado sin decir de qué norma es deja a quien lo lee sin poder ubicarlo.\n"
            f"3. **Respuesta correcta**: debe ser inequívoca y extraída directamente del texto.\n"
            f"4. **Distractores**: deben ser técnicamente plausibles, basados en confusiones comunes, errores típicos o elementos similares del propio documento.\n"
            f"5. **Neutralidad**: evita lenguaje coloquial, ambigüedades, opiniones o preguntas triviales.\n"
            f"6. **Explicación**: repasa TODAS las opciones, una por línea y en orden, con este formato exacto: \"A) es correcta/incorrecta porque... B) es correcta/incorrecta porque... C) ... D) ...\", citando o basándote en el contenido del documento.\n"
            f"7. **Autocontenida**: quien responde el test NUNCA ve el documento de origen, solo la pregunta. Nunca remitas a \"el documento\", \"el contenido\", \"el texto\" o \"lo mencionado/anterior\" (p. ej. \"¿qué tienen en común los X mencionados en el contenido?\") -- nombra tú mismo, explícitamente, de qué elementos concretos hablas.\n"
            f"8. **Sin siglas**: nunca abrevies el nombre de una ley o norma con siglas (\"CE\", \"TREBEP\", \"LPAC\"...) ni escribas \"art.\" en vez de \"artículo\" -- los exámenes oficiales de esta oposición escriben siempre el nombre completo, tal como aparece en el documento. Esto incluye también abreviar el tipo de norma delante de su número (\"LO 3/2007\", \"RD 203/2021\"...) en vez de escribirlo entero (\"Ley Orgánica 3/2007\", \"Real Decreto 203/2021\").\n"
            f"9. **Diversidad**: las {n} preguntas deben tratar {n} hechos, artículos, plazos o cifras DISTINTOS entre sí -- si el documento repite el mismo dato en varios sitios, pregúntalo como mucho una vez; no reformules la misma pregunta con otro enunciado ni dediques dos preguntas al mismo hecho central.\n"
            f"Devuelve SOLO un array JSON válido con este formato exacto:\n"
            f"[{{\"pregunta\": \"...\", \"opciones\": {{\"A\": \"...\", \"B\": \"...\", \"C\": \"...\", \"D\": \"...\"}}, \"respuesta_correcta\": \"A\", \"explicacion\": \"...\"}}]\n"
            f"NO añadas texto adicional antes ni después del array JSON."
        )
        if fragmento is not None:
            system_prompt += (
                "\n\nIMPORTANTE: el documento de abajo es SOLO UNA PARTE del documento completo -- hay más "
                "contenido en otras partes que no ves aquí (ya se están generando preguntas sobre ellas por "
                "separado). Basa tus preguntas ÚNICAMENTE en lo que aparece en este fragmento, sin dar por "
                "hecho ni inventar contenido de las partes que no ves."
            )
        return f"{system_prompt}\n\nDocumento para crear preguntas test:\n{documento}"

    uid = g.uid
    plan_actual = g.plan_actual

    # reservar_uso comprueba Y cobra en una única transacción atómica, por
    # adelantado (no al llegar "fin"): el hilo de fondo sigue generando y
    # gastando en DeepSeek aunque el cliente corte la conexión SSE, así que
    # cobrar al final permitía saltarse la cuota abortando la petición en
    # bucle -- y hacerlo en una transacción (en vez de la comprobación de
    # arriba, que es sin transacción y solo un filtro rápido) cierra además
    # la ventana de carrera entre comprobar y cobrar. Si la generación falla
    # de verdad (0 preguntas), se devuelve con devolver_uso.
    #
    # Sentry PYTHON-FLASK-1: la transacción de Firestore puede expirar
    # (InvalidArgument) por un problema transitorio de Firestore ajeno a
    # esta petición -- no debe convertirse en un 500 para el usuario por el
    # fallo de un simple contador de cuota, así que se deja pasar (fail
    # open) igual que hacía antes el registrar_uso equivalente.
    permitido, mensaje_error = True, None
    try:
        permitido, mensaje_error, _usados, _limite = reservar_uso(db, uid, "pdf_ia", plan_actual)
    except google_exceptions.InvalidArgument:
        logger.warning(
            "No se pudo reservar el uso de pdf_ia (transacción de Firestore expirada) para uid=%s en %s",
            uid, datetime.utcnow().isoformat(),
        )
    if not permitido:
        return jsonify({"error": mensaje_error}), 429

    def generar():
        eventos = queue.Queue()
        acumulador_tokens = AcumuladorTokens()

        def _en_hilo_de_fondo():
            def on_progreso(evento_progreso):
                # "pregunta" se manda como evento aparte (no como parte de
                # "progreso") para que el frontend pueda empezar el test en
                # cuanto lleguen las primeras N preguntas aceptadas, sin
                # esperar a que termine todo el test -- mismo patrón que
                # /generar-test-avanzado usa para Test Personalizado (ver
                # blueprints/test_ia.py).
                pregunta = evento_progreso.pop("pregunta", None)
                eventos.put({"tipo": "progreso", **evento_progreso})
                if pregunta:
                    eventos.put({
                        "tipo": "pregunta", "pregunta": pregunta,
                        "completadas": evento_progreso["completadas"], "total": evento_progreso["total"],
                    })
            try:
                preguntas, errores_lotes = generar_preguntas_ia_en_lotes(
                    construir_prompt, num_preguntas, text, on_progreso=on_progreso,
                    on_usage=acumulador_tokens.add, preguntas_a_evitar=preguntas_previas,
                )
                if not preguntas:
                    # Si TODOS los errores de lote son de verificación (no de
                    # generación), ninguna pregunta llegó a fallar por un
                    # problema técnico de DeepSeek: el documento sencillamente
                    # no tenía suficiente contenido distinto para las
                    # preguntas pedidas, y decirlo así evita el mensaje
                    # confuso de "error técnico" (ver test_generator.py,
                    # _pedir_lote_verificado).
                    if errores_lotes and all(e.startswith("Ninguna de las") for e in errores_lotes):
                        mensaje_error = (
                            f"No se pudo generar ninguna pregunta que superase la verificación de calidad "
                            f"a partir de este documento para las {num_preguntas} preguntas solicitadas. "
                            f"El PDF puede ser demasiado corto o repetitivo para tantas preguntas distintas "
                            f"-- prueba a pedir menos preguntas o sube un documento más extenso."
                        )
                    else:
                        mensaje_error = "La IA no devolvió un JSON válido para las preguntas. Error técnico."
                    resultado = {
                        "test": [],
                        "error": mensaje_error,
                        "respuesta_cruda": "; ".join(errores_lotes)[:500]
                    }
                else:
                    preguntas_validadas = [
                        normalizada for p in preguntas
                        if (normalizada := _normalizar_pregunta_pdf(p)) is not None
                    ]
                    if not preguntas_validadas:
                        resultado = {"test": [], "error": "La IA generó preguntas vacías o inválidas."}
                    else:
                        resultado = {"test": preguntas_validadas, "documento_id": documento_id, "nombre_archivo": nombre_archivo}
                        if len(preguntas_validadas) < num_preguntas:
                            resultado["advertencia"] = f"Solo se generaron {len(preguntas_validadas)} de {num_preguntas} preguntas."
            except Exception:
                logger.exception("Error en /generar-test-desde-pdf")
                resultado = {"test": [], "error": "Error al procesar el PDF o generar preguntas."}
            if not resultado.get("test"):
                devolver_uso(db, uid, "pdf_ia", plan_actual)
            # Este hilo corre desligado de la petición (igual que el generador
            # de Test Personalizado, ver generador_preguntas_verificado.py) --
            # flask.g no está disponible aquí, así que se vuelca directo a
            # Firestore en vez de a través del teardown_request habitual.
            acumulador_tokens.volcar_directo(db, uid)
            eventos.put({"tipo": "fin", **resultado})

        hilo = threading.Thread(target=_en_hilo_de_fondo, daemon=True)
        hilo.start()

        while True:
            evento = eventos.get()
            yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
            if evento["tipo"] == "fin":
                break

    return Response(
        stream_with_context(generar()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
    )


@bp.route('/generar-tarjetas-desde-pdf', methods=['POST'])
@limiter.limit("5 per minute")
@requiere_plan(db, "premium", global_check=True)
def generar_tarjetas_desde_pdf():
    # En streaming (SSE, mismo patrón que /generar-test-desde-pdf/
    # /resumir-pdf/generar-esquema-desde-pdf) para dar progreso real por
    # tarjeta verificada en vez de mensajes rotativos cosméticos.
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "pdf_ia")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    text, documento_id, nombre_archivo, error = _resolver_texto_documento(g.plan_actual)
    if error:
        return error
    if not os.getenv("DEEPSEEK_API_KEY"):
        return jsonify({"error": "API key de DeepSeek no configurada"}), 500

    # max_length=800000: mismo motivo y mismo valor que
    # /generar-test-desde-pdf (ver el comentario largo ahí) -- soportar los
    # PDFs de hasta 200 páginas que los usuarios van a poder subir sin
    # cortar el documento en silencio antes de llegar al reparto por
    # fragmentos.
    max_length = 800000
    if len(text) > max_length:
        text = text[:max_length]
    try:
        num_tarjetas = int(request.form.get("num_tarjetas", 10))
    except (TypeError, ValueError):
        num_tarjetas = 10
    num_tarjetas = max(1, min(num_tarjetas, 50))

    uid = g.uid
    plan_actual = g.plan_actual
    # Se comprueba y se cobra en una única transacción atómica (reservar_uso,
    # ver el comentario largo en /resumir-pdf) por adelantado (mismo motivo
    # que /generar-test-desde-pdf: el hilo de fondo sigue gastando en
    # DeepSeek aunque el cliente corte la conexión SSE, así que cobrar solo
    # al final permitiría saltarse la cuota abortando la petición en bucle)
    # y se devuelve si no se genera ninguna tarjeta válida.
    permitido, mensaje_error, _usados, _limite = reservar_uso(db, uid, "pdf_ia", plan_actual)
    if not permitido:
        return jsonify({"error": mensaje_error}), 429

    def generar():
        eventos = queue.Queue()
        acumulador_tokens = AcumuladorTokens()

        def _en_hilo_de_fondo():
            def on_progreso(evento_progreso):
                # "tarjeta" se manda como evento aparte (no como parte de
                # "progreso") para que el frontend pueda dejar repasar las
                # tarjetas en cuanto lleguen las primeras N aceptadas, sin
                # esperar a que termine todo el documento -- mismo patrón
                # que /generar-test-desde-pdf usa para sus preguntas.
                tarjeta = evento_progreso.pop("tarjeta", None)
                eventos.put({"tipo": "progreso", **evento_progreso})
                if tarjeta:
                    eventos.put({
                        "tipo": "tarjeta", "tarjeta": tarjeta,
                        "completadas": evento_progreso["completadas"], "total": evento_progreso["total"],
                    })
            try:
                resultado_generacion = generar_tarjetas_verificadas(
                    text, num_tarjetas, on_usage=acumulador_tokens.add, on_progreso=on_progreso,
                )
                if not resultado_generacion["tarjetas"]:
                    resultado = {"error": "La IA no generó ninguna tarjeta válida a partir del documento."}
                else:
                    resultado = {
                        "tarjetas": resultado_generacion["tarjetas"],
                        "documento_id": documento_id,
                        "nombre_archivo": nombre_archivo,
                    }
                    if "advertencia" in resultado_generacion:
                        resultado["advertencia"] = resultado_generacion["advertencia"]
            except Exception:
                logger.exception("Error en /generar-tarjetas-desde-pdf")
                resultado = {"error": "Error al procesar el PDF o generar tarjetas."}
            if not resultado.get("tarjetas"):
                devolver_uso(db, uid, "pdf_ia", plan_actual)
            acumulador_tokens.volcar_directo(db, uid)
            eventos.put({"tipo": "fin", **resultado})

        hilo = threading.Thread(target=_en_hilo_de_fondo, daemon=True)
        hilo.start()

        while True:
            evento = eventos.get()
            yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
            if evento["tipo"] == "fin":
                break

    return Response(
        stream_with_context(generar()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
    )


# ===================================================================
# BANCO DE PREGUNTAS/TARJETAS (03/08/2026): en vez de generar un número fijo
# de preguntas/tarjetas por petición y descartar el resto del documento, se
# genera en segundo plano el máximo aprovechable de un documento (hasta
# TOPE_BANCO_PREGUNTAS/TOPE_BANCO_TARJETAS, ver generar_banco_preguntas_
# adaptativo/generar_banco_tarjetas_adaptativo) y se guarda de forma
# incremental en Firestore (usuarios/{uid}/banco_preguntas_pdf|
# banco_tarjetas_pdf/{documento_id}, ver documentos_pdf.py) para que quede
# disponible en "Mis documentos" aunque el usuario cierre la pestaña antes
# de que termine -- mismo motivo que ya justificaba correr la generación en
# un hilo daemon desligado de la petición SSE (ver el comentario en
# generar_test_desde_pdf), llevado un paso más allá: antes, si nadie estaba
# escuchando cuando llegaba el evento "fin", el contenido generado se
# perdía por completo pese a haberse cobrado ya el uso.
# ===================================================================
@bp.route('/generar-banco-preguntas-desde-pdf', methods=['POST'])
@limiter.limit("5 per minute")
@requiere_plan(db, "premium", global_check=True)
def generar_banco_preguntas_desde_pdf():
    # Ruta de entrada única (mismo patrón que /generar-test-desde-pdf, ver
    # _resolver_texto_documento): acepta tanto un PDF nuevo (campo "pdf")
    # como un documento ya subido (campo "documento_id"). Sustituye a la
    # generación de un número fijo de preguntas como punto de entrada
    # normal desde "Subir PDF" (03/08/2026, decisión explícita del
    # usuario): en vez de preguntar "¿cuántas preguntas quieres?" y generar
    # solo esas, se genera directamente el banco completo (máximo
    # aprovechable del documento) y el frontend arranca el test con todo
    # lo generado -- si luego quiere repetir con menos, ya puede elegir
    # "Test de 10" desde "Mis documentos" sobre el mismo banco, sin volver
    # a gastar en IA.
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "pdf_ia")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    text, documento_id, nombre_archivo, error = _resolver_texto_documento(g.plan_actual)
    if error:
        return error
    banco_existente = obtener_banco(db, g.uid, documento_id, "preguntas")
    if banco_existente and banco_existente.get("estado") == "generando":
        return jsonify({"error": "Ya se está generando el banco de preguntas de este documento."}), 409

    max_length = 800000
    if len(text) > max_length:
        text = text[:max_length]
    preguntas_previas = obtener_preguntas_previas(db, g.uid, documento_id)

    def construir_prompt(n, fragmento=None):
        documento_texto = fragmento if fragmento is not None else text
        system_prompt = (
            f"Eres un experto en la elaboración de preguntas tipo test para oposiciones oficiales en España. "
            f"Tu tarea es generar EXACTAMENTE {n} preguntas de opción múltiple de alta calidad, "
            f"basadas únicamente en el documento proporcionado. Cada pregunta debe cumplir lo siguiente:\n"
            f"1. **Formato**: pregunta clara y directa, seguida de cuatro opciones (A, B, C, D).\n"
            f"2. **Precisión**: si el documento menciona leyes, artículos, plazos, funciones, definiciones, principios o procedimientos, la pregunta debe reflejarlos con exactitud. Si citas un número de artículo, di TAMBIÉN en la misma frase el nombre de la ley o norma a la que pertenece (tal como aparece en el documento) -- un artículo mencionado sin decir de qué norma es deja a quien lo lee sin poder ubicarlo.\n"
            f"3. **Respuesta correcta**: debe ser inequívoca y extraída directamente del texto.\n"
            f"4. **Distractores**: deben ser técnicamente plausibles, basados en confusiones comunes, errores típicos o elementos similares del propio documento.\n"
            f"5. **Neutralidad**: evita lenguaje coloquial, ambigüedades, opiniones o preguntas triviales.\n"
            f"6. **Explicación**: repasa TODAS las opciones, una por línea y en orden, con este formato exacto: \"A) es correcta/incorrecta porque... B) es correcta/incorrecta porque... C) ... D) ...\", citando o basándote en el contenido del documento.\n"
            f"7. **Autocontenida**: quien responde el test NUNCA ve el documento de origen, solo la pregunta. Nunca remitas a \"el documento\", \"el contenido\", \"el texto\" o \"lo mencionado/anterior\" (p. ej. \"¿qué tienen en común los X mencionados en el contenido?\") -- nombra tú mismo, explícitamente, de qué elementos concretos hablas.\n"
            f"8. **Sin siglas**: nunca abrevies el nombre de una ley o norma con siglas (\"CE\", \"TREBEP\", \"LPAC\"...) ni escribas \"art.\" en vez de \"artículo\" -- los exámenes oficiales de esta oposición escriben siempre el nombre completo, tal como aparece en el documento. Esto incluye también abreviar el tipo de norma delante de su número (\"LO 3/2007\", \"RD 203/2021\"...) en vez de escribirlo entero (\"Ley Orgánica 3/2007\", \"Real Decreto 203/2021\").\n"
            f"9. **Diversidad**: las {n} preguntas deben tratar {n} hechos, artículos, plazos o cifras DISTINTOS entre sí -- si el documento repite el mismo dato en varios sitios, pregúntalo como mucho una vez; no reformules la misma pregunta con otro enunciado ni dediques dos preguntas al mismo hecho central.\n"
            f"Devuelve SOLO un array JSON válido con este formato exacto:\n"
            f"[{{\"pregunta\": \"...\", \"opciones\": {{\"A\": \"...\", \"B\": \"...\", \"C\": \"...\", \"D\": \"...\"}}, \"respuesta_correcta\": \"A\", \"explicacion\": \"...\"}}]\n"
            f"NO añadas texto adicional antes ni después del array JSON."
        )
        if fragmento is not None:
            system_prompt += (
                "\n\nIMPORTANTE: el documento de abajo es SOLO UNA PARTE del documento completo -- hay más "
                "contenido en otras partes que no ves aquí (ya se están generando preguntas sobre ellas por "
                "separado). Basa tus preguntas ÚNICAMENTE en lo que aparece en este fragmento, sin dar por "
                "hecho ni inventar contenido de las partes que no ves."
            )
        return f"{system_prompt}\n\nDocumento para crear preguntas test:\n{documento_texto}"

    uid = g.uid
    plan_actual = g.plan_actual
    # banco_pdf_mensual ya no se cobra aquí (se cobra una única vez al subir
    # el documento, en _resolver_texto_documento) -- este cupo es solo
    # pdf_ia, igual que el resto de rutas. reservar_uso comprueba y cobra en
    # una única transacción atómica, que es lo que de verdad cierra la
    # ventana de carrera frente a la comprobación previa (solo un filtro
    # rápido, ver el comentario largo en /resumir-pdf).
    permitido, mensaje_error, _usados, _limite = reservar_uso(db, uid, "pdf_ia", plan_actual)
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    iniciar_banco(db, uid, documento_id, "preguntas", TOPE_BANCO_PREGUNTAS, nombre_archivo)

    def generar():
        eventos = queue.Queue()
        acumulador_tokens = AcumuladorTokens()
        preguntas_normalizadas = []

        def _en_hilo_de_fondo():
            evento_parada = generacion_control.registrar(uid, documento_id, "banco_preguntas") if documento_id else None

            def on_progreso(evento_progreso):
                if evento_progreso.get("pregunta"):
                    normalizada = _normalizar_pregunta_pdf(dict(evento_progreso["pregunta"]))
                    if normalizada:
                        anadir_al_banco(db, uid, documento_id, "preguntas", normalizada)
                        preguntas_normalizadas.append(normalizada)
                eventos.put({
                    "tipo": "progreso",
                    "completadas": evento_progreso["completadas"],
                    "objetivo": evento_progreso["objetivo"],
                })
            try:
                generar_banco_preguntas_adaptativo(
                    construir_prompt, text, on_usage=acumulador_tokens.add, on_progreso=on_progreso,
                    preguntas_a_evitar=preguntas_previas, evento_parada=evento_parada,
                )
                # "preguntas" en el evento "fin" (03/08/2026): antes solo se
                # mandaba el total -- el frontend necesita el contenido real
                # para poder arrancar el test directamente al terminar, sin
                # una segunda llamada a /banco-preguntas. Se usan las
                # versiones YA normalizadas/barajadas (mismas que se
                # persistieron), no el valor de retorno crudo de
                # generar_banco_preguntas_adaptativo.
                estado_final = "completo" if preguntas_normalizadas else "error"
                resultado = {
                    "total": len(preguntas_normalizadas), "documento_id": documento_id,
                    "nombre_archivo": nombre_archivo, "preguntas": preguntas_normalizadas,
                }
                if not preguntas_normalizadas:
                    resultado["error"] = "No se pudo generar ninguna pregunta a partir de este documento."
            except Exception:
                logger.exception("Error en /generar-banco-preguntas-desde-pdf")
                estado_final = "error"
                resultado = {"error": "Error al generar el banco de preguntas."}
            finalizar_banco(db, uid, documento_id, "preguntas", estado=estado_final, mensaje_error=resultado.get("error"))
            if estado_final == "error":
                devolver_uso(db, uid, "pdf_ia", plan_actual)
            acumulador_tokens.volcar_directo(db, uid)
            if documento_id:
                generacion_control.desregistrar(uid, documento_id, "banco_preguntas")
            eventos.put({"tipo": "fin", **resultado})

        hilo = threading.Thread(target=_en_hilo_de_fondo, daemon=True)
        hilo.start()

        # "inicio" (03/08/2026): documento_id ya existe en Firestore en este
        # punto (iniciar_banco ya corrió antes de construir este generador),
        # así que se manda de inmediato, sin esperar a la generación en sí
        # -- el frontend de "Subir PDF" ya no espera al final del banco
        # (puede tardar varios minutos): lee SOLO este evento para saber a
        # qué documento redirigir en "Mis documentos" y abandona el resto
        # del stream (ver blueprints/pdf_ia/__init__.py y subida-pdf-generar-test/
        # script.js).
        yield f"data: {json.dumps({'tipo': 'inicio', 'documento_id': documento_id, 'nombre_archivo': nombre_archivo}, ensure_ascii=False)}\n\n"

        while True:
            evento = eventos.get()
            yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
            if evento["tipo"] == "fin":
                break

    return Response(
        stream_with_context(generar()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
    )


@bp.route('/generar-banco-tarjetas-desde-pdf', methods=['POST'])
@limiter.limit("5 per minute")
@requiere_plan(db, "premium", global_check=True)
def generar_banco_tarjetas_desde_pdf():
    # Ruta de entrada única: ver el comentario largo en
    # generar_banco_preguntas_desde_pdf -- mismo motivo y mismo patrón,
    # aplicado a tarjetas.
    permitido, mensaje_error, _usados, _limite = verificar_limite_uso(db, g.uid, g.plan_actual, "pdf_ia")
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    text, documento_id, nombre_archivo, error = _resolver_texto_documento(g.plan_actual)
    if error:
        return error
    banco_existente = obtener_banco(db, g.uid, documento_id, "tarjetas")
    if banco_existente and banco_existente.get("estado") == "generando":
        return jsonify({"error": "Ya se está generando el banco de tarjetas de este documento."}), 409

    max_length = 800000
    if len(text) > max_length:
        text = text[:max_length]
    uid = g.uid
    plan_actual = g.plan_actual
    # Ver el comentario largo en generar_banco_preguntas_desde_pdf: solo
    # pdf_ia (banco_pdf_mensual se cobra al subir el documento), con
    # reservar_uso para cerrar la ventana de carrera.
    permitido, mensaje_error, _usados, _limite = reservar_uso(db, uid, "pdf_ia", plan_actual)
    if not permitido:
        return jsonify({"error": mensaje_error}), 429
    iniciar_banco(db, uid, documento_id, "tarjetas", TOPE_BANCO_TARJETAS, nombre_archivo)

    def generar():
        eventos = queue.Queue()
        acumulador_tokens = AcumuladorTokens()
        tarjetas_generadas = []

        def _en_hilo_de_fondo():
            evento_parada = generacion_control.registrar(uid, documento_id, "banco_tarjetas") if documento_id else None

            def on_progreso(evento_progreso):
                if evento_progreso.get("tarjeta"):
                    anadir_al_banco(db, uid, documento_id, "tarjetas", evento_progreso["tarjeta"])
                    tarjetas_generadas.append(evento_progreso["tarjeta"])
                eventos.put({
                    "tipo": "progreso",
                    "completadas": evento_progreso["completadas"],
                    "objetivo": evento_progreso["objetivo"],
                })
            try:
                generar_banco_tarjetas_adaptativo(
                    text, on_usage=acumulador_tokens.add, on_progreso=on_progreso, evento_parada=evento_parada,
                )
                # "tarjetas" en el evento "fin": ver el comentario largo en
                # generar_banco_preguntas_desde_pdf -- mismo motivo.
                estado_final = "completo" if tarjetas_generadas else "error"
                resultado = {
                    "total": len(tarjetas_generadas), "documento_id": documento_id,
                    "nombre_archivo": nombre_archivo, "tarjetas": tarjetas_generadas,
                }
                if not tarjetas_generadas:
                    resultado["error"] = "No se pudo generar ninguna tarjeta a partir de este documento."
            except Exception:
                logger.exception("Error en /generar-banco-tarjetas-desde-pdf")
                estado_final = "error"
                resultado = {"error": "Error al generar el banco de tarjetas."}
            finalizar_banco(db, uid, documento_id, "tarjetas", estado=estado_final, mensaje_error=resultado.get("error"))
            if estado_final == "error":
                devolver_uso(db, uid, "pdf_ia", plan_actual)
            acumulador_tokens.volcar_directo(db, uid)
            if documento_id:
                generacion_control.desregistrar(uid, documento_id, "banco_tarjetas")
            eventos.put({"tipo": "fin", **resultado})

        hilo = threading.Thread(target=_en_hilo_de_fondo, daemon=True)
        hilo.start()

        # "inicio": ver el comentario largo en generar_banco_preguntas_desde_pdf.
        yield f"data: {json.dumps({'tipo': 'inicio', 'documento_id': documento_id, 'nombre_archivo': nombre_archivo}, ensure_ascii=False)}\n\n"

        while True:
            evento = eventos.get()
            yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
            if evento["tipo"] == "fin":
                break

    return Response(
        stream_with_context(generar()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
    )


# /pdf-ia/documento/<id>/detener/<herramienta> (10/08/2026, a petición
# explícita del usuario: "quiero un botón para parar una generación mía en
# curso, no quiero consumir tokens de más haciendo pruebas" -- gated tras
# requiere_admin porque así lo pidió, aunque en la práctica solo puede
# parar generaciones DE SU PROPIA cuenta, ver generacion_control.py: la
# clave registrada es g.uid + documento_id + herramienta, no hay forma de
# apuntar a la generación de otro usuario desde aquí). herramienta es una
# de "resumen"|"esquema"|"banco_preguntas"|"banco_tarjetas" -- las cuatro
# que de verdad comprueban evento_parada en sus puntos de control (ver
# deepseek_utils.generar_documento_largo_por_partes,
# test_generator.generar_banco_preguntas_adaptativo,
# tarjetas_generator.generar_banco_tarjetas_adaptativo). No cancela ninguna
# llamada YA en marcha (no es seguro interrumpir una petición HTTP a
# mitad) -- solo evita que se lance la siguiente ronda/fragmento/fusión.
@bp.route('/pdf-ia/documento/<documento_id>/detener/<herramienta>', methods=['POST'])
@requiere_admin
def detener_generacion(documento_id, herramienta):
    if not generacion_control.solicitar_parada(g.uid, documento_id, herramienta):
        return jsonify({"error": "No hay ninguna generación en curso para detener."}), 404
    return jsonify({"detenido": True})


@bp.route('/documento/<documento_id>/banco-preguntas', methods=['GET'])
@requiere_plan(db, "premium", global_check=True)
def documento_banco_preguntas(documento_id):
    banco = obtener_banco(db, g.uid, documento_id, "preguntas") or {}
    preguntas = banco.get("preguntas", [])
    modo = request.args.get("modo", "todas")
    if modo == "aleatorias" and preguntas:
        try:
            cantidad = int(request.args.get("cantidad", 10))
        except (TypeError, ValueError):
            cantidad = 10
        cantidad = max(1, min(cantidad, len(preguntas)))
        preguntas = random.sample(preguntas, cantidad)
    return jsonify({
        "estado": banco.get("estado", "sin_generar"),
        "total": banco.get("total", 0),
        "objetivo": banco.get("objetivo", 0),
        "nombre_archivo": banco.get("nombre_archivo"),
        "preguntas": preguntas,
    })


@bp.route('/documento/<documento_id>/banco-tarjetas', methods=['GET'])
@requiere_plan(db, "premium", global_check=True)
def documento_banco_tarjetas(documento_id):
    banco = obtener_banco(db, g.uid, documento_id, "tarjetas") or {}
    tarjetas = banco.get("tarjetas", [])
    modo = request.args.get("modo", "todas")
    if modo == "aleatorias" and tarjetas:
        try:
            cantidad = int(request.args.get("cantidad", 10))
        except (TypeError, ValueError):
            cantidad = 10
        cantidad = max(1, min(cantidad, len(tarjetas)))
        tarjetas = random.sample(tarjetas, cantidad)
    return jsonify({
        "estado": banco.get("estado", "sin_generar"),
        "total": banco.get("total", 0),
        "objetivo": banco.get("objetivo", 0),
        "nombre_archivo": banco.get("nombre_archivo"),
        "tarjetas": tarjetas,
    })


@bp.route('/subir-pdf-chat', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def subir_pdf_chat():
    # Comparte _resolver_texto_documento con resumen/esquema/test/tarjetas
    # (12/08/2026): acepta tanto un 'pdf' nuevo como un 'documento_id' ya
    # existente en "Mis documentos", y el texto queda en la misma
    # biblioteca -- antes este endpoint tenía su propio parseo duplicado y
    # guardaba el texto (recortado a 12.000 caracteres) en un campo aparte
    # "chat_pdf_activo" que ninguna otra herramienta veía.
    _text, documento_id, _nombre_archivo, error = _resolver_texto_documento(g.plan_actual)
    if error:
        return error
    documento = obtener_documento(db, g.uid, documento_id)
    return jsonify({
        "mensaje": "PDF cargado correctamente",
        "documento_id": documento_id,
        "nombre_archivo": documento.get("nombre_archivo", "documento.pdf") if documento else _nombre_archivo,
        "paginas": documento.get("num_paginas", 0) if documento else 0,
    })


def _preparar_mensajes_chat_pdf(datos):
    """Común a /chat-pdf-mensaje y /chat-pdf-mensaje/stream: valida la
    petición, resuelve el documento (leído ENTERO de "Mis documentos" en
    cada mensaje, no una copia recortada guardada aparte al subir -- así
    reutiliza exactamente el mismo texto ya extraído para resumen/esquema/
    test/tarjetas) y arma la lista de mensajes para DeepSeek. Devuelve
    (mensajes, documento_id, respuesta_error_o_None); si el último
    elemento no es None, la ruta debe devolverlo tal cual."""
    mensaje = (datos.get("mensaje") or "").strip()
    if not mensaje:
        return None, None, (jsonify({"error": "Falta el mensaje"}), 400)
    documento_id = datos.get("documento_id")
    if not documento_id:
        return None, None, (jsonify({"error": "Primero sube o selecciona un documento para poder chatear sobre él."}), 400)
    historial = datos.get("historial") or []
    if not isinstance(historial, list):
        historial = []

    documento = obtener_documento(db, g.uid, documento_id)
    if not documento:
        return None, None, (jsonify({"error": "No se encontró el documento indicado."}), 404)
    texto_pdf = documento.get("texto")
    if not texto_pdf:
        return None, None, (jsonify({"error": "Primero sube o selecciona un documento para poder chatear sobre él."}), 400)

    system_prompt = (
        "Eres un asistente que ayuda a un opositor a entender un documento que ha subido. "
        "Responde SOLO basándote en el contenido de este documento. Si la respuesta no está "
        "en el documento, dilo claramente en vez de inventar información.\n\n"
        f"Documento ({documento.get('nombre_archivo', 'sin nombre')}):\n{texto_pdf}"
    )
    mensajes = [{"role": "system", "content": system_prompt}]
    # Últimos turnos de la conversación, para que la IA recuerde el
    # contexto sin dejar que el prompt crezca sin límite en chats largos.
    for turno in historial[-12:]:
        role = turno.get("role")
        content = turno.get("content")
        if role in ("user", "assistant") and content:
            mensajes.append({"role": role, "content": str(content)[:2000]})
    mensajes.append({"role": "user", "content": mensaje})
    return mensajes, documento_id, None


@bp.route('/chat-pdf-mensaje', methods=['POST'])
@limiter.limit("20 per minute")
@requiere_plan(db, "premium", global_check=True)
def chat_pdf_mensaje():
    datos = request.get_json(silent=True) or {}
    mensajes, documento_id, error = _preparar_mensajes_chat_pdf(datos)
    if error:
        return error

    # reservar_uso comprueba Y cobra en una única transacción atómica, ANTES
    # de llamar a la IA (no solo verificar y cobrar aparte después de tener
    # la respuesta) -- así dos peticiones concurrentes no pueden pasar la
    # comprobación las dos a la vez. Se reembolsa con devolver_uso si
    # DeepSeek no llega a responder.
    permitido, mensaje_error, _usados, _limite = reservar_uso(db, g.uid, "chat_pdf", g.plan_actual)
    if not permitido:
        return jsonify({"error": mensaje_error}), 429

    # call_deepseek_api (en vez de requests.post a pelo, como antes):
    # registra el coste real de la llamada automáticamente (vía flask.g,
    # el mismo mecanismo que ya usa el resto de la app) y no filtra nunca
    # el texto interno de una excepción al cliente.
    respuesta = call_deepseek_api(
        mensajes, max_tokens=800, temperature=0.4, contexto=f"chat_pdf documento={documento_id}",
    )
    if not respuesta:
        devolver_uso(db, g.uid, "chat_pdf", g.plan_actual)
        return jsonify({"error": "No se pudo generar la respuesta. Inténtalo de nuevo en unos segundos."}), 500
    return jsonify({"respuesta": respuesta, "documento_id": documento_id})


# Misma ruta que /chat-pdf-mensaje pero en streaming (Server-Sent Events,
# mismo patrón que /tu-tutor/stream): cada fragmento de la respuesta se
# manda al frontend según va llegando de DeepSeek, para el efecto de
# "escritura" en vez de esperar a la respuesta completa -- se percibe
# mucho más rápido aunque el backend tarde lo mismo, y aquí el documento
# entero va en el prompt, así que la generación puede tardar bastante más
# que una pregunta corta. Permisos/límite se comprueban ANTES de abrir el
# stream; registrar_uso ocurre por adelantado (si el cliente corta la
# conexión a mitad, el generador no llega a "fin" y no se devuelve el
# uso -- mismo criterio que /tu-tutor/stream) y se devuelve solo si
# DeepSeek falla del todo con el cliente aún conectado.
@bp.route('/chat-pdf-mensaje/stream', methods=['POST'])
@limiter.limit("20 per minute")
@requiere_plan(db, "premium", global_check=True)
def chat_pdf_mensaje_stream():
    datos = request.get_json(silent=True) or {}
    mensajes, documento_id, error = _preparar_mensajes_chat_pdf(datos)
    if error:
        return error

    uid = g.uid
    plan_actual = g.plan_actual
    # Ver el comentario en /chat-pdf-mensaje: reservar_uso fusiona
    # comprobación y cobro en una única transacción atómica.
    permitido, mensaje_error, _usados, _limite = reservar_uso(db, uid, "chat_pdf", plan_actual)
    if not permitido:
        return jsonify({"error": mensaje_error}), 429

    def generar():
        fragmentos = []
        for fragmento in call_deepseek_api_stream(mensajes, max_tokens=800, temperature=0.4):
            if not fragmento:
                continue
            fragmentos.append(fragmento)
            yield f"data: {json.dumps({'tipo': 'delta', 'texto': fragmento}, ensure_ascii=False)}\n\n"
        texto_respuesta = "".join(fragmentos).strip()
        if not texto_respuesta:
            devolver_uso(db, uid, "chat_pdf", plan_actual)
            yield f"data: {json.dumps({'tipo': 'error'}, ensure_ascii=False)}\n\n"
            return
        yield f"data: {json.dumps({'tipo': 'fin', 'documento_id': documento_id}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generar()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
    )


# ===================================================================
# NUEVAS RUTAS PARA GUARDAR CONTENIDO DESDE PDF
# ===================================================================
@bp.route('/guardar-test-pdf', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def guardar_test_pdf():
    try:
        data = request.get_json()
        test_data = data.get('test_data', {})
        preguntas = test_data.get('preguntas', [])
        respuestas = test_data.get('respuestas', [])
        metadatos_entrada = test_data.get('metadatos', {})
        nombre_archivo = data.get('nombre_archivo', 'documento.pdf')
        documento_id = data.get('documento_id')

        # Se guarda en dos sitios con propósitos distintos:
        # - "test_pdf" (colección tests_pdf): el banco de preguntas ya
        #   generadas de este documento, para "Generar más"/"Ver" desde Mis
        #   Documentos sin volver a llamar a la IA. Ya existía.
        # - "test" (colección tests, mismo tipo que usan test-personalizado/
        #   test-oficial/etc.): el INTENTO en sí -- respuestas del usuario,
        #   aciertos/fallos, nota -- que antes no se guardaba en absoluto
        #   para tests desde PDF, así que nunca aparecían en Mis Tests ni en
        #   las estadísticas. Reutiliza el mismo test_id que el autoguardado
        #   "en_progreso" de la propia página, así el borrador se convierte
        #   en el registro final en vez de quedar duplicado o huérfano.
        guardar_resultado_en_firestore(
            db=db,
            tipo="test_pdf",
            contenido=preguntas,
            usuario_id=g.uid,
            metadatos={
                'nombre_archivo': nombre_archivo,
                'documento_id': documento_id,
                'num_preguntas': len(preguntas),
                'fecha_procesamiento': datetime.utcnow().isoformat()
            }
        )
        guardar_resultado_en_firestore(
            db=db,
            tipo="test",
            contenido=preguntas,
            usuario_id=g.uid,
            metadatos={
                "tipo": "test_pdf",
                "respuestas": respuestas,
                "tiempo": metadatos_entrada.get("tiempo", 0),
            },
            oposicion=obtener_oposicion_solicitada(),
            test_id=data.get('test_id'),
            marcadas_duda=data.get('marcadas_duda', []),
        )
        return jsonify({'mensaje': 'Test desde PDF guardado correctamente'})
    except Exception:
        logger.exception("Error en /guardar-test-pdf")
        return jsonify({'error': 'No se pudo guardar el test.'}), 500


@bp.route('/guardar-resumen-pdf', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def guardar_resumen_pdf():
    try:
        data = request.get_json()
        resumen = data.get('resumen', '')
        nombre_archivo = data.get('nombre_archivo', 'documento.pdf')
        guardar_resultado_en_firestore(
            db=db,
            tipo="resumen_pdf",
            contenido=resumen,
            usuario_id=g.uid,
            metadatos={
                'nombre_archivo': nombre_archivo,
                'documento_id': data.get('documento_id'),
                'longitud': len(resumen),
                'fecha_procesamiento': datetime.utcnow().isoformat()
            }
        )
        return jsonify({'mensaje': 'Resumen desde PDF guardado correctamente'})
    except Exception:
        logger.exception("Error en /guardar-resumen-pdf")
        return jsonify({'error': 'No se pudo guardar el resumen.'}), 500


@bp.route('/guardar-esquema-pdf', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def guardar_esquema_pdf():
    try:
        data = request.get_json()
        esquema = data.get('esquema', '')
        nombre_archivo = data.get('nombre_archivo', 'documento.pdf')
        guardar_resultado_en_firestore(
            db=db,
            tipo="esquema_pdf",
            contenido=esquema,
            usuario_id=g.uid,
            metadatos={
                'nombre_archivo': nombre_archivo,
                'documento_id': data.get('documento_id'),
                'longitud': len(esquema),
                'fecha_procesamiento': datetime.utcnow().isoformat()
            }
        )
        return jsonify({'mensaje': 'Esquema desde PDF guardado correctamente'})
    except Exception:
        logger.exception("Error en /guardar-esquema-pdf")
        return jsonify({'error': 'No se pudo guardar el esquema.'}), 500


@bp.route('/guardar-tarjetas-pdf', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def guardar_tarjetas_pdf():
    try:
        data = request.get_json()
        tarjetas = data.get('tarjetas', [])
        nombre_archivo = data.get('nombre_archivo', 'documento.pdf')
        guardar_resultado_en_firestore(
            db=db,
            tipo="tarjetas_pdf",
            contenido=tarjetas,
            usuario_id=g.uid,
            metadatos={
                'nombre_archivo': nombre_archivo,
                'documento_id': data.get('documento_id'),
                'num_tarjetas': len(tarjetas),
                'fecha_procesamiento': datetime.utcnow().isoformat()
            }
        )
        return jsonify({'mensaje': 'Tarjetas desde PDF guardadas correctamente'})
    except Exception:
        logger.exception("Error en /guardar-tarjetas-pdf")
        return jsonify({'error': 'No se pudieron guardar las tarjetas.'}), 500


# ===================================================================
# "MIS DOCUMENTOS": biblioteca de PDFs subidos, para repasar más tarde el
# contenido de IA ya generado (resumen/esquema/tarjetas/test) sin tener que
# volver a subir el archivo ni volver a generarlo.
# ===================================================================
@bp.route('/mis-documentos', methods=['GET'])
@requiere_plan(db, "premium", global_check=True)
def mis_documentos():
    documentos = listar_documentos(db, g.uid)
    tests_en_progreso = obtener_tests_en_progreso_por_documento(db, g.uid)
    for documento in documentos:
        documento["test_en_progreso"] = tests_en_progreso.get(documento["id"])
    # Cuota mensual de documentos NUEVOS SUBIDOS (ver limites_uso.py,
    # "banco_pdf_mensual") -- se expone aquí para que el frontend pueda
    # avisar de forma discreta ANTES de que se agote (05/08/2026), en vez
    # de que el usuario se entere solo cuando le sale el 429. Sin cifras de
    # coste, solo el conteo de documentos, igual que el resto de límites
    # que sí se enseñan al usuario.
    _permitido, _mensaje, usados, limite = verificar_limite_uso(db, g.uid, g.plan_actual, "banco_pdf_mensual")
    return jsonify({
        "documentos": documentos,
        "carpetas": listar_carpetas(db, g.uid),
        "cuota_documentos_mes": {"usados": usados, "limite": limite},
        # limite_generaciones_contenido (17/08/2026): tope de resumen/esquema
        # POR DOCUMENTO (ver LIMITE_GENERACIONES_POR_DOCUMENTO), distinto del
        # cupo mensual de arriba -- se manda aquí para que el frontend no
        # tenga que hardcodear el número.
        "limite_generaciones_contenido": LIMITE_GENERACIONES_POR_DOCUMENTO,
    })


@bp.route('/subir-documento', methods=['POST'])
@limiter.limit("10 per minute")
@requiere_plan(db, "premium", global_check=True)
def subir_documento():
    """Sube un PDF y lo deja guardado en "Mis documentos" sin generar
    ningún contenido todavía (reutiliza _resolver_texto_documento, que ya
    crea la entrada en la biblioteca la primera vez que se ve un texto).
    Pensado para el botón "Subir documento" de Mis Documentos: el usuario
    decide DESPUÉS si quiere generar preguntas o tarjetas, en vez de tener
    que elegir la herramienta antes de subir el archivo. No genera nada
    con IA, así que no consume ninguna cuota de uso."""
    _texto, documento_id, nombre_archivo, error = _resolver_texto_documento(g.plan_actual)
    if error:
        return error
    return jsonify({"documento_id": documento_id, "nombre_archivo": nombre_archivo})


@bp.route('/carpetas-documentos', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def crear_carpeta_documentos():
    datos = request.get_json(silent=True) or {}
    nombre = crear_carpeta(db, g.uid, datos.get("nombre"))
    if not nombre:
        return jsonify({"error": "El nombre de la carpeta no puede estar vacío."}), 400
    return jsonify({"mensaje": "ok", "nombre": nombre})


@bp.route('/carpetas-documentos', methods=['DELETE'])
@requiere_plan(db, "premium", global_check=True)
def eliminar_carpeta_documentos():
    datos = request.get_json(silent=True) or {}
    eliminar_carpeta(db, g.uid, datos.get("nombre") or "")
    return jsonify({"mensaje": "ok"})


@bp.route('/documento/<documento_id>/carpeta', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def documento_carpeta(documento_id):
    datos = request.get_json(silent=True) or {}
    ok = actualizar_carpeta(db, g.uid, documento_id, datos.get("carpeta", ""))
    if not ok:
        return jsonify({"error": "No se encontró el documento indicado."}), 404
    return jsonify({"mensaje": "Carpeta actualizada"})


@bp.route('/documento/<documento_id>/titulo', methods=['POST'])
@requiere_plan(db, "premium", global_check=True)
def documento_titulo(documento_id):
    datos = request.get_json(silent=True) or {}
    titulo = (datos.get("titulo") or "").strip()
    if not titulo:
        return jsonify({"error": "El nombre no puede estar vacío."}), 400
    ok = actualizar_titulo(db, g.uid, documento_id, titulo)
    if not ok:
        return jsonify({"error": "No se encontró el documento indicado."}), 404
    return jsonify({"mensaje": "Nombre actualizado", "titulo": titulo[:120]})


@bp.route('/documento/<documento_id>', methods=['DELETE'])
@requiere_plan(db, "premium", global_check=True)
def eliminar_documento_route(documento_id):
    ok = eliminar_documento(db, g.uid, documento_id)
    if not ok:
        return jsonify({"error": "No se encontró el documento indicado."}), 404
    return jsonify({"mensaje": "Documento eliminado"})


@bp.route('/documento/<documento_id>/resumen', methods=['GET'])
@requiere_plan(db, "premium", global_check=True)
def documento_resumen(documento_id):
    datos = _ultimo_por_documento("resumenes_pdf", documento_id, g.uid)
    if not datos:
        return jsonify({"error": "Este documento todavía no tiene un resumen generado."}), 404
    return jsonify({"resumen": datos.get("resumen"), "nombre_archivo": datos.get("nombre_archivo"), "fecha": datos.get("fecha")})


@bp.route('/documento/<documento_id>/esquema', methods=['GET'])
@requiere_plan(db, "premium", global_check=True)
def documento_esquema(documento_id):
    datos = _ultimo_por_documento("esquemas_pdf", documento_id, g.uid)
    if not datos:
        return jsonify({"error": "Este documento todavía no tiene un esquema generado."}), 404
    return jsonify({"esquema": datos.get("esquema"), "nombre_archivo": datos.get("nombre_archivo"), "fecha": datos.get("fecha")})


@bp.route('/documento/<documento_id>/test', methods=['GET'])
@requiere_plan(db, "premium", global_check=True)
def documento_test(documento_id):
    datos = _ultimo_por_documento("tests_pdf", documento_id, g.uid)
    if not datos:
        return jsonify({"error": "Este documento todavía no tiene un test generado."}), 404
    return jsonify({"test": datos.get("preguntas", []), "nombre_archivo": datos.get("nombre_archivo"), "fecha": datos.get("fecha")})


@bp.route('/documento/<documento_id>/tarjetas', methods=['GET'])
@requiere_plan(db, "premium", global_check=True)
def documento_tarjetas(documento_id):
    docs = (
        db.collection("usuarios").document(g.uid).collection("tarjetas_pdf")
        .where("documento_id", "==", documento_id)
        .stream()
    )
    todas = []
    for d in docs:
        todas.extend((d.to_dict() or {}).get("tarjetas", []))
    if not todas:
        return jsonify({"error": "Este documento todavía no tiene tarjetas generadas."}), 404
    modo = request.args.get("modo", "todas")
    if modo == "aleatorias":
        try:
            cantidad = int(request.args.get("cantidad", 10))
        except (TypeError, ValueError):
            cantidad = 10
        cantidad = max(1, min(cantidad, len(todas)))
        todas = random.sample(todas, cantidad)
    return jsonify({"tarjetas": todas})
