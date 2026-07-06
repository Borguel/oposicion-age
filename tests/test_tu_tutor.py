"""Pruebas de Tu Tutor (chat_controller.responder_tutor + blueprints/tu_tutor.py):
el chat unificado que sustituye a los antiguos Chat IA y Asistente Premium.
Cubre lo más importante de fusionarlos en uno solo: que la detección de si
hace falta RAG (buscar contenido real del temario) o no se dispare en el
caso correcto, y que el historial siga persistiendo en Firestore."""
from unittest.mock import patch

from chat_controller import responder_tutor


def _sembrar_tema(db, coleccion="Temario AGE"):
    db.sembrar((coleccion, "bloque_01"), {"titulo": "Bloque I"})
    db.sembrar((coleccion, "bloque_01", "temas", "tema_01"), {"titulo": "La Constitución Española de 1978"})
    db.sembrar((coleccion, "bloque_01", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Estructura",
        "texto": "La Constitución Española consta de un preámbulo, 169 artículos y varias disposiciones."
    })


def test_pregunta_sobre_un_tema_del_temario_activa_rag(db):
    _sembrar_tema(db)
    with patch("chat_controller.call_deepseek_api", return_value="Respuesta con contexto") as mock_llamada, \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        texto, chat_id, usar_rag = responder_tutor(
            "Explícame la Constitución Española", db=db, usuario_id="u1"
        )
    assert usar_rag is True
    assert texto == "Respuesta con contexto"
    mensajes_enviados = mock_llamada.call_args.kwargs["messages"]
    system_prompt = mensajes_enviados[0]["content"]
    user_prompt = mensajes_enviados[1]["content"]
    assert system_prompt == "Eres un asistente experto en oposiciones."
    assert "CONTENIDO DEL TEMARIO" in user_prompt
    assert "preámbulo" in user_prompt
    # Historial persistido en Firestore (no en localStorage).
    conversacion = db.leer(("conversaciones_IA", "u1", "conversaciones", chat_id))
    assert conversacion["mensajes"][0]["content"] == "Explícame la Constitución Española"
    assert conversacion["mensajes"][1]["content"] == "Respuesta con contexto"


def test_pregunta_generica_sobre_el_proceso_selectivo_no_activa_rag(db):
    _sembrar_tema(db)
    with patch("chat_controller.call_deepseek_api", return_value="Ánimo, sigue así") as mock_llamada:
        texto, chat_id, usar_rag = responder_tutor(
            "¿Qué consejos me das para no rendirme antes del examen?", db=db, usuario_id="u1", oposicion="AGE"
        )
    assert usar_rag is False
    mensajes_enviados = mock_llamada.call_args.kwargs["messages"]
    system_prompt = mensajes_enviados[0]["content"]
    user_prompt = mensajes_enviados[1]["content"]
    assert "Tu Tutor" in system_prompt
    assert user_prompt == "¿Qué consejos me das para no rendirme antes del examen?"


def test_mencionar_un_articulo_concreto_tambien_activa_rag(db):
    _sembrar_tema(db)
    with patch("chat_controller.call_deepseek_api", return_value="ok") as mock_llamada, \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        _texto, _chat_id, usar_rag = responder_tutor(
            "¿Qué dice el artículo 14 de la Constitución?", db=db, usuario_id="u1"
        )
    assert usar_rag is True
    mensajes_enviados = mock_llamada.call_args.kwargs["messages"]
    assert "CONTENIDO DEL TEMARIO" in mensajes_enviados[1]["content"]


def test_historial_de_una_conversacion_persiste_y_se_amplia_en_firestore(db):
    with patch("chat_controller.call_deepseek_api", side_effect=["primera respuesta", "segunda respuesta"]):
        _texto1, chat_id, _usar_rag = responder_tutor("Hola, ¿cómo estás?", db=db, usuario_id="u1")
        _texto2, chat_id_2, _usar_rag2 = responder_tutor(
            "Cuéntame más", db=db, usuario_id="u1", chat_id=chat_id
        )

    assert chat_id_2 == chat_id
    conversacion = db.leer(("conversaciones_IA", "u1", "conversaciones", chat_id))
    contenidos = [m["content"] for m in conversacion["mensajes"]]
    assert contenidos == ["Hola, ¿cómo estás?", "primera respuesta", "Cuéntame más", "segunda respuesta"]


def test_ruta_tu_tutor_requiere_premium_y_registra_uso(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "premium", "subscription_status": "active"}}
    })
    parche_auth = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "u1@example.com"})
    parche_auth.start()
    try:
        with patch("chat_controller.call_deepseek_api", return_value="Hola desde Tu Tutor"):
            resp = client.post(
                "/tu-tutor",
                json={"mensaje": "¿Qué consejos me das para el examen?", "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"}
            )
        assert resp.status_code == 200
        assert resp.get_json()["respuesta"] == "Hola desde Tu Tutor"
        datos_usuario = db.leer(("usuarios", "u1"))
        assert datos_usuario["limites_uso"]["chat_temario"]["contador"] == 1
    finally:
        parche_auth.stop()


def test_ruta_tu_tutor_bloqueada_para_plan_gratis(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "gratis"}}
    })
    parche_auth = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "u1@example.com"})
    parche_auth.start()
    try:
        resp = client.post(
            "/tu-tutor",
            json={"mensaje": "Hola", "oposicion": "AGE"},
            headers={"Authorization": "Bearer x"}
        )
        assert resp.status_code == 403
    finally:
        parche_auth.stop()
