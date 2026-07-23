"""Redacta una propuesta de cambio al temario ("elimina este texto exacto,
añade este otro") cuando el BOE modifica una ley vigilada (ver
vigilancia_boe.py), con el mismo espíritu de generador_preguntas_verificado.py:

  1. Generación: se le da a la IA el texto nuevo real del artículo (según el
     BOE) y el contenido actual de los chunks candidatos del tema, y se le
     pide que localice cuál de ellos contiene la versión antigua y proponga
     el cambio exacto.
  2. Guardarraíl determinista en Python (no solo el LLM): el texto a
     eliminar propuesto tiene que aparecer LITERALMENTE en el chunk
     señalado -- si no, se descarta sin gastar la segunda llamada.
  3. Verificación: una segunda llamada independiente (temperatura 0), que
     no reutiliza el razonamiento de la primera, reconfirma la propuesta
     contra los mismos dos textos reales.

Si cualquier paso falla, se descarta la propuesta ENTERA (nunca se
"parchea") y no se genera nada esta vez -- se reintentará en el próximo
ciclo de vigilancia si la ley sigue detectándose como cambiada."""
import json
import logging

from deepseek_utils import call_deepseek_api

logger = logging.getLogger(__name__)


def _bloque_candidatos(subbloques):
    partes = []
    for sub in subbloques:
        partes.append(f"CHUNK_ID: {sub['chunk_id']}\nTÍTULO: {sub['titulo']}\nTEXTO ACTUAL:\n{sub['texto']}")
    return "\n\n---\n\n".join(partes)


def _prompt_generacion(texto_articulo_nuevo, subbloques):
    system = (
        "Eres un editor jurídico encargado de mantener al día el temario de una web de preparación de "
        "oposiciones. Te llega el texto VIGENTE (real, tal como lo publica el BOE) de un artículo que "
        "acaba de ser modificado, y el contenido actual de varios fragmentos ('chunks') del temario que "
        "podrían contener la versión antigua de ese mismo artículo.\n\n"
        "REGLAS INQUEBRANTABLES:\n"
        "1. Localiza EXACTAMENTE en qué chunk aparece la versión antigua de este artículo (por su número "
        "de artículo, no por similitud aproximada). Si ningún chunk lo contiene, o no estás seguro, "
        "responde con chunk_id_afectado vacío -- NUNCA inventes un chunk ni una respuesta aproximada.\n"
        "2. \"texto_eliminar\" debe ser una copia LITERAL, carácter a carácter, de un fragmento del texto "
        "actual de ese chunk (nunca resumido, parafraseado, ni con saltos de línea distintos) -- "
        "exactamente el pasaje que ya no es correcto según el texto vigente nuevo.\n"
        "3. \"texto_anadir\" debe ser el texto que debería sustituirlo, basado ÚNICAMENTE en el texto "
        "vigente nuevo proporcionado, con un estilo y formato coherente con el resto del chunk.\n"
        "4. \"resumen\" es una frase breve en español, para un no jurista, de qué ha cambiado (p. ej. "
        "\"el plazo pasa de 15 a 20 días hábiles\").\n\n"
        "Devuelve ÚNICAMENTE un JSON con esta forma exacta, sin bloques de código ni texto adicional:\n"
        '{"chunk_id_afectado": "...", "resumen": "...", "texto_eliminar": "...", "texto_anadir": "..."}'
    )
    user = (
        f"TEXTO VIGENTE (nuevo, según el BOE):\n{texto_articulo_nuevo}\n\n"
        f"CHUNKS CANDIDATOS DEL TEMARIO:\n{_bloque_candidatos(subbloques)}"
    )
    return system, user


def _prompt_verificacion(texto_articulo_nuevo, texto_chunk_afectado, propuesta):
    system = (
        "Eres un verificador jurídico independiente. Te llega una propuesta de cambio de temario YA "
        "REDACTADA por otro proceso (qué texto eliminar, qué texto añadir), el texto vigente real "
        "(según el BOE) y el texto actual del chunk del temario. No des por hecho que la propuesta es "
        "correcta: compruébala tú mismo contra ambos textos, como si la vieras por primera vez.\n\n"
        "Marca la propuesta como inválida si detectas CUALQUIERA de estos problemas:\n"
        "1. \"texto_eliminar\" no aparece literalmente en el texto actual del chunk.\n"
        "2. \"texto_anadir\" no coincide con lo que dice el texto vigente real, o añade información que "
        "no está en él.\n"
        "3. El cambio propuesto no refleja fielmente la diferencia real entre el texto antiguo del "
        "chunk y el texto vigente nuevo.\n"
        "4. El \"resumen\" no describe con precisión el cambio.\n\n"
        "Devuelve ÚNICAMENTE un JSON con esta forma exacta, sin texto adicional:\n"
        '{"valido": true, "problemas": []}\n'
        "Si encuentras algún problema, \"valido\" debe ser false y \"problemas\" debe listar cada motivo."
    )
    user = (
        f"TEXTO VIGENTE (nuevo, según el BOE):\n{texto_articulo_nuevo}\n\n"
        f"TEXTO ACTUAL DEL CHUNK:\n{texto_chunk_afectado}\n\n"
        f"PROPUESTA A VERIFICAR:\n{json.dumps(propuesta, ensure_ascii=False)}"
    )
    return system, user


def generar_propuesta_cambio(texto_articulo_nuevo, subbloques_candidatos):
    """Devuelve {"chunk_id_afectado", "resumen", "texto_eliminar",
    "texto_anadir"} si se genera y verifica una propuesta válida, o None si
    no (nada que localizar, texto no literal, o la verificación la
    rechaza)."""
    if not texto_articulo_nuevo or not subbloques_candidatos:
        return None

    system_gen, user_gen = _prompt_generacion(texto_articulo_nuevo, subbloques_candidatos)
    generado = call_deepseek_api(
        messages=[{"role": "system", "content": system_gen}, {"role": "user", "content": user_gen}],
        temperature=0.3,
        max_tokens=1200,
        response_format_json=True,
    )
    if not generado:
        return None
    try:
        propuesta = json.loads(generado)
    except json.JSONDecodeError:
        logger.warning("generar_propuesta_cambio: respuesta de generación no es JSON válido")
        return None

    chunk_id = propuesta.get("chunk_id_afectado")
    texto_eliminar = propuesta.get("texto_eliminar")
    texto_anadir = propuesta.get("texto_anadir")
    if not chunk_id or not texto_eliminar or not texto_anadir or not propuesta.get("resumen"):
        return None

    chunk_afectado = next((s for s in subbloques_candidatos if s["chunk_id"] == chunk_id), None)
    if not chunk_afectado:
        return None
    # Guardarraíl determinista: si el LLM no copió el texto literalmente,
    # ni siquiera merece la pena gastar la segunda llamada de verificación.
    if texto_eliminar not in chunk_afectado["texto"]:
        logger.info("generar_propuesta_cambio: texto_eliminar propuesto no es literal en el chunk %s, descartado", chunk_id)
        return None

    system_ver, user_ver = _prompt_verificacion(texto_articulo_nuevo, chunk_afectado["texto"], propuesta)
    verificacion_raw = call_deepseek_api(
        messages=[{"role": "system", "content": system_ver}, {"role": "user", "content": user_ver}],
        temperature=0.0,
        max_tokens=400,
        response_format_json=True,
    )
    if not verificacion_raw:
        return None
    try:
        verificacion = json.loads(verificacion_raw)
    except json.JSONDecodeError:
        return None
    if verificacion.get("valido") is not True:
        logger.info(
            "generar_propuesta_cambio: propuesta para el chunk %s rechazada en verificación: %s",
            chunk_id, verificacion.get("problemas"),
        )
        return None

    return {
        "chunk_id_afectado": chunk_id,
        "resumen": propuesta["resumen"],
        "texto_eliminar": texto_eliminar,
        "texto_anadir": texto_anadir,
    }
