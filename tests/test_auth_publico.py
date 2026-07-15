"""Pruebas de /recuperar-contrasena: la única ruta del backend pensada para
alguien que todavía no ha iniciado sesión. Lo crítico a comprobar es que
SIEMPRE responde igual (200, mismo mensaje) exista o no ese correo -- si no,
la ruta se podría usar para averiguar qué correos están registrados."""
from unittest.mock import patch

from firebase_admin import auth as firebase_auth


def _mensaje_generico(resp):
    return resp.get_json()["mensaje"]


def test_email_vacio_responde_generico_sin_llamar_a_firebase(client):
    with patch("blueprints.auth_publico.firebase_auth.generate_password_reset_link") as mock_link:
        resp = client.post("/recuperar-contrasena", json={"email": ""})
    assert resp.status_code == 200
    assert "recibirás un enlace" in _mensaje_generico(resp)
    mock_link.assert_not_called()


def test_email_con_formato_invalido_responde_generico_sin_llamar_a_firebase(client):
    with patch("blueprints.auth_publico.firebase_auth.generate_password_reset_link") as mock_link:
        resp = client.post("/recuperar-contrasena", json={"email": "no-es-un-correo"})
    assert resp.status_code == 200
    assert "recibirás un enlace" in _mensaje_generico(resp)
    mock_link.assert_not_called()


def test_email_existente_genera_enlace_y_envia_por_brevo(client):
    with patch("blueprints.auth_publico.firebase_auth.generate_password_reset_link",
               return_value="https://dominatuopo.com/login/?oobCode=abc") as mock_link, \
         patch("blueprints.auth_publico.enviar_email_recuperar_contrasena") as mock_enviar:
        resp = client.post("/recuperar-contrasena", json={"email": "u@example.com"})

    assert resp.status_code == 200
    assert "recibirás un enlace" in _mensaje_generico(resp)
    mock_link.assert_called_once()
    assert mock_link.call_args.args[0] == "u@example.com"
    mock_enviar.assert_called_once_with("u@example.com", "https://dominatuopo.com/login/?oobCode=abc")


def test_email_no_registrado_responde_igual_y_no_envia_nada(client):
    with patch("blueprints.auth_publico.firebase_auth.generate_password_reset_link",
               side_effect=firebase_auth.UserNotFoundError("no existe")), \
         patch("blueprints.auth_publico.enviar_email_recuperar_contrasena") as mock_enviar:
        resp = client.post("/recuperar-contrasena", json={"email": "fantasma@example.com"})

    assert resp.status_code == 200
    assert "recibirás un enlace" in _mensaje_generico(resp)
    mock_enviar.assert_not_called()


def test_fallo_inesperado_de_firebase_no_rompe_la_ruta(client):
    with patch("blueprints.auth_publico.firebase_auth.generate_password_reset_link",
               side_effect=RuntimeError("firebase caído")), \
         patch("blueprints.auth_publico.enviar_email_recuperar_contrasena") as mock_enviar:
        resp = client.post("/recuperar-contrasena", json={"email": "u@example.com"})

    assert resp.status_code == 200
    assert "recibirás un enlace" in _mensaje_generico(resp)
    mock_enviar.assert_not_called()


def test_no_requiere_autenticacion(client):
    # A diferencia del resto de rutas: no manda Authorization y no debe
    # devolver 401 -- es la ruta que usa alguien que aún no puede iniciar
    # sesión (por eso está pidiendo recuperar la contraseña).
    with patch("blueprints.auth_publico.firebase_auth.generate_password_reset_link"):
        resp = client.post("/recuperar-contrasena", json={"email": "u@example.com"})
    assert resp.status_code != 401
