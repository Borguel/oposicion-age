"""Pruebas de las rutas de suscripción a notificaciones push (guardar,
deduplicar por endpoint y borrar), de que el cron de racha en riesgo
avise por push además de por email a quien tenga una suscripción
guardada, y de que el cifrado "aes128gcm" (RFC 8291) implementado a mano
en push_utils.py (en vez de con la librería pywebpush, que no se pudo
compilar en el entorno de despliegue) sea correcto de verdad: se cifra
con push_utils y se descifra de forma independiente simulando el lado
del navegador, para comprobar que un tercero con la clave privada
correcta recupera el mensaje exacto."""
import base64
import os
from datetime import date, timedelta
from unittest.mock import patch

import jwt as pyjwt
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import push_utils


def _b64url(datos):
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")


def _descifrar_como_navegador(clave_privada_navegador, secreto_auth, cuerpo):
    sal = cuerpo[:16]
    idlen = cuerpo[20]
    clave_efimera_publica = cuerpo[21:21 + idlen]
    cifrado = cuerpo[21 + idlen:]

    clave_publica_navegador = clave_privada_navegador.public_key().public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint)
    clave_efimera = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), clave_efimera_publica)

    secreto_ecdh = clave_privada_navegador.exchange(ec.ECDH(), clave_efimera)
    info_clave = b"WebPush: info\x00" + clave_publica_navegador + clave_efimera_publica
    prk_clave = push_utils._hkdf_extract(secreto_auth, secreto_ecdh)
    ikm = push_utils._hkdf_expand(prk_clave, info_clave, 32)
    prk = push_utils._hkdf_extract(sal, ikm)
    clave_contenido = push_utils._hkdf_expand(prk, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = push_utils._hkdf_expand(prk, b"Content-Encoding: nonce\x00", 12)

    texto_con_delimitador = AESGCM(clave_contenido).decrypt(nonce, cifrado, None)
    assert texto_con_delimitador[-1:] == b"\x02"
    return texto_con_delimitador[:-1]


def test_cifrado_aes128gcm_se_descifra_correctamente_como_navegador():
    clave_privada_navegador = ec.generate_private_key(ec.SECP256R1())
    clave_publica_navegador = clave_privada_navegador.public_key().public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint)
    secreto_auth = os.urandom(16)

    mensaje = b'{"title": "Racha en riesgo", "body": "No la pierdas"}'
    cuerpo_cifrado = push_utils._cifrar_aes128gcm(clave_publica_navegador, secreto_auth, mensaje)
    recuperado = _descifrar_como_navegador(clave_privada_navegador, secreto_auth, cuerpo_cifrado)

    assert recuperado == mensaje


def test_token_vapid_tiene_los_claims_correctos():
    with patch.object(push_utils, "VAPID_PUBLIC_KEY", "BFnc-isMGgSxRYKJIYeGntH0GmmPvBR7RT9X2HfvqlSQtKQiJn6qUpGt7c8TNllFOwBLyn8WOENbU62IRTx7S5c"), \
         patch.object(push_utils, "VAPID_PRIVATE_KEY", "R547iaeIs8sPk12l_pkncx_6jIwrWXt3Uv8BzB3M5sI"), \
         patch.object(push_utils, "VAPID_CLAIMS_EMAIL", "mailto:soporte@oposicion-age.com"):
        assert push_utils.push_disponible() is True

        token = push_utils._token_vapid("https://fcm.googleapis.com/fcm/send/abc123")
        claims = pyjwt.decode(token, options={"verify_signature": False})
        assert claims["aud"] == "https://fcm.googleapis.com"
        assert claims["sub"] == "mailto:soporte@oposicion-age.com"


SUSCRIPCION = {"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "x", "auth": "y"}}


def test_suscribir_guarda_la_suscripcion(client, db, usuario_autenticado):
    db.sembrar(("usuarios", "u1"), {})
    usuario_autenticado()
    resp = client.post("/notificaciones-push/suscribir", json=SUSCRIPCION,
                        headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    guardado = db.leer(("usuarios", "u1"))
    assert guardado["push_subscriptions"] == [SUSCRIPCION]


def test_suscribir_dos_veces_no_duplica(client, db, usuario_autenticado):
    db.sembrar(("usuarios", "u1"), {})
    usuario_autenticado()
    client.post("/notificaciones-push/suscribir", json=SUSCRIPCION, headers={"Authorization": "Bearer x"})
    client.post("/notificaciones-push/suscribir", json=SUSCRIPCION, headers={"Authorization": "Bearer x"})
    guardado = db.leer(("usuarios", "u1"))
    assert len(guardado["push_subscriptions"]) == 1


def test_desuscribir_quita_la_suscripcion(client, db, usuario_autenticado):
    db.sembrar(("usuarios", "u1"), {"push_subscriptions": [SUSCRIPCION]})
    usuario_autenticado()
    resp = client.post("/notificaciones-push/desuscribir", json={"endpoint": SUSCRIPCION["endpoint"]},
                        headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    guardado = db.leer(("usuarios", "u1"))
    assert guardado["push_subscriptions"] == []


def test_suscribir_sin_endpoint_devuelve_error(client, db, usuario_autenticado):
    db.sembrar(("usuarios", "u1"), {})
    usuario_autenticado()
    resp = client.post("/notificaciones-push/suscribir", json={"keys": {}},
                        headers={"Authorization": "Bearer x"})
    assert resp.status_code == 400


def test_clave_publica_no_requiere_login(client):
    resp = client.get("/notificaciones-push/clave-publica")
    assert resp.status_code == 200
    assert "clave_publica" in resp.get_json()


def _fecha_hace(dias):
    return (date.today() - timedelta(days=dias)).isoformat()


def test_cron_racha_en_riesgo_envia_push_a_suscripciones_guardadas(client, db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "racha": {"racha_actual": 5, "ultima_fecha": _fecha_hace(1)},
        "push_subscriptions": [SUSCRIPCION],
    })
    with patch.dict(os.environ, {"CRON_SECRET_KEY": "secreta"}), \
         patch("blueprints.tareas_programadas.enviar_email_racha_en_riesgo"), \
         patch("blueprints.tareas_programadas.enviar_email_reengagement"), \
         patch("blueprints.tareas_programadas.enviar_push") as mock_push:
        resp = client.post("/tareas/recordatorios-racha", headers={"X-Cron-Key": "secreta"})
        assert resp.status_code == 200
        mock_push.assert_called_once()
        args, _ = mock_push.call_args
        assert args[0] == SUSCRIPCION
