"""Pruebas de exportación y borrado de cuenta (gestion_cuenta.py + rutas de
blueprints/pagos.py): que la exportación incluya todo lo del usuario, y que
borrar la cuenta cancele Stripe, borre subcolecciones y la cuenta de auth."""
import os
from unittest.mock import patch, MagicMock

import generacion_control
from gestion_cuenta import exportar_datos_usuario, eliminar_cuenta_usuario


def test_exportar_datos_incluye_perfil_y_subcolecciones(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "nombre": "Ana"})
    db.sembrar(("usuarios", "u1", "tests", "t1"), {"tipo": "oficial"})
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Tema 1"})

    datos = exportar_datos_usuario(db, "u1")

    assert datos["perfil"]["nombre"] == "Ana"
    assert datos["tests"] == [{"id": "t1", "tipo": "oficial"}]
    assert datos["documentos"] == [{"id": "d1", "titulo": "Tema 1"}]
    assert datos["esquemas_pdf"] == []


def test_eliminar_cuenta_borra_subcolecciones_y_documento(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    db.sembrar(("usuarios", "u1", "tests", "t1"), {"tipo": "oficial"})
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Tema 1"})

    with patch("gestion_cuenta.firebase_auth.delete_user") as mock_delete_user:
        eliminar_cuenta_usuario(db, "u1")
        mock_delete_user.assert_called_once_with("u1")

    assert db.leer(("usuarios", "u1")) is None
    assert db.leer(("usuarios", "u1", "tests", "t1")) is None
    assert db.leer(("usuarios", "u1", "documentos", "d1")) is None


def test_eliminar_cuenta_borra_firebase_auth_antes_que_firestore(db):
    # Si el borrado de Firebase Auth falla por algo que no sea "ya no
    # existe", los datos de Firestore deben seguir intactos para poder
    # reintentar sin dejar una cuenta de Auth huérfana con datos perdidos.
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    db.sembrar(("usuarios", "u1", "tests", "t1"), {"tipo": "oficial"})

    with patch("gestion_cuenta.firebase_auth.delete_user", side_effect=RuntimeError("red caída")):
        try:
            eliminar_cuenta_usuario(db, "u1")
        except RuntimeError:
            pass

    assert db.leer(("usuarios", "u1")) is not None
    assert db.leer(("usuarios", "u1", "tests", "t1")) is not None


def test_exportar_datos_incluye_conversaciones_de_tu_tutor(db):
    # Las conversaciones de Tu Tutor cuelgan de conversaciones_IA/{uid}/conversaciones,
    # NO de usuarios/{uid}/conversaciones (ver chat_controller.py: crear_conversacion).
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    db.sembrar(("conversaciones_IA", "u1", "conversaciones", "c1"), {"titulo": "Duda sobre el TREBEP"})

    datos = exportar_datos_usuario(db, "u1")

    assert datos["conversaciones"] == [{"id": "c1", "titulo": "Duda sobre el TREBEP"}]


def test_eliminar_cuenta_borra_conversaciones_de_tu_tutor(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    db.sembrar(("conversaciones_IA", "u1", "conversaciones", "c1"), {"titulo": "Duda sobre el TREBEP"})

    with patch("gestion_cuenta.firebase_auth.delete_user"):
        eliminar_cuenta_usuario(db, "u1")

    assert db.leer(("conversaciones_IA", "u1", "conversaciones", "c1")) is None
    assert db.leer(("conversaciones_IA", "u1")) is None


def test_eliminar_cuenta_cancela_suscripciones_de_stripe(db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"stripe_subscription_id": "sub_123"}}
    })

    with patch("gestion_cuenta.stripe.Subscription.delete") as mock_cancelar, \
         patch("gestion_cuenta.firebase_auth.delete_user"):
        eliminar_cuenta_usuario(db, "u1")
        mock_cancelar.assert_called_once_with("sub_123")


def test_eliminar_cuenta_no_falla_si_stripe_da_error(db):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"stripe_subscription_id": "sub_123"}}
    })

    with patch("gestion_cuenta.stripe.Subscription.delete", side_effect=RuntimeError("stripe caído")), \
         patch("gestion_cuenta.firebase_auth.delete_user"):
        eliminar_cuenta_usuario(db, "u1")  # no debe lanzar

    assert db.leer(("usuarios", "u1")) is None


def test_eliminar_cuenta_avisa_por_email_si_stripe_da_error(db):
    # Sin este aviso, una suscripción que Stripe no pudo cancelar podía
    # seguir cobrando indefinidamente a una cuenta ya borrada, sin que
    # nadie se enterase hasta un impago meses después.
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"stripe_subscription_id": "sub_123"}}
    })

    with patch("gestion_cuenta.stripe.Subscription.delete", side_effect=RuntimeError("stripe caído")), \
         patch("gestion_cuenta.firebase_auth.delete_user"), \
         patch("gestion_cuenta.enviar_email_alerta_cancelacion_stripe_fallida") as mock_alerta:
        eliminar_cuenta_usuario(db, "u1")

    mock_alerta.assert_called_once_with(os.environ.get("BREVO_FROM_EMAIL"), "u1", "sub_123")


def test_exportar_datos_incluye_bancos_pdf_favoritas_y_bajas_motivos(db):
    # Bug real (24/08/2026): estas 4 subcolecciones faltaban en
    # COLECCIONES_USUARIO -- ni se exportaban (derecho de acceso
    # incompleto) ni se borraban al eliminar la cuenta (ver el siguiente
    # test), quedando huérfanas en Firestore para siempre.
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    db.sembrar(("usuarios", "u1", "banco_preguntas_pdf", "d1"), {"estado": "completo"})
    db.sembrar(("usuarios", "u1", "banco_tarjetas_pdf", "d1"), {"estado": "completo"})
    db.sembrar(("usuarios", "u1", "preguntas_favoritas", "p1"), {"pregunta": "?"})
    db.sembrar(("usuarios", "u1", "bajas_motivos", "b1"), {"motivo": "precio"})

    datos = exportar_datos_usuario(db, "u1")

    assert datos["banco_preguntas_pdf"] == [{"id": "d1", "estado": "completo"}]
    assert datos["banco_tarjetas_pdf"] == [{"id": "d1", "estado": "completo"}]
    assert datos["preguntas_favoritas"] == [{"id": "p1", "pregunta": "?"}]
    assert datos["bajas_motivos"] == [{"id": "b1", "motivo": "precio"}]


def test_eliminar_cuenta_borra_bancos_pdf_favoritas_y_bajas_motivos(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    db.sembrar(("usuarios", "u1", "banco_preguntas_pdf", "d1"), {"estado": "completo"})
    db.sembrar(("usuarios", "u1", "banco_tarjetas_pdf", "d1"), {"estado": "completo"})
    db.sembrar(("usuarios", "u1", "preguntas_favoritas", "p1"), {"pregunta": "?"})
    db.sembrar(("usuarios", "u1", "bajas_motivos", "b1"), {"motivo": "precio"})

    with patch("gestion_cuenta.firebase_auth.delete_user"):
        eliminar_cuenta_usuario(db, "u1")

    assert db.leer(("usuarios", "u1", "banco_preguntas_pdf", "d1")) is None
    assert db.leer(("usuarios", "u1", "banco_tarjetas_pdf", "d1")) is None
    assert db.leer(("usuarios", "u1", "preguntas_favoritas", "p1")) is None
    assert db.leer(("usuarios", "u1", "bajas_motivos", "b1")) is None


def test_eliminar_cuenta_detiene_generaciones_en_curso(db):
    # Sin esto, un hilo de fondo seguía gastando llamadas a DeepSeek (ya
    # cobradas) sobre una cuenta que ya no existe -- ver
    # generacion_control.solicitar_parada_todas.
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    evento = generacion_control.registrar("u1", "d1", "resumen")
    try:
        with patch("gestion_cuenta.firebase_auth.delete_user"):
            eliminar_cuenta_usuario(db, "u1")
        assert evento.is_set()
    finally:
        generacion_control.desregistrar("u1", "d1", "resumen")


def test_ruta_exportar_datos(client, db, usuario_autenticado):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "nombre": "Ana"})
    usuario_autenticado()
    resp = client.get("/mi-cuenta/exportar-datos", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert resp.get_json()["perfil"]["nombre"] == "Ana"


def test_ruta_eliminar_cuenta(client, db, usuario_autenticado):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com"})
    usuario_autenticado()
    with patch("gestion_cuenta.firebase_auth.delete_user"):
        resp = client.delete("/mi-cuenta", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert db.leer(("usuarios", "u1")) is None
