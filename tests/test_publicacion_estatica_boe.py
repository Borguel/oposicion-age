"""Pruebas de publicacion_estatica_boe.py: se mockea la API REST de GitHub
(requests.get/requests.put) -- lo que se comprueba es que la sustitución
entre marcadores es correcta, que no se hace ningún commit si el contenido
no cambia, y que un fallo (sin token, marcadores no encontrados, 409 de
GitHub, excepción de red) nunca se propaga hacia quien llama (la
aprobación del aviso en Firestore no debe romperse nunca por esto)."""
import base64
from unittest.mock import MagicMock, patch

import publicacion_estatica_boe as pub


def _fake_response(json_data=None, status_code=200, raise_exc=None):
    resp = MagicMock()
    resp.status_code = status_code
    if raise_exc:
        resp.raise_for_status = MagicMock(side_effect=raise_exc)
    else:
        resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=json_data or {})
    return resp


def _html_con_marcadores(cuerpo="<p>viejo</p>"):
    return (
        "<html><body>\n"
        "      <!-- AVISOS_OFICIALES_INICIO -->\n"
        f"{cuerpo}\n"
        "      <!-- AVISOS_OFICIALES_FIN -->\n"
        "</body></html>"
    )


def _respuesta_contenido(html, sha="abc123"):
    return _fake_response({"sha": sha, "content": base64.b64encode(html.encode("utf-8")).decode("ascii")})


def test_generar_html_avisos_vacio_muestra_mensaje_de_arranque():
    html = pub.generar_html_avisos([])
    assert "Todavía no hay avisos recientes" in html


def test_generar_html_avisos_incluye_tipo_titulo_y_enlaces():
    avisos = [{
        "oposicion": "AGE", "tipo": "convocatoria",
        "titulo": "Convocatoria 2026", "url_boe": "https://www.boe.es/x",
    }]
    html = pub.generar_html_avisos(avisos)
    assert "Convocatoria" in html
    assert "Convocatoria 2026" in html
    assert "https://www.boe.es/x" in html
    assert pub._URL_INAP_GENERAL in html


def test_generar_html_avisos_sin_url_boe_no_muestra_enlace_roto():
    # Sin url_boe, mejor no mostrar el enlace "Ver la resolución oficial"
    # que uno con href="" que da la sensación de estar roto.
    avisos = [{"oposicion": "AGE", "tipo": "llamamiento_extraordinario", "titulo": "Repesca"}]
    html = pub.generar_html_avisos(avisos)
    assert 'href=""' not in html
    assert pub._URL_INAP_GENERAL in html  # el de INAP, siempre fijo, sigue apareciendo


def test_actualizar_pagina_sin_github_token_no_llama_a_requests(monkeypatch, db):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with patch("publicacion_estatica_boe.requests.get") as mock_get:
        resultado = pub.actualizar_pagina_estatica_avisos(db, "AGE")
    mock_get.assert_not_called()
    assert resultado is False


def test_actualizar_pagina_sustituye_entre_marcadores_y_comitea(monkeypatch, db):
    monkeypatch.setenv("GITHUB_TOKEN", "token-de-prueba")
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposicion": "AGE", "tipo": "convocatoria", "titulo": "Convocatoria 2026",
        "url_boe": "https://www.boe.es/x", "estado": "publicado", "fecha_boe": "2026-07-20",
    })
    html_actual = _html_con_marcadores()

    with patch("publicacion_estatica_boe.requests.get", return_value=_respuesta_contenido(html_actual)), \
         patch("publicacion_estatica_boe.requests.put", return_value=_fake_response()) as mock_put:
        resultado = pub.actualizar_pagina_estatica_avisos(db, "AGE")

    assert resultado is True
    mock_put.assert_called_once()
    payload = mock_put.call_args.kwargs["json"]
    assert payload["sha"] == "abc123"
    assert payload["branch"] == pub._RAMA
    html_nuevo = base64.b64decode(payload["content"]).decode("utf-8")
    assert "Convocatoria 2026" in html_nuevo
    assert "<p>viejo</p>" not in html_nuevo
    # La cabecera/pie fuera de los marcadores no se toca.
    assert html_nuevo.startswith("<html><body>")
    assert html_nuevo.endswith("</body></html>")


def test_actualizar_pagina_no_comitea_si_no_hay_avisos_publicados_y_ya_estaba_vacio(monkeypatch, db):
    monkeypatch.setenv("GITHUB_TOKEN", "token-de-prueba")
    html_actual = _html_con_marcadores(pub.generar_html_avisos([]))

    with patch("publicacion_estatica_boe.requests.get", return_value=_respuesta_contenido(html_actual)), \
         patch("publicacion_estatica_boe.requests.put") as mock_put:
        resultado = pub.actualizar_pagina_estatica_avisos(db, "AGE")

    assert resultado is True
    mock_put.assert_not_called()


def test_actualizar_pagina_sin_marcadores_no_lanza_y_no_comitea(monkeypatch, db):
    monkeypatch.setenv("GITHUB_TOKEN", "token-de-prueba")
    html_sin_marcadores = "<html><body><p>sin marcadores</p></body></html>"

    with patch("publicacion_estatica_boe.requests.get", return_value=_respuesta_contenido(html_sin_marcadores)), \
         patch("publicacion_estatica_boe.requests.put") as mock_put:
        resultado = pub.actualizar_pagina_estatica_avisos(db, "AGE")  # no debe lanzar

    assert resultado is False
    mock_put.assert_not_called()


def test_actualizar_pagina_conflicto_409_no_lanza_excepcion(monkeypatch, db):
    monkeypatch.setenv("GITHUB_TOKEN", "token-de-prueba")
    db.sembrar(("avisos_oficiales", "a1"), {
        "oposicion": "AGE", "tipo": "convocatoria", "titulo": "Convocatoria 2026",
        "url_boe": "https://www.boe.es/x", "estado": "publicado", "fecha_boe": "2026-07-20",
    })
    html_actual = _html_con_marcadores()
    error_409 = Exception("409 Conflict")

    with patch("publicacion_estatica_boe.requests.get", return_value=_respuesta_contenido(html_actual)), \
         patch("publicacion_estatica_boe.requests.put", return_value=_fake_response(status_code=409, raise_exc=error_409)):
        resultado = pub.actualizar_pagina_estatica_avisos(db, "AGE")  # no debe lanzar

    assert resultado is False


def test_actualizar_pagina_oposicion_desconocida_devuelve_false_sin_llamar(monkeypatch, db):
    monkeypatch.setenv("GITHUB_TOKEN", "token-de-prueba")
    with patch("publicacion_estatica_boe.requests.get") as mock_get:
        resultado = pub.actualizar_pagina_estatica_avisos(db, "INEXISTENTE")
    mock_get.assert_not_called()
    assert resultado is False


def test_notificar_usuarios_manda_solo_a_los_de_esa_oposicion(db):
    db.sembrar(("usuarios", "u1"), {"email": "interesado@example.com", "suscripciones": {"AGE": {"plan": "premium"}}})
    db.sembrar(("usuarios", "u2"), {"email": "activo@example.com", "estadisticas": {"AGE": {"tests_realizados": 3}}})
    db.sembrar(("usuarios", "u3"), {"email": "otra_oposicion@example.com", "suscripciones": {"GACE": {"plan": "premium"}}})
    db.sembrar(("usuarios", "u4"), {"suscripciones": {"AGE": {"plan": "premium"}}})  # sin email

    aviso = {
        "oposicion": "AGE", "tipo": "convocatoria", "titulo": "Convocatoria 2026",
        "url_boe": "https://www.boe.es/x",
    }
    with patch("publicacion_estatica_boe.enviar_email_aviso_oficial") as mock_enviar:
        enviados = pub.notificar_usuarios_aviso_oficial(db, aviso)

    assert enviados == 2
    destinatarios = {c.args[0] for c in mock_enviar.call_args_list}
    assert destinatarios == {"interesado@example.com", "activo@example.com"}


def test_notificar_usuarios_fallo_en_firestore_no_lanza_excepcion(db):
    aviso = {"oposicion": "AGE", "titulo": "x", "url_boe": "https://www.boe.es/x"}
    with patch.object(db, "collection", side_effect=RuntimeError("caído")):
        enviados = pub.notificar_usuarios_aviso_oficial(db, aviso)  # no debe lanzar
    assert enviados == 0
