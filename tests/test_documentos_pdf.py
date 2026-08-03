"""Pruebas de documentos_pdf.py: obtener_o_crear_documento debe sumar las
páginas del documento al contador global paginas_analizadas del usuario
UNA sola vez -- si el mismo PDF se reutiliza en otra herramienta (mismo
texto, mismo hash), no debe volver a sumarse."""
from documentos_pdf import (
    obtener_o_crear_documento, actualizar_titulo, obtener_tests_en_progreso_por_documento,
    eliminar_documento, listar_documentos, iniciar_banco, anadir_al_banco, finalizar_banco,
    obtener_banco,
)


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


class TestEliminarDocumento:
    # Pensado sobre todo para poder quitar una subida duplicada de la
    # biblioteca -- borra el documento y descuenta del contador
    # paginas_analizadas del usuario las páginas que había sumado al
    # crearse (ver obtener_o_crear_documento).

    def test_elimina_el_documento_y_descuenta_sus_paginas(self, db):
        db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "paginas_analizadas": 20})
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Apuntes", "num_paginas": 12})

        ok = eliminar_documento(db, "u1", "d1")

        assert ok is True
        assert db.leer(("usuarios", "u1", "documentos", "d1")) is None
        assert db.leer(("usuarios", "u1"))["paginas_analizadas"] == 8

    def test_documento_inexistente_devuelve_false(self, db):
        db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "paginas_analizadas": 20})
        assert eliminar_documento(db, "u1", "no_existe") is False
        assert db.leer(("usuarios", "u1"))["paginas_analizadas"] == 20

    def test_no_afecta_a_otros_documentos_del_usuario(self, db):
        db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "paginas_analizadas": 20})
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Duplicado", "num_paginas": 5})
        db.sembrar(("usuarios", "u1", "documentos", "d2"), {"titulo": "Bueno", "num_paginas": 15})

        eliminar_documento(db, "u1", "d1")

        assert db.leer(("usuarios", "u1", "documentos", "d1")) is None
        assert db.leer(("usuarios", "u1", "documentos", "d2")) is not None
        assert db.leer(("usuarios", "u1"))["paginas_analizadas"] == 15

    def test_documento_sin_num_paginas_no_rompe(self, db):
        db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "paginas_analizadas": 3})
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Sin páginas registradas"})

        ok = eliminar_documento(db, "u1", "d1")

        assert ok is True
        assert db.leer(("usuarios", "u1"))["paginas_analizadas"] == 3


class TestObtenerTestsEnProgresoPorDocumento:
    # Para que "Mis documentos" pueda ofrecer "Continuar" en la fila de
    # Test cuando hay un autoguardado sin terminar -- antes, un test
    # empezado y no acabado no aparecía por ningún sitio en la biblioteca.

    def test_test_en_progreso_de_un_documento(self, db):
        db.sembrar(("usuarios", "u1", "tests", "t1"), {
            "estado": "en_progreso", "tipo": "test_pdf", "documento_id": "d1", "fecha": "2026-01-01",
        })
        assert obtener_tests_en_progreso_por_documento(db, "u1") == {"d1": "t1"}

    def test_test_finalizado_no_cuenta(self, db):
        db.sembrar(("usuarios", "u1", "tests", "t1"), {
            "estado": "finalizado", "tipo": "test_pdf", "documento_id": "d1", "fecha": "2026-01-01",
        })
        assert obtener_tests_en_progreso_por_documento(db, "u1") == {}

    def test_test_personalizado_en_progreso_no_cuenta(self, db):
        # Un test en_progreso que no es de PDF (personalizado, oficial...)
        # no tiene documento_id que ofrecer en la biblioteca de documentos.
        db.sembrar(("usuarios", "u1", "tests", "t1"), {
            "estado": "en_progreso", "tipo": "personalizado", "documento_id": None, "fecha": "2026-01-01",
        })
        assert obtener_tests_en_progreso_por_documento(db, "u1") == {}

    def test_se_queda_con_el_mas_reciente_si_hay_varios(self, db):
        db.sembrar(("usuarios", "u1", "tests", "viejo"), {
            "estado": "en_progreso", "tipo": "test_pdf", "documento_id": "d1", "fecha": "2026-01-01",
        })
        db.sembrar(("usuarios", "u1", "tests", "nuevo"), {
            "estado": "en_progreso", "tipo": "test_pdf", "documento_id": "d1", "fecha": "2026-06-01",
        })
        assert obtener_tests_en_progreso_por_documento(db, "u1") == {"d1": "nuevo"}

    def test_sin_tests_devuelve_vacio(self, db):
        assert obtener_tests_en_progreso_por_documento(db, "u1") == {}


class TestBancoPreguntasYTarjetas:
    # Banco de preguntas/tarjetas pre-generado en segundo plano (03/08/2026):
    # iniciar_banco/anadir_al_banco/finalizar_banco persisten de forma
    # incremental (ver el comentario largo junto a iniciar_banco en
    # documentos_pdf.py) para que un banco a medio generar no se pierda si
    # el proceso se corta a mitad.

    def test_obtener_banco_inexistente_devuelve_none(self, db):
        assert obtener_banco(db, "u1", "d1", "preguntas") is None

    def test_iniciar_banco_deja_estado_generando_y_sin_items(self, db):
        iniciar_banco(db, "u1", "d1", "preguntas", objetivo=100, nombre_archivo="a.pdf")
        banco = obtener_banco(db, "u1", "d1", "preguntas")
        assert banco["estado"] == "generando"
        assert banco["objetivo"] == 100
        assert banco["total"] == 0
        assert banco["preguntas"] == []
        assert banco["nombre_archivo"] == "a.pdf"

    def test_anadir_al_banco_acumula_items_y_total(self, db):
        iniciar_banco(db, "u1", "d1", "preguntas", objetivo=100, nombre_archivo="a.pdf")
        anadir_al_banco(db, "u1", "d1", "preguntas", {"pregunta": "¿Uno?"})
        anadir_al_banco(db, "u1", "d1", "preguntas", {"pregunta": "¿Dos?"})
        banco = obtener_banco(db, "u1", "d1", "preguntas")
        assert banco["total"] == 2
        assert [p["pregunta"] for p in banco["preguntas"]] == ["¿Uno?", "¿Dos?"]

    def test_anadir_al_banco_de_tarjetas_usa_su_propia_coleccion(self, db):
        iniciar_banco(db, "u1", "d1", "tarjetas", objetivo=50, nombre_archivo="a.pdf")
        anadir_al_banco(db, "u1", "d1", "tarjetas", {"pregunta": "¿Qué es X?", "respuesta": "Y"})
        banco_tarjetas = obtener_banco(db, "u1", "d1", "tarjetas")
        assert banco_tarjetas["total"] == 1
        # No debe haber tocado el banco de preguntas del mismo documento.
        assert obtener_banco(db, "u1", "d1", "preguntas") is None

    def test_finalizar_banco_completo(self, db):
        iniciar_banco(db, "u1", "d1", "preguntas", objetivo=100, nombre_archivo="a.pdf")
        finalizar_banco(db, "u1", "d1", "preguntas", estado="completo")
        assert obtener_banco(db, "u1", "d1", "preguntas")["estado"] == "completo"

    def test_finalizar_banco_error_guarda_mensaje(self, db):
        iniciar_banco(db, "u1", "d1", "preguntas", objetivo=100, nombre_archivo="a.pdf")
        finalizar_banco(db, "u1", "d1", "preguntas", estado="error", mensaje_error="Fallo de generación")
        banco = obtener_banco(db, "u1", "d1", "preguntas")
        assert banco["estado"] == "error"
        assert banco["mensaje_error"] == "Fallo de generación"

    def test_listar_documentos_incluye_resumen_del_banco(self, db):
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Doc 1", "nombre_archivo": "a.pdf"})
        iniciar_banco(db, "u1", "d1", "preguntas", objetivo=100, nombre_archivo="a.pdf")
        anadir_al_banco(db, "u1", "d1", "preguntas", {"pregunta": "¿Uno?"})
        finalizar_banco(db, "u1", "d1", "preguntas", estado="completo")

        documentos = {d["id"]: d for d in listar_documentos(db, "u1")}
        assert documentos["d1"]["banco_preguntas_estado"] == "completo"
        assert documentos["d1"]["banco_preguntas_total"] == 1
        assert documentos["d1"]["banco_preguntas_objetivo"] == 100
        # Sin banco de tarjetas para este documento: debe caer en los
        # valores por defecto en vez de romper.
        assert documentos["d1"]["banco_tarjetas_estado"] == "sin_generar"
        assert documentos["d1"]["banco_tarjetas_total"] == 0

    def test_listar_documentos_sin_ningun_banco_usa_valores_por_defecto(self, db):
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Doc 1", "nombre_archivo": "a.pdf"})
        documentos = {d["id"]: d for d in listar_documentos(db, "u1")}
        assert documentos["d1"]["banco_preguntas_estado"] == "sin_generar"
        assert documentos["d1"]["banco_preguntas_total"] == 0
        assert documentos["d1"]["banco_tarjetas_estado"] == "sin_generar"


class TestBancoAtascado:
    # Bug real reportado (03/08/2026): un banco puede quedarse "generando"
    # para siempre si el hilo de fondo que lo rellena muere sin llegar a
    # llamar a finalizar_banco -- el caso típico es un despliegue/reinicio
    # del servidor a mitad de generación. obtener_banco/_resumen_bancos
    # deben dejar de tratarlo como "en curso" pasados unos minutos sin
    # ninguna actualización, para que la UI pueda ofrecer reintentar en vez
    # de mostrar "Generando..." indefinidamente.

    def test_banco_generando_reciente_se_mantiene_generando(self, db):
        from datetime import datetime
        iniciar_banco(db, "u1", "d1", "preguntas", objetivo=100, nombre_archivo="a.pdf")
        anadir_al_banco(db, "u1", "d1", "preguntas", {"pregunta": "¿Uno?"})
        assert obtener_banco(db, "u1", "d1", "preguntas")["estado"] == "generando"

    def test_banco_generando_sin_actualizar_en_mucho_tiempo_se_reporta_atascado(self, db):
        from datetime import datetime, timedelta
        iniciar_banco(db, "u1", "d1", "preguntas", objetivo=100, nombre_archivo="a.pdf")
        viejo = (datetime.utcnow() - timedelta(minutes=30)).isoformat()
        db.sembrar(("usuarios", "u1", "banco_preguntas_pdf", "d1"), {
            "estado": "generando", "total": 3, "objetivo": 100, "actualizado": viejo,
        })
        assert obtener_banco(db, "u1", "d1", "preguntas")["estado"] == "atascado"

    def test_banco_completo_no_se_ve_afectado_por_la_antiguedad(self, db):
        from datetime import datetime, timedelta
        viejo = (datetime.utcnow() - timedelta(days=30)).isoformat()
        db.sembrar(("usuarios", "u1", "banco_preguntas_pdf", "d1"), {
            "estado": "completo", "total": 20, "objetivo": 100, "actualizado": viejo,
        })
        assert obtener_banco(db, "u1", "d1", "preguntas")["estado"] == "completo"

    def test_listar_documentos_refleja_el_banco_atascado(self, db):
        from datetime import datetime, timedelta
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Doc 1", "nombre_archivo": "a.pdf"})
        viejo = (datetime.utcnow() - timedelta(minutes=30)).isoformat()
        db.sembrar(("usuarios", "u1", "banco_preguntas_pdf", "d1"), {
            "estado": "generando", "total": 3, "objetivo": 100, "actualizado": viejo,
        })
        documentos = {d["id"]: d for d in listar_documentos(db, "u1")}
        assert documentos["d1"]["banco_preguntas_estado"] == "atascado"
