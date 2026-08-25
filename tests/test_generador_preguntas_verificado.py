"""Pruebas del generador de Test Personalizado con arquitectura
generar -> verificar -> reintentar (generador_preguntas_verificado.py).

Lo más importante a cubrir: que una pregunta que no pasa la verificación se
descarta ENTERA y se reintenta desde cero (nunca se "corrige"), que el
artículo se recupera del texto real y no lo inventa el modelo, y que
agotar los intentos no bloquea el resto del test."""
import itertools
import json
import threading
from unittest.mock import patch

import generacion_control
from generador_preguntas_verificado import (
    MAX_RONDAS_RELLENO,
    _extraer_articulos,
    _elegir_ancla_legal,
    _generar_candidatos_lote,
    _generar_lote_preguntas_verificadas,
    _generar_pregunta_verificada,
    _prompt_generacion,
    _prompt_generacion_lote_normativo,
    _prompt_verificacion,
    _tema_es_normativo,
    generar_test_verificado,
)
from limites_uso import _clave_periodo
from utils import buscar_pregunta_banco_ia


def test_contenido_normativo_usa_prompts_juridicos():
    # Ancla con artículo detectado -> prompts jurídicos (exigen artículo, plazos,
    # lenguaje de la norma).
    anclas = [{"norma": "Ley 39/2015", "articulo": "Artículo 21",
               "texto_legal": "Artículo 21. La Administración está obligada a resolver.",
               "etiqueta_subbloque": "s1"}]
    system_gen, user_gen = _prompt_generacion(anclas, "memoria_literal", "AGE")
    system_ver, _user = _prompt_verificacion({"pregunta": "x"}, anclas)
    assert "TEXTO LEGAL" in user_gen
    assert "jurídic" in system_gen.lower()
    assert "jurídic" in system_ver.lower()


def test_prompt_normativo_exige_nombrar_la_norma_al_citar_un_articulo():
    # Regresión: una pregunta generada decía "Según el artículo 52.1..." sin
    # decir de qué ley -- el opositor no tenía forma de saber de qué norma
    # hablaba. El prompt de generación y el de verificación deben exigir
    # explícitamente que toda mención a un artículo vaya acompañada del
    # nombre de la norma.
    anclas = [{"norma": "Ley 29/1998, reguladora de la Jurisdicción Contencioso-Administrativa",
               "articulo": "Artículo 52.1",
               "texto_legal": "Artículo 52.1. Plazo común de vista a las partes.",
               "etiqueta_subbloque": "s1"}]
    system_gen, _user_gen = _prompt_generacion(anclas, "memoria_literal", "AGE")
    system_ver, _user_ver = _prompt_verificacion({"pregunta": "x"}, anclas)
    assert "nombre de la norma" in system_gen
    assert "nombre de la norma" in system_ver


def test_contenido_descriptivo_sin_articulos_usa_prompts_descriptivos():
    # Contenido de ofimática (sin "Artículo N.") -> prompts descriptivos: no
    # deben exigir artículos ni lenguaje jurídico, que es lo que hacía que se
    # descartara la mayoría de preguntas de estos temas.
    anclas = [{"norma": "Informática básica", "articulo": None,
               "texto_legal": "El sistema operativo gestiona los recursos del ordenador.",
               "etiqueta_subbloque": "s1"}]
    system_gen, user_gen = _prompt_generacion(anclas, "memoria_literal", "AGE")
    system_ver, _user = _prompt_verificacion({"pregunta": "x"}, anclas)
    assert "CONTENIDO 1" in user_gen
    assert "TEXTO LEGAL" not in user_gen
    assert "jurídic" not in system_gen.lower()
    assert "jurídic" not in system_ver.lower()
    # El verificador descriptivo debe decir EXPLÍCITAMENTE que no exija
    # artículos ni lenguaje legal (esa exigencia era la que descartaba las
    # preguntas de temas no normativos como ofimática).
    assert "no exijas artículos" in system_ver.lower()


def test_prompt_descriptivo_prohibe_remitir_al_contenido_invisible():
    # Regresión: "¿Qué tienen en común todas las escalas y auxiliares
    # mencionados en el contenido?" -- quien responde el test nunca ve el
    # material de origen, así que el prompt de generación y el de
    # verificación deben prohibir explícitamente ese tipo de remisión.
    anclas = [{"norma": "Organización de la Administración", "articulo": None,
               "texto_legal": "La escala de gestión y la escala auxiliar tienen funciones distintas.",
               "etiqueta_subbloque": "s1"}]
    system_gen, _user_gen = _prompt_generacion(anclas, "memoria_literal", "AGE")
    system_ver, _user_ver = _prompt_verificacion({"pregunta": "x"}, anclas)
    assert "mencionados en el contenido" in system_gen.lower()
    assert "mencionados en el contenido" in system_ver.lower()


def test_prompt_normativo_prohibe_abreviar_el_nombre_de_la_norma():
    # Los exámenes oficiales nunca abrevian ("CE" en vez de "Constitución
    # Española", "TREBEP", "LPAC"...) -- el prompt de generación y el de
    # verificación deben exigir el nombre completo.
    anclas = [{"norma": "Constitución Española", "articulo": "Artículo 24",
               "texto_legal": "Artículo 24. Todas las personas tienen derecho a la tutela judicial efectiva.",
               "etiqueta_subbloque": "s1"}]
    system_gen, _user_gen = _prompt_generacion(anclas, "memoria_literal", "AGE")
    system_ver, _user_ver = _prompt_verificacion({"pregunta": "x"}, anclas)
    assert "sigla" in system_gen.lower()
    assert '"ce"' in system_gen.lower()
    assert "sigla" in system_ver.lower()


def test_prompt_normativo_prohibe_abreviar_tipo_de_norma_con_numero():
    # Regresión: "Según la LO 3/2007..." abrevia "Ley Orgánica 3/2007" con el
    # tipo de norma + número en vez del nombre completo -- un patrón distinto
    # de las siglas fijas ("CE", "TREBEP"...) que el prompt debe cubrir
    # también, tanto en generación como en verificación.
    anclas = [{"norma": "Ley Orgánica 3/2007", "articulo": "Artículo 1",
               "texto_legal": "Artículo 1. Las mujeres y los hombres son iguales en dignidad humana.",
               "etiqueta_subbloque": "s1"}]
    system_gen, _user_gen = _prompt_generacion(anclas, "memoria_literal", "AGE")
    system_ver, _user_ver = _prompt_verificacion({"pregunta": "x"}, anclas)
    assert "lo 3/2007" in system_gen.lower()
    assert "lo 3/2007" in system_ver.lower()


def _pregunta_valida(texto_pregunta="¿Pregunta de ejemplo?"):
    return json.dumps({
        "norma": "Ley 39/2015",
        "articulo": "Artículo 1",
        "tipo_pregunta": "memoria_literal",
        "pregunta": texto_pregunta,
        "opciones": {"A": "Opción a", "B": "Opción b", "C": "Opción c", "D": "Opción d"},
        "respuesta_correcta": "A",
        "explicacion": "Explicación suficientemente larga para superar la validación estructural.",
        "referencia_legal": "Artículo 1",
    })


def test_extraer_articulos_trocea_por_articulo_real():
    texto = (
        "Artículo 66. Las Cortes Generales representan al pueblo español.\n\n"
        "Artículo 67. Nadie podrá ser miembro de las dos Cámaras simultáneamente."
    )
    fragmentos = _extraer_articulos(texto)
    assert [f["articulo"] for f in fragmentos] == ["Artículo 66", "Artículo 67"]
    assert "Cortes Generales" in fragmentos[0]["texto"]
    assert "Cortes Generales" not in fragmentos[1]["texto"]
    assert "dos Cámaras" in fragmentos[1]["texto"]


def test_extraer_articulos_sin_cabeceras_degrada_a_texto_completo():
    texto = "Disposición adicional única. Esta norma no numera artículos de esta forma."
    fragmentos = _extraer_articulos(texto)
    assert len(fragmentos) == 1
    assert fragmentos[0]["articulo"] is None
    assert fragmentos[0]["texto"] == texto


def test_elegir_ancla_legal_evita_repetir_subbloques_ya_usados():
    subbloques = [
        {"etiqueta": "s1", "titulo": "Norma A", "texto": "Artículo 1. Contenido de la norma A."},
        {"etiqueta": "s2", "titulo": "Norma B", "texto": "Artículo 5. Contenido de la norma B."},
    ]
    anclas = _elegir_ancla_legal(subbloques, {"s1"}, necesita_dos=False)
    assert len(anclas) == 1
    assert anclas[0]["etiqueta_subbloque"] == "s2"


def test_elegir_ancla_legal_distincion_articulos_devuelve_dos_articulos_distintos():
    subbloques = [{
        "etiqueta": "s1", "titulo": "Norma A",
        "texto": "Artículo 1. Primer contenido.\n\nArtículo 2. Segundo contenido distinto."
    }]
    anclas = _elegir_ancla_legal(subbloques, set(), necesita_dos=True)
    assert len(anclas) == 2
    assert anclas[0]["articulo"] != anclas[1]["articulo"]


def test_pregunta_invalida_se_descarta_entera_y_se_regenera_desde_cero():
    subbloques_tema = [{
        "etiqueta": "bloque_01-tema_01-sub_1", "titulo": "Ley 39/2015",
        "texto": "Artículo 1. Contenido real de ejemplo para anclar la pregunta."
    }]
    with patch("generador_preguntas_verificado.call_deepseek_api", side_effect=[
        _pregunta_valida("¿Primer intento, con un dato mal?"),   # generación intento 1
        json.dumps({"valido": False, "problemas": ["el plazo citado no coincide con el texto"]}),  # verificación 1
        _pregunta_valida("¿Segundo intento, ya correcto?"),      # generación intento 2 (desde cero)
        json.dumps({"valido": True, "problemas": []}),           # verificación 2
    ]) as mock_llamada:
        resultado = _generar_pregunta_verificada(
            subbloques_tema, "bloque_01-tema_01", "AGE",
            subbloques_ya_usados=set(), preguntas_ya_aceptadas=set(), lock=threading.Lock()
        )

    assert mock_llamada.call_count == 4
    # La pregunta final es la del SEGUNDO intento, nunca una versión
    # "corregida" del primero -- el primer intento se descartó por completo.
    assert resultado["pregunta"] == "¿Segundo intento, ya correcto?"
    assert resultado["tema_id"] == "bloque_01-tema_01"


def test_agotar_los_intentos_devuelve_none_sin_bloquear():
    subbloques_tema = [{
        "etiqueta": "bloque_01-tema_01-sub_1", "titulo": "Ley 39/2015",
        "texto": "Artículo 1. Contenido real de ejemplo para anclar la pregunta."
    }]
    with patch("generador_preguntas_verificado.call_deepseek_api", side_effect=[
        _pregunta_valida("¿Intento 1?"), json.dumps({"valido": False, "problemas": ["x"]}),
        _pregunta_valida("¿Intento 2?"), json.dumps({"valido": False, "problemas": ["y"]}),
    ]) as mock_llamada:
        resultado = _generar_pregunta_verificada(
            subbloques_tema, "bloque_01-tema_01", "AGE",
            subbloques_ya_usados=set(), preguntas_ya_aceptadas=set(), lock=threading.Lock(),
            max_intentos=2
        )

    assert resultado is None
    assert mock_llamada.call_count == 4  # 2 intentos x (generar + verificar), nunca más


def test_rechazo_de_verificacion_registra_errores_generacion(db):
    # Cada rechazo de la verificación legal (valido=False) debe dejar un
    # documento en errores_generacion con fuente="auto_verificacion", sin
    # cambiar en nada el comportamiento de reintento ya cubierto arriba.
    subbloques_tema = [{
        "etiqueta": "bloque_01-tema_01-sub_1", "titulo": "Ley 39/2015",
        "texto": "Artículo 1. Contenido real de ejemplo para anclar la pregunta."
    }]
    with patch("generador_preguntas_verificado.call_deepseek_api", side_effect=[
        _pregunta_valida("¿Primer intento, con un dato mal?"),
        json.dumps({"valido": False, "problemas": ["el plazo citado no coincide con el texto"]}),
        _pregunta_valida("¿Segundo intento, ya correcto?"),
        json.dumps({"valido": True, "problemas": []}),
    ]):
        resultado = _generar_pregunta_verificada(
            subbloques_tema, "bloque_01-tema_01", "AGE",
            subbloques_ya_usados=set(), preguntas_ya_aceptadas=set(), lock=threading.Lock(), db=db,
        )

    assert resultado["pregunta"] == "¿Segundo intento, ya correcto?"
    documentos = [doc.to_dict() for doc in db.collection("errores_generacion").stream()]
    assert len(documentos) == 1  # solo el intento rechazado, no el aceptado
    doc = documentos[0]
    assert doc["tema_id"] == "bloque_01-tema_01"
    assert doc["fuente"] == "auto_verificacion"
    assert doc["oposicion"] == "AGE"
    assert doc["tipo_error"] == "desfase_legal"  # heurística: menciona "plazo"
    assert doc["pregunta_texto"] == "¿Primer intento, con un dato mal?"
    assert doc["detalle"] == "el plazo citado no coincide con el texto"
    assert doc["intento_numero"] == 1
    assert doc["resuelto"] is False
    assert "timestamp" in doc


def test_sin_db_no_registra_nada_ni_falla(db):
    # generar_test_verificado siempre pasa db, pero _generar_pregunta_verificada
    # debe seguir funcionando sin él (valor por defecto None, ver tests de
    # arriba que no lo pasan) -- no debe registrar nada ni reventar.
    subbloques_tema = [{
        "etiqueta": "bloque_01-tema_01-sub_1", "titulo": "Ley 39/2015",
        "texto": "Artículo 1. Contenido real de ejemplo para anclar la pregunta."
    }]
    with patch("generador_preguntas_verificado.call_deepseek_api", side_effect=[
        _pregunta_valida("¿Intento?"), json.dumps({"valido": False, "problemas": ["x"]}),
        _pregunta_valida("¿Intento 2?"), json.dumps({"valido": True, "problemas": []}),
    ]):
        resultado = _generar_pregunta_verificada(
            subbloques_tema, "bloque_01-tema_01", "AGE",
            subbloques_ya_usados=set(), preguntas_ya_aceptadas=set(), lock=threading.Lock(),
        )

    assert resultado["pregunta"] == "¿Intento 2?"
    assert list(db.collection("errores_generacion").stream()) == []


def test_fallo_inesperado_en_un_intento_consume_solo_ese_intento():
    # Si la respuesta de verificación viene con una forma que ningún
    # "continue" contempla (aquí una lista en vez de un objeto, que hace
    # que verificacion.get(...) reviente con AttributeError), el intento se
    # descarta como cualquier otro y el hueco se recupera en el siguiente
    # -- no se pierde el hueco entero a la primera.
    subbloques_tema = [{
        "etiqueta": "bloque_01-tema_01-sub_1", "titulo": "Ley 39/2015",
        "texto": "Artículo 1. Contenido real de ejemplo para anclar la pregunta."
    }]
    with patch("generador_preguntas_verificado.call_deepseek_api", side_effect=[
        _pregunta_valida("¿Intento con verificación de forma rara?"),  # generación intento 1
        json.dumps([]),                                                # verificación 1: no es un objeto -> revienta
        _pregunta_valida("¿Segundo intento, ya normal?"),               # generación intento 2
        json.dumps({"valido": True, "problemas": []}),                  # verificación 2
    ]) as mock_llamada:
        resultado = _generar_pregunta_verificada(
            subbloques_tema, "bloque_01-tema_01", "AGE",
            subbloques_ya_usados=set(), preguntas_ya_aceptadas=set(), lock=threading.Lock()
        )

    assert mock_llamada.call_count == 4
    assert resultado["pregunta"] == "¿Segundo intento, ya normal?"


class TestGeneracionEnLote:
    """Generación EN LOTE de varias preguntas en una sola llamada (ver
    TAMANO_LOTE_GENERACION). NOTA (02/08/2026): este enrutamiento está
    DESACTIVADO en generar_test_verificado (con datos reales resultó menos
    fiable, no más rápido -- ver el comentario junto al bucle principal en
    generador_preguntas_verificado.py); las funciones de abajo siguen
    funcionando correctamente por sí solas y se prueban aquí de forma
    aislada, por si se retoma el enrutamiento más adelante con otro
    enfoque."""

    def test_tema_es_normativo_detecta_articulo_real(self):
        subbloques = [{"etiqueta": "s1", "titulo": "Ley X", "texto": "Artículo 1. Contenido normativo real."}]
        assert _tema_es_normativo(subbloques) is True

    def test_tema_es_normativo_false_sin_articulos(self):
        subbloques = [{"etiqueta": "s1", "titulo": "Informática", "texto": "El sistema operativo gestiona recursos."}]
        assert _tema_es_normativo(subbloques) is False

    def test_prompt_lote_incluye_cada_texto_legal_numerado_y_prohibe_mezclar(self):
        especificaciones = [
            {"anclas": [{"norma": "Ley 39/2015", "articulo": "Artículo 21",
                         "texto_legal": "Artículo 21. Texto A.", "etiqueta_subbloque": "s1"}],
             "tipo_pregunta": "memoria_literal"},
            {"anclas": [{"norma": "Ley 40/2015", "articulo": "Artículo 5",
                         "texto_legal": "Artículo 5. Texto B.", "etiqueta_subbloque": "s2"}],
             "tipo_pregunta": "pregunta_trampa"},
        ]
        system, user = _prompt_generacion_lote_normativo(especificaciones, "AGE")
        assert "TEXTO LEGAL 1" in user and "Texto A." in user
        assert "TEXTO LEGAL 2" in user and "Texto B." in user
        assert "PREGUNTA 1" in user and "PREGUNTA 2" in user
        assert "exactamente 2 elementos" in system
        # Regla explícita anti-contaminación entre preguntas del mismo lote.
        assert "NUNCA en el texto legal de otra pregunta del lote" in system

    def test_generar_candidatos_lote_empareja_por_pregunta_num_no_por_posicion(self):
        especificaciones = [
            {"anclas": [{"norma": "Ley A", "articulo": "Artículo 1", "texto_legal": "...", "etiqueta_subbloque": "s1"}],
             "tipo_pregunta": "memoria_literal"},
            {"anclas": [{"norma": "Ley B", "articulo": "Artículo 2", "texto_legal": "...", "etiqueta_subbloque": "s2"}],
             "tipo_pregunta": "comprension"},
        ]
        # El modelo las devuelve en orden invertido -- el emparejamiento debe
        # seguir siendo correcto porque se hace por pregunta_num, no por
        # posición en la lista.
        respuesta = json.dumps({"preguntas": [
            {"pregunta_num": 2, "pregunta": "¿Segunda?", "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"},
             "respuesta_correcta": "A", "explicacion": "Explicación suficientemente larga para pasar."},
            {"pregunta_num": 1, "pregunta": "¿Primera?", "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"},
             "respuesta_correcta": "A", "explicacion": "Explicación suficientemente larga para pasar."},
        ]})
        with patch("generador_preguntas_verificado.call_deepseek_api", return_value=respuesta):
            candidatos = _generar_candidatos_lote(especificaciones, "AGE", None, "contexto")
        assert candidatos[0]["pregunta"] == "¿Primera?"
        assert candidatos[1]["pregunta"] == "¿Segunda?"

    def test_generar_candidatos_lote_descarta_indice_repetido_en_vez_de_arriesgar_el_emparejamiento(self):
        # Dos elementos con el MISMO pregunta_num=1: mejor perder esa
        # posición que anclarla por error al texto legal de otra pregunta
        # -- eso aprobaría en la verificación posterior una pregunta
        # comparada contra el texto EQUIVOCADO.
        especificaciones = [
            {"anclas": [{"norma": "Ley A", "articulo": "Artículo 1", "texto_legal": "...", "etiqueta_subbloque": "s1"}],
             "tipo_pregunta": "memoria_literal"},
            {"anclas": [{"norma": "Ley B", "articulo": "Artículo 2", "texto_legal": "...", "etiqueta_subbloque": "s2"}],
             "tipo_pregunta": "comprension"},
        ]
        respuesta = json.dumps({"preguntas": [
            {"pregunta_num": 1, "pregunta": "¿Primera?", "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"},
             "respuesta_correcta": "A", "explicacion": "Explicación suficientemente larga para pasar."},
            {"pregunta_num": 1, "pregunta": "¿Duplicada?", "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"},
             "respuesta_correcta": "A", "explicacion": "Explicación suficientemente larga para pasar."},
        ]})
        with patch("generador_preguntas_verificado.call_deepseek_api", return_value=respuesta):
            candidatos = _generar_candidatos_lote(especificaciones, "AGE", None, "contexto")
        assert candidatos[0]["pregunta"] == "¿Primera?"
        assert candidatos[1] is None  # pregunta_num=2 nunca llegó

    def test_generar_candidatos_lote_devuelve_todo_none_si_la_llamada_falla(self):
        especificaciones = [
            {"anclas": [{"norma": "Ley A", "articulo": "Artículo 1", "texto_legal": "...", "etiqueta_subbloque": "s1"}],
             "tipo_pregunta": "memoria_literal"},
        ] * 3
        with patch("generador_preguntas_verificado.call_deepseek_api", return_value=None):
            candidatos = _generar_candidatos_lote(especificaciones, "AGE", None, "contexto")
        assert candidatos == [None, None, None]

    def test_generar_candidatos_lote_no_reintenta_internamente_si_trunca(self):
        # Un reintento de LOTE es caro (max_tokens ya varias veces mayor
        # que una llamada normal) -- si trunca, debe ceder el turno YA al
        # relleno final en vez de pagar un segundo intento gigante dentro
        # del mismo lote (ver max_reintentos_truncamiento=0 en la llamada).
        especificaciones = [
            {"anclas": [{"norma": "Ley A", "articulo": "Artículo 1", "texto_legal": "...", "etiqueta_subbloque": "s1"}],
             "tipo_pregunta": "memoria_literal"},
        ]
        with patch("generador_preguntas_verificado.call_deepseek_api", return_value=None) as mock_llamada:
            _generar_candidatos_lote(especificaciones, "AGE", None, "contexto")
        assert mock_llamada.call_args.kwargs["max_reintentos_truncamiento"] == 0

    def test_generar_lote_preguntas_verificadas_ancla_cada_pregunta_a_su_propio_tema(self):
        subbloques_por_tema = {
            "bloque_01-tema_01": [{"etiqueta": "s1", "titulo": "Ley A", "texto": "Artículo 1. Contenido A."}],
            "bloque_02-tema_01": [{"etiqueta": "s2", "titulo": "Ley B", "texto": "Artículo 2. Contenido B."}],
        }
        huecos_lote = ["bloque_01-tema_01", "bloque_02-tema_01"]

        def _mock(messages, **kwargs):
            if "PREGUNTA A VERIFICAR" in messages[-1]["content"]:
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps({"preguntas": [
                {"pregunta_num": 1, "pregunta": "¿Pregunta del tema 1?",
                 "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"}, "respuesta_correcta": "A",
                 "explicacion": "Explicación suficientemente larga para pasar la validación."},
                {"pregunta_num": 2, "pregunta": "¿Pregunta del tema 2?",
                 "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"}, "respuesta_correcta": "A",
                 "explicacion": "Explicación suficientemente larga para pasar la validación."},
            ]})

        with patch("generador_preguntas_verificado.call_deepseek_api", side_effect=_mock):
            resultados = _generar_lote_preguntas_verificadas(
                huecos_lote, subbloques_por_tema, "AGE",
                subbloques_ya_usados=set(), preguntas_ya_aceptadas=set(), lock=threading.Lock(),
            )
        assert resultados[0]["tema_id"] == "bloque_01-tema_01"
        assert resultados[0]["pregunta"] == "¿Pregunta del tema 1?"
        assert resultados[1]["tema_id"] == "bloque_02-tema_01"
        assert resultados[1]["pregunta"] == "¿Pregunta del tema 2?"

    def test_generar_lote_preguntas_verificadas_un_fallo_de_verificacion_no_tira_el_resto(self):
        # Si la verificación de UNA pregunta del lote falla (o revienta con
        # una forma inesperada), las demás del mismo lote deben seguir
        # aceptándose -- un lote no es "todo o nada".
        subbloques_por_tema = {
            "bloque_01-tema_01": [{"etiqueta": "s1", "titulo": "Ley A", "texto": "Artículo 1. Contenido A."}],
            "bloque_02-tema_01": [{"etiqueta": "s2", "titulo": "Ley B", "texto": "Artículo 2. Contenido B."}],
        }
        huecos_lote = ["bloque_01-tema_01", "bloque_02-tema_01"]

        def _mock(messages, **kwargs):
            contenido = messages[-1]["content"]
            if "PREGUNTA A VERIFICAR" in contenido:
                if "tema 1" in contenido:
                    return json.dumps({"valido": False, "problemas": ["no coincide con el texto"]})
                return json.dumps({"valido": True, "problemas": []})
            return json.dumps({"preguntas": [
                {"pregunta_num": 1, "pregunta": "¿Pregunta del tema 1?",
                 "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"}, "respuesta_correcta": "A",
                 "explicacion": "Explicación suficientemente larga para pasar la validación."},
                {"pregunta_num": 2, "pregunta": "¿Pregunta del tema 2?",
                 "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"}, "respuesta_correcta": "A",
                 "explicacion": "Explicación suficientemente larga para pasar la validación."},
            ]})

        with patch("generador_preguntas_verificado.call_deepseek_api", side_effect=_mock):
            resultados = _generar_lote_preguntas_verificadas(
                huecos_lote, subbloques_por_tema, "AGE",
                subbloques_ya_usados=set(), preguntas_ya_aceptadas=set(), lock=threading.Lock(),
            )
        assert resultados[0] is None  # tema 1: verificación rechazada
        assert resultados[1]["tema_id"] == "bloque_02-tema_01"  # tema 2: sobrevive igual

    def test_generar_lote_preguntas_verificadas_verifica_en_paralelo_no_secuencial(self):
        # Agrupar la GENERACIÓN en una sola llamada no debe mover el cuello
        # de botella a la verificación: verificar las N preguntas del lote
        # una detrás de otra tardaría tanto como las N llamadas de
        # generación que se acaban de ahorrar agrupándolas.
        import time
        RETRASO = 0.05
        subbloques_por_tema = {
            f"bloque_0{i}-tema_01": [{"etiqueta": f"s{i}", "titulo": f"Ley {i}", "texto": f"Artículo {i}. Contenido {i}."}]
            for i in range(1, 5)
        }
        huecos_lote = list(subbloques_por_tema.keys())

        def _mock(messages, **kwargs):
            contenido = messages[-1]["content"]
            if "PREGUNTA A VERIFICAR" in contenido:
                time.sleep(RETRASO)
                return json.dumps({"valido": True, "problemas": []})
            preguntas = [
                {"pregunta_num": i, "pregunta": f"¿Pregunta {i}?",
                 "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"}, "respuesta_correcta": "A",
                 "explicacion": "Explicación suficientemente larga para pasar la validación."}
                for i in range(1, 5)
            ]
            return json.dumps({"preguntas": preguntas})

        with patch("generador_preguntas_verificado.call_deepseek_api", side_effect=_mock):
            inicio = time.perf_counter()
            resultados = _generar_lote_preguntas_verificadas(
                huecos_lote, subbloques_por_tema, "AGE",
                subbloques_ya_usados=set(), preguntas_ya_aceptadas=set(), lock=threading.Lock(),
            )
            duracion = time.perf_counter() - inicio

        assert all(r is not None for r in resultados)
        # Secuencial habría tardado 4 * RETRASO; en paralelo debe quedar muy
        # por debajo (cota floja pero suficiente para distinguir "en
        # paralelo" de "uno detrás de otro").
        assert duracion < RETRASO * len(huecos_lote)

    # NOTA (02/08/2026): no hay test aquí de "generar_test_verificado usa el
    # lote" -- ese enrutamiento está DESACTIVADO (ver el comentario junto al
    # bucle principal en generador_preguntas_verificado.py). Las funciones
    # de lote de arriba siguen probadas de forma aislada (siguen
    # funcionando correctamente por sí solas); si se retoma el enrutamiento
    # más adelante, aquí es donde vuelve a tener sentido un test de
    # integración para ello.


def _mock_deepseek_siempre_valido(contador, lock_contador):
    # La generación en lote está DESACTIVADA en generar_test_verificado
    # (ver el comentario en el propio archivo, 02/08/2026) -- este mock
    # vuelve a su forma simple de siempre, sin detección de lote: los
    # tests de _generar_lote_preguntas_verificadas/_generar_candidatos_lote
    # más abajo usan sus propios mocks dedicados para ese formato.
    def _mock(messages, temperature=0.5, max_tokens=1000, response_format_json=False, on_usage=None, model=None, contexto=None, stream=False, frequency_penalty=None, max_reintentos_truncamiento=None, thinking_enabled=None):
        contenido_usuario = messages[-1]["content"]
        if "PREGUNTA A VERIFICAR" in contenido_usuario:
            return json.dumps({"valido": True, "problemas": []})
        with lock_contador:
            n = next(contador)
        return _pregunta_valida(f"¿Pregunta única número {n}?")
    return _mock


def test_generar_test_verificado_reparte_cupo_y_reporta_progreso(db):
    # obtener_subbloques_individuales descarta subbloques de menos de 30
    # palabras (mismo filtro que ya usaba el generador anterior de Test
    # Personalizado), así que el texto de prueba tiene que ser lo bastante
    # largo para no quedar fuera antes de tiempo.
    relleno = " ".join(["palabra"] * 30)
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 39/2015", "texto": f"Artículo 1. Contenido del primer subbloque del tema 1. {relleno}"
    })
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_2"), {
        "titulo": "Ley 40/2015", "texto": f"Artículo 5. Contenido del segundo subbloque del tema 1. {relleno}"
    })
    db.sembrar(("Temario AGE", "bloque_02", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 19/2013", "texto": f"Artículo 3. Contenido del tema 2. {relleno}"
    })

    eventos_progreso = []
    contador = itertools.count()
    lock_contador = threading.Lock()
    with patch("generador_preguntas_verificado.call_deepseek_api",
               side_effect=_mock_deepseek_siempre_valido(contador, lock_contador)), \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        resultado = generar_test_verificado(
            db, temas=["bloque_01-tema_01", "bloque_02-tema_01"], num_preguntas=4,
            coleccion="Temario AGE", oposicion="AGE",
            on_progreso=lambda evento: eventos_progreso.append(evento)
        )

    assert len(resultado["test"]) == 4
    assert resultado["descartadas"] == 0
    assert "advertencia" not in resultado
    assert len(eventos_progreso) == 4
    assert [e["completadas"] for e in eventos_progreso] == [1, 2, 3, 4]
    assert eventos_progreso[-1]["total"] == 4
    # Cada evento de progreso lleva también la pregunta recién aceptada
    # (para que el llamante pueda ir entregándola sin esperar al final).
    assert all(e["pregunta"] is not None for e in eventos_progreso)
    assert {e["pregunta"]["pregunta"] for e in eventos_progreso} == {p["pregunta"] for p in resultado["test"]}
    # Cada pregunta generada sabe de qué tema salió de verdad.
    temas_de_las_preguntas = {p["tema_id"] for p in resultado["test"]}
    assert temas_de_las_preguntas == {"bloque_01-tema_01", "bloque_02-tema_01"}

    # Toda pregunta aceptada se acumula también en el banco de preguntas de
    # esa oposición (ver banco_preguntas_ia.py) -- de momento solo para
    # tener un repositorio propio, no se usa aún en ninguna ruta pública.
    guardadas = [doc.to_dict() for doc in db.collection("banco_preguntas_ia_AGE").stream()]
    assert len(guardadas) == 4
    assert {p["pregunta"] for p in guardadas} == {p["pregunta"] for p in resultado["test"]}
    assert all(p["tema_id"] for p in guardadas)


def test_pregunta_recien_generada_se_encuentra_de_inmediato_en_tu_tutor(db):
    # Bug real visto en producción: la caché de obtener_preguntas_banco_ia
    # ya estaba "caliente" (p. ej. de un mensaje anterior a Tu Tutor) ANTES
    # de que el test personalizado generase esta pregunta -- sin la
    # invalidación tras guardar_pregunta_generada, buscar_pregunta_banco_ia
    # seguiría viendo el banco vacío hasta que venciera el TTL, y Tu Tutor no
    # podría dar el "DATO VERIFICADO" de una pregunta de su propio test recién
    # generado.
    relleno = " ".join(["palabra"] * 30)
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 39/2015", "texto": f"Artículo 1. Contenido del subbloque. {relleno}"
    })

    # Primer barrido: cachea el banco vacío (como si Tu Tutor ya se hubiera
    # usado para esta oposición antes de generar este test).
    buscar_pregunta_banco_ia(db, "AGE", "cualquier texto de prueba ya suficientemente largo para buscar")

    contador = itertools.count()
    lock_contador = threading.Lock()
    with patch("generador_preguntas_verificado.call_deepseek_api",
               side_effect=_mock_deepseek_siempre_valido(contador, lock_contador)), \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        resultado = generar_test_verificado(
            db, temas=["bloque_01-tema_01"], num_preguntas=1,
            coleccion="Temario AGE", oposicion="AGE",
        )

    pregunta_generada = resultado["test"][0]
    encontrada = buscar_pregunta_banco_ia(db, "AGE", pregunta_generada["pregunta"])
    assert encontrada is not None
    assert encontrada["pregunta"] == pregunta_generada["pregunta"]


def test_generar_test_verificado_sobrevive_a_un_fallo_inesperado_de_un_hueco(db):
    # Reproduce el caso real reportado: con varios huecos generándose en
    # paralelo, si UNO revienta con una excepción inesperada (aquí forzada
    # directamente sobre _generar_pregunta_verificada, simulando por ejemplo
    # una forma de respuesta de DeepSeek que ningún "continue" contemplaba),
    # las preguntas que los OTROS hilos ya habían aceptado no deben perderse
    # ni propagar el error hacia arriba -- se cuenta como una más descartada,
    # pero el relleno (ver test siguiente) le da una oportunidad más y
    # recupera igualmente el número de preguntas pedido.
    # _tema_es_normativo forzado a False: este test ejercita la vía
    # INDIVIDUAL (_generar_pregunta_verificada, la que patchea), no el lote
    # de generación (ver test_generar_lote... para la resiliencia dentro
    # de un lote, un camino distinto con su propio try/except).
    relleno = " ".join(["palabra"] * 30)
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 39/2015", "texto": f"Artículo 1. Contenido del subbloque. {relleno}"
    })

    contador = itertools.count()
    lock_contador = threading.Lock()

    def _peta_la_primera_vez(subbloques_tema, tema_id, oposicion, subbloques_ya_usados,
                              preguntas_ya_aceptadas, lock, on_usage=None, max_intentos=4):
        with lock_contador:
            n = next(contador)
        if n == 0:
            raise ValueError("forma de respuesta inesperada de DeepSeek")
        return {
            "pregunta": f"¿Pregunta {n}?",
            "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"},
            "respuesta_correcta": "A",
            "explicacion": "Explicación suficientemente larga para pasar la validación.",
            "tema_id": tema_id,
            "tipo_pregunta": "memoria_literal",
        }

    with patch("generador_preguntas_verificado._generar_pregunta_verificada",
               side_effect=_peta_la_primera_vez), \
         patch("generador_preguntas_verificado._tema_es_normativo", return_value=False), \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        resultado = generar_test_verificado(
            db, temas=["bloque_01-tema_01"], num_preguntas=3,
            coleccion="Temario AGE", oposicion="AGE"
        )

    # Las 2 preguntas de los huecos que SÍ funcionaron llegan igual, en vez
    # de perderse todas por el fallo del tercero, y el relleno recupera la
    # tercera que faltaba -- las 3 pedidas llegan igual.
    assert len(resultado["test"]) == 3
    assert resultado["descartadas"] == 1


def test_generar_test_verificado_rellena_hueco_agotado_con_otro_tema(db):
    # Caso real reportado: pedir 100 preguntas de AGE con temario de sobra y
    # recibir 99 -- un hueco concreto agotó sus MAX_INTENTOS_POR_PREGUNTA
    # (aquí forzado devolviendo None, como cuando la verificación rechaza la
    # pregunta las 4 veces) no debe traducirse en menos preguntas de las
    # pedidas si otro tema todavía tiene contenido disponible.
    # _tema_es_normativo forzado a False: este test ejercita la vía
    # INDIVIDUAL (_generar_pregunta_verificada, la que patchea), no el lote
    # de generación -- ver el comentario del test anterior.
    relleno = " ".join(["palabra"] * 30)
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 39/2015", "texto": f"Artículo 1. Contenido del tema 1. {relleno}"
    })
    db.sembrar(("Temario AGE", "bloque_02", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 19/2013", "texto": f"Artículo 3. Contenido del tema 2. {relleno}"
    })

    contador = itertools.count()
    lock_contador = threading.Lock()

    def _falla_siempre_el_tema_2(subbloques_tema, tema_id, oposicion, subbloques_ya_usados,
                                  preguntas_ya_aceptadas, lock, on_usage=None, max_intentos=4):
        if tema_id == "bloque_02-tema_01":
            return None  # agotó sus intentos "de verdad" -- ninguna superó la verificación
        with lock_contador:
            n = next(contador)
        return {
            "pregunta": f"¿Pregunta {n}?", "opciones": {"A": "a", "B": "b", "C": "c", "D": "d"},
            "respuesta_correcta": "A", "explicacion": "Explicación suficientemente larga para pasar.",
            "tema_id": tema_id, "tipo_pregunta": "memoria_literal",
        }

    with patch("generador_preguntas_verificado._generar_pregunta_verificada",
               side_effect=_falla_siempre_el_tema_2), \
         patch("generador_preguntas_verificado._tema_es_normativo", return_value=False), \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        resultado = generar_test_verificado(
            db, temas=["bloque_01-tema_01", "bloque_02-tema_01"], num_preguntas=2,
            coleccion="Temario AGE", oposicion="AGE"
        )

    # Las 2 preguntas pedidas llegan igual: la del tema 2 se pierde, pero el
    # relleno la recupera generando otra en el tema 1 (que sí tiene cupo).
    assert len(resultado["test"]) == 2
    assert resultado["descartadas"] == 1
    assert "advertencia" not in resultado


def test_generar_test_verificado_si_el_relleno_tambien_falla_avisa_del_numero_real(db):
    # Si NINGÚN tema tiene ya más contenido que dé preguntas válidas (aquí
    # forzado para que todo falle), el relleno no debe insistir sin límite
    # ni fingir que llegó al número pedido -- se entrega lo que haya y se
    # avisa, igual que antes de que existiera el relleno.
    # _tema_es_normativo forzado a False: este test ejercita la vía
    # INDIVIDUAL (_generar_pregunta_verificada, la que patchea), no el lote
    # de generación -- ver el comentario de los tests anteriores.
    relleno = " ".join(["palabra"] * 30)
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 39/2015", "texto": f"Artículo 1. Contenido del tema. {relleno}"
    })

    with patch("generador_preguntas_verificado._generar_pregunta_verificada", return_value=None), \
         patch("generador_preguntas_verificado._tema_es_normativo", return_value=False), \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        resultado = generar_test_verificado(
            db, temas=["bloque_01-tema_01"], num_preguntas=3,
            coleccion="Temario AGE", oposicion="AGE"
        )

    assert len(resultado["test"]) == 0
    # 3 huecos originales + MAX_RONDAS_RELLENO rondas de relleno (3 intentos
    # cada una, porque sigue faltando el total las 3 rondas) -- el relleno
    # también cuenta como descartada cuando falla de verdad, y se detiene
    # solo tras agotar las rondas, nunca insiste sin límite.
    assert resultado["descartadas"] == 3 + 3 * MAX_RONDAS_RELLENO
    assert "advertencia" in resultado
    assert "0 de 3" in resultado["advertencia"]


def test_generar_test_verificado_evento_parada_detiene_el_relleno(db):
    # Bug real (24/08/2026): esta generación no tenía forma alguna de
    # cancelarse -- ver generacion_control.py. evento_parada ya marcado
    # ANTES de arrancar debe saltarse todas las rondas de relleno (mismo
    # "punto de comprobación natural" que ya usan resumen/esquema), sin
    # que la función lance ninguna excepción ni deje de devolver lo que sí
    # se aceptó en el hueco original.
    relleno = " ".join(["palabra"] * 30)
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 39/2015", "texto": f"Artículo 1. Contenido del tema. {relleno}"
    })
    evento_parada = threading.Event()
    evento_parada.set()

    with patch("generador_preguntas_verificado._generar_pregunta_verificada", return_value=None), \
         patch("generador_preguntas_verificado._tema_es_normativo", return_value=False), \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        resultado = generar_test_verificado(
            db, temas=["bloque_01-tema_01"], num_preguntas=3,
            coleccion="Temario AGE", oposicion="AGE", evento_parada=evento_parada,
        )

    assert len(resultado["test"]) == 0
    # Solo los 3 huecos originales -- CERO rondas de relleno, porque el
    # evento ya estaba marcado antes de la primera comprobación.
    assert resultado["descartadas"] == 3
    assert "advertencia" in resultado


def test_generar_test_verificado_modo_realista_pondera_por_bloque(db):
    relleno = " ".join(["palabra"] * 30)
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 39/2015", "texto": f"Artículo 1. Contenido del bloque 1. {relleno}"
    })
    db.sembrar(("Temario AGE", "bloque_06", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 40/2015", "texto": f"Artículo 5. Contenido del bloque 6. {relleno}"
    })
    # bloque_06 concentra el 90% de las preguntas históricas de examenes
    # oficiales -> con modo_reparto="realista" debe llevarse la mayoría del
    # cupo del test personalizado, no la mitad como haría "equitativo".
    db.sembrar(("examenes_oficiales_AGE", "b1-0"), {"tipo": "pregunta", "tema_id": "bloque_01-tema_01"})
    for i in range(9):
        db.sembrar(("examenes_oficiales_AGE", f"b6-{i}"), {"tipo": "pregunta", "tema_id": "bloque_06-tema_01"})

    contador = itertools.count()
    lock_contador = threading.Lock()
    with patch("generador_preguntas_verificado.call_deepseek_api",
               side_effect=_mock_deepseek_siempre_valido(contador, lock_contador)), \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        resultado = generar_test_verificado(
            db, temas=["bloque_01-tema_01", "bloque_06-tema_01"], num_preguntas=10,
            coleccion="Temario AGE", oposicion="AGE", modo_reparto="realista"
        )

    assert len(resultado["test"]) == 10
    temas_de_las_preguntas = [p["tema_id"] for p in resultado["test"]]
    assert temas_de_las_preguntas.count("bloque_06-tema_01") == 9
    assert temas_de_las_preguntas.count("bloque_01-tema_01") == 1


def test_generar_test_verificado_sin_temas_no_falla(db):
    resultado = generar_test_verificado(db, temas=[], num_preguntas=5, coleccion="Temario AGE", oposicion="AGE")
    assert resultado["test"] == []
    assert "advertencia" in resultado


def test_generar_test_verificado_sin_contenido_real_no_falla(db):
    resultado = generar_test_verificado(
        db, temas=["bloque_99-tema_99"], num_preguntas=5, coleccion="Temario AGE", oposicion="AGE"
    )
    assert resultado["test"] == []
    assert "advertencia" in resultado


# ============================================================
# Ruta /generar-test-avanzado en streaming (Server-Sent Events)
# ============================================================

def _eventos_sse(cuerpo_respuesta):
    return [
        json.loads(linea[len("data: "):])
        for linea in cuerpo_respuesta.split("\n\n")
        if linea.startswith("data: ")
    ]


def test_ruta_generar_test_avanzado_emite_eventos_y_registra_uso(client, db, usuario_autenticado):
    relleno = " ".join(["palabra"] * 30)
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 39/2015", "texto": f"Artículo 1. Contenido real de prueba. {relleno}"
    })
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active"}}
    })
    usuario_autenticado()
    contador = itertools.count()
    lock_contador = threading.Lock()
    with patch("generador_preguntas_verificado.call_deepseek_api",
               side_effect=_mock_deepseek_siempre_valido(contador, lock_contador)), \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        resp = client.post(
            "/generar-test-avanzado",
            json={"temas": ["bloque_01-tema_01"], "num_preguntas": 2, "oposicion": "AGE"},
            headers={"Authorization": "Bearer x"}
        )
        # El cuerpo hay que leerlo (drenar el generador SSE del todo)
        # TODAVÍA dentro del "with": la ruta lanza un hilo en segundo
        # plano que sigue llamando a call_deepseek_api mientras se
        # consume el stream, así que si se lee fuera del "with" el mock
        # ya se ha desactivado a medias y algunas llamadas usan la
        # función real (fallando por falta de red en el sandbox).
        cuerpo = resp.get_data(as_text=True)
    assert resp.status_code == 200
    eventos = _eventos_sse(cuerpo)
    assert eventos[-1]["tipo"] == "fin"
    assert len(eventos[-1]["test"]) == 2
    # También se han retransmitido eventos de progreso reales por el
    # camino, no solo el resultado final de golpe.
    assert any(e["tipo"] == "progreso" for e in eventos)
    # Y las preguntas aceptadas se retransmiten individualmente en
    # cuanto están listas, en un evento aparte -- para que el frontend
    # pueda empezar el test antes de que termine todo el streaming.
    eventos_pregunta = [e for e in eventos if e["tipo"] == "pregunta"]
    assert len(eventos_pregunta) == 2
    assert all("pregunta" in e and "opciones" in e["pregunta"] for e in eventos_pregunta)
    # El evento "progreso" no debe llevar la pregunta duplicada dentro.
    assert all("pregunta" not in e for e in eventos if e["tipo"] == "progreso")
    datos_usuario = db.leer(("usuarios", "u1"))
    # El cupo se mide en preguntas: un test de 2 preguntas gasta 2 unidades
    # -- en el cupo diario Y en el tope mensual adicional, a la vez.
    assert datos_usuario["limites_uso"]["test_avanzado_verificado"]["dia"]["contador"] == 2
    assert datos_usuario["limites_uso"]["test_avanzado_verificado_mensual"]["mes"]["contador"] == 2


def test_ruta_generar_test_avanzado_no_deja_registro_colgado_en_generacion_control(client, db, usuario_autenticado):
    # Bug real (24/08/2026): esta ruta no registraba nada en
    # generacion_control -- ni borrar la cuenta ni ningún otro mecanismo
    # podían pararla nunca (ver generacion_control.solicitar_parada_todas,
    # ya usado por eliminar_cuenta_usuario y el webhook de Stripe). Tras
    # una generación normal que termina bien, no debe quedar ningún
    # registro colgado (el "finally" del hilo de fondo desregistra
    # siempre, con éxito o sin él).
    relleno = " ".join(["palabra"] * 30)
    db.sembrar(("Temario AGE", "bloque_01", "temas", "tema_01", "subbloques", "sub_1"), {
        "titulo": "Ley 39/2015", "texto": f"Artículo 1. Contenido real de prueba. {relleno}"
    })
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active"}}
    })
    usuario_autenticado()
    contador = itertools.count()
    lock_contador = threading.Lock()
    with patch("generador_preguntas_verificado.call_deepseek_api",
               side_effect=_mock_deepseek_siempre_valido(contador, lock_contador)), \
         patch("utils.contar_tokens", side_effect=lambda texto, modelo="gpt-3.5-turbo": len(texto.split())):
        resp = client.post(
            "/generar-test-avanzado",
            json={"temas": ["bloque_01-tema_01"], "num_preguntas": 1, "oposicion": "AGE"},
            headers={"Authorization": "Bearer x"}
        )
        resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert generacion_control.solicitar_parada_todas("u1") == 0


def test_ruta_generar_test_avanzado_429_si_supera_el_limite(client, db, usuario_autenticado):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active"}},
        "limites_uso": {"test_avanzado_verificado": {"dia": {"clave": _clave_periodo("dia"), "contador": 300}}}
    })
    usuario_autenticado()
    with patch("generador_preguntas_verificado.call_deepseek_api") as mock_llamada:
        resp = client.post(
            "/generar-test-avanzado",
            json={"temas": ["bloque_01-tema_01"], "num_preguntas": 2, "oposicion": "AGE"},
            headers={"Authorization": "Bearer x"}
        )
    assert resp.status_code == 429
    mock_llamada.assert_not_called()


def test_ruta_generar_test_avanzado_429_si_supera_el_tope_mensual_aunque_el_diario_este_libre(client, db, usuario_autenticado):
    # El tope mensual es un cupo INDEPENDIENTE del diario: agotarlo bloquea
    # la ruta aunque el contador diario esté a cero (p. ej. si el usuario ya
    # gastó su cupo mensual en días anteriores).
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "basico", "subscription_status": "active"}},
        "limites_uso": {"test_avanzado_verificado_mensual": {"mes": {"clave": _clave_periodo("mes"), "contador": 400}}}
    })
    usuario_autenticado()
    with patch("generador_preguntas_verificado.call_deepseek_api") as mock_llamada:
        resp = client.post(
            "/generar-test-avanzado",
            json={"temas": ["bloque_01-tema_01"], "num_preguntas": 2, "oposicion": "AGE"},
            headers={"Authorization": "Bearer x"}
        )
    assert resp.status_code == 429
    mock_llamada.assert_not_called()


def test_ruta_generar_test_avanzado_bloqueada_para_plan_gratis(client, db, usuario_autenticado):
    db.sembrar(("usuarios", "u1"), {
        "email": "u1@example.com",
        "suscripciones": {"AGE": {"plan": "gratis"}}
    })
    usuario_autenticado()
    resp = client.post(
        "/generar-test-avanzado",
        json={"temas": ["bloque_01-tema_01"], "num_preguntas": 2, "oposicion": "AGE"},
        headers={"Authorization": "Bearer x"}
    )
    assert resp.status_code == 403
