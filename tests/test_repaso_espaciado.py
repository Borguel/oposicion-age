"""Pruebas del repaso espaciado aplicado a los tests generados desde el
banco de preguntas falladas y desde el banco de favoritas (ver
banco_fallos.ordenar_por_prioridad_repaso y
banco_favoritas.ordenar_por_prioridad_repaso): en vez de un muestreo
puramente aleatorio, deben priorizarse las preguntas que de verdad hace
falta repasar ya."""
from datetime import datetime, timedelta

from banco_favoritas import _id_pregunta
from conftest import sembrar_usuario_activo


def _pregunta_base(texto, tema_id="b1-t1"):
    return {
        "oposicion": "AGE",
        "tema_id": tema_id,
        "pregunta": texto,
        "opciones": {"A": "x", "B": "y"},
        "respuesta_correcta": "A",
        "explicacion": "Explicación.",
    }


def test_generar_test_fallos_prioriza_la_mas_fallada(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    hace_poco = (datetime.utcnow() - timedelta(days=1)).isoformat()
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "poco_fallada"), dict(
        _pregunta_base("¿Poco fallada?"), veces_fallada=1, fecha_ultimo_fallo=hace_poco))
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "muy_fallada"), dict(
        _pregunta_base("¿Muy fallada?"), veces_fallada=5, fecha_ultimo_fallo=hace_poco))

    usuario_autenticado()
    resp = client.post("/generar-test-fallos?oposicion=AGE", json={"num_preguntas": 1},
                        headers={"Authorization": "Bearer x"})
    datos = resp.get_json()
    assert datos["total_disponibles"] == 2
    assert datos["test"][0]["pregunta"] == "¿Muy fallada?"


def test_generar_test_fallos_a_igualdad_prioriza_la_mas_antigua(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    hace_mucho = (datetime.utcnow() - timedelta(days=30)).isoformat()
    hace_poco = (datetime.utcnow() - timedelta(days=1)).isoformat()
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "reciente"), dict(
        _pregunta_base("¿Reciente?"), veces_fallada=2, fecha_ultimo_fallo=hace_poco))
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "antigua"), dict(
        _pregunta_base("¿Antigua?"), veces_fallada=2, fecha_ultimo_fallo=hace_mucho))

    usuario_autenticado()
    resp = client.post("/generar-test-fallos?oposicion=AGE", json={"num_preguntas": 1},
                        headers={"Authorization": "Bearer x"})
    datos = resp.get_json()
    assert datos["test"][0]["pregunta"] == "¿Antigua?"


def test_generar_test_fallos_num_preguntas_invalido_usa_el_valor_por_defecto(client, db, usuario_autenticado):
    """Bug real (25/08/2026, auditoría): a diferencia de las rutas hermanas
    (/generar-test-avanzado, /generar-test-oficial...), num_preguntas no se
    convertía a int ni se acotaba -- un valor no numérico (p.ej. un string
    mal formado desde el frontend) rompía el slice de la lista con un
    TypeError en vez de degradar al valor por defecto."""
    sembrar_usuario_activo(db, "u1", plan="basico")
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "f1"), _pregunta_base("¿Fallada?"))

    usuario_autenticado()
    resp = client.post("/generar-test-fallos?oposicion=AGE", json={"num_preguntas": "no-es-un-numero"},
                        headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert len(resp.get_json()["test"]) == 1


def test_generar_test_favoritas_prioriza_la_nunca_repasada(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    hace_poco = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    db.sembrar(("usuarios", "u1", "preguntas_favoritas", _id_pregunta("AGE", "¿Ya repasada?")), dict(
        _pregunta_base("¿Ya repasada?"), fecha_marcada=hace_poco, fecha_ultimo_repaso=hace_poco))
    db.sembrar(("usuarios", "u1", "preguntas_favoritas", _id_pregunta("AGE", "¿Nunca repasada?")), dict(
        _pregunta_base("¿Nunca repasada?"), fecha_marcada=hace_poco))

    usuario_autenticado()
    resp = client.post("/generar-test-favoritas?oposicion=AGE", json={"num_preguntas": 1},
                        headers={"Authorization": "Bearer x"})
    datos = resp.get_json()
    assert datos["total_disponibles"] == 2
    assert datos["test"][0]["pregunta"] == "¿Nunca repasada?"


def test_generar_test_favoritas_num_preguntas_invalido_usa_el_valor_por_defecto(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    db.sembrar(("usuarios", "u1", "preguntas_favoritas", _id_pregunta("AGE", "¿Favorita?")), _pregunta_base("¿Favorita?"))

    usuario_autenticado()
    resp = client.post("/generar-test-favoritas?oposicion=AGE", json={"num_preguntas": None},
                        headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert len(resp.get_json()["test"]) == 1


def test_preguntas_pendientes_repaso_cuenta_solo_la_oposicion_pedida(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico", suscripciones={
        "AGE": {"plan": "basico", "subscription_status": "active"},
        "GACE": {"plan": "basico", "subscription_status": "active"},
    })
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "age1"), _pregunta_base("¿AGE 1?", "b1-t1"))
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "age2"), _pregunta_base("¿AGE 2?", "b1-t1"))
    gace = dict(_pregunta_base("¿GACE 1?", "b1-t1"))
    gace["oposicion"] = "GACE"
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "gace1"), gace)

    usuario_autenticado()
    resp = client.get("/preguntas-pendientes-repaso?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert resp.get_json()["total_pendientes"] == 2

    resp_gace = client.get("/preguntas-pendientes-repaso?oposicion=GACE", headers={"Authorization": "Bearer x"})
    assert resp_gace.get_json()["total_pendientes"] == 1


def test_preguntas_pendientes_repaso_requiere_login(client):
    resp = client.get("/preguntas-pendientes-repaso?oposicion=AGE")
    assert resp.status_code == 401


def test_listar_preguntas_falladas_incluye_veces_fallada(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico")
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "muy_fallada"), dict(
        _pregunta_base("¿Muy fallada?"), veces_fallada=3))

    usuario_autenticado()
    resp = client.get("/preguntas-falladas?oposicion=AGE", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    falladas = resp.get_json()["falladas"]
    assert len(falladas) == 1
    assert falladas[0]["veces_fallada"] == 3


def test_listar_preguntas_falladas_no_se_mezclan_entre_oposiciones(client, db, usuario_autenticado):
    sembrar_usuario_activo(db, "u1", plan="basico", suscripciones={
        "AGE": {"plan": "basico", "subscription_status": "active"},
        "GACE": {"plan": "basico", "subscription_status": "active"},
    })
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "age1"), _pregunta_base("¿AGE?"))
    gace = dict(_pregunta_base("¿GACE?"))
    gace["oposicion"] = "GACE"
    db.sembrar(("usuarios", "u1", "preguntas_falladas", "gace1"), gace)

    usuario_autenticado()
    resp = client.get("/preguntas-falladas?oposicion=GACE", headers={"Authorization": "Bearer x"})
    falladas = resp.get_json()["falladas"]
    assert len(falladas) == 1
    assert falladas[0]["pregunta"] == "¿GACE?"


def test_generar_test_favoritas_no_marca_fecha_ultimo_repaso(client, db, usuario_autenticado):
    """Bug real (25/08/2026, auditoría): antes se marcaba como repasada ya al
    GENERAR el test -- si el usuario cerraba la pestaña o el guardado fallaba
    a mitad, la pregunta quedaba marcada como repasada sin haberse visto de
    verdad, y dejaba de priorizarse una temporada."""
    sembrar_usuario_activo(db, "u1", plan="basico")
    doc_id = _id_pregunta("AGE", "¿Nunca repasada?")
    db.sembrar(("usuarios", "u1", "preguntas_favoritas", doc_id), _pregunta_base("¿Nunca repasada?"))

    usuario_autenticado()
    resp = client.post("/generar-test-favoritas?oposicion=AGE", json={"num_preguntas": 1},
                        headers={"Authorization": "Bearer x"})
    assert resp.get_json()["total_disponibles"] == 1

    guardada = db.leer(("usuarios", "u1", "preguntas_favoritas", doc_id))
    assert not guardada.get("fecha_ultimo_repaso")


def test_guardar_test_favoritas_marca_fecha_ultimo_repaso(client, db, usuario_autenticado):
    """La fecha de último repaso se marca al GUARDAR el resultado del test
    (cuando de verdad se ha completado), no al generarlo -- mismo momento en
    que actualizar_banco_fallos actualiza el banco de falladas."""
    sembrar_usuario_activo(db, "u1", plan="basico")
    doc_id = _id_pregunta("AGE", "¿Nunca repasada?")
    db.sembrar(("usuarios", "u1", "preguntas_favoritas", doc_id), _pregunta_base("¿Nunca repasada?"))

    usuario_autenticado()
    resp = client.post("/guardar-test?oposicion=AGE", json={
        "contenido": [_pregunta_base("¿Nunca repasada?")],
        "respuestas": ["A"],
        "metadatos": {"tipo": "favoritas", "tiempo": 0},
    }, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200

    guardada = db.leer(("usuarios", "u1", "preguntas_favoritas", doc_id))
    assert guardada.get("fecha_ultimo_repaso")
