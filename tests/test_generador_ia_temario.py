"""Pruebas de los generadores de test/análisis basados en el TEMARIO
oficial vía IA "libre" (sin anclaje verificado a un artículo real, a
diferencia de generador_preguntas_verificado.py -- ver ese módulo y
tests/test_generador_preguntas_verificado.py para /generar-test-avanzado).

Cubre: generar_preguntas_ia_en_lotes (test_generator.py, motor compartido
con generar-test-desde-pdf), y la ruta /analisis-rendimiento de
blueprints/test_ia.py."""
import itertools
import json
from unittest.mock import patch

from test_generator import generar_preguntas_ia_en_lotes


def _con_sesion(cliente, uid="u1", email="u1@example.com"):
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email})
    parche.start()
    return parche


def _usuario_basico(db, uid="u1"):
    db.sembrar(("usuarios", uid), {
        "email": f"{uid}@example.com",
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active"}}
    })


def _pregunta_json(texto):
    return json.dumps([{
        "pregunta": texto,
        "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"},
        "respuesta_correcta": "A",
        "explicacion": "A) correcta porque sí. B) incorrecta. C) incorrecta. D) incorrecta.",
    }])


# ============================================================
# generar_preguntas_ia_en_lotes (test_generator.py)
# ============================================================

def test_pide_en_lotes_de_como_mucho_tamano_lote():
    llamadas = []
    contador = itertools.count()

    def construir_prompt(n):
        llamadas.append(n)
        return f"pide {n}"

    def fake_call(**kw):
        # Cada lote genera tantas preguntas (únicas) como se le pidieron --
        # así se completan las 22 solicitadas sin necesitar relleno, que no
        # es lo que este test quiere comprobar (ver test_relleno_completa_*
        # más abajo para eso).
        n = int(kw["messages"][0]["content"].split()[-1])
        return json.dumps([
            {"pregunta": f"¿P{next(contador)}?", "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"},
             "respuesta_correcta": "A", "explicacion": "..."}
            for _ in range(n)
        ])

    with patch("test_generator.call_deepseek_api", side_effect=fake_call):
        preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, 22, tamano_lote=15)

    assert sorted(llamadas) == [7, 15]  # 22 = 15 + 7, nunca un lote más grande que tamano_lote
    assert errores == []


def test_dedupe_por_texto_normalizado_entre_lotes():
    # La primera respuesta usa mayúsculas/espacios distintos a la segunda
    # (misma pregunta normalizada); cualquier llamada extra -- incluido el
    # relleno que ahora intenta cerrar el hueco que deja la duplicada --
    # repite la misma pregunta normalizada, así que nunca se libera del
    # dedup y el resultado final sigue siendo 1 sola.
    respuestas = iter([_pregunta_json("¿Cuál es la capital?")])

    def fake_call(**kw):
        try:
            return next(respuestas)
        except StopIteration:
            return _pregunta_json("¿cuál   es la capital?  ")

    with patch("test_generator.call_deepseek_api", side_effect=fake_call):
        preguntas, errores = generar_preguntas_ia_en_lotes(lambda n: "prompt", 2, tamano_lote=1)

    assert len(preguntas) == 1  # la segunda es la misma pregunta con espacios/mayúsculas distintas


def test_lote_con_json_invalido_no_bloquea_los_demas():
    contador = itertools.count()

    def fake_call(**kw):
        if next(contador) == 0:
            return "esto no es json"
        return _pregunta_json("¿P2?")

    with patch("test_generator.call_deepseek_api", side_effect=fake_call):
        preguntas, errores = generar_preguntas_ia_en_lotes(lambda n: "prompt", 2, tamano_lote=1)

    assert len(preguntas) == 1
    assert preguntas[0]["pregunta"] == "¿P2?"
    # El error del lote con JSON inválido, más el aviso de que el relleno
    # tampoco pudo completar el hueco (todos sus intentos repiten "¿P2?",
    # ya aceptada) -- 2 en total, no 1.
    assert len(errores) == 2


def test_on_progreso_se_llama_una_vez_por_pregunta():
    # Con num_preguntas=2 y tamano_lote=1 hay 2 lotes, cada uno con su
    # propia candidata única -- se completan las 2 sin relleno, y "total"
    # debe ser num_preguntas (2), no el número de lotes -- ver
    # test_test_generator.py para el mismo contrato con verificación
    # (texto_fuente) activada.
    eventos_progreso = []
    contador = itertools.count()
    with patch("test_generator.call_deepseek_api", side_effect=lambda **kw: _pregunta_json(f"¿P{next(contador)}?")):
        generar_preguntas_ia_en_lotes(
            lambda n: "prompt", 2, tamano_lote=1,
            on_progreso=lambda evento: eventos_progreso.append(evento)
        )

    assert len(eventos_progreso) == 2
    assert {e["total"] for e in eventos_progreso} == {2}
    assert sorted(e["completadas"] for e in eventos_progreso) == [1, 2]


def test_lote_sin_respuesta_de_deepseek_se_reporta_como_error():
    with patch("test_generator.call_deepseek_api", return_value=None):
        preguntas, errores = generar_preguntas_ia_en_lotes(lambda n: "prompt", 3, tamano_lote=3)

    assert preguntas == []
    # El error del lote sin respuesta, más el aviso de que el relleno
    # tampoco pudo completar ninguna de las 3 (misma falta de respuesta).
    assert len(errores) == 2


# ============================================================
# /analisis-rendimiento
# ============================================================

def test_ruta_analisis_rendimiento_sin_datos_suficientes_no_llama_a_la_ia(client, db):
    _usuario_basico(db)
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active"}},
        "estadisticas": {"AGE": {"rendimiento_por_tema": {}}}
    })
    parche = _con_sesion(client)
    try:
        with patch("blueprints.test_ia.call_deepseek_api") as mock_ia:
            resp = client.get("/analisis-rendimiento?oposicion=AGE", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        assert resp.get_json()["analisis"] is None
        mock_ia.assert_not_called()
    finally:
        parche.stop()


def test_ruta_analisis_rendimiento_con_datos_suficientes_devuelve_texto(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active"}},
        "estadisticas": {"AGE": {"rendimiento_por_tema": {
            "bloque_01-tema_01": {"aciertos": 8, "fallos": 2, "blancos": 0},
            "bloque_01-tema_02": {"aciertos": 1, "fallos": 9, "blancos": 0},
        }}}
    })
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01"), {"titulo": "Tema fuerte"})
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_02"), {"titulo": "Tema flojo"})
    parche = _con_sesion(client)
    try:
        with patch("blueprints.test_ia.call_deepseek_api", return_value="Vas muy bien en Tema fuerte, refuerza Tema flojo.") as mock_ia:
            resp = client.get("/analisis-rendimiento?oposicion=AGE", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        assert "Tema flojo" in resp.get_json()["analisis"]
        mock_ia.assert_called_once()
        datos_usuario = db.leer(("usuarios", "u1"))
        assert datos_usuario["limites_uso"]["analisis_ia"]["mes"]["contador"] == 1
    finally:
        parche.stop()
