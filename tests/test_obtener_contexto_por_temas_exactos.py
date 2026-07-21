"""Pruebas de utils.obtener_contexto_por_temas_exactos: el RAG de Tu Tutor.
Antes esta función no tenía ningún test dedicado -- todos los de RAG en
test_tu_tutor.py siembran un único subbloque por tema, así que no podían
detectar ni el problema de orden (Firestore no garantiza ninguno en
.stream()) ni el de recorte silencioso al superar el límite de tokens."""
from unittest.mock import patch

from utils import obtener_contexto_por_temas_exactos


def _contar_tokens_por_palabras(texto, modelo="gpt-3.5-turbo"):
    # Mismo sustituto que usa el resto de la suite: tiktoken necesita
    # descargar su codificación por red, bloqueada en este sandbox.
    return len(texto.split())


def _sembrar_subbloque(db, coleccion, bloque_id, tema_id, sub_id, titulo, texto):
    db.sembrar((coleccion, bloque_id, "temas", tema_id, "subbloques", sub_id), {
        "titulo": titulo,
        "texto": texto,
    })


def test_incluye_por_relevancia_no_por_orden_de_almacenamiento(db):
    coleccion = "Temario AGE"
    # sub_1 (primero por id) es irrelevante para el mensaje; sub_3 (último
    # por id) es el que de verdad responde a la pregunta -- debe incluirse
    # igualmente aunque un orden por id lo dejase el último en la cola.
    _sembrar_subbloque(db, coleccion, "bloque_01", "tema_01", "sub_1",
                        "Historia", "Contenido sobre historia antigua sin relación con la pregunta.")
    _sembrar_subbloque(db, coleccion, "bloque_01", "tema_01", "sub_2",
                        "Geografía", "Contenido sobre geografía, tampoco relacionado.")
    _sembrar_subbloque(db, coleccion, "bloque_01", "tema_01", "sub_3",
                        "MUFACE", "MUFACE es el régimen especial de la Seguridad Social de los funcionarios.")

    with patch("utils.contar_tokens", side_effect=_contar_tokens_por_palabras):
        contexto, truncado = obtener_contexto_por_temas_exactos(
            db, ["bloque_01-tema_01"], "¿qué es MUFACE?", token_limit=15, coleccion=coleccion
        )

    assert "MUFACE es el régimen especial" in contexto
    assert truncado is True


def test_no_truncado_cuando_todo_cabe(db):
    coleccion = "Temario AGE"
    _sembrar_subbloque(db, coleccion, "bloque_01", "tema_01", "sub_1", "Estructura", "Texto breve.")

    with patch("utils.contar_tokens", side_effect=_contar_tokens_por_palabras):
        contexto, truncado = obtener_contexto_por_temas_exactos(
            db, ["bloque_01-tema_01"], "pregunta", token_limit=4000, coleccion=coleccion
        )

    assert "Texto breve" in contexto
    assert truncado is False


def test_tras_fragmento_grande_poco_relevante_que_no_cabe_sigue_probando_otros(db):
    coleccion = "Temario AGE"
    # sub_1 es MUY relevante pero grande (no cabe); sub_2 es poco relevante
    # pero pequeño -- debe entrar igualmente en vez de abandonar el resto al
    # primer tropiezo (mejor aprovechamiento del presupuesto de tokens).
    _sembrar_subbloque(
        db, coleccion, "bloque_01", "tema_01", "sub_1", "MUFACE",
        "MUFACE MUFACE MUFACE " + " ".join(f"palabra{i}" for i in range(30)),
    )
    _sembrar_subbloque(db, coleccion, "bloque_01", "tema_01", "sub_2", "Otro", "Un texto corto cualquiera.")

    with patch("utils.contar_tokens", side_effect=_contar_tokens_por_palabras):
        contexto, truncado = obtener_contexto_por_temas_exactos(
            db, ["bloque_01-tema_01"], "MUFACE", token_limit=15, coleccion=coleccion
        )

    assert "Un texto corto cualquiera" in contexto
    assert truncado is True


def test_sin_mensaje_conserva_el_orden_original_por_id(db):
    coleccion = "Temario AGE"
    _sembrar_subbloque(db, coleccion, "bloque_01", "tema_01", "sub_1", "Primero", "Texto uno.")
    _sembrar_subbloque(db, coleccion, "bloque_01", "tema_01", "sub_2", "Segundo", "Texto dos.")

    with patch("utils.contar_tokens", side_effect=_contar_tokens_por_palabras):
        contexto, truncado = obtener_contexto_por_temas_exactos(
            db, ["bloque_01-tema_01"], token_limit=4000, coleccion=coleccion
        )

    assert contexto.index("Texto uno") < contexto.index("Texto dos")
    assert truncado is False
