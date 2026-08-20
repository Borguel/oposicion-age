"""Prueba que /guardar-test NO se fía de la "respuesta_correcta" que manda
el cliente para los tests "oficial"/"psicotécnico"/"personalizado": la
recalcula contra el banco real de Firestore (ver
guardar_resultado._corregir_con_banco_verificado).

Sin esto, cualquiera podía guardar un test con una respuesta_correcta
fabricada para sacar siempre nota máxima -- las estadísticas y el ranking
público se calculan a partir de este resultado (hallazgo C2 de la auditoría
de seguridad, docs/auditoria-seguridad-agosto-2026.md). Personalizado se
verifica desde 18/08/2026 contra banco_preguntas_ia_<oposicion>, donde
generador_preguntas_verificado.py ya guarda cada pregunta que genera."""


from conftest import sembrar_usuario_activo
from oposiciones import coleccion_psicotecnico


def _guardar_y_leer_resultado(client, oposicion, contenido, respuestas, tipo_test):
    resp = client.post(
        f"/guardar-test?oposicion={oposicion}",
        json={
            "contenido": contenido,
            "respuestas": respuestas,
            "metadatos": {"tipo": tipo_test, "tiempo": 0},
        },
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 200
    listado = client.get(
        f"/mis-tests?oposicion={oposicion}", headers={"Authorization": "Bearer x"}
    ).get_json()
    assert len(listado["tests"]) == 1
    return listado["tests"][0]


def test_test_oficial_ignora_respuesta_correcta_fabricada_por_el_cliente(client, db, usuario_autenticado):
    """La pregunta real tiene "A" como respuesta correcta. El cliente manda
    "B" (su propia elección) como respuesta_correcta Y como respuesta
    elegida -- si el servidor se fiara del payload, esto puntuaría como
    acierto. Debe puntuar como fallo, porque la respuesta real es "A"."""
    sembrar_usuario_activo(db, "u1", plan="basico")
    db.sembrar(
        ("examenes_oficiales_AGE", "p1"),
        {
            "tipo": "pregunta",
            "pregunta": "¿Capital de España?",
            "opciones": {"A": "Madrid", "B": "Barcelona"},
            "respuesta_correcta": "A",
            "activa": True,
        },
    )
    usuario_autenticado()
    contenido = [
        {
            "pregunta": "¿Capital de España?",
            "opciones": {"A": "Madrid", "B": "Barcelona"},
            "respuesta_correcta": "B",  # fabricada por el cliente
        }
    ]
    resultado = _guardar_y_leer_resultado(client, "AGE", contenido, ["B"], "oficial")
    assert resultado["aciertos"] == 0
    assert resultado["fallos"] == 1


def test_test_oficial_con_respuesta_correcta_real_sigue_puntuando_acierto(client, db, usuario_autenticado):
    """Caso normal (sin manipular nada): la respuesta_correcta que manda un
    cliente honesto coincide con el banco real, así que sigue puntuando
    igual que antes."""
    sembrar_usuario_activo(db, "u1", plan="basico")
    db.sembrar(
        ("examenes_oficiales_AGE", "p1"),
        {
            "tipo": "pregunta",
            "pregunta": "¿Capital de España?",
            "opciones": {"A": "Madrid", "B": "Barcelona"},
            "respuesta_correcta": "A",
            "activa": True,
        },
    )
    usuario_autenticado()
    contenido = [
        {
            "pregunta": "¿Capital de España?",
            "opciones": {"A": "Madrid", "B": "Barcelona"},
            "respuesta_correcta": "A",
        }
    ]
    resultado = _guardar_y_leer_resultado(client, "AGE", contenido, ["A"], "oficial")
    assert resultado["aciertos"] == 1
    assert resultado["fallos"] == 0


def test_test_oficial_pregunta_no_encontrada_en_banco_no_rompe_el_guardado(client, db, usuario_autenticado):
    """Si la pregunta ya no está en el banco (se borró/editó entre generar
    y corregir el test), no se debe bloquear ni fallar el guardado -- se
    deja la respuesta_correcta tal cual la mandó el cliente para ESA
    pregunta en concreto."""
    sembrar_usuario_activo(db, "u1", plan="basico")
    usuario_autenticado()
    contenido = [
        {
            "pregunta": "Pregunta que ya no existe en el banco",
            "opciones": {"A": "x", "B": "y"},
            "respuesta_correcta": "A",
        }
    ]
    resultado = _guardar_y_leer_resultado(client, "AGE", contenido, ["A"], "oficial")
    assert resultado["aciertos"] == 1


def test_test_psicotecnico_tambien_ignora_respuesta_correcta_fabricada(client, db, usuario_autenticado):
    coleccion = coleccion_psicotecnico("METRO")
    sembrar_usuario_activo(db, "u1", plan="basico", oposicion="METRO")
    db.sembrar(
        (coleccion, "p1"),
        {
            "pregunta": "Serie: 2, 4, 6, ¿?",
            "opciones": {"A": "8", "B": "9"},
            "respuesta_correcta": "A",
            "activa": True,
        },
    )
    usuario_autenticado()
    contenido = [
        {
            "pregunta": "Serie: 2, 4, 6, ¿?",
            "opciones": {"A": "8", "B": "9"},
            "respuesta_correcta": "B",  # fabricada
        }
    ]
    resultado = _guardar_y_leer_resultado(client, "METRO", contenido, ["B"], "psicotecnico")
    assert resultado["aciertos"] == 0
    assert resultado["fallos"] == 1


def test_test_personalizado_ignora_respuesta_correcta_fabricada_por_el_cliente(client, db, usuario_autenticado):
    """La pregunta ya se generó y se guardó (verificada) en
    banco_preguntas_ia_AGE con "A" como respuesta correcta -- ver
    generador_preguntas_verificado.guardar_pregunta_generada. El cliente
    manda "B" al guardar el resultado -- si el servidor se fiara del
    payload, esto puntuaría como acierto. Debe puntuar como fallo."""
    sembrar_usuario_activo(db, "u1", plan="basico")
    db.sembrar(
        ("banco_preguntas_ia_AGE", "p1"),
        {
            "pregunta": "¿Capital de España?",
            "opciones": {"A": "Madrid", "B": "Barcelona"},
            "respuesta_correcta": "A",
        },
    )
    usuario_autenticado()
    contenido = [
        {
            "pregunta": "¿Capital de España?",
            "opciones": {"A": "Madrid", "B": "Barcelona"},
            "respuesta_correcta": "B",  # fabricada por el cliente
        }
    ]
    resultado = _guardar_y_leer_resultado(client, "AGE", contenido, ["B"], "personalizado")
    assert resultado["aciertos"] == 0
    assert resultado["fallos"] == 1


def test_test_personalizado_con_respuesta_correcta_real_sigue_puntuando_acierto(client, db, usuario_autenticado):
    """Caso normal (sin manipular nada): la respuesta_correcta que manda un
    cliente honesto coincide con el banco de IA, así que sigue puntuando
    igual que antes."""
    sembrar_usuario_activo(db, "u1", plan="basico")
    db.sembrar(
        ("banco_preguntas_ia_AGE", "p1"),
        {
            "pregunta": "¿Capital de España?",
            "opciones": {"A": "Madrid", "B": "Barcelona"},
            "respuesta_correcta": "A",
        },
    )
    usuario_autenticado()
    contenido = [
        {
            "pregunta": "¿Capital de España?",
            "opciones": {"A": "Madrid", "B": "Barcelona"},
            "respuesta_correcta": "A",
        }
    ]
    resultado = _guardar_y_leer_resultado(client, "AGE", contenido, ["A"], "personalizado")
    assert resultado["aciertos"] == 1
    assert resultado["fallos"] == 0


def test_test_personalizado_pregunta_no_encontrada_en_banco_no_rompe_el_guardado(client, db, usuario_autenticado):
    """Si la pregunta no está en banco_preguntas_ia (p. ej. se guardó antes
    de que existiera esta verificación), no se debe bloquear ni fallar el
    guardado -- se deja la respuesta_correcta tal cual la mandó el cliente
    para ESA pregunta en concreto."""
    sembrar_usuario_activo(db, "u1", plan="basico")
    usuario_autenticado()
    contenido = [
        {
            "pregunta": "Pregunta que no está en el banco de IA",
            "opciones": {"A": "x", "B": "y"},
            "respuesta_correcta": "A",
        }
    ]
    resultado = _guardar_y_leer_resultado(client, "AGE", contenido, ["A"], "personalizado")
    assert resultado["aciertos"] == 1


def test_test_personalizado_con_dos_verificaciones_contradictorias_no_elige_ninguna(client, db, usuario_autenticado):
    """banco_preguntas_ia no deduplica al escribir (ver
    guardar_pregunta_generada): si la IA generó el mismo enunciado dos
    veces con una respuesta_correcta distinta cada vez, ninguna de las dos
    gana arbitrariamente -- se deja la respuesta_correcta tal cual la mandó
    el cliente para esa pregunta, igual que si no hubiera ningún match."""
    sembrar_usuario_activo(db, "u1", plan="basico")
    db.sembrar(
        ("banco_preguntas_ia_AGE", "p1"),
        {
            "pregunta": "Pregunta con verificaciones contradictorias",
            "opciones": {"A": "x", "B": "y"},
            "respuesta_correcta": "A",
        },
    )
    db.sembrar(
        ("banco_preguntas_ia_AGE", "p2"),
        {
            "pregunta": "Pregunta con verificaciones contradictorias",
            "opciones": {"A": "x", "B": "y"},
            "respuesta_correcta": "B",
        },
    )
    usuario_autenticado()
    contenido = [
        {
            "pregunta": "Pregunta con verificaciones contradictorias",
            "opciones": {"A": "x", "B": "y"},
            "respuesta_correcta": "A",
        }
    ]
    resultado = _guardar_y_leer_resultado(client, "AGE", contenido, ["A"], "personalizado")
    assert resultado["aciertos"] == 1
