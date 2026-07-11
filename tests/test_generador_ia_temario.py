"""Pruebas de los generadores de test/esquema/análisis basados en el
TEMARIO oficial vía IA "libre" (sin anclaje verificado a un artículo real,
a diferencia de generador_preguntas_verificado.py -- ver ese módulo y
tests/test_generador_preguntas_verificado.py para /generar-test-avanzado).

Cubre: generar_preguntas_ia_en_lotes (test_generator.py, motor compartido
por /generar-test-inteligente y por generar-test-desde-pdf), y las rutas
/generar-esquema, /analisis-rendimiento y /generar-test-inteligente de
blueprints/test_ia.py."""
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

    def construir_prompt(n):
        llamadas.append(n)
        return f"pide {n}"

    with patch("test_generator.call_deepseek_api", side_effect=lambda **kw: _pregunta_json("¿P?")):
        preguntas, errores = generar_preguntas_ia_en_lotes(construir_prompt, 22, tamano_lote=15)

    assert sorted(llamadas) == [7, 15]  # 22 = 15 + 7, nunca un lote más grande que tamano_lote
    assert errores == []


def test_dedupe_por_texto_normalizado_entre_lotes():
    respuestas = [_pregunta_json("¿Cuál es la capital?"), _pregunta_json("¿cuál   es la capital?  ")]
    with patch("test_generator.call_deepseek_api", side_effect=respuestas):
        preguntas, errores = generar_preguntas_ia_en_lotes(lambda n: "prompt", 2, tamano_lote=1)

    assert len(preguntas) == 1  # la segunda es la misma pregunta con espacios/mayúsculas distintas


def test_lote_con_json_invalido_no_bloquea_los_demas():
    with patch("test_generator.call_deepseek_api", side_effect=["esto no es json", _pregunta_json("¿P2?")]):
        preguntas, errores = generar_preguntas_ia_en_lotes(lambda n: "prompt", 2, tamano_lote=1)

    assert len(preguntas) == 1
    assert preguntas[0]["pregunta"] == "¿P2?"
    assert len(errores) == 1


def test_on_progreso_se_llama_una_vez_por_lote():
    eventos_progreso = []
    with patch("test_generator.call_deepseek_api", side_effect=lambda **kw: _pregunta_json("¿P?")):
        generar_preguntas_ia_en_lotes(
            lambda n: "prompt", 22, tamano_lote=15,
            on_progreso=lambda evento: eventos_progreso.append(evento)
        )

    # 22 preguntas con tamano_lote=15 -> 2 lotes (15 + 7), un evento por lote.
    assert len(eventos_progreso) == 2
    assert {e["total"] for e in eventos_progreso} == {2}
    assert sorted(e["completadas"] for e in eventos_progreso) == [1, 2]


def test_lote_sin_respuesta_de_deepseek_se_reporta_como_error():
    with patch("test_generator.call_deepseek_api", return_value=None):
        preguntas, errores = generar_preguntas_ia_en_lotes(lambda n: "prompt", 3, tamano_lote=3)

    assert preguntas == []
    assert len(errores) == 1


# ============================================================
# /generar-esquema
# ============================================================

def test_ruta_generar_esquema_devuelve_resultado_y_registra_uso(client, db):
    _usuario_basico(db)
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01"), {"titulo": "Un tema"})
    parche = _con_sesion(client)
    try:
        with patch("blueprints.test_ia.generar_esquema", return_value="# Esquema\n- punto 1") as mock_esquema:
            resp = client.post(
                "/generar-esquema",
                json={"temas": ["bloque_01-tema_01"], "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"}
            )
        assert resp.status_code == 200
        assert resp.get_json()["esquema"] == "# Esquema\n- punto 1"
        mock_esquema.assert_called_once()
        datos_usuario = db.leer(("usuarios", "u1"))
        assert datos_usuario["limites_uso"]["generacion_ia"]["contador"] == 1
    finally:
        parche.stop()


def test_ruta_generar_esquema_sin_json_devuelve_400(client, db):
    _usuario_basico(db)
    parche = _con_sesion(client)
    try:
        resp = client.post("/generar-esquema", data="no es json", content_type="text/plain",
                            headers={"Authorization": "Bearer x"})
        assert resp.status_code == 400
    finally:
        parche.stop()


def test_ruta_generar_esquema_bloqueada_para_plan_gratis(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "suscripciones": {"AGE": {"plan": "gratis"}}})
    parche = _con_sesion(client)
    try:
        with patch("blueprints.test_ia.generar_esquema") as mock_esquema:
            resp = client.post("/generar-esquema", json={"temas": ["bloque_01-tema_01"], "oposicion": "AGE"},
                                headers={"Authorization": "Bearer x"})
        assert resp.status_code == 403
        mock_esquema.assert_not_called()
    finally:
        parche.stop()


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
        assert datos_usuario["limites_uso"]["generacion_ia"]["contador"] == 1
    finally:
        parche.stop()


# ============================================================
# /generar-test-inteligente
# ============================================================

def test_ruta_generar_test_inteligente_devuelve_preguntas_barajadas(client, db):
    _usuario_basico(db)
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01"), {"titulo": "Un tema"})
    parche = _con_sesion(client)
    try:
        with patch("test_generator.call_deepseek_api",
                    side_effect=lambda **kw: _pregunta_json("¿Pregunta generada?")):
            resp = client.post(
                "/generar-test-inteligente",
                json={"temas": ["bloque_01-tema_01"], "num_preguntas": 1, "oposicion": "AGE"},
                headers={"Authorization": "Bearer x"}
            )
        assert resp.status_code == 200
        test = resp.get_json()["test"]
        assert len(test) == 1
        assert set(test[0]["opciones"].keys()) == {"A", "B", "C", "D"}
    finally:
        parche.stop()


def test_ruta_generar_test_inteligente_sin_temas_devuelve_400(client, db):
    _usuario_basico(db)
    parche = _con_sesion(client)
    try:
        resp = client.post("/generar-test-inteligente", json={"temas": [], "oposicion": "AGE"},
                            headers={"Authorization": "Bearer x"})
        assert resp.status_code == 400
    finally:
        parche.stop()
