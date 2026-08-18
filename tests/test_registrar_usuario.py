"""Pruebas de /registrar-usuario: valida nombre/apellidos/teléfono/dirección
antes de guardarlos (ver validacion_perfil.py) -- sin esto, cualquiera podía
registrar una cuenta con un enlace, HTML o una fórmula de hoja de cálculo
como "nombre", que luego se enseña tal cual en el panel admin, en las
exportaciones CSV y en el saludo de los correos transaccionales."""



def test_registrar_usuario_guarda_nombre_y_apellidos_validos(client, db, usuario_autenticado):
    usuario_autenticado()
    resp = client.post(
        "/registrar-usuario",
        json={
            "nombre": "María José",
            "apellidos": "O'Brien-García",
            "telefono": "+34 600 11 22 33",
        },
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 200
    datos = db.leer(("usuarios", "u1"))
    assert datos["nombre"] == "María José"
    assert datos["apellidos"] == "O'Brien-García"
    assert datos["telefono"] == "+34 600 11 22 33"


def test_registrar_usuario_admite_nombres_fuera_del_alfabeto_latino(client, db, usuario_autenticado):
    """No debe rechazar nombres reales solo por no ser caracteres latinos
    (cirílico, chino...) -- la validación es por TIPO de carácter
    (str.isalpha()), no por un rango fijo tipo A-Za-z."""
    usuario_autenticado()
    resp = client.post(
        "/registrar-usuario",
        json={"nombre": "Владимир", "apellidos": "李"},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 200
    datos = db.leer(("usuarios", "u1"))
    assert datos["nombre"] == "Владимир"
    assert datos["apellidos"] == "李"


def test_registrar_usuario_rechaza_nombre_con_enlace(client, db, usuario_autenticado):
    usuario_autenticado()
    resp = client.post(
        "/registrar-usuario",
        json={"nombre": "http://evil.example"},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 400
    assert not db.leer(("usuarios", "u1")).get("nombre")  # nunca se llega a escribir


def test_registrar_usuario_rechaza_nombre_con_formula_csv(client, db, usuario_autenticado):
    usuario_autenticado()
    resp = client.post(
        "/registrar-usuario",
        json={"nombre": '=HYPERLINK("http://evil.example")'},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 400


def test_registrar_usuario_rechaza_nombre_con_html(client, db, usuario_autenticado):
    usuario_autenticado()
    resp = client.post(
        "/registrar-usuario",
        json={"nombre": "<img src=x onerror=alert(1)>"},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 400


def test_registrar_usuario_rechaza_telefono_no_numerico(client, db, usuario_autenticado):
    usuario_autenticado()
    resp = client.post(
        "/registrar-usuario",
        json={"telefono": "llama-al 900"},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 400


def test_registrar_usuario_rechaza_direccion_con_enlace(client, db, usuario_autenticado):
    usuario_autenticado()
    resp = client.post(
        "/registrar-usuario",
        json={"direccion": "Visita www.evil.example para más info"},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 400


def test_registrar_usuario_admite_direccion_postal_normal(client, db, usuario_autenticado):
    usuario_autenticado()
    resp = client.post(
        "/registrar-usuario",
        json={"direccion": "Calle Mayor 12, 3º B, 28013 Madrid"},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 200
    assert db.leer(("usuarios", "u1"))["direccion"] == "Calle Mayor 12, 3º B, 28013 Madrid"
