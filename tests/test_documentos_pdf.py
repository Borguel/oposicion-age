"""Pruebas de documentos_pdf.py: obtener_o_crear_documento debe sumar las
páginas del documento al contador global paginas_analizadas del usuario
UNA sola vez -- si el mismo PDF se reutiliza en otra herramienta (mismo
texto, mismo hash), no debe volver a sumarse."""
from documentos_pdf import (
    obtener_o_crear_documento, actualizar_titulo, obtener_tests_en_progreso_por_documento,
    eliminar_documento, listar_documentos, iniciar_banco, anadir_al_banco, finalizar_banco,
    obtener_banco, _recortar_a_bytes_utf8, LIMITE_BYTES_TEXTO_DOCUMENTO,
    actualizar_tipo_contenido, resolver_tipo_contenido,
    actualizar_progreso_generacion, limpiar_progreso_generacion,
    obtener_preguntas_previas, _LIMITE_DOCUMENTOS_LISTADOS,
    marcar_generado, limite_regeneraciones_alcanzado, LIMITE_GENERACIONES_POR_DOCUMENTO,
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


class TestRecortarABytesUtf8:
    """05/08/2026: el texto guardado se recorta por BYTES de UTF-8 (no por
    nº de caracteres) para respetar de verdad el límite de 1 MiB por
    documento de Firestore -- con caracteres multibyte (tildes, ñ...) un
    recorte por caracteres no garantiza un tamaño en bytes concreto."""

    def test_texto_corto_no_se_toca(self):
        texto = "Un documento corto con tildes: ñ, á, é."
        assert _recortar_a_bytes_utf8(texto, 1000) == texto

    def test_texto_justo_en_el_limite_no_se_toca(self):
        texto = "a" * 500
        assert _recortar_a_bytes_utf8(texto, 500) == texto

    def test_recorta_cuando_supera_el_limite(self):
        texto = "a" * 1000
        recortado = _recortar_a_bytes_utf8(texto, 500)
        assert len(recortado.encode("utf-8")) <= 500
        assert recortado == "a" * 500

    def test_no_deja_a_medias_un_caracter_multibyte_en_el_corte(self):
        # "ñ" ocupa 2 bytes en UTF-8 -- un límite que caiga justo en medio
        # de uno no debe producir un carácter roto ni lanzar excepción.
        texto = "a" * 9 + "ñ" + "a" * 9  # 9 + 2 + 9 = 20 bytes en UTF-8
        recortado = _recortar_a_bytes_utf8(texto, 10)
        assert len(recortado.encode("utf-8")) <= 10
        # decode(errors="ignore") no debe dejar bytes sueltos que rompan la cadena.
        recortado.encode("utf-8").decode("utf-8")

    def test_documento_dentro_del_limite_guarda_el_texto_completo(self, db):
        db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "paginas_analizadas": 0})
        texto = "Fuentes del derecho, con tildes: artículo, según, ratificación. " * 200
        _id, documento = obtener_o_crear_documento(db, "u1", texto, "temario.pdf", num_paginas=20)
        assert documento["texto"] == texto

    def test_documento_muy_largo_se_recorta_por_debajo_del_limite_de_firestore(self, db):
        db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "paginas_analizadas": 0})
        texto = "Texto con tildes y eñes: artículo, según, año. " * 30000  # ~1,4M caracteres
        _id, documento = obtener_o_crear_documento(db, "u1", texto, "temario_largo.pdf", num_paginas=400)
        assert len(documento["texto"].encode("utf-8")) <= LIMITE_BYTES_TEXTO_DOCUMENTO
        # Muy por encima de lo que se guardaba con el límite antiguo de
        # 150.000 caracteres -- confirma que ahora aprovecha el margen real.
        assert len(documento["texto"]) > 150000


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


# Extractos usados en TestTipoContenido -- mismos umbrales calibrados que
# TestDetectarTextoLegal en tests/test_deepseek_utils.py (densidad,
# diversidad de patrones y suelo absoluto de coincidencias).
_TEXTO_LEGAL = (
    "Artículo 1. Objeto y ámbito de aplicación.\n"
    "La presente Ley 39/2015 regula los requisitos de validez y eficacia de los "
    "actos administrativos y el procedimiento administrativo común.\n\n"
    "Artículo 2. Ámbito subjetivo de aplicación.\n"
    "Esta ley se aplica al sector público, que comprende la Administración General "
    "del Estado y las Administraciones de las Comunidades Autónomas.\n\n"
    "Artículo 3. Principios generales.\n"
    "Las Administraciones Públicas actúan de acuerdo con los principios de "
    "eficacia, jerarquía, descentralización, desconcentración y coordinación.\n\n"
    "Artículo 4. Interesados en el procedimiento.\n"
    "Se consideran interesados en el procedimiento administrativo quienes lo "
    "promuevan como titulares de derechos o intereses legítimos.\n\n"
    "Disposición adicional primera. Especialidades por razón de materia.\n"
    "Las previsiones de esta Ley se aplicarán sin perjuicio de las especialidades "
    "de su legislación específica.\n\n"
    "El Real Decreto 203/2021, de 30 de marzo, desarrolla lo previsto en el "
    "artículo 14 de esta misma norma."
)
_TEXTO_GENERAL = (
    "El proceso de construcción europea comenzó tras la Segunda Guerra Mundial, "
    "con el objetivo de garantizar la paz y la prosperidad en el continente a "
    "través de la cooperación económica. Los llamados Padres Fundadores de "
    "Europa impulsaron la creación de la Comunidad Europea del Carbón y del "
    "Acero en 1951, germen de lo que hoy conocemos como la Unión Europea."
) * 3


class TestTipoContenido:
    # tipo_contenido (05/08/2026): auto-detectado con detectar_texto_legal
    # al crear el documento (ver obtener_o_crear_documento) para no
    # re-analizarlo cada vez que se regenera resumen/esquema/tarjetas/test
    # desde el mismo documento_id -- y resolver_tipo_contenido decide qué
    # usar en cada generación concreta, con el override manual del usuario
    # por delante de lo ya guardado.
    def test_obtener_o_crear_documento_detecta_y_guarda_legal(self, db):
        db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "paginas_analizadas": 0})
        _id, datos = obtener_o_crear_documento(db, "u1", _TEXTO_LEGAL, "ley.pdf", num_paginas=3)
        assert datos["tipo_contenido"] == "legal"

    def test_obtener_o_crear_documento_detecta_y_guarda_general(self, db):
        db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "paginas_analizadas": 0})
        _id, datos = obtener_o_crear_documento(db, "u1", _TEXTO_GENERAL, "tema.pdf", num_paginas=3)
        assert datos["tipo_contenido"] == "general"

    def test_actualizar_tipo_contenido_persiste_el_cambio(self, db):
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {"tipo_contenido": "general"})
        ok = actualizar_tipo_contenido(db, "u1", "d1", "legal")
        assert ok is True
        assert db.leer(("usuarios", "u1", "documentos", "d1"))["tipo_contenido"] == "legal"

    def test_actualizar_tipo_contenido_documento_inexistente_devuelve_false(self, db):
        assert actualizar_tipo_contenido(db, "u1", "no_existe", "legal") is False

    def test_resolver_tipo_contenido_override_true_gana_y_persiste(self, db):
        # El texto es narrativo (auto-detección daría "general"), pero el
        # usuario fuerza "legal" a mano -- debe ganar Y guardarse para que
        # la siguiente regeneración de este documento no necesite que lo
        # repita.
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {"tipo_contenido": "general"})
        tipo = resolver_tipo_contenido(db, "u1", "d1", {"tipo_contenido": "general"}, _TEXTO_GENERAL, True)
        assert tipo == "legal"
        assert db.leer(("usuarios", "u1", "documentos", "d1"))["tipo_contenido"] == "legal"

    def test_resolver_tipo_contenido_override_false_gana_y_persiste(self, db):
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {"tipo_contenido": "legal"})
        tipo = resolver_tipo_contenido(db, "u1", "d1", {"tipo_contenido": "legal"}, _TEXTO_LEGAL, False)
        assert tipo == "general"
        assert db.leer(("usuarios", "u1", "documentos", "d1"))["tipo_contenido"] == "general"

    def test_resolver_tipo_contenido_usa_lo_ya_guardado_sin_override(self, db):
        # El texto ahora sería "general" según detectar_texto_legal, pero
        # el documento ya tenía "legal" guardado (de una detección o un
        # override anterior) -- sin override en ESTA petición, debe
        # respetar lo ya guardado en vez de re-detectar.
        documento = {"tipo_contenido": "legal"}
        tipo = resolver_tipo_contenido(db, "u1", "d1", documento, _TEXTO_GENERAL, None)
        assert tipo == "legal"

    def test_resolver_tipo_contenido_sin_nada_guardado_detecta_y_persiste(self, db):
        # Documento sin tipo_contenido (p. ej. creado antes de este campo
        # existir): se detecta sobre la marcha Y se persiste, para que la
        # siguiente llamada ya no vuelva a pasar por aquí.
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {})
        tipo = resolver_tipo_contenido(db, "u1", "d1", {}, _TEXTO_LEGAL, None)
        assert tipo == "legal"
        assert db.leer(("usuarios", "u1", "documentos", "d1"))["tipo_contenido"] == "legal"


def test_listar_documentos_expone_tipo_contenido(db):
    db.sembrar(("usuarios", "u1"), {"email": "u1@example.com", "paginas_analizadas": 0})
    obtener_o_crear_documento(db, "u1", _TEXTO_LEGAL, "ley.pdf", num_paginas=3)
    resultado = listar_documentos(db, "u1")
    assert resultado[0]["tipo_contenido"] == "legal"


def test_listar_documentos_usa_general_por_defecto_si_falta_el_campo(db):
    # Documentos creados antes de que tipo_contenido existiera como campo.
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Viejo", "ultima_actividad": "2026-01-01"})
    resultado = listar_documentos(db, "u1")
    assert resultado[0]["tipo_contenido"] == "general"


def test_listar_documentos_sin_generacion_en_curso_progreso_es_none(db):
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Doc", "ultima_actividad": "2026-01-01"})
    resultado = listar_documentos(db, "u1")
    assert resultado[0]["progreso_resumen"] is None
    assert resultado[0]["progreso_esquema"] is None


def test_listar_documentos_no_trae_mas_de_un_limite_razonable(db):
    # 12/08/2026, bug real: sin límite, un usuario con muchos documentos
    # subidos traía la colección entera en cada carga de "Mis Documentos".
    for i in range(_LIMITE_DOCUMENTOS_LISTADOS + 5):
        db.sembrar(("usuarios", "u1", "documentos", f"d{i}"), {"titulo": f"Doc {i}", "ultima_actividad": "2026-01-01"})
    resultado = listar_documentos(db, "u1")
    assert len(resultado) == _LIMITE_DOCUMENTOS_LISTADOS


def test_marcar_generado_incrementa_el_contador_de_generaciones(db):
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Doc", "generaciones_resumen": 0, "generaciones_esquema": 0})
    marcar_generado(db, "u1", "d1", "resumen_pdf")
    doc = db.leer(("usuarios", "u1", "documentos", "d1"))
    assert doc["generaciones_resumen"] == 1
    assert doc["tiene_resumen"] is True
    marcar_generado(db, "u1", "d1", "resumen_pdf")
    assert db.leer(("usuarios", "u1", "documentos", "d1"))["generaciones_resumen"] == 2


def test_marcar_generado_resumen_y_esquema_llevan_contadores_independientes(db):
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Doc", "generaciones_resumen": 0, "generaciones_esquema": 0})
    marcar_generado(db, "u1", "d1", "resumen_pdf")
    marcar_generado(db, "u1", "d1", "resumen_pdf")
    marcar_generado(db, "u1", "d1", "esquema_pdf")
    doc = db.leer(("usuarios", "u1", "documentos", "d1"))
    assert doc["generaciones_resumen"] == 2
    assert doc["generaciones_esquema"] == 1


def test_limite_regeneraciones_alcanzado_con_el_tope_exacto():
    assert limite_regeneraciones_alcanzado({"generaciones_resumen": LIMITE_GENERACIONES_POR_DOCUMENTO}, "resumen") is True
    assert limite_regeneraciones_alcanzado({"generaciones_resumen": LIMITE_GENERACIONES_POR_DOCUMENTO - 1}, "resumen") is False


def test_limite_regeneraciones_alcanzado_documento_sin_el_campo_no_esta_agotado():
    # Documentos creados antes de que este campo existiera: empiezan a
    # contar desde ahora, no pierden regeneraciones ya hechas en el pasado.
    assert limite_regeneraciones_alcanzado({}, "resumen") is False
    assert limite_regeneraciones_alcanzado(None, "esquema") is False


def test_listar_documentos_expone_los_contadores_de_generaciones(db):
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {
        "titulo": "Doc", "ultima_actividad": "2026-01-01",
        "generaciones_resumen": 2, "generaciones_esquema": 1,
    })
    resultado = listar_documentos(db, "u1")
    assert resultado[0]["generaciones_resumen"] == 2
    assert resultado[0]["generaciones_esquema"] == 1


def test_listar_documentos_contadores_de_generaciones_a_cero_por_defecto(db):
    db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Doc viejo", "ultima_actividad": "2026-01-01"})
    resultado = listar_documentos(db, "u1")
    assert resultado[0]["generaciones_resumen"] == 0
    assert resultado[0]["generaciones_esquema"] == 0


def test_obtener_preguntas_previas_acota_la_consulta_no_solo_la_salida(db):
    # 12/08/2026, bug real: se traían TODOS los tests_pdf del documento y
    # solo se recortaba la lista final de preguntas -- ahora la propia
    # consulta a Firestore se acota con un margen prudente sobre `limite`.
    for i in range(30):
        db.sembrar(("usuarios", "u1", "tests_pdf", f"t{i}"), {
            "documento_id": "doc1",
            "preguntas": [{"pregunta": f"¿Pregunta {i}?", "opciones": {"A": "1"}, "respuesta_correcta": "A"}],
        })
    resultado = obtener_preguntas_previas(db, "u1", "doc1", limite=5)
    # Con el margen (limite * 3 = 15 tests_pdf leídos, 1 pregunta cada uno)
    # sigue habiendo de sobra para completar el límite final pedido.
    assert len(resultado) == 5


class TestProgresoGeneracion:
    """actualizar_progreso_generacion/limpiar_progreso_generacion (10/08/2026):
    permiten que /mis-documentos enseñe el progreso real de una generación
    de resumen/esquema en curso -- ver el comentario largo junto a su
    definición en documentos_pdf.py."""

    def test_actualizar_progreso_generacion_lo_deja_visible_en_listar_documentos(self, db):
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Doc", "ultima_actividad": "2026-01-01"})
        actualizar_progreso_generacion(db, "u1", "d1", "resumen", completadas=2, total=5, fase="generando")
        resultado = listar_documentos(db, "u1")
        progreso = resultado[0]["progreso_resumen"]
        assert progreso["completadas"] == 2
        assert progreso["total"] == 5
        assert progreso["fase"] == "generando"
        assert "actualizado" in progreso
        # El esquema no se ha tocado -- no debe verse afectado.
        assert resultado[0]["progreso_esquema"] is None

    def test_limpiar_progreso_generacion_lo_deja_en_none(self, db):
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Doc", "ultima_actividad": "2026-01-01"})
        actualizar_progreso_generacion(db, "u1", "d1", "esquema", completadas=1, total=3, fase="generando")
        limpiar_progreso_generacion(db, "u1", "d1", "esquema")
        resultado = listar_documentos(db, "u1")
        assert resultado[0]["progreso_esquema"] is None


class TestProgresoAtascado:
    # Mismo bug que TestBancoAtascado pero para progreso_resumen/progreso_
    # esquema (10/08/2026): si el hilo de fondo que genera un resumen o un
    # esquema muere a mitad (p. ej. un redeploy de Render), el progreso se
    # queda pegado en Firestore como "generando" para siempre -- ver
    # _progreso_atascado.

    def test_progreso_reciente_se_mantiene_como_generando(self, db):
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {"titulo": "Doc", "ultima_actividad": "2026-01-01"})
        actualizar_progreso_generacion(db, "u1", "d1", "resumen", completadas=2, total=5, fase="generando")
        resultado = listar_documentos(db, "u1")
        assert resultado[0]["progreso_resumen"]["completadas"] == 2
        assert resultado[0]["error_resumen"] is None

    def test_progreso_sin_actualizar_en_mucho_tiempo_se_reporta_como_error(self, db):
        from datetime import datetime, timedelta
        viejo = (datetime.utcnow() - timedelta(minutes=30)).isoformat()
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {
            "titulo": "Doc", "ultima_actividad": "2026-01-01",
            "progreso_resumen": {"completadas": 2, "total": 5, "fase": "generando", "actualizado": viejo},
        })
        resultado = listar_documentos(db, "u1")
        assert resultado[0]["progreso_resumen"] is None
        assert resultado[0]["error_resumen"]["mensaje"] == "La generación se interrumpió antes de terminar."
        # El esquema no se ha tocado -- no debe verse afectado.
        assert resultado[0]["progreso_esquema"] is None
        assert resultado[0]["error_esquema"] is None

    def test_progreso_sin_marca_de_tiempo_tambien_se_considera_atascado(self, db):
        # Progreso guardado antes de que "actualizado" existiera como campo.
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {
            "titulo": "Doc", "ultima_actividad": "2026-01-01",
            "progreso_esquema": {"completadas": 1, "total": 3, "fase": "generando"},
        })
        resultado = listar_documentos(db, "u1")
        assert resultado[0]["progreso_esquema"] is None
        assert resultado[0]["error_esquema"] is not None

    def test_error_de_una_generacion_normal_no_se_pisa_por_el_chequeo_de_atascado(self, db):
        # Un error real (marcar_error_generacion) sin progreso en curso no
        # debe verse afectado por _progreso_atascado (progreso=None -> nunca
        # se considera atascado).
        db.sembrar(("usuarios", "u1", "documentos", "d1"), {
            "titulo": "Doc", "ultima_actividad": "2026-01-01",
            "error_resumen": {"mensaje": "Fallo real de la IA", "fecha": "2026-01-01"},
        })
        resultado = listar_documentos(db, "u1")
        assert resultado[0]["progreso_resumen"] is None
        assert resultado[0]["error_resumen"]["mensaje"] == "Fallo real de la IA"


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
