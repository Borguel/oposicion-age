"""Pruebas de documentos_pdf.py: obtener_o_crear_documento debe sumar las
páginas del documento al contador global paginas_analizadas del usuario
UNA sola vez -- si el mismo PDF se reutiliza en otra herramienta (mismo
texto, mismo hash), no debe volver a sumarse."""
from documentos_pdf import obtener_o_crear_documento, actualizar_titulo


def test_documento_nuevo_suma_sus_paginas_al_contador_del_usuario(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "paginas_analizadas": 0})
    obtener_o_crear_documento(db, "u1", "Texto de prueba largo y distinto.", "apuntes.pdf", num_paginas=12)
    assert db.leer(("usuarios", "u1"))["paginas_analizadas"] == 12


def test_reutilizar_el_mismo_documento_no_vuelve_a_sumar_paginas(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "paginas_analizadas": 0})
    texto = "Mismo texto exacto para las dos herramientas."
    obtener_o_crear_documento(db, "u1", texto, "apuntes.pdf", num_paginas=8)
    # Se sube "de nuevo" el mismo PDF (mismo texto extraído) a otra
    # herramienta -- obtener_o_crear_documento debe devolver el documento
    # ya existente sin sumar las 8 páginas otra vez.
    obtener_o_crear_documento(db, "u1", texto, "apuntes.pdf", num_paginas=8)
    assert db.leer(("usuarios", "u1"))["paginas_analizadas"] == 8


def test_dos_documentos_distintos_suman_sus_paginas_por_separado(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "paginas_analizadas": 0})
    obtener_o_crear_documento(db, "u1", "Primer documento con su propio texto.", "a.pdf", num_paginas=5)
    obtener_o_crear_documento(db, "u1", "Segundo documento con texto diferente.", "b.pdf", num_paginas=7)
    assert db.leer(("usuarios", "u1"))["paginas_analizadas"] == 12


def test_actualizar_titulo_permite_renombrar_el_documento(db):
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Nombre automático", "nombre_archivo": "a.pdf"})
    ok = actualizar_titulo(db, "u1", "d1", "Mi nombre personalizado")
    assert ok is True
    assert db.leer(("usuarios", "u1", "documentos", "d1"))["titulo"] == "Mi nombre personalizado"


def test_actualizar_titulo_recorta_espacios_y_longitud(db):
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "x", "nombre_archivo": "a.pdf"})
    actualizar_titulo(db, "u1", "d1", "  " + ("Y" * 200) + "  ")
    titulo = db.leer(("usuarios", "u1", "documentos", "d1"))["titulo"]
    assert titulo == "Y" * 120


def test_actualizar_titulo_vacio_no_hace_nada(db):
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Original", "nombre_archivo": "a.pdf"})
    ok = actualizar_titulo(db, "u1", "d1", "   ")
    assert ok is False
    assert db.leer(("usuarios", "u1", "documentos", "d1"))["titulo"] == "Original"


def test_actualizar_titulo_documento_inexistente_devuelve_false(db):
    assert actualizar_titulo(db, "u1", "no_existe", "Nuevo nombre") is False
