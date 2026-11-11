"""Ciclo de vida de un reporte de pregunta: el usuario reporta
(POST /reportar-pregunta, blueprints/test_ia.py) -> el admin corrige la
pregunta (PUT /admin/api/preguntas/<id>) y/o marca el reporte como revisado
(PATCH /admin/api/reportes/<id>) -> el usuario recibe los correos de recibo,
de "corregida" o de "sin cambios" (email_utils.py)."""
from contextlib import contextmanager
from unittest.mock import patch

_AUTH = {"Authorization": "Bearer x"}
_COLECCION_GACE = "examenes_oficiales_GACE"

_PREGUNTA = {
    "tipo": "pregunta",
    "pregunta": "Señale cómo se retribuye la peligrosidad o penosidad de un puesto de trabajo:",
    "opciones": {
        "A": "Complemento de productividad.",
        "B": "Complemento específico.",
        "C": "Complemento de destino.",
        "D": "Gratificación por servicios extraordinarios.",
    },
    "respuesta_correcta": "C",
    "explicacion": "Explicación antigua.",
    "tema_id": "bloque_05-tema_02",
    "examen": "GACE 2008",
    "numero": 81,
    "psicotecnico": False,
}


@contextmanager
def _como(uid="admin1", email="admin@example.com"):
    with patch("auth_utils.firebase_auth.verify_id_token", return_value={"uid": uid, "email": email, "admin": True}):
        yield


def _reportar(client, uid="u1", email="u1@x.com", texto=None, motivo="La respuesta correcta es la B", oposicion="GACE"):
    cuerpo = {"pregunta_texto": texto or _PREGUNTA["pregunta"], "motivo": motivo, "oposicion": oposicion}
    with _como(uid=uid, email=email):
        return client.post("/reportar-pregunta", json=cuerpo, headers=_AUTH)


def _reportes(db):
    return {doc.id: doc.to_dict() for doc in db.collection("errores_generacion").stream()}


def _editar_pregunta(client, **cambios):
    cuerpo = {
        "oposicion": "GACE",
        "pregunta": _PREGUNTA["pregunta"],
        "opciones": dict(_PREGUNTA["opciones"]),
        "respuesta_correcta": "C",
        "explicacion": "Explicación antigua.",
        "tema_id": "bloque_05-tema_02",
        "examen": "GACE 2008",
    }
    cuerpo.update(cambios)
    with _como():
        return client.put("/admin/api/preguntas/p81", json=cuerpo, headers=_AUTH)


def _revisar(client, rid, estado="revisado", **extra):
    with _como():
        return client.patch(f"/admin/api/reportes/{rid}", json={"estado": estado, **extra}, headers=_AUTH)


# ---------------------------------------------------------------- alta


def test_reportar_guarda_el_email_y_manda_la_confirmacion(client, db):
    db.sembrar(("usuarios", "u1"), {"nombre": "Ana"})
    with patch("blueprints.test_ia.enviar_email_pregunta_reportada") as mock_email:
        r = _reportar(client)

    assert r.status_code == 201
    reporte = next(iter(_reportes(db).values()))
    assert reporte["email"] == "u1@x.com"
    assert reporte["estado"] == "pendiente"
    mock_email.assert_called_once_with("u1@x.com", _PREGUNTA["pregunta"], "La respuesta correcta es la B", "Ana")


def test_reportar_lo_mismo_dos_veces_no_duplica_ni_reenvia_el_correo(client, db):
    with patch("blueprints.test_ia.enviar_email_pregunta_reportada") as mock_email:
        primero = _reportar(client)
        segundo = _reportar(client)

    assert primero.status_code == 201
    assert segundo.status_code == 200
    assert len(_reportes(db)) == 1
    mock_email.assert_called_once()


def test_otro_usuario_puede_reportar_la_misma_pregunta(client, db):
    with patch("blueprints.test_ia.enviar_email_pregunta_reportada") as mock_email:
        _reportar(client, uid="u1", email="u1@x.com")
        r = _reportar(client, uid="u2", email="u2@x.com")

    assert r.status_code == 201
    assert len(_reportes(db)) == 2
    assert mock_email.call_count == 2


def test_reportar_de_nuevo_tras_revisarse_el_anterior_crea_uno_nuevo(client, db):
    with patch("blueprints.test_ia.enviar_email_pregunta_reportada"):
        _reportar(client)
        rid = next(iter(_reportes(db)))
        with patch("blueprints.admin.enviar_email_pregunta_sin_cambios"):
            _revisar(client, rid)
        r = _reportar(client)

    assert r.status_code == 201
    assert len(_reportes(db)) == 2


def test_reportar_sin_motivo_o_sin_pregunta_400_y_sin_correo(client, db):
    with patch("blueprints.test_ia.enviar_email_pregunta_reportada") as mock_email:
        sin_motivo = _reportar(client, motivo="   ")
        sin_pregunta = _reportar(client, texto="   ")

    assert sin_motivo.status_code == 400
    assert sin_pregunta.status_code == 400
    assert _reportes(db) == {}
    mock_email.assert_not_called()


def test_reportar_no_confirma_si_el_reporte_no_se_pudo_guardar(client, db):
    with patch("blueprints.test_ia.registrar_error_generacion", return_value=None), \
         patch("blueprints.test_ia.enviar_email_pregunta_reportada") as mock_email:
        r = _reportar(client)

    assert r.status_code == 201
    mock_email.assert_not_called()


# ------------------------------------------------- edición -> corrección


def test_listar_reportes_incluye_el_id_y_los_campos_de_la_pregunta_oficial(client, db):
    db.sembrar((_COLECCION_GACE, "p81"), _PREGUNTA)
    with patch("blueprints.test_ia.enviar_email_pregunta_reportada"):
        _reportar(client)

    with _como():
        d = client.get("/admin/api/reportes?estado=pendiente", headers=_AUTH).get_json()

    oficial = d["reportes"][0]["pregunta_oficial"]
    assert oficial["id"] == "p81"
    assert oficial["numero"] == 81
    assert oficial["tema_id"] == "bloque_05-tema_02"
    assert oficial["examen"] == "GACE 2008"
    assert d["reportes"][0]["tiene_correccion"] is False


def test_editar_la_pregunta_anota_la_correccion_en_el_reporte_abierto(client, db):
    db.sembrar((_COLECCION_GACE, "p81"), _PREGUNTA)
    with patch("blueprints.test_ia.enviar_email_pregunta_reportada"):
        _reportar(client)

    r = _editar_pregunta(client, respuesta_correcta="B", explicacion="Explicación nueva.")

    assert r.status_code == 200
    reporte = next(iter(_reportes(db).values()))
    correccion = reporte["correccion"]
    assert correccion["pregunta_id"] == "p81"
    assert {c["campo"]: (c["antes"], c["despues"]) for c in correccion["cambios"]} == {
        "respuesta_correcta": ("C", "B"),
        "explicacion": ("Explicación antigua.", "Explicación nueva."),
    }
    assert correccion["despues"]["respuesta_correcta"] == "B"


def test_editar_sin_cambios_visibles_no_anota_nada(client, db):
    db.sembrar((_COLECCION_GACE, "p81"), _PREGUNTA)
    with patch("blueprints.test_ia.enviar_email_pregunta_reportada"):
        _reportar(client)

    _editar_pregunta(client, tema_id="bloque_05-tema_03")  # solo metadatos

    assert "correccion" not in next(iter(_reportes(db).values()))


def test_la_correccion_solo_se_anota_en_reportes_abiertos_de_esa_pregunta(client, db):
    db.sembrar((_COLECCION_GACE, "p81"), _PREGUNTA)
    with patch("blueprints.test_ia.enviar_email_pregunta_reportada"):
        _reportar(client, uid="u1", email="u1@x.com")  # abierto, misma pregunta
        _reportar(client, uid="u2", email="u2@x.com", texto="Otra pregunta distinta")  # otra pregunta
        _reportar(client, uid="u3", email="u3@x.com", oposicion="AGE")  # misma pregunta, pero ya revisado
    por_uid = {d["uid"]: rid for rid, d in _reportes(db).items()}
    with patch("blueprints.admin.enviar_email_pregunta_sin_cambios"):
        _revisar(client, por_uid["u3"])

    _editar_pregunta(client, respuesta_correcta="B")

    reportes = _reportes(db)
    assert "correccion" in reportes[por_uid["u1"]]
    assert "correccion" not in reportes[por_uid["u2"]]
    assert "correccion" not in reportes[por_uid["u3"]]


def test_la_edicion_conserva_numero_y_psicotecnico(client, db):
    db.sembrar((_COLECCION_GACE, "p81"), {**_PREGUNTA, "psicotecnico": True})

    r = _editar_pregunta(client, explicacion="Otra explicación.")  # el formulario no envía numero/psicotecnico

    assert r.status_code == 200
    guardada = db.leer((_COLECCION_GACE, "p81"))
    assert guardada["numero"] == 81
    assert guardada["psicotecnico"] is True


def test_dos_ediciones_seguidas_fusionan_los_cambios_del_reporte(client, db):
    db.sembrar((_COLECCION_GACE, "p81"), _PREGUNTA)
    with patch("blueprints.test_ia.enviar_email_pregunta_reportada"):
        _reportar(client)

    _editar_pregunta(client, respuesta_correcta="B", pregunta="Enunciado reformulado:")
    _editar_pregunta(
        client, respuesta_correcta="D", pregunta="Enunciado reformulado:",
        opciones={**_PREGUNTA["opciones"], "A": "Otra A."},
    )

    cambios = next(iter(_reportes(db).values()))["correccion"]["cambios"]
    por_campo = {c["campo"]: (c["antes"], c["despues"]) for c in cambios}
    assert por_campo["respuesta_correcta"] == ("C", "D")  # antes de la 1ª edición, después de la última
    assert por_campo["enunciado"][1] == "Enunciado reformulado:"
    assert por_campo["opcion_A"] == ("Complemento de productividad.", "Otra A.")


def test_tras_corregir_el_enunciado_el_reporte_sigue_localizando_la_pregunta_por_id(client, db):
    db.sembrar((_COLECCION_GACE, "p81"), _PREGUNTA)
    with patch("blueprints.test_ia.enviar_email_pregunta_reportada"):
        _reportar(client)
    _editar_pregunta(client, pregunta="Enunciado reformulado:")

    with _como():
        reporte = client.get("/admin/api/reportes?estado=pendiente", headers=_AUTH).get_json()["reportes"][0]

    assert reporte["tiene_correccion"] is True
    assert reporte["pregunta_oficial"]["id"] == "p81"
    assert reporte["pregunta_oficial"]["pregunta"] == "Enunciado reformulado:"


# ------------------------------------------------ revisión -> correo


def test_revisar_un_reporte_corregido_manda_el_correo_de_corregida(client, db):
    db.sembrar((_COLECCION_GACE, "p81"), _PREGUNTA)
    db.sembrar(("usuarios", "u1"), {"nombre": "Ana"})
    with patch("blueprints.test_ia.enviar_email_pregunta_reportada"):
        _reportar(client)
    rid = next(iter(_reportes(db)))
    _editar_pregunta(client, respuesta_correcta="B", explicacion="Explicación nueva.")

    with patch("blueprints.admin.enviar_email_pregunta_corregida") as mock_corregida, \
         patch("blueprints.admin.enviar_email_pregunta_sin_cambios") as mock_sin_cambios:
        r = _revisar(client, rid, nota="Gracias por la precisión")

    assert r.status_code == 200
    assert r.get_json()["email_enviado"] is True
    mock_sin_cambios.assert_not_called()
    destinatario, pregunta, cambios, nombre, nota = mock_corregida.call_args.args
    assert destinatario == "u1@x.com"
    assert pregunta["respuesta_correcta"] == "B"
    assert pregunta["explicacion"] == "Explicación nueva."
    assert {c["campo"] for c in cambios} == {"respuesta_correcta", "explicacion"}
    assert (nombre, nota) == ("Ana", "Gracias por la precisión")
    guardado = _reportes(db)[rid]
    assert guardado["estado"] == "revisado"
    assert guardado["resultado"] == "corregida"
    assert guardado["email_resolucion_enviado"] is True
    assert guardado["nota"] == "Gracias por la precisión"


def test_revisar_un_reporte_sin_correccion_manda_el_correo_de_sin_cambios(client, db):
    db.sembrar((_COLECCION_GACE, "p81"), _PREGUNTA)
    with patch("blueprints.test_ia.enviar_email_pregunta_reportada"):
        _reportar(client)
    rid = next(iter(_reportes(db)))

    with patch("blueprints.admin.enviar_email_pregunta_corregida") as mock_corregida, \
         patch("blueprints.admin.enviar_email_pregunta_sin_cambios") as mock_sin_cambios:
        r = _revisar(client, rid)

    assert r.get_json()["email_enviado"] is True
    mock_corregida.assert_not_called()
    destinatario, pregunta, nombre, nota = mock_sin_cambios.call_args.args
    assert destinatario == "u1@x.com"
    assert pregunta["opciones"]["B"] == "Complemento específico."  # la pregunta completa, del banco
    assert nota == ""
    assert _reportes(db)[rid]["resultado"] == "sin_cambios"


def test_revisar_un_reporte_de_pregunta_de_ia_manda_sin_cambios_con_solo_el_enunciado(client, db):
    with patch("blueprints.test_ia.enviar_email_pregunta_reportada"):
        _reportar(client, texto="Pregunta generada por IA")
    rid = next(iter(_reportes(db)))

    with patch("blueprints.admin.enviar_email_pregunta_sin_cambios") as mock_sin_cambios:
        _revisar(client, rid)

    pregunta = mock_sin_cambios.call_args.args[1]
    assert pregunta == {"pregunta": "Pregunta generada por IA"}


def test_descartar_no_avisa_al_usuario(client, db):
    with patch("blueprints.test_ia.enviar_email_pregunta_reportada"):
        _reportar(client)
    rid = next(iter(_reportes(db)))

    with patch("blueprints.admin.enviar_email_pregunta_corregida") as mock_corregida, \
         patch("blueprints.admin.enviar_email_pregunta_sin_cambios") as mock_sin_cambios:
        r = _revisar(client, rid, estado="descartado")

    assert r.status_code == 200
    assert r.get_json()["email_enviado"] is False
    mock_corregida.assert_not_called()
    mock_sin_cambios.assert_not_called()
    assert _reportes(db)[rid]["estado"] == "descartado"


def test_revisar_dos_veces_no_reenvia_el_correo(client, db):
    with patch("blueprints.test_ia.enviar_email_pregunta_reportada"):
        _reportar(client)
    rid = next(iter(_reportes(db)))

    with patch("blueprints.admin.enviar_email_pregunta_sin_cambios") as mock_sin_cambios:
        _revisar(client, rid)
        _revisar(client, rid, estado="pendiente")  # se reabre
        r = _revisar(client, rid)  # y se vuelve a revisar

    assert r.get_json()["email_enviado"] is False
    mock_sin_cambios.assert_called_once()


def test_un_reporte_ya_revisado_antes_de_esta_funcion_no_manda_correo(client, db):
    db.sembrar(("errores_generacion", "viejo"), {
        "fuente": "usuario_admin", "estado": "revisado", "uid": "u1", "email": "u1@x.com",
        "pregunta_texto": "x", "detalle": "y", "oposicion": "GACE",
    })

    with patch("blueprints.admin.enviar_email_pregunta_sin_cambios") as mock_sin_cambios:
        r = _revisar(client, "viejo")

    assert r.status_code == 200
    mock_sin_cambios.assert_not_called()


def test_reporte_antiguo_sin_email_usa_el_de_usuarios(client, db):
    db.sembrar(("usuarios", "u9"), {"email": "guardado@x.com", "nombre": "Luis"})
    db.sembrar(("errores_generacion", "r1"), {
        "fuente": "usuario_admin", "estado": "pendiente", "uid": "u9",
        "pregunta_texto": "Pregunta de IA", "detalle": "y", "oposicion": "GACE",
    })

    with patch("blueprints.admin.enviar_email_pregunta_sin_cambios") as mock_sin_cambios:
        r = _revisar(client, "r1")

    assert r.get_json()["email_enviado"] is True
    assert mock_sin_cambios.call_args.args[0] == "guardado@x.com"
    assert mock_sin_cambios.call_args.args[2] == "Luis"


def test_sin_ningun_email_conocido_se_revisa_sin_fallar_ni_enviar(client, db):
    db.sembrar(("errores_generacion", "r1"), {
        "fuente": "usuario_admin", "estado": "pendiente", "uid": "u404",
        "pregunta_texto": "Pregunta de IA", "detalle": "y", "oposicion": "GACE",
    })

    with patch("blueprints.admin.enviar_email_pregunta_sin_cambios") as mock_sin_cambios:
        r = _revisar(client, "r1")

    assert r.status_code == 200
    assert r.get_json()["email_enviado"] is False
    mock_sin_cambios.assert_not_called()
    assert _reportes(db)["r1"]["estado"] == "revisado"
    assert "email_resolucion_enviado" not in _reportes(db)["r1"]
