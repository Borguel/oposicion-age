"""Pruebas del generador de Test Oficial (banco de preguntas de exámenes
reales ya cargados en Firestore, sin llamar a ninguna IA) y del reparto
por cuotas que comparte con el Test Personalizado verificado."""
from unittest.mock import patch

from utils import repartir_cupos_por_tema, seleccionar_preguntas_con_cuota


def _con_sesion(cliente, uid="u1", email="u1@example.com"):
    parche = patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email})
    parche.start()
    return parche


def _pregunta(numero, tema_id, examen="AGE 2025 - Ejercicio único (ingreso libre)"):
    return {
        "pregunta": f"Pregunta {numero}",
        "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"},
        "respuesta_correcta": "A",
        "explicacion": "porque sí",
        "examen": examen,
        "numero": numero,
        "tema_id": tema_id,
    }


# ============================================================
# repartir_cupos_por_tema / seleccionar_preguntas_con_cuota (utils.py)
# ============================================================

def test_repartir_cupos_reparte_el_resto_sin_perder_unidades():
    cupos = repartir_cupos_por_tema(["t1", "t2", "t3"], 10)
    assert sum(cupos.values()) == 10
    assert set(cupos.keys()) == {"t1", "t2", "t3"}
    # división entera 10/3 = 3, resto 1 -> como mucho un tema con 4, el resto con 3
    assert sorted(cupos.values()) == [3, 3, 4]


def test_repartir_cupos_sin_temas_devuelve_vacio():
    assert repartir_cupos_por_tema([], 10) == {}


def test_seleccionar_sin_filtro_de_tema_es_muestreo_simple():
    preguntas = [_pregunta(i, "b1-t1") for i in range(20)]
    seleccionadas = seleccionar_preguntas_con_cuota(preguntas, 5, temas_filtro=None)
    assert len(seleccionadas) == 5
    # todas vienen del conjunto original, sin inventarse nada
    numeros_originales = {p["numero"] for p in preguntas}
    assert all(p["numero"] in numeros_originales for p in seleccionadas)


def test_seleccionar_con_filtro_reparte_equitativamente_entre_temas():
    preguntas = [_pregunta(i, "b1-t1") for i in range(10)] + [_pregunta(100 + i, "b1-t2") for i in range(10)]
    seleccionadas = seleccionar_preguntas_con_cuota(preguntas, 6, temas_filtro=["b1-t1", "b1-t2"])
    assert len(seleccionadas) == 6
    por_tema = {}
    for p in seleccionadas:
        por_tema[p["tema_id"]] = por_tema.get(p["tema_id"], 0) + 1
    assert por_tema == {"b1-t1": 3, "b1-t2": 3}


def test_seleccionar_redistribuye_cupo_cuando_un_tema_se_queda_corto():
    # Solo hay 2 preguntas de t1 pero se piden 8 preguntas entre t1 y t2:
    # el cupo que t1 no puede cubrir debe recaer sobre t2, no perderse.
    preguntas = [_pregunta(i, "b1-t1") for i in range(2)] + [_pregunta(100 + i, "b1-t2") for i in range(10)]
    seleccionadas = seleccionar_preguntas_con_cuota(preguntas, 8, temas_filtro=["b1-t1", "b1-t2"])
    assert len(seleccionadas) == 8
    por_tema = {}
    for p in seleccionadas:
        por_tema[p["tema_id"]] = por_tema.get(p["tema_id"], 0) + 1
    assert por_tema["b1-t1"] == 2  # todo lo que había, ni una menos
    assert por_tema["b1-t2"] == 6  # el resto del cupo recae aquí


def test_seleccionar_ignora_temas_sin_preguntas_disponibles():
    preguntas = [_pregunta(i, "b1-t1") for i in range(5)]
    seleccionadas = seleccionar_preguntas_con_cuota(preguntas, 3, temas_filtro=["b1-t1", "b1-t9-inexistente"])
    assert len(seleccionadas) == 3
    assert all(p["tema_id"] == "b1-t1" for p in seleccionadas)


# ============================================================
# /generar-test-oficial
# ============================================================

def test_ruta_generar_test_oficial_devuelve_preguntas_de_firestore(client, db):
    for i in range(5):
        db.sembrar(("examenes_oficiales_AGE", f"age_2025_eu_{i:03d}"), {
            "tipo": "pregunta", **_pregunta(i, "bloque_01-tema_01")
        })
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active"}}
    })
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/generar-test-oficial",
            json={"num_preguntas": 3, "oposicion": "AGE"},
            headers={"Authorization": "Bearer x"}
        )
        assert resp.status_code == 200
        test = resp.get_json()["test"]
        assert len(test) == 3
        # las opciones se normalizan siempre a mayúsculas
        assert set(test[0]["opciones"].keys()) == {"A", "B", "C", "D"}
    finally:
        parche.stop()


def test_ruta_generar_test_oficial_filtra_por_examen(client, db):
    db.sembrar(("examenes_oficiales_AGE", "a1"), {
        "tipo": "pregunta", **_pregunta(1, "bloque_01-tema_01", examen="AGE 2022 - Ejercicio único (ingreso libre)")
    })
    db.sembrar(("examenes_oficiales_AGE", "a2"), {
        "tipo": "pregunta", **_pregunta(2, "bloque_01-tema_01", examen="AGE 2025 - Ejercicio único (ingreso libre)")
    })
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active"}}
    })
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/generar-test-oficial",
            json={"num_preguntas": 10, "oposicion": "AGE", "examenes": ["AGE 2022 - Ejercicio único (ingreso libre)"]},
            headers={"Authorization": "Bearer x"}
        )
        test = resp.get_json()["test"]
        assert len(test) == 1
        assert test[0]["numero"] == 1
    finally:
        parche.stop()


def test_ruta_generar_test_oficial_modo_realista_pondera_por_bloque(client, db):
    # bloque_06 tiene muchas más preguntas históricas cargadas que
    # bloque_01, así que con modo_reparto=realista debe llevarse la
    # mayoría de las preguntas del test aunque se filtre por ambos temas.
    for i in range(2):
        db.sembrar(("examenes_oficiales_AGE", f"b1-{i}"), {"tipo": "pregunta", **_pregunta(i, "bloque_01-tema_01")})
    for i in range(18):
        db.sembrar(("examenes_oficiales_AGE", f"b6-{i}"), {"tipo": "pregunta", **_pregunta(100 + i, "bloque_06-tema_01")})
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active"}}
    })
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/generar-test-oficial",
            json={
                "num_preguntas": 10, "oposicion": "AGE",
                "temas": ["bloque_01-tema_01", "bloque_06-tema_01"],
                "modo_reparto": "realista",
            },
            headers={"Authorization": "Bearer x"}
        )
        assert resp.status_code == 200
        test = resp.get_json()["test"]
        assert len(test) == 10
        de_bloque_06 = sum(1 for p in test if p["tema_id"] == "bloque_06-tema_01")
        # 18 de 20 preguntas históricas son de bloque_06 -> 90% de peso.
        assert de_bloque_06 == 9
    finally:
        parche.stop()


def test_ruta_generar_test_oficial_modo_reparto_invalido_cae_a_equitativo(client, db):
    for i in range(10):
        db.sembrar(("examenes_oficiales_AGE", f"b1-{i}"), {"tipo": "pregunta", **_pregunta(i, "bloque_01-tema_01")})
    for i in range(10):
        db.sembrar(("examenes_oficiales_AGE", f"b2-{i}"), {"tipo": "pregunta", **_pregunta(100 + i, "bloque_02-tema_01")})
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active"}}
    })
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/generar-test-oficial",
            json={
                "num_preguntas": 6, "oposicion": "AGE",
                "temas": ["bloque_01-tema_01", "bloque_02-tema_01"],
                "modo_reparto": "esto-no-existe",
            },
            headers={"Authorization": "Bearer x"}
        )
        test = resp.get_json()["test"]
        por_tema = {}
        for p in test:
            por_tema[p["tema_id"]] = por_tema.get(p["tema_id"], 0) + 1
        assert por_tema == {"bloque_01-tema_01": 3, "bloque_02-tema_01": 3}
    finally:
        parche.stop()


def test_ruta_generar_test_oficial_excluye_psicotecnicas_si_se_pide(client, db):
    for i in range(5):
        db.sembrar(("examenes_oficiales_AUXILIAR", f"c{i:03d}"), {
            "tipo": "pregunta", **_pregunta(i, "bloque_01-tema_01", examen="AUXILIAR 2025 - Ejercicio único (ingreso libre)"),
            "psicotecnico": False,
        })
    for i in range(5):
        db.sembrar(("examenes_oficiales_AUXILIAR", f"p{i:03d}"), {
            "tipo": "pregunta", **_pregunta(100 + i, "", examen="AUXILIAR 2025 - Ejercicio único (ingreso libre)"),
            "psicotecnico": True,
        })
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AUXILIAR": {"plan": "basico", "subscription_status": "active"}}
    })
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/generar-test-oficial",
            json={"num_preguntas": 10, "oposicion": "AUXILIAR", "excluir_psicotecnicas": True},
            headers={"Authorization": "Bearer x"}
        )
        assert resp.status_code == 200
        test = resp.get_json()["test"]
        assert len(test) == 5
        assert all(not p["psicotecnico"] for p in test)
    finally:
        parche.stop()


def test_ruta_generar_test_oficial_incluye_psicotecnicas_por_defecto(client, db):
    db.sembrar(("examenes_oficiales_AUXILIAR", "p001"), {
        "tipo": "pregunta", **_pregunta(1, "", examen="AUXILIAR 2025 - Ejercicio único (ingreso libre)"),
        "psicotecnico": True,
    })
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AUXILIAR": {"plan": "basico", "subscription_status": "active"}}
    })
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/generar-test-oficial",
            json={"num_preguntas": 5, "oposicion": "AUXILIAR"},
            headers={"Authorization": "Bearer x"}
        )
        assert resp.status_code == 200
        test = resp.get_json()["test"]
        assert len(test) == 1
        assert test[0]["psicotecnico"] is True
    finally:
        parche.stop()


def test_ruta_generar_test_oficial_404_si_no_hay_preguntas_cargadas(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"GACE": {"plan": "basico", "subscription_status": "active"}}
    })
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/generar-test-oficial",
            json={"num_preguntas": 5, "oposicion": "GACE"},
            headers={"Authorization": "Bearer x"}
        )
        assert resp.status_code == 404
        assert resp.get_json()["test"] == []
    finally:
        parche.stop()


def test_ruta_generar_test_oficial_bloqueada_para_plan_gratis(client, db):
    db.sembrar(("examenes_oficiales_AGE", "a1"), {"tipo": "pregunta", **_pregunta(1, "bloque_01-tema_01")})
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "gratis"}}
    })
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/generar-test-oficial",
            json={"num_preguntas": 5, "oposicion": "AGE"},
            headers={"Authorization": "Bearer x"}
        )
        assert resp.status_code == 403
    finally:
        parche.stop()


# ============================================================
# /guardar-test-oficial
# ============================================================

def test_ruta_guardar_test_oficial_guarda_el_resultado(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/guardar-test-oficial",
            json={"contenido": [_pregunta(1, "bloque_01-tema_01")], "respuestas": {"0": "A"}, "metadatos": {"examen": "AGE 2025"}},
            headers={"Authorization": "Bearer x"}
        )
        assert resp.status_code == 200
        guardados = list(db.collection("test_oficiales").stream())
        assert len(guardados) == 1
        assert guardados[0].to_dict()["usuario_id"] == "u1"
    finally:
        parche.stop()


def test_ruta_guardar_test_oficial_400_si_faltan_datos(client, db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    parche = _con_sesion(client)
    try:
        resp = client.post(
            "/guardar-test-oficial",
            json={"contenido": [_pregunta(1, "bloque_01-tema_01")]},  # falta "respuestas"
            headers={"Authorization": "Bearer x"}
        )
        assert resp.status_code == 400
    finally:
        parche.stop()


def test_ruta_guardar_test_oficial_requiere_login(client, db):
    resp = client.post(
        "/guardar-test-oficial",
        json={"contenido": [_pregunta(1, "bloque_01-tema_01")], "respuestas": {"0": "A"}},
    )
    assert resp.status_code == 401
