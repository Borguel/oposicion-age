"""Pruebas de Tu Tutor (chat_controller.responder_tutor + blueprints/tu_tutor.py):
el chat unificado que sustituye a los antiguos Chat IA y Asistente Premium.
Cubre lo más importante de fusionarlos en uno solo: que la detección de si
hace falta RAG (buscar contenido real del temario) o no se dispare en el
caso correcto, y que el historial siga persistiendo en Firestore."""
import json
from unittest.mock import patch

from chat_controller import responder_tutor, responder_tutor_stream, sugerencia_inicial_usuario
from utils import obtener_catalogo_temas


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
    # Mismo system prompt (persona/tono/reglas de honestidad de Tu Tutor)
    # que el resto de respuestas -- antes la rama RAG usaba uno genérico
    # aparte y perdía todo eso justo al responder con contenido real.
    assert "Tu Tutor" in system_prompt
    assert "CONTENIDO DEL TEMARIO" in user_prompt
    assert "preámbulo" in user_prompt
    # Debe citar de qué tema procede el contenido, para que el usuario
    # pueda verificarlo (no una simple afirmación sin fuente).
    assert "La Constitución Española de 1978" in user_prompt
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


def test_pregunta_de_seguimiento_sin_repetir_el_tema_tambien_activa_rag(db):
    # Antes de esto, solo se miraba el mensaje actual para decidir si hacía
    # falta RAG -- una pregunta de seguimiento que no repite el nombre del
    # tema ("¿y cuántos artículos tiene?") se contestaba sin contenido real,
    # aunque el turno anterior fuera justo sobre ese tema.
    _sembrar_tema(db)
    with patch("chat_controller.call_deepseek_api", side_effect=["Respuesta sobre la Constitución Española", "ok"]) as mock_llamada, \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        _texto1, chat_id, usar_rag1 = responder_tutor(
            "Explícame la Constitución Española", db=db, usuario_id="u1"
        )
        _texto2, _chat_id2, usar_rag2 = responder_tutor(
            "¿Y cuántas disposiciones adicionales tiene?", db=db, usuario_id="u1", chat_id=chat_id
        )
    assert usar_rag1 is True
    assert usar_rag2 is True
    segunda_llamada_mensajes = mock_llamada.call_args_list[1].kwargs["messages"]
    assert "CONTENIDO DEL TEMARIO" in segunda_llamada_mensajes[-1]["content"]


def test_pregunta_sin_relacion_con_el_turno_anterior_no_fuerza_rag(db):
    _sembrar_tema(db)
    with patch("chat_controller.call_deepseek_api", side_effect=["Ánimo, tú puedes", "ok"]) as mock_llamada:
        _texto1, chat_id, usar_rag1 = responder_tutor(
            "Estoy agobiado, ¿algún consejo para gestionar el estrés?", db=db, usuario_id="u1"
        )
        _texto2, _chat_id2, usar_rag2 = responder_tutor(
            "¿Cuántas plazas hay convocadas?", db=db, usuario_id="u1", chat_id=chat_id
        )
    assert usar_rag1 is False
    assert usar_rag2 is False


def test_deteccion_de_pregunta_de_test():
    from chat_controller import _es_pregunta_de_test
    # Formato en que el frontend pega las opciones (letras sueltas en mayúscula).
    assert _es_pregunta_de_test("¿...? A La Comisión B El Ministro C El Presidente D El Pleno")
    # Clásico a) b) c) d).
    assert _es_pregunta_de_test("Pregunta: a) uno b) dos c) tres d) cuatro")
    # Preguntas normales NO se confunden con un test.
    assert not _es_pregunta_de_test("¿Qué dice el artículo 14 de la Constitución?")
    assert not _es_pregunta_de_test("Explícame el poder ejecutivo del Estado")


def test_pregunta_de_test_pegada_no_hereda_el_tema_anterior(db):
    # Se habla de la Constitución y luego se pega una pregunta de test de OTRA
    # cosa (Consejo de Estado). No debe arrastrar el tema anterior ni meter su
    # contenido: debe recibir la instrucción de resolver la pregunta directa.
    _sembrar_tema(db)
    mcq = ("Según el artículo veintiséis, ¿a quién corresponde aprobar los gastos? "
           "A A la Comisión Permanente B Al Ministro de Hacienda "
           "C Al Presidente del Consejo de Estado D Al Pleno del Consejo de Estado")
    with patch("chat_controller.call_deepseek_api", side_effect=["Sobre la Constitución...", "La correcta es la A"]) as mock_llamada, \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        _t1, chat_id, _r1 = responder_tutor("Explícame la Constitución Española de 1978", db=db, usuario_id="u1")
        _t2, _c2, usar_rag2 = responder_tutor(mcq, db=db, usuario_id="u1", chat_id=chat_id)
    assert usar_rag2 is False  # sin tema concreto identificado -> se responde directo
    prompt = mock_llamada.call_args_list[1].kwargs["messages"][-1]["content"]
    assert "opción correcta" in prompt          # se le pide resolver la pregunta
    assert "CONTENIDO DEL TEMARIO" not in prompt  # no se cuela el tema equivocado


def test_rag_avisa_de_que_el_contenido_no_lo_ha_pasado_el_usuario(db):
    # El contenido del temario lo carga la plataforma, no el usuario: el prompt
    # debe dejarlo claro para que el tutor no diga "según el temario que me has
    # pasado" ni se niegue a responder si la pregunta no encaja con él.
    _sembrar_tema(db)
    with patch("chat_controller.call_deepseek_api", return_value="ok") as mock_llamada, \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        responder_tutor("Explícame la Constitución Española de 1978", db=db, usuario_id="u1")
    prompt = mock_llamada.call_args.kwargs["messages"][-1]["content"]
    assert "NO te ha pasado" in prompt
    assert "CONTENIDO DEL TEMARIO" in prompt
    assert "MENSAJE DEL USUARIO" in prompt


def _texto_sistema(mensajes):
    return " ".join(m["content"] for m in mensajes if m["role"] == "system")


def test_pregunta_de_test_oficial_usa_la_respuesta_verificada(db):
    # Si la pregunta pegada coincide con una del banco de exámenes oficiales,
    # el tutor recibe la respuesta correcta ya corregida para no razonarla ni
    # contradecir lo que marca el test.
    db.sembrar(("examenes_oficiales_AGE", "of1"), {
        "tipo": "pregunta",
        "pregunta": "El plazo para interponer recurso de alzada es de un mes desde la notificacion",
        "opciones": {"A": "Un mes", "B": "Tres meses", "C": "Quince dias", "D": "Dos meses"},
        "respuesta_correcta": "A",
        "explicacion": "El recurso de alzada se interpone en el plazo de un mes (art. 122 LPAC).",
        "examen": "AGE 2025",
    })
    mcq = ("El plazo para interponer recurso de alzada es de un mes desde la notificación. "
           "A Un mes B Tres meses C Quince días D Dos meses")
    with patch("chat_controller.call_deepseek_api", return_value="ok") as mock_llamada:
        responder_tutor(mcq, db=db, usuario_id="u1", oposicion="AGE", coleccion="Temario AGE")
    sistema = _texto_sistema(mock_llamada.call_args.kwargs["messages"])
    assert "DATO VERIFICADO" in sistema
    assert "opción A" in sistema
    assert "art. 122 LPAC" in sistema  # explicación oficial incluida


def test_pregunta_de_test_no_oficial_no_inventa_dato_verificado(db):
    # Una pregunta que NO está en el banco oficial no debe generar un bloque
    # "DATO VERIFICADO" (que daría falsa autoridad a una respuesta inventada).
    db.sembrar(("examenes_oficiales_AGE", "of1"), {
        "tipo": "pregunta",
        "pregunta": "El plazo para interponer recurso de alzada es de un mes",
        "opciones": {"A": "Un mes", "B": "Tres meses"},
        "respuesta_correcta": "A",
    })
    mcq = "¿Capital de Francia? A Madrid B París C Roma D Berlín"
    with patch("chat_controller.call_deepseek_api", return_value="ok") as mock_llamada:
        responder_tutor(mcq, db=db, usuario_id="u1", oposicion="AGE", coleccion="Temario AGE")
    sistema = _texto_sistema(mock_llamada.call_args.kwargs["messages"])
    assert "DATO VERIFICADO" not in sistema


def test_contexto_de_pagina_pasa_la_pregunta_en_pantalla(db):
    # El widget manda la pregunta que el usuario tiene delante en un test; el
    # tutor debe recibirla para resolver "¿cuál es la correcta?" sin pegarla.
    contexto = {
        "tipo": "test",
        "enunciado": "¿Qué órgano aprueba los Presupuestos Generales del Estado?",
        "opciones": {"A": "El Gobierno", "B": "Las Cortes Generales", "C": "El Rey"},
    }
    with patch("chat_controller.call_deepseek_api", return_value="ok") as mock_llamada:
        responder_tutor("¿Cuál es la correcta?", db=db, usuario_id="u1", oposicion="AGE",
                        coleccion="Temario AGE", contexto_pagina=contexto)
    sistema = _texto_sistema(mock_llamada.call_args.kwargs["messages"])
    assert "PREGUNTA EN PANTALLA" in sistema
    assert "Presupuestos Generales del Estado" in sistema
    assert "Las Cortes Generales" in sistema


def test_buscar_pregunta_oficial_por_contencion_del_enunciado(db):
    from utils import buscar_pregunta_oficial
    db.sembrar(("examenes_oficiales_AGE", "of1"), {
        "tipo": "pregunta",
        "pregunta": "La soberanía nacional reside en el pueblo español",
        "opciones": {"A": "El pueblo español", "B": "El Rey"},
        "respuesta_correcta": "A",
    })
    # El texto pegado trae el enunciado + opciones: debe emparejar.
    encontrada = buscar_pregunta_oficial(db, "AGE", "La soberanía nacional reside en el pueblo español. A ... B ...")
    assert encontrada is not None
    assert encontrada["respuesta_correcta"] == "A"
    # Un texto sin relación no empareja.
    assert buscar_pregunta_oficial(db, "AGE", "¿Cuántos ríos hay en España?") is None


def test_si_deepseek_falla_no_guarda_nada_y_devuelve_none(db):
    with patch("chat_controller.call_deepseek_api", return_value=None), \
         patch("chat_controller.crear_conversacion") as mock_crear, \
         patch("chat_controller.agregar_mensaje_a_conversacion") as mock_agregar:
        texto, chat_id, _usar_rag = responder_tutor("Hola", db=db, usuario_id="u1")
    assert texto is None
    assert chat_id is None
    mock_crear.assert_not_called()
    mock_agregar.assert_not_called()


def test_responder_tutor_stream_emite_deltas_y_guarda_al_final(db):
    with patch("chat_controller.call_deepseek_api_stream", return_value=iter(["Hola", " que tal"])):
        eventos = list(responder_tutor_stream("Dame consejos para estudiar", db=db, usuario_id="u1"))
    assert [e["tipo"] for e in eventos] == ["delta", "delta", "fin"]
    assert eventos[0]["texto"] == "Hola"
    assert eventos[1]["texto"] == " que tal"
    chat_id = eventos[-1]["chat_id"]
    conversacion = db.leer(("conversaciones_IA", "u1", "conversaciones", chat_id))
    assert conversacion["mensajes"][1]["content"] == "Hola que tal"


def test_stream_por_ruta_guarda_la_conversacion_y_sale_en_historial(client, db):
    # Flujo completo de producción: POST a /tu-tutor/stream, consumir el SSE
    # entero, y comprobar que la conversación queda guardada y aparece en
    # /conversaciones (regresión del "historial en blanco").
    db.sembrar(("usuarios", "u1"), {"suscripciones": {"AGE": {"plan": "premium", "subscription_status": "active"}}})
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "u1@x.com"}), \
         patch("chat_controller.call_deepseek_api_stream", return_value=iter(["Hola", " mundo"])):
        r = client.post("/tu-tutor/stream", json={"mensaje": "Dame consejos", "oposicion": "AGE"},
                        headers={"Authorization": "Bearer x"})
        r.get_data(as_text=True)  # consume el stream entero (dispara el guardado)
        lista = client.get("/conversaciones", headers={"Authorization": "Bearer x"}).get_json()
    assert len(lista["conversaciones"]) == 1
    assert lista["conversaciones"][0]["titulo"] == "Dame consejos"


def test_anadir_mensaje_a_conversacion_inexistente_la_crea(db):
    # Si llega un chat_id que ya no existe (obsoleto/borrado), el turno debe
    # guardarse igualmente creando la conversación, no perderse.
    from chat_controller import agregar_mensaje_a_conversacion
    agregar_mensaje_a_conversacion(db, "u1", "id_fantasma", "user", "¿Hola?")
    conv = db.leer(("conversaciones_IA", "u1", "conversaciones", "id_fantasma"))
    assert conv is not None
    assert conv["mensajes"][0]["content"] == "¿Hola?"
    assert conv.get("timestamp_inicio")


def test_listar_conversaciones_incluye_las_antiguas_sin_timestamp(client, db):
    # Regresión: el histórico salía en blanco porque se ordenaba con
    # order_by("timestamp_inicio"), que EXCLUYE las conversaciones sin ese
    # campo. Ahora deben listarse todas, ordenadas por fecha (las que no
    # tienen fecha van al final, pero aparecen).
    db.sembrar(("usuarios", "u1"), {"suscripciones": {"AGE": {"plan": "premium", "subscription_status": "active"}}})
    db.sembrar(("conversaciones_IA", "u1", "conversaciones", "nueva"),
               {"titulo": "Reciente", "timestamp_inicio": "2026-07-14T10:00:00"})
    db.sembrar(("conversaciones_IA", "u1", "conversaciones", "antigua"),
               {"titulo": "Sin fecha"})  # conversación legacy, sin timestamp_inicio
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "u1@x.com"}):
        r = client.get("/conversaciones", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    convs = r.get_json()["conversaciones"]
    titulos = [c["titulo"] for c in convs]
    assert "Reciente" in titulos
    assert "Sin fecha" in titulos  # antes se perdía
    assert titulos[0] == "Reciente"  # la que tiene fecha, primero


def test_responder_tutor_stream_emite_error_si_deepseek_no_devuelve_nada(db):
    with patch("chat_controller.call_deepseek_api_stream", return_value=iter([])), \
         patch("chat_controller.crear_conversacion") as mock_crear:
        eventos = list(responder_tutor_stream("Hola", db=db, usuario_id="u1"))
    assert eventos == [{"tipo": "error"}]
    mock_crear.assert_not_called()


def test_pregunta_sobre_estructura_del_examen_usa_datos_oficiales_si_existen(db):
    db.sembrar(("datos_convocatoria", "GACE"), {
        "oposicion": "GACE", "anio": 2025, "fuente": "BOE 2025",
        "texto": "El primer ejercicio tiene un máximo de 100 preguntas y dura 90 minutos."
    })
    with patch("chat_controller.call_deepseek_api", return_value="ok") as mock_llamada:
        _texto, _chat_id, usar_rag = responder_tutor(
            "¿Cuántas preguntas tiene el primer ejercicio?", db=db, usuario_id="u1", oposicion="GACE"
        )
    assert usar_rag is False
    mensajes_enviados = mock_llamada.call_args.kwargs["messages"]
    user_prompt = mensajes_enviados[1]["content"]
    assert "DATOS OFICIALES" in user_prompt
    assert "máximo de 100 preguntas" in user_prompt
    assert "¿Cuántas preguntas tiene el primer ejercicio?" in user_prompt


def test_pregunta_sobre_como_se_divide_el_temario_usa_el_catalogo_real(db):
    # Antes de esto, una pregunta genérica sobre la estructura del temario
    # no activaba ni el RAG ni ningún contexto real, así que el modelo se
    # inventaba bloques/temas que no existen de verdad en el catálogo.
    db.sembrar(("Temario AGE", "bloque_01"), {"titulo": "Organización del Estado"})
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01"), {"titulo": "La Constitución Española de 1978"})
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_02"), {"titulo": "La Corona"})
    db.sembrar(("Temario AGE", "bloque_02"), {"titulo": "Derecho administrativo"})
    db.sembrar(("Temario AGE", "bloque_02", "temas", "tema_01"), {"titulo": "El acto administrativo"})
    with patch("chat_controller.call_deepseek_api", return_value="ok") as mock_llamada:
        _texto, _chat_id, usar_rag = responder_tutor(
            "¿Cómo se divide el temario?", db=db, usuario_id="u1", oposicion="AGE", coleccion="Temario AGE"
        )
    assert usar_rag is False
    user_prompt = mock_llamada.call_args.kwargs["messages"][1]["content"]
    assert "ESTRUCTURA REAL DEL TEMARIO" in user_prompt
    assert "Bloque I. Organización del Estado (2 temas)" in user_prompt
    assert "1. La Constitución Española de 1978" in user_prompt
    assert "2. La Corona" in user_prompt
    assert "Bloque II. Derecho administrativo (1 temas)" in user_prompt


def test_variaciones_de_orden_de_la_pregunta_tambien_usan_el_catalogo_real(db):
    # Bug real reportado: "¿qué estructura tiene el temario?" no activaba
    # nada porque la detección comparaba frases EXACTAS ("estructura del
    # temario") y esta pregunta trae las mismas palabras en otro orden, así
    # que el modelo acababa inventando una estructura de 2 bloques que no
    # existe. La detección ahora es por palabras sueltas, sin importar el
    # orden.
    db.sembrar(("Temario AGE", "bloque_01"), {"titulo": "Organización del Estado"})
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01"), {"titulo": "La Constitución Española de 1978"})
    preguntas = [
        "¿Qué estructura tiene el temario?",
        "¿Cómo está organizado el temario?",
        "¿De qué se compone el temario?",
        "¿Cuántos bloques tiene la oposición?",
    ]
    for pregunta in preguntas:
        with patch("chat_controller.call_deepseek_api", return_value="ok") as mock_llamada:
            _texto, _chat_id, usar_rag = responder_tutor(
                pregunta, db=db, usuario_id="u1", oposicion="AGE", coleccion="Temario AGE"
            )
        assert usar_rag is False
        user_prompt = mock_llamada.call_args.kwargs["messages"][1]["content"]
        assert "ESTRUCTURA REAL DEL TEMARIO" in user_prompt, f"no se detectó para: {pregunta!r}"


def test_pregunta_sobre_el_temario_sin_catalogo_cargado_no_falla(db):
    with patch("chat_controller.call_deepseek_api", return_value="ok") as mock_llamada:
        texto, _chat_id, usar_rag = responder_tutor(
            "¿Cuántos bloques tiene el temario?", db=db, usuario_id="u1", oposicion="AGE"
        )
    assert usar_rag is False
    assert texto == "ok"
    user_prompt = mock_llamada.call_args.kwargs["messages"][1]["content"]
    assert user_prompt == "¿Cuántos bloques tiene el temario?"


def test_contexto_personal_del_usuario_se_incluye_en_el_prompt(db):
    db.sembrar(("Temario AGE", "bloque_01"), {"titulo": "Organización del Estado"})
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01"), {"titulo": "La Constitución Española de 1978"})
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_02"), {"titulo": "La Corona"})
    db.sembrar(("Temario AGE", "bloque_02"), {"titulo": "Derecho administrativo"})
    db.sembrar(("Temario AGE", "bloque_02", "temas", "tema_01"), {"titulo": "El acto administrativo"})
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "nombre": "María",
        "racha": {"racha_actual": 6},
        "fechas_examen": {"AGE": "2026-10-15"},
        "estadisticas": {
            "AGE": {
                "rendimiento_por_tema": {
                    "bloque_01-tema_01": {"aciertos": 9, "fallos": 1, "blancos": 0},  # va bien
                    "bloque_01-tema_02": {"aciertos": 1, "fallos": 5, "blancos": 0},  # muy flojo
                    "bloque_02-tema_01": {"aciertos": 2, "fallos": 4, "blancos": 0},  # flojo
                }
            }
        }
    })
    with patch("chat_controller.call_deepseek_api", return_value="ok") as mock_llamada:
        responder_tutor(
            "¿Qué consejos me das para el examen?", db=db, usuario_id="u1", oposicion="AGE", coleccion="Temario AGE"
        )

    mensajes_enviados = mock_llamada.call_args.kwargs["messages"]
    assert mensajes_enviados[1]["role"] == "system"
    contexto_personal = mensajes_enviados[1]["content"]
    assert "María" in contexto_personal
    assert "6 días" in contexto_personal
    assert "2026-10-15" in contexto_personal
    # Los 2 temas con peor ratio de aciertos, no el que va bien (solo se
    # avisa de un máximo de 2 para no abrumar).
    assert "La Corona" in contexto_personal
    assert "El acto administrativo" in contexto_personal
    assert "La Constitución Española de 1978" not in contexto_personal


def test_contexto_personal_incluye_la_nota_del_ultimo_test(db):
    # El tutor debe poder responder "¿qué nota saqué?" con datos reales del
    # historial (antes decía que no tenía acceso al historial de resultados).
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "nombre": "Ana",
        "estadisticas": {
            "AGE": {
                "tests_realizados": 3,
                "tests_aprobados": 1,
                "historial_tests": [
                    {"aciertos": 4, "fallos": 6, "blancos": 0, "tipo": "personalizado", "resultado": "suspendido"},
                    {"aciertos": 5, "fallos": 5, "blancos": 0, "tipo": "personalizado", "resultado": "suspendido"},
                    # Último: 8 aciertos, 1 fallo, 1 blanco de 10 -> nota alta, aprobado.
                    {"aciertos": 8, "fallos": 1, "blancos": 1, "tipo": "oficial", "resultado": "aprobado"},
                ],
            }
        },
    })
    with patch("chat_controller.call_deepseek_api", return_value="ok") as mock_llamada:
        responder_tutor("¿Qué nota saqué en el último test?", db=db, usuario_id="u1", oposicion="AGE", coleccion="Temario AGE")

    contexto_personal = mock_llamada.call_args.kwargs["messages"][1]["content"]
    # Nota del último (8 - 1/3 = 7.67 sobre 10) y que fue aprobado.
    assert "7.67 sobre 10" in contexto_personal
    assert "aprobado" in contexto_personal
    # Nota media real sobre 10, no la media de aciertos.
    assert "sobre 10" in contexto_personal
    # Sube desde 1.0 hasta 7.67 -> debe detectar tendencia al alza.
    assert "subiendo" in contexto_personal


def test_sugerencia_inicial_recomienda_practicar_el_tema_mas_flojo(db):
    db.sembrar(("Temario AGE", "bloque_01"), {"titulo": "Organización del Estado"})
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01"), {"titulo": "La Constitución Española de 1978"})
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_02"), {"titulo": "La Corona"})
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "nombre": "Borja",
        "estadisticas": {
            "AGE": {
                "tests_realizados": 4,
                "rendimiento_por_tema": {
                    "bloque_01-tema_01": {"aciertos": 9, "fallos": 1, "blancos": 0},  # va bien
                    "bloque_01-tema_02": {"aciertos": 1, "fallos": 5, "blancos": 0},  # muy flojo
                },
            }
        },
    })
    catalogo = obtener_catalogo_temas(db, "Temario AGE")
    sugerencia = sugerencia_inicial_usuario(db, "u1", "AGE", catalogo)

    assert "Borja" in sugerencia["saludo"]
    # La acción debe apuntar al tema flojo concreto (para el deep-link a
    # generar un test de ESE tema), no a otro.
    assert sugerencia["accion"]["tema_id"] == "bloque_01-tema_02"
    assert "La Corona" in sugerencia["accion"]["label"]
    assert isinstance(sugerencia["sugerencias"], list) and sugerencia["sugerencias"]


def test_sugerencia_inicial_usuario_nuevo_sin_tests_no_tiene_accion(db):
    db.sembrar(("Temario AGE", "bloque_01"), {"titulo": "Organización del Estado"})
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01"), {"titulo": "La Constitución Española de 1978"})
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    catalogo = obtener_catalogo_temas(db, "Temario AGE")
    sugerencia = sugerencia_inicial_usuario(db, "u1", "AGE", catalogo)

    # Sin tests hechos, no se recomienda practicar ningún tema concreto: solo
    # un saludo genérico y sugerencias de arranque.
    assert sugerencia["accion"] is None
    assert sugerencia["saludo"]
    assert sugerencia["sugerencias"]


def test_stream_incluye_temas_relacionados_para_generar_test(db):
    # Cuando la respuesta va sobre un tema concreto del temario, el evento
    # "fin" lleva ese tema (id + título) para que el frontend pueda ofrecer un
    # "Generar test de este tema" debajo del mensaje.
    _sembrar_tema(db)
    with patch("chat_controller.call_deepseek_api_stream", return_value=iter(["La Constitución ", "consta de..."])), \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        eventos = list(responder_tutor_stream(
            "Explícame la Constitución Española", db=db, usuario_id="u1", oposicion="AGE", coleccion="Temario AGE"
        ))
    fin = [e for e in eventos if e["tipo"] == "fin"][0]
    assert fin["temas_relacionados"] == [
        {"tema_id": "bloque_01-tema_01", "titulo": "La Constitución Española de 1978"}
    ]


def test_stream_sin_tema_concreto_no_incluye_acciones_de_tema(db):
    _sembrar_tema(db)
    with patch("chat_controller.call_deepseek_api_stream", return_value=iter(["Ánimo, sigue así"])):
        eventos = list(responder_tutor_stream(
            "¿Qué consejos me das para no rendirme?", db=db, usuario_id="u1", oposicion="AGE", coleccion="Temario AGE"
        ))
    fin = [e for e in eventos if e["tipo"] == "fin"][0]
    assert fin["temas_relacionados"] == []


def test_tema_con_pocos_intentos_no_cuenta_como_flojo_ni_se_menciona(db):
    db.sembrar(("Temario AGE", "bloque_01"), {"titulo": "Organización del Estado"})
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01"), {"titulo": "La Constitución Española de 1978"})
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "estadisticas": {"AGE": {"rendimiento_por_tema": {"bloque_01-tema_01": {"aciertos": 0, "fallos": 1, "blancos": 0}}}}
    })
    with patch("chat_controller.call_deepseek_api", return_value="ok") as mock_llamada:
        responder_tutor("Hola", db=db, usuario_id="u1", oposicion="AGE", coleccion="Temario AGE")

    mensajes_enviados = mock_llamada.call_args.kwargs["messages"]
    # Sin nombre/racha/fecha, y con un único tema que solo tiene 1 intento
    # (por debajo del mínimo para considerarlo "flojo"), no hay nada que
    # contar todavía -- no debe insertarse ningún mensaje de contexto
    # personal de más.
    assert mensajes_enviados[1]["role"] == "user"


def test_memoria_cruzada_se_actualiza_al_completar_un_lote_de_turnos(db):
    chat_id = None
    with patch("chat_controller.call_deepseek_api", return_value="respuesta") as mock_llamada:
        for i in range(5):
            _texto, chat_id, _usar_rag = responder_tutor(f"mensaje {i}", db=db, usuario_id="u1", chat_id=chat_id)

    # 5 turnos, por debajo del lote de 6 -- de momento solo se cuenta,
    # ninguna llamada de más al modelo aparte de la respuesta normal.
    assert mock_llamada.call_count == 5
    datos_usuario = db.leer(("usuarios", "u1"))
    assert datos_usuario["memoria_tutor"]["turnos_pendientes"] == 5
    assert "resumen" not in datos_usuario["memoria_tutor"]

    with patch("chat_controller.call_deepseek_api", side_effect=["respuesta 6", "Le preocupa el bloque de informática"]) as mock_llamada2:
        responder_tutor("mensaje 5", db=db, usuario_id="u1", chat_id=chat_id)

    # Al completar el 6º turno: la respuesta normal + una llamada extra
    # para actualizar la memoria persistente entre conversaciones.
    assert mock_llamada2.call_count == 2
    datos_usuario = db.leer(("usuarios", "u1"))
    assert datos_usuario["memoria_tutor"]["resumen"] == "Le preocupa el bloque de informática"
    assert datos_usuario["memoria_tutor"]["turnos_pendientes"] == 0


def test_memoria_cruzada_se_usa_en_una_conversacion_nueva_distinta(db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "memoria_tutor": {"resumen": "Le preocupa mucho el bloque de informática.", "turnos_pendientes": 0}
    })
    with patch("chat_controller.call_deepseek_api", return_value="ok") as mock_llamada:
        responder_tutor("Hola de nuevo", db=db, usuario_id="u1", oposicion="AGE")

    # chat_id=None -> conversación nueva, sin relación con la anterior; aun
    # así debe usarse lo que se recuerda de conversaciones pasadas.
    mensajes_enviados = mock_llamada.call_args.kwargs["messages"]
    assert mensajes_enviados[1]["role"] == "system"
    assert "Le preocupa mucho el bloque de informática." in mensajes_enviados[1]["content"]


def test_pregunta_sobre_estructura_del_examen_sin_datos_cargados_no_falla(db):
    with patch("chat_controller.call_deepseek_api", return_value="ok") as mock_llamada:
        texto, _chat_id, usar_rag = responder_tutor(
            "¿Cuánto tiempo hay para el segundo ejercicio?", db=db, usuario_id="u1", oposicion="GACE"
        )
    assert usar_rag is False
    assert texto == "ok"
    mensajes_enviados = mock_llamada.call_args.kwargs["messages"]
    user_prompt = mensajes_enviados[1]["content"]
    assert user_prompt == "¿Cuánto tiempo hay para el segundo ejercicio?"


def test_segundo_mensaje_de_una_conversacion_incluye_el_historial_previo(db):
    # Antes de esto, cada mensaje se mandaba aislado al modelo (solo system
    # prompt + mensaje actual), así que un "cuéntame más" no tenía forma de
    # saber a qué se refería -- el historial se guardaba en Firestore pero
    # nunca se reenviaba de vuelta al modelo.
    with patch("chat_controller.call_deepseek_api", side_effect=["Encantado de ayudarte", "Claro, te explico más"]) as mock_llamada:
        _texto1, chat_id, _usar_rag = responder_tutor("Hola, ¿cómo estás?", db=db, usuario_id="u1")
        _texto2, _chat_id_2, _usar_rag2 = responder_tutor(
            "Cuéntame más", db=db, usuario_id="u1", chat_id=chat_id
        )

    primera_llamada_mensajes = mock_llamada.call_args_list[0].kwargs["messages"]
    assert len(primera_llamada_mensajes) == 2  # sin historial: primer mensaje de la conversación

    segunda_llamada_mensajes = mock_llamada.call_args_list[1].kwargs["messages"]
    assert segunda_llamada_mensajes[1] == {"role": "user", "content": "Hola, ¿cómo estás?"}
    assert segunda_llamada_mensajes[2] == {"role": "assistant", "content": "Encantado de ayudarte"}
    assert segunda_llamada_mensajes[3] == {"role": "user", "content": "Cuéntame más"}


def test_historial_se_limita_a_los_ultimos_mensajes_en_conversaciones_muy_largas(db):
    mensajes_previos = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"mensaje {i}"}
        for i in range(50)
    ]
    db.sembrar(("conversaciones_IA", "u1", "conversaciones", "conv1"), {
        "usuario_id": "u1", "titulo": "conv larga", "mensajes": mensajes_previos
    })
    with patch("chat_controller.call_deepseek_api", return_value="ok") as mock_llamada:
        responder_tutor("Pregunta nueva", db=db, usuario_id="u1", chat_id="conv1")

    mensajes_enviados = mock_llamada.call_args.kwargs["messages"]
    historial_enviado = mensajes_enviados[1:-1]
    # Los 20 mensajes que caen fuera de la ventana de los últimos 30 no se
    # pierden sin más: se comprimen en un resumen que se antepone al
    # historial reciente (por eso hay 31 elementos, no 30).
    assert len(historial_enviado) == 31
    assert historial_enviado[0]["role"] == "system"
    assert "Resumen" in historial_enviado[0]["content"]
    assert historial_enviado[1]["content"] == "mensaje 20"
    assert historial_enviado[-1]["content"] == "mensaje 49"


def test_resumen_de_mensajes_antiguos_se_guarda_y_se_reutiliza(db):
    mensajes_previos = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"mensaje {i}"}
        for i in range(40)  # 40 - 30 = 10 mensajes fuera de ventana (justo un lote)
    ]
    db.sembrar(("conversaciones_IA", "u1", "conversaciones", "conv1"), {
        "usuario_id": "u1", "titulo": "conv larga", "mensajes": mensajes_previos
    })
    with patch("chat_controller.call_deepseek_api", side_effect=["Resumen de lo hablado", "respuesta final"]) as mock_llamada:
        responder_tutor("Pregunta nueva", db=db, usuario_id="u1", chat_id="conv1")

    primera_llamada_mensajes = mock_llamada.call_args_list[0].kwargs["messages"]
    assert "mensaje 0" in primera_llamada_mensajes[-1]["content"]

    conversacion = db.leer(("conversaciones_IA", "u1", "conversaciones", "conv1"))
    assert conversacion["resumen_antiguo"] == "Resumen de lo hablado"
    assert conversacion["resumen_cubre_mensajes"] == 10

    segunda_llamada_mensajes = mock_llamada.call_args_list[1].kwargs["messages"]
    assert segunda_llamada_mensajes[1]["role"] == "system"
    assert "Resumen de lo hablado" in segunda_llamada_mensajes[1]["content"]


def test_resumen_no_se_regenera_hasta_completar_un_lote_de_mensajes_nuevos(db):
    mensajes_previos = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"mensaje {i}"}
        for i in range(35)  # solo 5 mensajes fuera de ventana, por debajo del lote de 10
    ]
    db.sembrar(("conversaciones_IA", "u1", "conversaciones", "conv1"), {
        "usuario_id": "u1", "titulo": "conv larga", "mensajes": mensajes_previos,
        "resumen_antiguo": "Resumen ya guardado", "resumen_cubre_mensajes": 0
    })
    with patch("chat_controller.call_deepseek_api", return_value="respuesta") as mock_llamada:
        responder_tutor("Pregunta nueva", db=db, usuario_id="u1", chat_id="conv1")

    # Solo debe haberse llamado una vez (la respuesta), no para volver a
    # resumir -- el lote de mensajes nuevos fuera de ventana aún es pequeño.
    assert mock_llamada.call_count == 1
    mensajes_enviados = mock_llamada.call_args.kwargs["messages"]
    assert "Resumen ya guardado" in mensajes_enviados[1]["content"]


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


def test_ruta_tu_tutor_devuelve_502_si_deepseek_falla_y_no_gasta_cupo(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "premium", "subscription_status": "active"}}
    })
    parche_auth = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "u1@example.com"})
    parche_auth.start()
    try:
        with patch("chat_controller.call_deepseek_api", return_value=None):
            resp = client.post(
                "/tu-tutor",
                json={"mensaje": "Hola", "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"}
            )
        assert resp.status_code == 502
        assert "error" in resp.get_json()
        datos_usuario = db.leer(("usuarios", "u1"))
        assert (datos_usuario.get("limites_uso") or {}).get("chat_temario") is None
    finally:
        parche_auth.stop()


def _eventos_sse(cuerpo_respuesta):
    return [
        json.loads(linea[len("data: "):])
        for linea in cuerpo_respuesta.split("\n\n")
        if linea.startswith("data: ")
    ]


def test_ruta_tu_tutor_stream_emite_eventos_y_registra_uso(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "premium", "subscription_status": "active"}}
    })
    parche_auth = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "u1@example.com"})
    parche_auth.start()
    try:
        with patch("chat_controller.call_deepseek_api_stream", return_value=iter(["Hola ", "Mundo"])):
            resp = client.post(
                "/tu-tutor/stream",
                json={"mensaje": "Hola", "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"}
            )
        assert resp.status_code == 200
        eventos = _eventos_sse(resp.get_data(as_text=True))
        assert [e["tipo"] for e in eventos] == ["delta", "delta", "fin"]
        assert eventos[0]["texto"] == "Hola "
        assert eventos[1]["texto"] == "Mundo"
        assert eventos[2]["chat_id"]
        datos_usuario = db.leer(("usuarios", "u1"))
        assert datos_usuario["limites_uso"]["chat_temario"]["contador"] == 1
    finally:
        parche_auth.stop()


def test_ruta_tu_tutor_stream_no_registra_uso_si_deepseek_falla(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "premium", "subscription_status": "active"}}
    })
    parche_auth = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "u1@example.com"})
    parche_auth.start()
    try:
        with patch("chat_controller.call_deepseek_api_stream", return_value=iter([])):
            resp = client.post(
                "/tu-tutor/stream",
                json={"mensaje": "Hola", "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"}
            )
        assert resp.status_code == 200
        eventos = _eventos_sse(resp.get_data(as_text=True))
        assert eventos == [{"tipo": "error"}]
        # El uso se cobra por adelantado y, al fallar DeepSeek del todo, se
        # devuelve: el neto queda en 0 (no se consume cuota por un fallo
        # técnico, aunque el contador ya exista por el cobro+devolución).
        datos_usuario = db.leer(("usuarios", "u1"))
        assert datos_usuario["limites_uso"]["chat_temario"]["contador"] == 0
    finally:
        parche_auth.stop()


def test_ruta_eliminar_conversacion_borra_de_firestore(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "premium", "subscription_status": "active"}}
    })
    with patch("chat_controller.call_deepseek_api", return_value="Hola"):
        _texto, chat_id, _usar_rag = responder_tutor("Hola", db=db, usuario_id="u1")
    parche_auth = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "u1@example.com"})
    parche_auth.start()
    try:
        resp = client.delete(f"/conversacion/{chat_id}", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        assert db.leer(("conversaciones_IA", "u1", "conversaciones", chat_id)) is None
    finally:
        parche_auth.stop()


def test_ruta_eliminar_conversacion_inexistente_da_404(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "premium", "subscription_status": "active"}}
    })
    parche_auth = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": "u1", "email": "u1@example.com"})
    parche_auth.start()
    try:
        resp = client.delete("/conversacion/no-existe", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 404
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
