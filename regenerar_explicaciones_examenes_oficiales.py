"""Regenera el campo `explicacion` de las preguntas de examenes oficiales
(AGE, AUXILIAR, GACE) que no repasan las 4 opciones -- solo justifican la
correcta, igual que hace ya Test Personalizado (generador_preguntas_
verificado.py, regla 4 de _prompt_generacion_normativo/_descriptivo):
"A) es correcta/incorrecta porque... B) ... C) ... D) ...".

Motivo: al cargar los examenes oficiales (cargar_examen_oficial_age.py y
sus gemelos de auxiliar/gace), la explicacion de cada pregunta se toma de
un fichero *_explicaciones.json curado a mano o, si falta, se genera con
`generar_explicacion()` (definida en cada uno de esos loaders) -- un
prompt mucho mas simple que solo pide justificar la opcion correcta,
nunca las otras 3. El resultado es una explicacion pobre frente a las de
Test Personalizado, que si desglosan las 4.

Por seguridad va en dos pasos, como el resto de scripts de datos de este
proyecto (ver reasignar_temas_examenes.py):
    python regenerar_explicaciones_examenes_oficiales.py              # solo AUDITA
    python regenerar_explicaciones_examenes_oficiales.py --aplicar    # regenera de verdad

Es idempotente: el criterio de "pendiente" (_tiene_formato_bueno) se
recalcula cada vez sobre el estado actual de Firestore, asi que volver a
lanzarlo tras una interrupcion o algun fallo puntual solo reintenta lo
que de verdad siga sin arreglar.

Ademas incluye un modo --verificar (tambien de dos pasos), pensado para
revisar la CALIDAD de las explicaciones ya regeneradas: a diferencia de
Test Personalizado (generador_preguntas_verificado.py), aqui no hay texto
legal de origen contra el que comparar, asi que la explicacion se genera
solo con el conocimiento general del modelo -- en matices finos (p. ej.
una clasificacion legal exacta) puede sonar segura y aun asi ser
imprecisa. --verificar hace una segunda pasada de autocritica (una IA
revisa cada explicacion ya escrita buscando afirmaciones demasiado
tajantes o contradicciones) y, con --aplicar, regenera solo las que
fallen esa revision, esta vez con el problema detectado como pista:
    python regenerar_explicaciones_examenes_oficiales.py --verificar
    python regenerar_explicaciones_examenes_oficiales.py --verificar --aplicar

Requiere FIREBASE_CREDENTIALS_JSON (o FIREBASE_KEY_PATH) y
DEEPSEEK_API_KEY, igual que el resto de scripts de datos.
"""
import os
import re
import sys
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

from coste_ia import AcumuladorTokens, coste_estimado
from deepseek_utils import call_deepseek_api
from oposiciones import OPOSICIONES, coleccion_examenes_oficiales

load_dotenv()

MAX_WORKERS = 8
# Preguntas de muestra a generar en modo auditoria (llamada real, coste
# minimo) para poder juzgar la calidad antes de decidir aplicar nada.
MUESTRAS_AUDITORIA_POR_OPOSICION = 1

# Una letra seguida de ")" -- p. ej. "A)" -- en cualquier punto del texto.
# Una explicacion se considera "ya buena" si repasa las 4 opciones.
_PATRON_OPCION = {letra: re.compile(rf"{letra}\)") for letra in "ABCD"}


def _init_firebase():
    if firebase_admin._apps:
        return
    cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if cred_json:
        cred = credentials.Certificate(json.loads(cred_json))
    else:
        cred = credentials.Certificate(os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json"))
    firebase_admin.initialize_app(cred)


def _tiene_formato_bueno(explicacion):
    """True si la explicacion ya repasa las 4 opciones (A)/B)/C)/D)) --
    tanto una explicacion vacia como la vieja ("solo la correcta") caen en
    False, que es justo lo que hay que regenerar."""
    explicacion = explicacion or ""
    return all(patron.search(explicacion) for patron in _PATRON_OPCION.values())


def _prompt_explicacion(pregunta, opciones, respuesta_correcta, problemas_previos=None):
    opciones_texto = "\n".join(f"{letra}) {texto}" for letra, texto in sorted(opciones.items()))
    aviso_revision = ""
    if problemas_previos:
        lista = "\n".join(f"- {p}" for p in problemas_previos)
        aviso_revision = (
            "\n\nUn revisor jurídico ya detectó estos problemas en un intento anterior de "
            f"explicar esta misma pregunta -- corrígelos explícitamente esta vez:\n{lista}\n"
        )
    return (
        "Eres un experto en oposiciones y en legislación española. A continuación tienes una "
        "pregunta REAL de un examen oficial de oposición, con su respuesta correcta ya conocida "
        "y verificada -- no la cuestiones, dala por cierta.\n\n"
        "Escribe la explicación repasando TODAS las opciones, una por línea y en orden, con este "
        "formato exacto: \"A) es correcta/incorrecta porque... B) es correcta/incorrecta "
        "porque... C) ... D) ...\". Cada línea debe ser UNA sola frase breve (máximo 25-30 "
        "palabras) que vaya directa al motivo -- nunca repitas el enunciado de la pregunta ni el "
        "texto de las opciones, ni añadas relleno.\n\n"
        "Si el enunciado o alguna opción ya menciona un artículo o una norma concreta, cítalo en "
        "la línea de la respuesta correcta usando la terminología oficial (no sinónimos). Si NO "
        "se menciona ningún artículo o norma, no inventes ninguna referencia legal -- limítate a "
        "explicar el motivo con tus propios conocimientos de la materia. No afirmes una "
        "clasificación legal exacta (p. ej. si algo pertenece a una categoría concreta de la "
        "norma) salvo que estés seguro de que es así -- en ese caso, formúlalo con matiz en vez "
        "de darlo por hecho sin más.\n"
        f"{aviso_revision}\n"
        f"Pregunta: {pregunta}\n\n{opciones_texto}\n\n"
        f"Respuesta correcta: {respuesta_correcta}) {opciones.get(respuesta_correcta, '')}\n\n"
        "Devuelve SOLO las 4 líneas de la explicación, sin encabezados, comillas ni texto "
        "adicional."
    )


def _generar_explicacion_mejorada(pregunta, opciones, respuesta_correcta, contexto,
                                   acumulador=None, problemas_previos=None):
    """Genera la explicacion nueva y valida que sigue el formato pedido --
    un reintento si la primera respuesta no lo cumple. Devuelve None (sin
    reintentar mas) si sigue sin cumplirlo -- nunca se devuelve una
    explicacion que no pasa su propia validacion."""
    prompt = _prompt_explicacion(pregunta, opciones, respuesta_correcta, problemas_previos)
    for _intento in range(2):
        respuesta = call_deepseek_api(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=350,
            on_usage=acumulador.add if acumulador else None,
            contexto=contexto,
        )
        respuesta = (respuesta or "").strip()
        if _tiene_formato_bueno(respuesta):
            return respuesta
    return None


def _prompt_verificacion(pregunta, opciones, respuesta_correcta, explicacion):
    """A diferencia de la verificación grounded de Test Personalizado
    (_prompt_verificacion_normativo/_descriptivo en generador_preguntas_
    verificado.py, que compara contra el texto legal real), aquí no hay
    ningún texto de origen contra el que contrastar -- es una segunda
    pasada de autocrítica del propio modelo. Por eso el techo es más
    bajo: pilla contradicciones y afirmaciones demasiado tajantes, pero no
    puede detectar un error que el modelo tampoco sabría corregir."""
    opciones_texto = "\n".join(f"{letra}) {texto}" for letra, texto in sorted(opciones.items()))
    return (
        "Eres un revisor jurídico escéptico, especializado en oposiciones españolas. Te llega una "
        "pregunta REAL de un examen oficial (la respuesta correcta ya está verificada, no la "
        "cuestiones) y una explicación YA ESCRITA por otro proceso, que debes revisar con ojo "
        "crítico -- no la des por buena solo porque suena segura.\n\n"
        "Marca la explicación como inválida si detectas CUALQUIERA de estos problemas:\n"
        "1. Alguna línea afirma como hecho una clasificación legal exacta (p. ej. que algo "
        "pertenece a una categoría concreta de una norma) que podría no ser precisa o que tiene "
        "matices que la explicación no menciona.\n"
        "2. Alguna línea se limita a repetir la premisa de la propia pregunta en vez de "
        "justificar de forma independiente por qué esa opción es correcta o incorrecta.\n"
        "3. Hay una contradicción entre dos líneas, o entre la línea de la respuesta correcta y "
        "cuál es realmente la letra marcada como correcta.\n"
        "4. Se cita un artículo o una norma que no aparece ya en el enunciado o las opciones "
        "(posible invención).\n"
        "5. Alguna línea no tiene sentido, está incompleta, o no sigue el formato \"A) es "
        "correcta/incorrecta porque...\".\n\n"
        "No marques inválida una explicación solo por ser concisa o por no citar ningún artículo "
        "cuando la pregunta tampoco lo hace -- eso es correcto. Solo marca problemas concretos y "
        "señalables, no dudas genéricas.\n\n"
        "Devuelve ÚNICAMENTE un JSON con esta forma exacta, sin texto adicional:\n"
        '{"valido": true, "problemas": []}\n'
        "Si encuentras algún problema, \"valido\" debe ser false y \"problemas\" debe listar cada "
        "motivo -- cada elemento de \"problemas\" debe ser UNA sola frase breve (máximo 20-25 "
        "palabras).\n\n"
        f"Pregunta: {pregunta}\n\n{opciones_texto}\n\n"
        f"Respuesta correcta: {respuesta_correcta}) {opciones.get(respuesta_correcta, '')}\n\n"
        f"Explicación a revisar:\n{explicacion}"
    )


def _verificar_explicacion(pregunta, opciones, respuesta_correcta, explicacion, contexto, acumulador=None):
    """Devuelve (estado, problemas): estado es "valida", "invalida" o
    "sin_verificar" (la IA no devolvió un JSON parseable -- fallo raro/
    transitorio, se deja constancia en vez de darla por buena en
    silencio)."""
    prompt = _prompt_verificacion(pregunta, opciones, respuesta_correcta, explicacion)
    respuesta = call_deepseek_api(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=300,
        response_format_json=True,
        on_usage=acumulador.add if acumulador else None,
        contexto=contexto,
    )
    try:
        datos = json.loads(respuesta or "")
    except (json.JSONDecodeError, TypeError):
        return "sin_verificar", []
    if datos.get("valido", True):
        return "valida", []
    return "invalida", datos.get("problemas", [])


def _recolectar_ya_generadas(db):
    """Como _recolectar_pendientes pero con la condición invertida: las
    preguntas activas cuya explicación YA tiene el formato bueno -- el
    universo que --verificar revisa."""
    listas = {oposicion: [] for oposicion in OPOSICIONES}
    for oposicion in OPOSICIONES:
        coleccion = coleccion_examenes_oficiales(oposicion)
        for doc in db.collection(coleccion).stream():
            d = doc.to_dict() or {}
            if d.get("tipo") != "pregunta":
                continue
            if d.get("activa", True) is False:
                continue
            explicacion = (d.get("explicacion") or "").strip()
            if not _tiene_formato_bueno(explicacion):
                continue
            opciones = d.get("opciones") or {}
            respuesta_correcta = d.get("respuesta_correcta")
            if not opciones or respuesta_correcta not in opciones:
                continue
            listas[oposicion].append({
                "doc_id": doc.id,
                "pregunta": d.get("pregunta", ""),
                "opciones": opciones,
                "respuesta_correcta": respuesta_correcta,
                "explicacion": explicacion,
            })
    return listas


def _ejecutar_verificacion(db, aplicar):
    ya_generadas = _recolectar_ya_generadas(db)
    tareas = [(oposicion, item) for oposicion in OPOSICIONES for item in ya_generadas[oposicion]]
    total = len(tareas)
    print("=" * 70)
    print(f"Verificando {total} explicaciones ya generadas con {MAX_WORKERS} hilos en paralelo "
          f"(revisión de autocrítica, sin texto legal de origen -- pilla parte de los casos, no "
          f"todos)...")

    acumulador = AcumuladorTokens()
    resultados = {}  # doc_id -> (oposicion, item, estado, problemas)

    def _procesar(oposicion, item):
        estado, problemas = _verificar_explicacion(
            item["pregunta"], item["opciones"], item["respuesta_correcta"], item["explicacion"],
            contexto=f"verificar-explicacion oposicion={oposicion} doc={item['doc_id']}",
            acumulador=acumulador,
        )
        return (oposicion, item, estado, problemas)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futuros = [executor.submit(_procesar, oposicion, item) for oposicion, item in tareas]
        hechas = 0
        for futuro in as_completed(futuros):
            oposicion, item, estado, problemas = futuro.result()
            resultados[item["doc_id"]] = (oposicion, item, estado, problemas)
            hechas += 1
            if hechas % 100 == 0 or hechas == total:
                print(f"  {hechas}/{total} revisadas...")

    invalidas = [r for r in resultados.values() if r[2] == "invalida"]
    validas = [r for r in resultados.values() if r[2] == "valida"]
    sin_verificar = [r for r in resultados.values() if r[2] == "sin_verificar"]

    print(f"\nVálidas: {len(validas)}  ·  Inválidas: {len(invalidas)}  ·  "
          f"Sin verificar (fallo al parsear): {len(sin_verificar)}")
    print(f"Coste de la verificación: {coste_estimado(acumulador.tin, acumulador.tout):.4f} €")

    if invalidas:
        print("\n" + "=" * 70)
        print(f"Ejemplos de explicaciones marcadas inválidas (hasta 10 de {len(invalidas)}):")
        for oposicion, item, _estado, problemas in invalidas[:10]:
            print(f"\n--- [{oposicion}] {item['doc_id']} ---")
            print(f"Pregunta: {item['pregunta']}")
            print(f"\nExplicación actual:\n{item['explicacion']}")
            print("\nProblemas detectados:")
            for p in problemas:
                print(f"   - {p}")

    if not aplicar:
        print("\n" + "=" * 70)
        print("(modo AUDITORÍA: no se ha escrito nada en Firestore. "
              "Lanza con --verificar --aplicar para regenerar las inválidas.)")
        return

    if not invalidas:
        print("\nNada que regenerar.")
        return

    print("\n" + "=" * 70)
    print(f"Regenerando {len(invalidas)} explicaciones inválidas (con el problema detectado como "
          f"pista)...")
    acumulador_regen = AcumuladorTokens()
    actualizadas = 0
    siguen_fallando = []

    def _regenerar(oposicion, item, problemas):
        nueva = _generar_explicacion_mejorada(
            item["pregunta"], item["opciones"], item["respuesta_correcta"],
            contexto=f"regenerar-tras-verificacion oposicion={oposicion} doc={item['doc_id']}",
            acumulador=acumulador_regen,
            problemas_previos=problemas,
        )
        if nueva is None:
            return (oposicion, item["doc_id"], False)
        db.collection(coleccion_examenes_oficiales(oposicion)).document(item["doc_id"]).update(
            {"explicacion": nueva}
        )
        return (oposicion, item["doc_id"], True)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futuros = [
            executor.submit(_regenerar, oposicion, item, problemas)
            for oposicion, item, _estado, problemas in invalidas
        ]
        for futuro in as_completed(futuros):
            oposicion, doc_id, ok = futuro.result()
            if ok:
                actualizadas += 1
            else:
                siguen_fallando.append((oposicion, doc_id))

    print(f"\nRegeneradas {actualizadas} de {len(invalidas)}.")
    if siguen_fallando:
        print(f"{len(siguen_fallando)} siguieron sin poder regenerarse:")
        for oposicion, doc_id in siguen_fallando[:30]:
            print(f"   - [{oposicion}] {doc_id}")

    print(f"\nCoste real de la regeneración: "
          f"{coste_estimado(acumulador_regen.tin, acumulador_regen.tout):.4f} €")
    print(f"Coste total de esta ejecución (verificación + regeneración): "
          f"{coste_estimado(acumulador.tin + acumulador_regen.tin, acumulador.tout + acumulador_regen.tout):.4f} €")


def _recolectar_pendientes(db):
    """Devuelve {oposicion: [ {doc_id, pregunta, opciones, respuesta_correcta,
    explicacion_actual}, ... ]} -- solo las preguntas activas cuya
    explicacion actual no repasa las 4 opciones y cuyos datos son lo
    bastante completos como para generar algo fiable."""
    pendientes = {oposicion: [] for oposicion in OPOSICIONES}
    totales = {oposicion: 0 for oposicion in OPOSICIONES}
    for oposicion in OPOSICIONES:
        coleccion = coleccion_examenes_oficiales(oposicion)
        for doc in db.collection(coleccion).stream():
            d = doc.to_dict() or {}
            if d.get("tipo") != "pregunta":
                continue
            if d.get("activa", True) is False:
                continue
            totales[oposicion] += 1
            explicacion_actual = (d.get("explicacion") or "").strip()
            if _tiene_formato_bueno(explicacion_actual):
                continue
            opciones = d.get("opciones") or {}
            respuesta_correcta = d.get("respuesta_correcta")
            if not opciones or respuesta_correcta not in opciones:
                continue
            pendientes[oposicion].append({
                "doc_id": doc.id,
                "pregunta": d.get("pregunta", ""),
                "opciones": opciones,
                "respuesta_correcta": respuesta_correcta,
                "explicacion_actual": explicacion_actual,
            })
    return pendientes, totales


def _auditar(db):
    pendientes, totales = _recolectar_pendientes(db)
    print("=" * 70)
    total_pendientes = 0
    for oposicion in OPOSICIONES:
        n_pend = len(pendientes[oposicion])
        total_pendientes += n_pend
        print(f"[{oposicion}] preguntas activas: {totales[oposicion]}  ·  "
              f"necesitan regenerar explicación: {n_pend}")
    print(f"\nTOTAL a regenerar: {total_pendientes}")

    if total_pendientes:
        print("\n" + "=" * 70)
        print(f"MUESTRA de antes/después (llamada real a la IA, coste mínimo -- "
              f"no se escribe nada en Firestore):")
        acumulador = AcumuladorTokens()
        for oposicion in OPOSICIONES:
            muestra = pendientes[oposicion][:MUESTRAS_AUDITORIA_POR_OPOSICION]
            for item in muestra:
                nueva = _generar_explicacion_mejorada(
                    item["pregunta"], item["opciones"], item["respuesta_correcta"],
                    contexto=f"auditoria-explicacion oposicion={oposicion} doc={item['doc_id']}",
                    acumulador=acumulador,
                )
                print(f"\n--- [{oposicion}] {item['doc_id']} ---")
                print(f"Pregunta: {item['pregunta']}")
                for letra, texto in sorted(item["opciones"].items()):
                    marca = " <- correcta" if letra == item["respuesta_correcta"] else ""
                    print(f"   {letra}) {texto}{marca}")
                print(f"\nANTES:\n{item['explicacion_actual'] or '(vacía)'}")
                print(f"\nDESPUÉS:\n{nueva or '(la IA no siguió el formato pedido ni al reintentar)'}")
        print(f"\nCoste de la muestra: {coste_estimado(acumulador.tin, acumulador.tout):.4f} €")
        # Estimación grosera del coste total a partir del coste medio real
        # de la muestra generada -- solo orientativa, el coste final tras
        # --aplicar se imprime con el gasto real acumulado.
        if acumulador.llamadas:
            coste_medio = coste_estimado(acumulador.tin, acumulador.tout) / acumulador.llamadas
            print(f"Coste estimado de regenerar las {total_pendientes} pendientes: "
                  f"~{coste_medio * total_pendientes:.2f} €")

    print("\n" + "=" * 70)
    print("(modo AUDITORÍA: no se ha escrito nada en Firestore. "
          "Lanza con --aplicar para regenerar de verdad.)")
    return pendientes


def _aplicar(db, pendientes):
    tareas = [
        (oposicion, item)
        for oposicion in OPOSICIONES
        for item in pendientes[oposicion]
    ]
    total = len(tareas)
    if not total:
        print("Nada pendiente, no hay nada que aplicar.")
        return

    print(f"Regenerando {total} explicaciones con {MAX_WORKERS} hilos en paralelo...")
    acumulador = AcumuladorTokens()
    actualizadas = 0
    fallidas = []

    def _procesar(oposicion, item):
        nueva = _generar_explicacion_mejorada(
            item["pregunta"], item["opciones"], item["respuesta_correcta"],
            contexto=f"regenerar-explicacion oposicion={oposicion} doc={item['doc_id']}",
            acumulador=acumulador,
        )
        if nueva is None:
            return (oposicion, item["doc_id"], False)
        db.collection(coleccion_examenes_oficiales(oposicion)).document(item["doc_id"]).update(
            {"explicacion": nueva}
        )
        return (oposicion, item["doc_id"], True)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futuros = [executor.submit(_procesar, oposicion, item) for oposicion, item in tareas]
        hechas = 0
        for futuro in as_completed(futuros):
            oposicion, doc_id, ok = futuro.result()
            hechas += 1
            if ok:
                actualizadas += 1
            else:
                fallidas.append((oposicion, doc_id))
            if hechas % 100 == 0 or hechas == total:
                print(f"  {hechas}/{total} procesadas ({actualizadas} actualizadas, "
                      f"{len(fallidas)} fallidas)...")

    print(f"\nActualizadas {actualizadas} de {total}.")
    if fallidas:
        print(f"{len(fallidas)} preguntas fallidas (la IA no siguió el formato ni al "
              f"reintentar -- se dejaron sin tocar, vuelve a lanzar el script para "
              f"reintentarlas):")
        for oposicion, doc_id in fallidas[:30]:
            print(f"   - [{oposicion}] {doc_id}")
        if len(fallidas) > 30:
            print(f"   ... y {len(fallidas) - 30} más")

    print(f"\nCoste real de esta ejecución: {coste_estimado(acumulador.tin, acumulador.tout):.4f} €"
          f"  ({acumulador.llamadas} llamadas, {acumulador.tin} tokens entrada, "
          f"{acumulador.tout} tokens salida)")


def main(aplicar, verificar):
    _init_firebase()
    db = firestore.client()

    if verificar:
        _ejecutar_verificacion(db, aplicar)
        return

    pendientes = _auditar(db)
    if not aplicar:
        return

    total_pendientes = sum(len(v) for v in pendientes.values())
    if not total_pendientes:
        return

    print("\n" + "=" * 70)
    _aplicar(db, pendientes)

    print("\n" + "=" * 70)
    print("DESPUÉS de aplicar:")
    _auditar(db)


if __name__ == "__main__":
    _args = sys.argv[1:]
    main(aplicar="--aplicar" in _args, verificar="--verificar" in _args)
