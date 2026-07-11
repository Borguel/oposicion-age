"""Pruebas del generador de Test Personalizado con arquitectura
generar -> verificar -> reintentar (generador_preguntas_verificado.py).

Lo más importante a cubrir: que una pregunta que no pasa la verificación se
descarta ENTERA y se reintenta desde cero (nunca se "corrige"), que el
artículo se recupera del texto real y no lo inventa el modelo, y que
agotar los intentos no bloquea el resto del test."""
import itertools
import json
import threading
from unittest.mock import patch

from generador_preguntas_verificado import (
    _extraer_articulos,
    _elegir_ancla_legal,
    _generar_pregunta_verificada,
    generar_test_verificado,
)
from limites_uso import _clave_periodo


def _pregunta_valida(texto_pregunta="¿Pregunta de ejemplo?"):
    return json.dumps({
        "norma": "Ley 39/2015",
        "articulo": "Artículo 1",
        "tipo_pregunta": "memoria_literal",
        "pregunta": texto_pregunta,
        "opciones": {"A": "Opción a", "B": "Opción b", "C": "Opción c", "D": "Opción d"},
        "respuesta_correcta": "A",
        "explicacion": "Explicación suficientemente larga para superar la validación estructural.",
        "referencia_legal": "Artículo 1",
    })


def test_extraer_articulos_trocea_por_articulo_real():
    texto = (
        "Artículo 66. Las Cortes Generales representan al pueblo español.\n\n"
        "Artículo 67. Nadie podrá ser miembro de las dos Cámaras simultáneamente."
    )
    fragmentos = _extraer_articulos(texto)
    assert [f["articulo"] for f in fragmentos] == ["Artículo 66", "Artículo 67"]
    assert "Cortes Generales" in fragmentos[0]["texto"]
    assert "Cortes Generales" not in fragmentos[1]["texto"]
    assert "dos Cámaras" in fragmentos[1]["texto"]


def test_extraer_articulos_sin_cabeceras_degrada_a_texto_completo():
    texto = "Disposición adicional única. Esta norma no numera artículos de esta forma."
    fragmentos = _extraer_articulos(texto)
    assert len(fragmentos) == 1
    assert fragmentos[0]["articulo"] is None
    assert fragmentos[0]["texto"] == texto


def test_elegir_ancla_legal_evita_repetir_subbloques_ya_usados():
    subbloques = [
        {"etiqueta": "s1", "titulo": "Norma A", "texto": "Artículo 1. Contenido de la norma A."},
        {"etiqueta": "s2", "titulo": "Norma B", "texto": "Artículo 5. Contenido de la norma B."},
    ]
    anclas = _elegir_ancla_legal(subbloques, {"s1"}, necesita_dos=False)
    assert len(anclas) == 1
    assert anclas[0]["etiqueta_subbloque"] == "s2"


def test_elegir_ancla_legal_distincion_articulos_devuelve_dos_articulos_distintos():
    subbloques = [{
        "etiqueta": "s1", "titulo": "Norma A",
        "texto": "Artículo 1. Primer contenido.\n\nArtículo 2. Segundo contenido distinto."
    }]
    anclas = _elegir_ancla_legal(subbloques, set(), necesita_dos=True)
    assert len(anclas) == 2
    assert anclas[0]["articulo"] != anclas[1]["articulo"]


def test_pregunta_invalida_se_descarta_entera_y_se_regenera_desde_cero():
    subbloques_tema = [{
        "etiqueta": "bloque_01-tema_01-sub_1", "titulo": "Ley 39/2015",
        "texto": "Artículo 1. Contenido real de ejemplo para anclar la pregunta."
    }]
    with patch("generador_preguntas_verificado.call_deepseek_api", side_effect=[
        _pregunta_valida("¿Primer intento, con un dato mal?"),   # generación intento 1
        json.dumps({"valido": False, "problemas": ["el plazo citado no coincide con el texto"]}),  # verificación 1
        _pregunta_valida("¿Segundo intento, ya correcto?"),      # generación intento 2 (desde cero)
        json.dumps({"valido": True, "problemas": []}),           # verificación 2
    ]) as mock_llamada:
        resultado = _generar_pregunta_verificada(
            subbloques_tema, "bloque_01-tema_01", "AGE",
            subbloques_ya_usados=set(), preguntas_ya_aceptadas=set(), lock=threading.Lock()
        )

    assert mock_llamada.call_count == 4
    # La pregunta final es la del SEGUNDO intento, nunca una versión
    # "corregida" del primero -- el primer intento se descartó por completo.
    assert resultado["pregunta"] == "¿Segundo intento, ya correcto?"
    assert resultado["tema_id"] == "bloque_01-tema_01"


def test_agotar_los_intentos_devuelve_none_sin_bloquear():
    subbloques_tema = [{
        "etiqueta": "bloque_01-tema_01-sub_1", "titulo": "Ley 39/2015",
        "texto": "Artículo 1. Contenido real de ejemplo para anclar la pregunta."
    }]
    with patch("generador_preguntas_verificado.call_deepseek_api", side_effect=[
        _pregunta_valida("¿Intento 1?"), json.dumps({"valido": False, "problemas": ["x"]}),
        _pregunta_valida("¿Intento 2?"), json.dumps({"valido": False, "problemas": ["y"]}),
    ]) as mock_llamada:
        resultado = _generar_pregunta_verificada(
            subbloques_tema, "bloque_01-tema_01", "AGE",
            subbloques_ya_usados=set(), preguntas_ya_aceptadas=set(), lock=threading.Lock(),
            max_intentos=2
        )

    assert resultado is None
    assert mock_llamada.call_count == 4  # 2 intentos x (generar + verificar), nunca más


def _mock_deepseek_siempre_valido(contador, lock_contador):
    def _mock(messages, temperature=0.5, max_tokens=1000, response_format_json=False):
        contenido_usuario = messages[-1]["content"]
        if "PREGUNTA A VERIFICAR" in contenido_usuario:
            return json.dumps({"valido": True, "problemas": []})
        with lock_contador:
            n = next(contador)
        return _pregunta_valida(f"¿Pregunta única número {n}?")
    return _mock


def test_generar_test_verificado_reparte_cupo_y_reporta_progreso(db):
    # obtener_subbloques_individuales descarta subbloques de menos de 30
    # palabras (mismo filtro que ya usaba el generador anterior de Test
    # Personalizado), así que el texto de prueba tiene que ser lo bastante
    # largo para no quedar fuera antes de tiempo.
    relleno = " ".join(["palabra"] * 30)
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 39/2015", "texto": f"Artículo 1. Contenido del primer subbloque del tema 1. {relleno}"
    })
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_2"), {
        "titulo": "Ley 40/2015", "texto": f"Artículo 5. Contenido del segundo subbloque del tema 1. {relleno}"
    })
    db.sembrar(("Temario AGE", "bloque_02", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 19/2013", "texto": f"Artículo 3. Contenido del tema 2. {relleno}"
    })

    eventos_progreso = []
    contador = itertools.count()
    lock_contador = threading.Lock()
    with patch("generador_preguntas_verificado.call_deepseek_api",
               side_effect=_mock_deepseek_siempre_valido(contador, lock_contador)), \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        resultado = generar_test_verificado(
            db, temas=["bloque_01-tema_01", "bloque_02-tema_01"], num_preguntas=4,
            coleccion="Temario AGE", oposicion="AGE",
            on_progreso=lambda evento: eventos_progreso.append(evento)
        )

    assert len(resultado["test"]) == 4
    assert resultado["descartadas"] == 0
    assert "advertencia" not in resultado
    assert len(eventos_progreso) == 4
    assert [e["completadas"] for e in eventos_progreso] == [1, 2, 3, 4]
    assert eventos_progreso[-1]["total"] == 4
    # Cada evento de progreso lleva también la pregunta recién aceptada
    # (para que el llamante pueda ir entregándola sin esperar al final).
    assert all(e["pregunta"] is not None for e in eventos_progreso)
    assert {e["pregunta"]["pregunta"] for e in eventos_progreso} == {p["pregunta"] for p in resultado["test"]}
    # Cada pregunta generada sabe de qué tema salió de verdad.
    temas_de_las_preguntas = {p["tema_id"] for p in resultado["test"]}
    assert temas_de_las_preguntas == {"bloque_01-tema_01", "bloque_02-tema_01"}


def test_generar_test_verificado_modo_realista_pondera_por_bloque(db):
    relleno = " ".join(["palabra"] * 30)
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 39/2015", "texto": f"Artículo 1. Contenido del bloque 1. {relleno}"
    })
    db.sembrar(("Temario AGE", "bloque_06", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 40/2015", "texto": f"Artículo 5. Contenido del bloque 6. {relleno}"
    })
    # bloque_06 concentra el 90% de las preguntas históricas de examenes
    # oficiales -> con modo_reparto="realista" debe llevarse la mayoría del
    # cupo del test personalizado, no la mitad como haría "equitativo".
    db.sembrar(("examenes_oficiales_AGE", "b1-0"), {"tipo": "pregunta", "tema_id": "bloque_01-tema_01"})
    for i in range(9):
        db.sembrar(("examenes_oficiales_AGE", f"b6-{i}"), {"tipo": "pregunta", "tema_id": "bloque_06-tema_01"})

    contador = itertools.count()
    lock_contador = threading.Lock()
    with patch("generador_preguntas_verificado.call_deepseek_api",
               side_effect=_mock_deepseek_siempre_valido(contador, lock_contador)), \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        resultado = generar_test_verificado(
            db, temas=["bloque_01-tema_01", "bloque_06-tema_01"], num_preguntas=10,
            coleccion="Temario AGE", oposicion="AGE", modo_reparto="realista"
        )

    assert len(resultado["test"]) == 10
    temas_de_las_preguntas = [p["tema_id"] for p in resultado["test"]]
    assert temas_de_las_preguntas.count("bloque_06-tema_01") == 9
    assert temas_de_las_preguntas.count("bloque_01-tema_01") == 1


def test_generar_test_verificado_sin_temas_no_falla(db):
    resultado = generar_test_verificado(db, temas=[], num_preguntas=5, coleccion="Temario AGE", oposicion="AGE")
    assert resultado["test"] == []
    assert "advertencia" in resultado


def test_generar_test_verificado_sin_contenido_real_no_falla(db):
    resultado = generar_test_verificado(
        db, temas=["bloque_99-tema_99"], num_preguntas=5, coleccion="Temario AGE", oposicion="AGE"
    )
    assert resultado["test"] == []
    assert "advertencia" in resultado


# ============================================================
# Ruta /generar-test-avanzado en streaming (Server-Sent Events)
# ============================================================

def _eventos_sse(cuerpo_respuesta):
    return [
        json.loads(linea[len("data: "):])
        for linea in cuerpo_respuesta.split("\n\n")
        if linea.startswith("data: ")
    ]


def test_ruta_generar_test_avanzado_emite_eventos_y_registra_uso(client, db):
    relleno = " ".join(["palabra"] * 30)
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 39/2015", "texto": f"Artículo 1. Contenido real de prueba. {relleno}"
    })
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active"}}
    })
    parche_auth = patch("auth_utils.firebase_auth.verify_id_token",
                         return_value={"uid": "u1", "email": "u1@example.com"})
    parche_auth.start()
    try:
        contador = itertools.count()
        lock_contador = threading.Lock()
        with patch("generador_preguntas_verificado.call_deepseek_api",
                   side_effect=_mock_deepseek_siempre_valido(contador, lock_contador)), \
             patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
            resp = client.post(
                "/generar-test-avanzado",
                json={"temas": ["bloque_01-tema_01"], "num_preguntas": 2, "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"}
            )
            # El cuerpo hay que leerlo (drenar el generador SSE del todo)
            # TODAVÍA dentro del "with": la ruta lanza un hilo en segundo
            # plano que sigue llamando a call_deepseek_api mientras se
            # consume el stream, así que si se lee fuera del "with" el mock
            # ya se ha desactivado a medias y algunas llamadas usan la
            # función real (fallando por falta de red en el sandbox).
            cuerpo = resp.get_data(as_text=True)
        assert resp.status_code == 200
        eventos = _eventos_sse(cuerpo)
        assert eventos[-1]["tipo"] == "fin"
        assert len(eventos[-1]["test"]) == 2
        # También se han retransmitido eventos de progreso reales por el
        # camino, no solo el resultado final de golpe.
        assert any(e["tipo"] == "progreso" for e in eventos)
        # Y las preguntas aceptadas se retransmiten individualmente en
        # cuanto están listas, en un evento aparte -- para que el frontend
        # pueda empezar el test antes de que termine todo el streaming.
        eventos_pregunta = [e for e in eventos if e["tipo"] == "pregunta"]
        assert len(eventos_pregunta) == 2
        assert all("pregunta" in e and "opciones" in e["pregunta"] for e in eventos_pregunta)
        # El evento "progreso" no debe llevar la pregunta duplicada dentro.
        assert all("pregunta" not in e for e in eventos if e["tipo"] == "progreso")
        datos_usuario = db.leer(("usuarios", "u1"))
        assert datos_usuario["limites_uso"]["test_avanzado_verificado"]["contador"] == 1
    finally:
        parche_auth.stop()


def test_ruta_generar_test_avanzado_429_si_supera_el_limite(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active"}},
        "limites_uso": {"test_avanzado_verificado": {"periodo": _clave_periodo("mes"), "contador": 8}}
    })
    parche_auth = patch("auth_utils.firebase_auth.verify_id_token",
                         return_value={"uid": "u1", "email": "u1@example.com"})
    parche_auth.start()
    try:
        with patch("generador_preguntas_verificado.call_deepseek_api") as mock_llamada:
            resp = client.post(
                "/generar-test-avanzado",
                json={"temas": ["bloque_01-tema_01"], "num_preguntas": 2, "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"}
            )
        assert resp.status_code == 429
        mock_llamada.assert_not_called()
    finally:
        parche_auth.stop()


def test_ruta_generar_test_avanzado_bloqueada_para_plan_gratis(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "gratis"}}
    })
    parche_auth = patch("auth_utils.firebase_auth.verify_id_token",
                         return_value={"uid": "u1", "email": "u1@example.com"})
    parche_auth.start()
    try:
        resp = client.post(
            "/generar-test-avanzado",
            json={"temas": ["bloque_01-tema_01"], "num_preguntas": 2, "oposicion": "AGE"},
            headers={"Authorization": "Bearer x"}
        )
        assert resp.status_code == 403
    finally:
        parche_auth.stop()
