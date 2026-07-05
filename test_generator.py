import random
import re
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from deepseek_utils import call_deepseek_api
from utils import obtener_subbloques_individuales, contar_tokens, repartir_cupos_por_tema
from validador_preguntas import validar_pregunta
from oposiciones import OPOSICIONES, OPOSICION_POR_DEFECTO


def generar_preguntas_ia_en_lotes(construir_prompt, num_preguntas, tamano_lote=15, temperature=0.4):
    """Genera 'num_preguntas' preguntas pidiéndolas a DeepSeek en varios lotes
    en paralelo (ThreadPoolExecutor) en vez de una única llamada gigante.

    Antes, /generar-test-inteligente y /generar-test-desde-pdf pedían todo el
    test de golpe con max_tokens=min(4000, 300*num_preguntas): a partir de
    ~13-14 preguntas ese tope de 4000 tokens ya se queda corto para el JSON
    completo (pregunta+opciones+explicación ronda 400-600 tokens cada una), y
    la respuesta se corta a medio JSON. Pedir lotes de como mucho
    'tamano_lote' preguntas mantiene cada llamada individual muy por debajo
    del límite, sea cual sea el total pedido.

    construir_prompt(n) debe devolver el prompt completo pidiendo EXACTAMENTE
    n preguntas, en el mismo formato de array JSON que ya usan esas dos rutas.

    Devuelve (preguntas, errores): preguntas ya deduplicadas por texto de
    pregunta normalizado (pedir el mismo tema en varios lotes en paralelo
    puede repetir alguna), errores es una lista de motivos de fallo por lote
    (vacía si todo fue bien) para poder avisar si faltan preguntas respecto a
    las pedidas.
    """
    lotes = []
    restante = num_preguntas
    while restante > 0:
        n = min(tamano_lote, restante)
        lotes.append(n)
        restante -= n

    def _pedir_lote(n):
        prompt = construir_prompt(n)
        generado = call_deepseek_api(
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=min(4000, 300 * n)
        )
        if not generado:
            return [], f"Sin respuesta de DeepSeek para un lote de {n} preguntas"
        inicio = generado.find("[")
        fin = generado.rfind("]") + 1
        if inicio == -1 or fin <= inicio:
            return [], "No se encontró un array JSON en la respuesta de un lote"
        try:
            return json.loads(generado[inicio:fin]), None
        except json.JSONDecodeError as je:
            return [], f"JSON inválido en un lote: {je}"

    preguntas = []
    errores = []
    with ThreadPoolExecutor(max_workers=min(5, len(lotes))) as executor:
        futuros = [executor.submit(_pedir_lote, n) for n in lotes]
        for futuro in as_completed(futuros):
            lote_preguntas, error = futuro.result()
            if error:
                errores.append(error)
            else:
                preguntas.extend(lote_preguntas)

    vistas = set()
    preguntas_unicas = []
    for p in preguntas:
        clave = re.sub(r"\s+", " ", str(p.get("pregunta", "")).strip().lower())
        if clave and clave not in vistas:
            vistas.add(clave)
            preguntas_unicas.append(p)

    return preguntas_unicas, errores


def _instrucciones(oposicion):
    nombre = OPOSICIONES.get(oposicion, OPOSICIONES[OPOSICION_POR_DEFECTO])["nombre"]
    return (
        f"Actúas como un generador profesional de preguntas tipo test, especializado en la oposición "
        f"al {nombre}. "
        "Tu objetivo es crear preguntas similares a las de exámenes oficiales de oposición, a partir del contenido proporcionado. "
        "Sigue estrictamente estas normas:\n\n"
        "1. Las preguntas deben ser claras, completas, bien formuladas y redactadas en un estilo técnico-formal.\n"
        "2. NO uses expresiones como 'según el texto', 'de acuerdo con lo anterior', 'en el contenido proporcionado'.\n"
        "3. Sustituye todas las siglas por su forma completa.\n"
        "4. Si el contenido no es suficiente, omítelo. No inventes datos.\n"
        "5. Las opciones incorrectas deben ser creíbles.\n"
        "6. Prioriza variedad temática.\n"
        "7. Redacta en un español técnico y preciso.\n"
        "8. La explicación debe ser breve (2-3 frases como máximo).\n\n"
        "Formato JSON:\n"
        "{\"pregunta\": \"...\", \"opciones\": {\"A\": \"...\", \"B\": \"...\", \"C\": \"...\", \"D\": \"...\"}, \"respuesta_correcta\": \"...\", \"explicacion\": \"...\"}\n"
        "Devuelve ÚNICAMENTE ese JSON: sin bloques de código, sin backticks (```), sin ningún texto antes o después."
    )


def _tema_id_de_etiqueta(etiqueta):
    """Extrae 'bloque_XX-tema_YY' de una etiqueta 'bloque_XX-tema_YY-sub_ZZZ'.
    Se centraliza aquí (en vez de repetir el split en cada sitio que lo
    necesita) para que el agrupado de subbloques por tema y el tema_id que
    se asigna a cada pregunta generada nunca puedan divergir."""
    partes = etiqueta.split("-")
    if len(partes) >= 2:
        return "-".join(partes[:2])
    return etiqueta


def _generar_pregunta_desde_subbloque(sub, oposicion=OPOSICION_POR_DEFECTO):
    etiqueta = sub.get("etiqueta", "")
    contenido = sub.get("texto", "")
    if contar_tokens(contenido) > 3000:
        contenido = contenido[:4000]

    prompt = f"{_instrucciones(oposicion)}\n\nContenido:\n{contenido}"

    messages = [{"role": "user", "content": prompt}]

    try:
        generado = call_deepseek_api(messages, max_tokens=1100, temperature=0.4)
        if not generado:
            return {"etiqueta": etiqueta, "error": "Sin respuesta de DeepSeek"}

        # DeepSeek a veces envuelve el JSON en un bloque de código markdown
        # (```json ... ```) pese a que se le pide que no lo haga; en vez de
        # descartar la pregunta por eso, se extrae el objeto {...} tal y como
        # ya se hace en las demás rutas de generación (app.py).
        inicio = generado.find("{")
        fin = generado.rfind("}") + 1
        if inicio == -1 or fin <= inicio:
            return {"etiqueta": etiqueta, "error": "No se encontró un objeto JSON en la respuesta"}
        generado_json = json.loads(generado[inicio:fin])

        if validar_pregunta(generado_json):
            # Se deriva de la etiqueta para que cada pregunta sepa de qué
            # tema salió realmente, en vez de que el frontend tenga que
            # adivinarlo/asignarlo al azar.
            generado_json["tema_id"] = _tema_id_de_etiqueta(etiqueta)
            return {"etiqueta": etiqueta, "pregunta": generado_json}
        return {"etiqueta": etiqueta, "error": "No pasó validación"}

    except json.JSONDecodeError as je:
        return {"etiqueta": etiqueta, "error": f"JSON inválido: {je}"}
    except Exception as e:
        return {"etiqueta": etiqueta, "error": f"Error DeepSeek: {e}"}


def _generar_preguntas_por_lotes(pendientes_por_tema, cupos, oposicion):
    """Genera preguntas para varios temas a la vez respetando la cuota
    (cupo) de cada uno, con un único ThreadPoolExecutor compartido por ronda
    -- para no perder el paralelismo entre temas que tenía la versión
    anterior con una única bolsa. En cada vuelta se pide "el doble" de
    subbloques por tema (misma heurística de siempre para compensar fallos
    de validación) y se repite hasta que cada tema alcanza su cupo o se le
    agotan los subbloques.

    pendientes_por_tema: dict tema_id -> lista de subbloques sin probar
        (mutable, ya barajada; se van consumiendo por el principio).
    cupos: dict tema_id -> nº de preguntas deseadas de ese tema.

    Devuelve (conseguidos, usados, errores):
      - conseguidos: dict tema_id -> lista de preguntas conseguidas (<= cupo)
      - usados: lista de etiquetas de subbloques usadas
      - errores: lista de {"etiqueta":..., "motivo":...}
    """
    conseguidos = {tid: [] for tid in cupos}
    usados = []
    errores = []

    while True:
        lote_total = []  # [(tema_id, subbloque), ...]
        for tid, cupo in cupos.items():
            faltan = cupo - len(conseguidos[tid])
            if faltan <= 0:
                continue
            pendientes = pendientes_por_tema[tid]
            if not pendientes:
                continue
            tamano = min(len(pendientes), max(faltan * 2, faltan))
            for _ in range(tamano):
                lote_total.append((tid, pendientes.pop(0)))

        if not lote_total:
            break  # nadie tiene ya cupo pendiente con subbloques que probar

        with ThreadPoolExecutor(max_workers=min(10, len(lote_total))) as executor:
            futuros = {
                executor.submit(_generar_pregunta_desde_subbloque, sub, oposicion): tid
                for tid, sub in lote_total
            }
            for futuro in as_completed(futuros):
                tid = futuros[futuro]
                resultado = futuro.result()
                if "pregunta" in resultado:
                    if len(conseguidos[tid]) < cupos[tid]:
                        conseguidos[tid].append(resultado["pregunta"])
                        usados.append(resultado["etiqueta"])
                else:
                    errores.append({"etiqueta": resultado["etiqueta"], "motivo": resultado["error"]})

    return conseguidos, usados, errores


def generar_test_avanzado(temas, db, num_preguntas=5, coleccion="Temario AGE", oposicion=OPOSICION_POR_DEFECTO):
    print("🔍 función generar_test_avanzado() llamada")
    print(f"🧪 Temas recibidos: {temas}")

    try:
        # Deduplicar preservando orden: evita pedir dos veces los subbloques
        # de un tema repetido en la lista y contarlo dos veces al repartir.
        temas_unicos = list(dict.fromkeys(temas))

        subbloques = obtener_subbloques_individuales(db, temas_unicos, coleccion=coleccion)
        if not subbloques:
            print("⚠️ No se encontraron subbloques.")
            return {"test": [], "subbloques_utilizados": [], "errores": [],
                    "advertencia": "No se encontraron subbloques válidos."}

        print(f"📚 Subbloques encontrados: {len(subbloques)}")

        # Agrupar por tema (a partir de la etiqueta) en vez de barajar la
        # bolsa conjunta: cada tema elegido reparte y consume su propio
        # contenido de forma independiente, así uno con muchos más
        # subbloques cargados que otro no se lleva casi todas las preguntas.
        pendientes_por_tema = {}
        for sub in subbloques:
            tid = _tema_id_de_etiqueta(sub["etiqueta"])
            pendientes_por_tema.setdefault(tid, []).append(sub)
        for lista in pendientes_por_tema.values():
            random.shuffle(lista)

        preguntas_generadas = []
        usados = []
        errores = []

        # Reparto equitativo con "mejor esfuerzo": se reparte la cuota entre
        # todos los temas con contenido; si en una ronda algún tema se queda
        # corto (agotó sus subbloques), el hueco se reparte de nuevo --
        # equitativamente y sin sesgo posicional -- entre los temas que
        # todavía tengan subbloques sin probar, en sucesivas rondas, hasta
        # completar el total pedido o hasta que ya nadie tenga contenido.
        candidatos = list(pendientes_por_tema.keys())
        restante = num_preguntas
        while restante > 0 and candidatos:
            cupos = repartir_cupos_por_tema(candidatos, restante)
            print(f"🧮 Cupos de esta ronda: {cupos}")
            conseguidos, usados_ronda, errores_ronda = _generar_preguntas_por_lotes(
                pendientes_por_tema, cupos, oposicion
            )
            usados.extend(usados_ronda)
            errores.extend(errores_ronda)

            avance = 0
            for tid in candidatos:
                preguntas_generadas.extend(conseguidos[tid])
                avance += len(conseguidos[tid])
            restante -= avance

            if avance == 0:
                break  # ningún tema pudo aportar más pese a tener pendientes

            # Solo siguen siendo candidatos los temas a los que aún les
            # quede contenido sin probar, para la siguiente ronda de reparto.
            candidatos = [tid for tid in candidatos if pendientes_por_tema[tid]]

        resultado_final = {
            "test": preguntas_generadas,
            "subbloques_utilizados": usados,
            "errores": errores
        }

        if len(preguntas_generadas) < num_preguntas:
            resultado_final["advertencia"] = f"Solo se generaron {len(preguntas_generadas)} de {num_preguntas} preguntas (no había suficiente contenido válido en los temas elegidos)."

        print(f"🎯 Preguntas generadas: {len(preguntas_generadas)}")
        return resultado_final

    except Exception as error:
        print(f"🔥 Error inesperado en generar_test_avanzado: {error}")
        return {"test": [], "error": str(error)}
