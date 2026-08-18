"""Prueba que /guardar-test NO se fía de la "respuesta_correcta" que manda
el cliente para los tests "oficial"/"psicotécnico": la recalcula contra el
banco real de Firestore (ver guardar_resultado._corregir_con_banco_oficial).

Sin esto, cualquiera podía guardar un test oficial con una
respuesta_correcta fabricada para sacar siempre nota máxima -- las
estadísticas y el ranking público se calculan a partir de este resultado
(hallazgo C2 de la auditoría de seguridad, docs/auditoria-seguridad-agosto-2026.md)."""

from unittest.mock import patch

from conftest import sembrar_usuario_activo
from oposiciones import coleccion_psicotecnico


def _con_sesion(cliente, uid="u1", email="u1@example.com"):
    parche = patch(
        "auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email}
    )
    parche.start()
    return parche


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


def test_test_oficial_ignora_respuesta_correcta_fabricada_por_el_cliente(client, db):
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
    parche = _con_sesion(client)
    try:
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
    finally:
        parche.stop()


def test_test_oficial_con_respuesta_correcta_real_sigue_puntuando_acierto(client, db):
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
    parche = _con_sesion(client)
    try:
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
    finally:
        parche.stop()


def test_test_oficial_pregunta_no_encontrada_en_banco_no_rompe_el_guardado(client, db):
    """Si la pregunta ya no está en el banco (se borró/editó entre generar
    y corregir el test), no se debe bloquear ni fallar el guardado -- se
    deja la respuesta_correcta tal cual la mandó el cliente para ESA
    pregunta en concreto."""
    sembrar_usuario_activo(db, "u1", plan="basico")
    parche = _con_sesion(client)
    try:
        contenido = [
            {
                "pregunta": "Pregunta que ya no existe en el banco",
                "opciones": {"A": "x", "B": "y"},
                "respuesta_correcta": "A",
            }
        ]
        resultado = _guardar_y_leer_resultado(client, "AGE", contenido, ["A"], "oficial")
        assert resultado["aciertos"] == 1
    finally:
        parche.stop()


def test_test_psicotecnico_tambien_ignora_respuesta_correcta_fabricada(client, db):
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
    parche = _con_sesion(client)
    try:
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
    finally:
        parche.stop()


def test_test_personalizado_no_se_toca_por_este_cambio(client, db):
    """El Test Personalizado (generado por IA, sin banco previo) queda
    fuera a propósito de esta verificación -- comportamiento sin cambios,
    para no romper nada ahí. Ver limitación conocida en el informe."""
    sembrar_usuario_activo(db, "u1", plan="basico")
    parche = _con_sesion(client)
    try:
        contenido = [
            {
                "pregunta": "Pregunta generada por IA",
                "opciones": {"A": "x", "B": "y"},
                "respuesta_correcta": "B",
            }
        ]
        resultado = _guardar_y_leer_resultado(client, "AGE", contenido, ["B"], "personalizado")
        assert resultado["aciertos"] == 1  # sigue fiándose del cliente, sin cambios
    finally:
        parche.stop()
