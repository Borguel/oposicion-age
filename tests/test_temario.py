"""Pruebas de blueprints/temario.py: catálogo de oposiciones y su
temario -- sin ningún test dedicado hasta ahora pese a ser la fuente que
usan Tu Tutor y el selector de temas del resto de la web."""

from conftest import sembrar_usuario_activo


def test_oposiciones_disponibles_no_requiere_login(client):
    resp = client.get("/oposiciones-disponibles")
    assert resp.status_code == 200
    # Sin sesión no hay forma de saber si tiene algo activado -- False.
    assert resp.get_json()["alguna_activada"] is False
    oposiciones = resp.get_json()["oposiciones"]
    ids = [o["id"] for o in oposiciones]
    assert "AGE" in ids
    assert "GACE" in ids
    # Formato real del simulacro oficial (para el botón "Simulacro oficial"
    # de un clic en /test-oficial/).
    por_id = {o["id"]: o for o in oposiciones}
    assert por_id["AGE"]["simulacro_oficial"] == {"num_preguntas": 70, "minutos": None}
    assert por_id["GACE"]["simulacro_oficial"] == {"num_preguntas": 100, "minutos": 90}
    assert por_id["AUXILIAR"]["simulacro_oficial"] == {"num_preguntas": 110, "minutos": 90}
    # Sin ningún examen oficial sembrado en el FakeFirestore de test, ninguna
    # oposición tiene datos para el reparto "realista" todavía.
    assert por_id["AGE"]["tiene_pesos_reales"] is False
    assert por_id["GACE"]["tiene_pesos_reales"] is False
    assert por_id["AUXILIAR"]["tiene_pesos_reales"] is False
    # Igual que con tiene_pesos_reales, sin ningún examen sembrado no hay
    # preguntas psicotécnicas para ninguna oposición.
    assert por_id["AGE"]["tiene_psicotecnicas"] is False
    assert por_id["AUXILIAR"]["tiene_psicotecnicas"] is False


def test_oposiciones_disponibles_marca_tiene_psicotecnicas_solo_donde_las_hay(client, db):
    db.sembrar(("examenes_oficiales_AUXILIAR", "p1"), {"tipo": "pregunta", "psicotecnico": True})
    db.sembrar(("examenes_oficiales_AGE", "a1"), {"tipo": "pregunta", "psicotecnico": False})
    resp = client.get("/oposiciones-disponibles")
    por_id = {o["id"]: o for o in resp.get_json()["oposiciones"]}
    assert por_id["AUXILIAR"]["tiene_psicotecnicas"] is True
    assert por_id["AGE"]["tiene_psicotecnicas"] is False


def test_oposiciones_disponibles_marca_tiene_pesos_reales_si_hay_examenes(client, db):
    db.sembrar(("examenes_oficiales_AGE", "p1"), {"tipo": "pregunta", "tema_id": "bloque_01-tema_01"})
    resp = client.get("/oposiciones-disponibles")
    por_id = {o["id"]: o for o in resp.get_json()["oposiciones"]}
    assert por_id["AGE"]["tiene_pesos_reales"] is True
    assert por_id["GACE"]["tiene_pesos_reales"] is False


def test_oposiciones_disponibles_no_incluye_ocultas_sin_sesion(client):
    resp = client.get("/oposiciones-disponibles")
    ids = [o["id"] for o in resp.get_json()["oposiciones"]]
    assert "METRO" not in ids


def test_oposiciones_disponibles_no_incluye_ocultas_sin_acceso_concedido(client, db, usuario_autenticado):
    usuario_autenticado(email_verified=True)
    sembrar_usuario_activo(db, "u1", plan="premium", oposicion="AGE")
    resp = client.get("/oposiciones-disponibles", headers={"Authorization": "Bearer x"})
    ids = [o["id"] for o in resp.get_json()["oposiciones"]]
    assert "METRO" not in ids


def test_oposiciones_disponibles_incluye_ocultas_si_usuario_tiene_suscripcion(client, db, usuario_autenticado):
    usuario_autenticado(email_verified=True)
    sembrar_usuario_activo(db, "u1", plan="premium", oposicion="METRO")
    resp = client.get("/oposiciones-disponibles", headers={"Authorization": "Bearer x"})
    datos = resp.get_json()
    por_id = {o["id"]: o for o in datos["oposiciones"]}
    assert "METRO" in por_id
    assert por_id["METRO"]["simulacro_oficial"] is None
    # Bug real (25/08/2026, reportado por un usuario): con SOLO una
    # oposición oculta activada (sin ninguna pública), alguna_activada
    # salía False -- Zona Opositor trataba la cuenta como nueva y mostraba
    # la pantalla de "elige tu oposición" (que ni siquiera ofrece METRO,
    # al ser oculta) en vez del panel normal con su oposición ya activada.
    assert datos["alguna_activada"] is True


def test_oposiciones_disponibles_con_sesion_pero_sin_activar_ninguna_muestra_las_publicas(client, db, usuario_autenticado):
    # Cuenta recién creada (sin ninguna entrada en suscripciones todavía):
    # se le sigue mostrando el catálogo público completo, para que pueda
    # elegir la primera (ver /activar-oposicion) -- no se queda sin ver
    # nada por no haber activado todavía.
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "suscripciones": {}})
    usuario_autenticado(email_verified=True)
    resp = client.get("/oposiciones-disponibles", headers={"Authorization": "Bearer x"})
    datos = resp.get_json()
    ids = {o["id"] for o in datos["oposiciones"]}
    assert ids == {"AGE", "GACE", "AUXILIAR"}
    # Bug real (11/08/2026): el frontend no puede distinguir "esto es el
    # catálogo para elegir" de "esto es lo que ya tienes" solo mirando
    # cuántas hay (aquí hay 3 en ambos casos) -- alguna_activada es la
    # señal explícita que hacía falta: False, porque no ha activado
    # ninguna de verdad todavía.
    assert datos["alguna_activada"] is False


def test_oposiciones_disponibles_solo_muestra_las_activadas_por_el_usuario(client, db, usuario_autenticado):
    # En cuanto ha activado AL MENOS una oposición pública, deja de verse
    # el catálogo completo: solo las que ha elegido de verdad, no las 3 a
    # la vez por defecto -- esto es justo lo que evita que una cuenta
    # nueva pueda usar las 3 pruebas gratuitas a la vez.
    sembrar_usuario_activo(db, "u1", plan="gratis", oposicion="AGE")
    usuario_autenticado(email_verified=True)
    resp = client.get("/oposiciones-disponibles", headers={"Authorization": "Bearer x"})
    datos = resp.get_json()
    ids = {o["id"] for o in datos["oposiciones"]}
    assert ids == {"AGE"}
    assert datos["alguna_activada"] is True


def test_activar_oposicion_requiere_login(client):
    resp = client.post("/activar-oposicion", json={"oposicion": "AGE"})
    assert resp.status_code == 401


def test_activar_oposicion_rechaza_oposicion_no_valida(client, usuario_autenticado):
    usuario_autenticado(email_verified=True)
    resp = client.post("/activar-oposicion", json={"oposicion": "NO_EXISTE"}, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 400


def test_activar_oposicion_crea_la_suscripcion_con_prueba(client, db, usuario_autenticado):
    usuario_autenticado(email_verified=True)
    resp = client.post("/activar-oposicion", json={"oposicion": "GACE"}, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    sub = db.leer(("usuarios", "u1"))["suscripciones"]["GACE"]
    assert sub["plan"] == "gratis"
    assert sub["prueba_fin"] is not None
    # Y a partir de ahora, la propia oposición activada aparece en el listado.
    usuario_autenticado(email_verified=True)
    ids = {o["id"] for o in client.get("/oposiciones-disponibles", headers={"Authorization": "Bearer x"}).get_json()["oposiciones"]}
    assert ids == {"GACE"}


def test_activar_oposicion_es_idempotente_via_ruta(client, db, usuario_autenticado):
    usuario_autenticado(email_verified=True)
    client.post("/activar-oposicion", json={"oposicion": "AGE"}, headers={"Authorization": "Bearer x"})
    fin_original = db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]["prueba_fin"]
    resp = client.post("/activar-oposicion", json={"oposicion": "AGE"}, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert db.leer(("usuarios", "u1"))["suscripciones"]["AGE"]["prueba_fin"] == fin_original


def test_temas_disponibles_requiere_login(client):
    resp = client.get("/temas-disponibles")
    assert resp.status_code == 401


def test_temas_disponibles_devuelve_bloque_y_tema(client, db, usuario_autenticado):
    db.collection("Temario AGE").document("bloque_01").set({"titulo": "Derecho constitucional"})
    db.collection("Temario AGE").document("bloque_01").collection("temas").document("tema_01").set({"titulo": "La Constitución"})
    sembrar_usuario_activo(db, "u1")

    usuario_autenticado(email_verified=True)
    resp = client.get("/temas-disponibles?oposicion=AGE", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 200
    datos = resp.get_json()
    assert datos["oposicion"] == "AGE"
    assert datos["temas"] == [{
        "id": "bloque_01-tema_01",
        "titulo": "La Constitución",
        "bloque_id": "bloque_01",
        "bloque_titulo": "Derecho constitucional",
    }]


def test_temas_disponibles_usa_la_coleccion_de_la_oposicion_pedida(client, db, usuario_autenticado):
    db.collection("Temario GACE").document("bloque_01").set({"titulo": "Bloque GACE"})
    db.collection("Temario GACE").document("bloque_01").collection("temas").document("tema_01").set({"titulo": "Tema GACE"})
    # AGE queda vacío a propósito -- si la ruta ignorase ?oposicion=GACE y
    # mirase siempre "Temario AGE", esto devolvería una lista vacía.
    sembrar_usuario_activo(db, "u1", oposicion="GACE")

    usuario_autenticado(email_verified=True)
    resp = client.get("/temas-disponibles?oposicion=GACE", headers={"Authorization": "Bearer x"})

    assert len(resp.get_json()["temas"]) == 1


def test_avisos_oficiales_requiere_login(client):
    resp = client.get("/avisos-oficiales?oposicion=AGE")
    assert resp.status_code == 401


def test_avisos_oficiales_devuelve_los_de_esa_oposicion(client, db, usuario_autenticado):
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposiciones": ["AGE"], "tipo": "convocatoria", "titulo": "Convocatoria AGE 2026",
        "estado": "publicado", "fecha_boe": "20260701",
    })
    db.sembrar(("avisos_oficiales", "a2"), {
        "oposiciones": ["GACE"], "tipo": "convocatoria", "titulo": "Convocatoria GACE 2026",
        "estado": "publicado", "fecha_boe": "20260702",
    })
    usuario_autenticado(email_verified=True)
    resp = client.get("/avisos-oficiales?oposicion=AGE", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 200
    avisos = resp.get_json()["avisos"]
    assert len(avisos) == 1
    assert avisos[0]["titulo"] == "Convocatoria AGE 2026"
    assert avisos[0]["id"] == "a1"


def test_avisos_oficiales_incluye_uno_que_afecta_a_varias_oposiciones(client, db, usuario_autenticado):
    # Regresión: un aviso guardado con "oposiciones": ["AGE", "GACE"] (el
    # nuevo formato, que permite publicar una vez para varias oposiciones)
    # tiene que seguir apareciendo para cada una de ellas por separado.
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposiciones": ["AGE", "GACE"], "tipo": "llamamiento_extraordinario",
        "titulo": "Llamamiento extraordinario (AGE y GACE)", "estado": "publicado", "fecha_boe": "20260701",
    })
    usuario_autenticado(email_verified=True)
    resp_age = client.get("/avisos-oficiales?oposicion=AGE", headers={"Authorization": "Bearer x"})
    resp_gace = client.get("/avisos-oficiales?oposicion=GACE", headers={"Authorization": "Bearer x"})

    assert len(resp_age.get_json()["avisos"]) == 1
    assert len(resp_gace.get_json()["avisos"]) == 1


def test_avisos_oficiales_ignora_los_de_otra_oposicion(client, db, usuario_autenticado):
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposiciones": ["AUXILIAR"], "tipo": "convocatoria", "titulo": "x", "estado": "publicado", "fecha_boe": "20260701",
    })
    usuario_autenticado(email_verified=True)
    resp = client.get("/avisos-oficiales?oposicion=AGE", headers={"Authorization": "Bearer x"})

    assert resp.get_json()["avisos"] == []


