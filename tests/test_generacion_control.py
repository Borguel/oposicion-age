"""Pruebas de generacion_control.py: registro en memoria de eventos de
parada por generación en curso (uid + documento_id + herramienta)."""
import generacion_control as gc


def test_registrar_devuelve_un_evento_no_marcado():
    evento = gc.registrar("u1", "d1", "resumen")
    try:
        assert not evento.is_set()
    finally:
        gc.desregistrar("u1", "d1", "resumen")


def test_solicitar_parada_marca_el_evento_registrado():
    evento = gc.registrar("u1", "d1", "resumen")
    try:
        ok = gc.solicitar_parada("u1", "d1", "resumen")
        assert ok is True
        assert evento.is_set()
    finally:
        gc.desregistrar("u1", "d1", "resumen")


def test_solicitar_parada_sin_generacion_en_curso_devuelve_false():
    assert gc.solicitar_parada("u1", "no-existe", "resumen") is False


def test_desregistrar_hace_que_solicitar_parada_deje_de_encontrarla():
    gc.registrar("u1", "d1", "resumen")
    gc.desregistrar("u1", "d1", "resumen")
    assert gc.solicitar_parada("u1", "d1", "resumen") is False


def test_claves_distintas_no_se_pisan():
    # Mismo documento, dos herramientas distintas (p. ej. resumen y
    # esquema a la vez) -- parar una no debe afectar a la otra. Igual con
    # el mismo uid+herramienta mismo pero distinto documento.
    evento_resumen = gc.registrar("u1", "d1", "resumen")
    evento_esquema = gc.registrar("u1", "d1", "esquema")
    evento_otro_doc = gc.registrar("u1", "d2", "resumen")
    try:
        gc.solicitar_parada("u1", "d1", "resumen")
        assert evento_resumen.is_set()
        assert not evento_esquema.is_set()
        assert not evento_otro_doc.is_set()
    finally:
        gc.desregistrar("u1", "d1", "resumen")
        gc.desregistrar("u1", "d1", "esquema")
        gc.desregistrar("u1", "d2", "resumen")


def test_solicitar_parada_todas_marca_todas_las_generaciones_del_usuario():
    evento_resumen = gc.registrar("u1", "d1", "resumen")
    evento_esquema = gc.registrar("u1", "d1", "esquema")
    evento_otro_doc = gc.registrar("u1", "d2", "banco_preguntas")
    evento_otro_usuario = gc.registrar("u2", "d1", "resumen")
    try:
        total = gc.solicitar_parada_todas("u1")
        assert total == 3
        assert evento_resumen.is_set()
        assert evento_esquema.is_set()
        assert evento_otro_doc.is_set()
        assert not evento_otro_usuario.is_set()
    finally:
        gc.desregistrar("u1", "d1", "resumen")
        gc.desregistrar("u1", "d1", "esquema")
        gc.desregistrar("u1", "d2", "banco_preguntas")
        gc.desregistrar("u2", "d1", "resumen")


def test_solicitar_parada_todas_sin_generaciones_en_curso_devuelve_cero():
    assert gc.solicitar_parada_todas("u-sin-generaciones") == 0


def test_registrar_de_nuevo_sobre_la_misma_clave_da_un_evento_fresco():
    # Si por lo que sea quedó un registro viejo sin desregistrar (no
    # debería pasar en producción, ver el finally de blueprints/pdf_ia),
    # una nueva generación sobre la misma clave debe partir de un evento
    # limpio, no heredar un "marcado" de la vez anterior.
    evento_viejo = gc.registrar("u1", "d1", "resumen")
    evento_viejo.set()
    evento_nuevo = gc.registrar("u1", "d1", "resumen")
    try:
        assert not evento_nuevo.is_set()
        assert evento_nuevo is not evento_viejo
    finally:
        gc.desregistrar("u1", "d1", "resumen")
