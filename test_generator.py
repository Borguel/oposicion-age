import re
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from deepseek_utils import call_deepseek_api


def generar_preguntas_ia_en_lotes(construir_prompt, num_preguntas, tamano_lote=15, temperature=0.4, on_progreso=None):
    """Genera 'num_preguntas' preguntas pidiéndolas a DeepSeek en varios lotes
    en paralelo (ThreadPoolExecutor) en vez de una única llamada gigante.

    on_progreso(evento), si se pasa, se llama cada vez que un lote termina
    (con éxito o error), con {"completadas": i, "total": n_lotes} -- pensado
    para retransmitir progreso real por SSE en vez de mensajes rotativos
    cosméticos (ver /generar-test-desde-pdf en blueprints/pdf_ia.py).

    Usada por blueprints/pdf_ia.py (generar_test_desde_pdf), donde
    construir_prompt(n) embebe el texto real del PDF subido por el usuario --
    para el temario oficial, ver generador_preguntas_verificado.py, que
    ancla cada pregunta a un artículo real y la verifica con una segunda
    llamada independiente antes de aceptarla.

    Antes, /generar-test-inteligente (hoy desactivado en la web) y
    /generar-test-desde-pdf pedían todo el test de golpe con
    max_tokens=min(4000, 300*num_preguntas): a partir de ~13-14 preguntas ese
    tope de 4000 tokens ya se queda corto para el JSON completo
    (pregunta+opciones+explicación ronda 400-600 tokens cada una), y la
    respuesta se corta a medio JSON. Pedir lotes de como mucho 'tamano_lote'
    preguntas mantiene cada llamada individual muy por debajo del límite,
    sea cual sea el total pedido.

    construir_prompt(n) debe devolver el prompt completo pidiendo EXACTAMENTE
    n preguntas, en el mismo formato de array JSON que ya usa esa ruta.

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
    completadas = 0
    with ThreadPoolExecutor(max_workers=min(5, len(lotes))) as executor:
        futuros = [executor.submit(_pedir_lote, n) for n in lotes]
        for futuro in as_completed(futuros):
            lote_preguntas, error = futuro.result()
            completadas += 1
            if error:
                errores.append(error)
            else:
                preguntas.extend(lote_preguntas)
            if on_progreso:
                on_progreso({"completadas": completadas, "total": len(lotes)})

    vistas = set()
    preguntas_unicas = []
    for p in preguntas:
        clave = re.sub(r"\s+", " ", str(p.get("pregunta", "")).strip().lower())
        if clave and clave not in vistas:
            vistas.add(clave)
            preguntas_unicas.append(p)

    return preguntas_unicas, errores
