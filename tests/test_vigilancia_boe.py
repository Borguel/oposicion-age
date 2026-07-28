"""Pruebas de vigilancia_boe.py: nunca publica/aplica nada sola -- solo
crea documentos "pendiente" en avisos_oficiales / cambios_temario_propuestos
para que el dueño los revise desde el panel de admin."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import requests

import vigilancia_boe
from oposiciones import coleccion_temario


def _fecha_hace(dias):
    return (datetime.utcnow().date() - timedelta(days=dias)).strftime("%Y%m%d")


def _fake_response(dato_json):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=dato_json)
    return resp


def _sumario_con_item(identificador, titulo, url_html="https://www.boe.es/x"):
    # Estructura deliberadamente anidada de forma distinta a como se
    # "esperaría" -- _buscar_lista/_buscar_clave la deben encontrar solo
    # por el nombre de la clave, sin depender de una ruta fija exacta.
    return {
        "data": {"sumario": {"diario": [{"seccion": [{
            "item": [{"identificador": identificador, "titulo": titulo, "url_html": url_html}]
        }]}]}}
    }


def _respuesta_http_error(status_code):
    resp = MagicMock()
    resp.status_code = status_code
    error = requests.exceptions.HTTPError(response=resp)
    resp.raise_for_status = MagicMock(side_effect=error)
    return resp


class TestGetJsonReintentos:
    # _get_json antes fallaba directo ante cualquier error -- un 502/503/504
    # transitorio del BOE perdía el día entero. Ahora reintenta unas pocas
    # veces con backoff, solo para esos códigos.

    def test_reintenta_en_502_y_acaba_devolviendo_el_resultado_bueno(self):
        respuestas = [_respuesta_http_error(502), _respuesta_http_error(502), _fake_response({"ok": True})]
        with patch("vigilancia_boe.requests.get", side_effect=respuestas), \
             patch("vigilancia_boe.time.sleep") as mock_sleep:
            resultado = vigilancia_boe._get_json("https://www.boe.es/x")

        assert resultado == {"ok": True}
        assert mock_sleep.call_count == 2  # una espera antes de cada reintento

    def test_agota_los_reintentos_y_devuelve_none(self):
        respuestas = [_respuesta_http_error(503)] * vigilancia_boe._REINTENTOS_TRANSITORIOS_BOE
        with patch("vigilancia_boe.requests.get", side_effect=respuestas), \
             patch("vigilancia_boe.time.sleep"):
            resultado = vigilancia_boe._get_json("https://www.boe.es/x")

        assert resultado is None

    def test_un_404_no_se_reintenta(self):
        with patch("vigilancia_boe.requests.get", return_value=_respuesta_http_error(404)) as mock_get, \
             patch("vigilancia_boe.time.sleep") as mock_sleep:
            resultado = vigilancia_boe._get_json("https://www.boe.es/x")

        assert resultado is None
        mock_get.assert_called_once()  # sin reintentos para un error no transitorio
        mock_sleep.assert_not_called()


def test_detectar_avisos_oficiales_crea_aviso_pendiente(db):
    titulo = (
        "Resolución de la Subsecretaría por la que se aprueba la convocatoria del proceso selectivo para "
        "ingreso en el Cuerpo General Administrativo del Estado"
    )
    with patch("vigilancia_boe.requests.get", return_value=_fake_response(_sumario_con_item("BOE-A-2026-100", titulo))):
        creados = vigilancia_boe.detectar_avisos_oficiales(db)

    assert creados == 1
    avisos = list(db.collection("avisos_oficiales").stream())
    assert len(avisos) == 1
    d = avisos[0].to_dict()
    assert d["oposiciones"] == ["AGE"]
    assert d["tipo"] == "convocatoria"
    assert d["estado"] == "pendiente"
    assert d["titulo"] == titulo


def test_detectar_avisos_oficiales_una_resolucion_para_varios_cuerpos_crea_un_solo_aviso(db):
    # Menciona a la vez al Cuerpo General Administrativo (AGE) y al de
    # Gestión (GACE) -- debe quedar en UN solo aviso con las dos
    # oposiciones, no en dos avisos duplicados (uno por oposición).
    titulo = (
        "Resolución conjunta por la que se publica el llamamiento extraordinario del ejercicio único del "
        "Cuerpo General Administrativo del Estado y del Cuerpo de Gestión de la Administración Civil del Estado"
    )
    with patch("vigilancia_boe.requests.get", return_value=_fake_response(_sumario_con_item("BOE-A-2026-200", titulo))):
        creados = vigilancia_boe.detectar_avisos_oficiales(db)

    assert creados == 1
    avisos = list(db.collection("avisos_oficiales").stream())
    assert len(avisos) == 1
    assert avisos[0].to_dict()["oposiciones"] == ["AGE", "GACE"]


def test_detectar_avisos_oficiales_no_duplica_uno_ya_visto(db):
    titulo = "Convocatoria del Cuerpo General Administrativo del Estado"
    db.sembrar(("config", "vigilancia_boe"), {"avisos_ids_vistos": ["BOE-A-2026-100"]})
    with patch("vigilancia_boe.requests.get", return_value=_fake_response(_sumario_con_item("BOE-A-2026-100", titulo))):
        creados = vigilancia_boe.detectar_avisos_oficiales(db)

    assert creados == 0
    assert list(db.collection("avisos_oficiales").stream()) == []


def test_detectar_avisos_oficiales_ignora_mencion_sin_tipo_de_aviso_reconocible(db):
    # Menciona el cuerpo pero no ninguna palabra de convocatoria/lista/examen.
    titulo = "Nombramiento de un funcionario del Cuerpo General Administrativo del Estado"
    with patch("vigilancia_boe.requests.get", return_value=_fake_response(_sumario_con_item("BOE-A-2026-100", titulo))):
        creados = vigilancia_boe.detectar_avisos_oficiales(db)
    assert creados == 0


def test_clasificar_aviso_llamamiento_extraordinario_no_es_fecha_examen():
    # Un llamamiento extraordinario (repesca a un grupo reducido de
    # aspirantes) es distinto de la fecha del ejercicio de la convocatoria
    # oficial -- tipos separados a propósito, ver ETIQUETA_TIPO_AVISO.
    titulo = "Resolución por la que se publica el llamamiento extraordinario del ejercicio único"
    assert vigilancia_boe._clasificar_aviso(titulo) == "llamamiento_extraordinario"

    titulo_normal = "Resolución por la que se fija la fecha de examen del Cuerpo General Administrativo"
    assert vigilancia_boe._clasificar_aviso(titulo_normal) == "fecha_examen"


def test_detectar_avisos_oficiales_ignora_lo_irrelevante_para_las_3_oposiciones(db):
    titulo = "Convocatoria de becas de investigación para el Cuerpo de Ingenieros de Montes"
    with patch("vigilancia_boe.requests.get", return_value=_fake_response(_sumario_con_item("BOE-A-2026-100", titulo))):
        creados = vigilancia_boe.detectar_avisos_oficiales(db)
    assert creados == 0


def test_leyes_vigiladas_bloque_tema_bien_formado():
    # Guarda mínima contra erratas al ampliar LEYES_VIGILADAS a mano: cada
    # entrada debe apuntar a una de las 3 oposiciones reales, sin ids
    # repetidos dentro de la misma ley (repetir (oposicion, bloque, tema)
    # generaría la misma propuesta dos veces).
    oposiciones_validas = {"AGE", "GACE", "AUXILIAR"}
    for boe_id, config_ley in vigilancia_boe.LEYES_VIGILADAS.items():
        assert config_ley["nombre"]
        vistos = set()
        for oposicion, bloque_id, tema_id in config_ley["bloque_tema"]:
            assert oposicion in oposiciones_validas, f"{boe_id}: oposición desconocida {oposicion!r}"
            assert bloque_id and tema_id, f"{boe_id}: bloque/tema vacío para {oposicion!r}"
            clave = (oposicion, bloque_id, tema_id)
            assert clave not in vistos, f"{boe_id}: entrada duplicada {clave!r}"
            vistos.add(clave)


def _metadatos(fecha):
    return {"data": {"metadatos": {"fecha_actualizacion": fecha}}}


def _indice(ids_bloque):
    return {"data": {"texto": {"bloque": [{"id": i} for i in ids_bloque]}}}


def _bloque(fecha_publicacion, texto):
    return {"data": {"texto": {"version": [{"fecha_publicacion": fecha_publicacion, "texto": texto}]}}}


def test_detectar_cambios_leyes_vigiladas_crea_propuesta_pendiente(db):
    # Aislado del resto de LEYES_VIGILADAS reales (que van creciendo con el
    # tiempo) para que este test compruebe solo el filtrado de bloques de
    # artículo vs. disposición, sin acoplarse a cuántas leyes haya
    # configuradas en producción en cada momento.
    boe_id = "BOE-A-2015-11719"
    ley_trebep = vigilancia_boe.LEYES_VIGILADAS[boe_id]
    oposicion, bloque_id, tema_id = ley_trebep["bloque_tema"][0]
    db.sembrar(
        (coleccion_temario(oposicion), bloque_id, "temas", tema_id, "subbloques", "c1"),
        {"titulo": "TREBEP", "texto": "El plazo es de quince días hábiles."},
    )

    llamadas_bloque = []

    def _get(url, headers=None, timeout=None):
        if "metadatos" in url:
            return _fake_response(_metadatos("2026-01-15"))
        if "texto/indice" in url:
            # Mezcla real vista en producción: artículos + disposiciones
            # (transitoria/derogatoria/final) -- las disposiciones deben
            # descartarse ANTES de pedir su texto (la API del BOE devuelve
            # 400 para ellas, y el temario nunca las usa).
            return _fake_response(_indice(["a1", "dttercera", "ddunica", "dfprimera"]))
        if "texto/bloque" in url:
            llamadas_bloque.append(url)
            return _fake_response(_bloque("2026-01-10", "El plazo es de veinte días hábiles."))
        raise AssertionError(f"URL inesperada: {url}")

    with patch("vigilancia_boe.LEYES_VIGILADAS", {boe_id: ley_trebep}), \
         patch("vigilancia_boe.requests.get", side_effect=_get), \
         patch("generador_diff_temario.generar_propuesta_cambio", return_value={
             "chunk_id_afectado": "c1",
             "resumen": "El plazo pasa de quince a veinte días hábiles.",
             "texto_eliminar": "quince días hábiles",
             "texto_anadir": "veinte días hábiles",
         }):
        creadas = vigilancia_boe.detectar_cambios_leyes_vigiladas(db)

    assert creadas == 1
    # Solo se pidió el texto del bloque de artículo -- las 3 disposiciones
    # ("dttercera", "ddunica", "dfprimera") se descartaron sin llamar a la API.
    assert llamadas_bloque == ["https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/BOE-A-2015-11719/texto/bloque/a1"]
    propuestas = list(db.collection("cambios_temario_propuestos").stream())
    assert len(propuestas) == creadas
    d = propuestas[0].to_dict()
    assert d["estado"] == "pendiente"
    assert d["texto_eliminar"] == "quince días hábiles"
    assert d["texto_anadir"] == "veinte días hábiles"
    assert d["boe_id"] == boe_id

    # El estado (fecha_actualizacion vista) queda guardado para no
    # regenerar la misma propuesta en el siguiente ciclo.
    estado = db.leer(("config", "vigilancia_boe"))
    assert estado["leyes_fecha_vista"][boe_id] == "2026-01-15"


def test_detectar_cambios_leyes_vigiladas_no_hace_nada_si_la_ley_no_cambio(db):
    # Mismo aislamiento que el test anterior -- solo importa que, para UNA
    # ley cuya fecha ya está vista, no se pida más que /metadatos.
    boe_id = "BOE-A-2015-11719"
    ley_trebep = vigilancia_boe.LEYES_VIGILADAS[boe_id]
    db.sembrar(("config", "vigilancia_boe"), {"leyes_fecha_vista": {boe_id: "2026-01-15"}})

    with patch("vigilancia_boe.LEYES_VIGILADAS", {boe_id: ley_trebep}), \
         patch("vigilancia_boe.requests.get", return_value=_fake_response(_metadatos("2026-01-15"))) as mock_get, \
         patch("generador_diff_temario.generar_propuesta_cambio") as mock_generar:
        creadas = vigilancia_boe.detectar_cambios_leyes_vigiladas(db)

    assert creadas == 0
    mock_generar.assert_not_called()
    # Sin cambio de fecha, solo se llama a /metadatos (nunca se piden
    # índice/bloques de una ley que no ha cambiado).
    assert all("metadatos" in c.args[0] for c in mock_get.call_args_list)


def test_bloque_con_texto_solo_espacios_se_descarta(db):
    # or "" en _buscar_clave(...) solo protege contra ausencia/None -- un
    # texto que sea solo espacios/saltos de línea pasaría el filtro
    # "if not texto_nuevo" sin el .strip().
    boe_id = "BOE-A-2015-11719"
    ley_trebep = vigilancia_boe.LEYES_VIGILADAS[boe_id]
    oposicion, bloque_id, tema_id = ley_trebep["bloque_tema"][0]
    db.sembrar(
        (coleccion_temario(oposicion), bloque_id, "temas", tema_id, "subbloques", "c1"),
        {"titulo": "TREBEP", "texto": "El plazo es de quince días hábiles."},
    )

    def _get(url, headers=None, timeout=None):
        if "metadatos" in url:
            return _fake_response(_metadatos("2026-01-15"))
        if "texto/indice" in url:
            return _fake_response(_indice(["a1"]))
        if "texto/bloque" in url:
            return _fake_response(_bloque("2026-01-10", "   \n   "))
        raise AssertionError(f"URL inesperada: {url}")

    with patch("vigilancia_boe.LEYES_VIGILADAS", {boe_id: ley_trebep}), \
         patch("vigilancia_boe.requests.get", side_effect=_get), \
         patch("generador_diff_temario.generar_propuesta_cambio") as mock_generar:
        creadas = vigilancia_boe.detectar_cambios_leyes_vigiladas(db)

    assert creadas == 0
    mock_generar.assert_not_called()


class TestExistePropuestaPendienteReciente:
    # Dedup de cambios_temario_propuestos: evita generar la misma
    # propuesta dos veces si el workflow se dispara dos veces seguidas
    # (p. ej. un reintento manual mientras la ejecución anterior sigue en
    # curso, antes de que leyes_fecha_vista se actualice al final).

    def test_true_si_ya_hay_una_pendiente_reciente(self, db):
        db.sembrar(("cambios_temario_propuestos", "p1"), {
            "boe_id": "BOE-A-X", "subbloque_id": "c1", "estado": "pendiente",
            "fecha_deteccion": datetime.utcnow().isoformat(),
        })
        assert vigilancia_boe._existe_propuesta_pendiente_reciente(db, "BOE-A-X", "c1") is True

    def test_false_si_no_hay_ninguna(self, db):
        assert vigilancia_boe._existe_propuesta_pendiente_reciente(db, "BOE-A-X", "c1") is False

    def test_false_si_la_unica_pendiente_es_de_otro_subbloque(self, db):
        db.sembrar(("cambios_temario_propuestos", "p1"), {
            "boe_id": "BOE-A-X", "subbloque_id": "c2", "estado": "pendiente",
            "fecha_deteccion": datetime.utcnow().isoformat(),
        })
        assert vigilancia_boe._existe_propuesta_pendiente_reciente(db, "BOE-A-X", "c1") is False

    def test_ignora_una_ya_antigua_fuera_de_la_ventana(self, db):
        db.sembrar(("cambios_temario_propuestos", "p1"), {
            "boe_id": "BOE-A-X", "subbloque_id": "c1", "estado": "pendiente",
            "fecha_deteccion": (datetime.utcnow() - timedelta(hours=72)).isoformat(),
        })
        assert vigilancia_boe._existe_propuesta_pendiente_reciente(db, "BOE-A-X", "c1") is False

    def test_ignora_una_ya_no_pendiente(self, db):
        db.sembrar(("cambios_temario_propuestos", "p1"), {
            "boe_id": "BOE-A-X", "subbloque_id": "c1", "estado": "aprobado",
            "fecha_deteccion": datetime.utcnow().isoformat(),
        })
        assert vigilancia_boe._existe_propuesta_pendiente_reciente(db, "BOE-A-X", "c1") is False

    def test_si_la_consulta_falla_no_rompe_y_asume_que_no_hay_duplicado(self):
        # Simula, por ejemplo, que el índice compuesto de Firestore
        # todavía no se ha creado en la consola -- nunca debe reventar el
        # ciclo completo de vigilancia por esto.
        db_roto = MagicMock()
        db_roto.collection.side_effect = Exception("The query requires an index")
        assert vigilancia_boe._existe_propuesta_pendiente_reciente(db_roto, "BOE-A-X", "c1") is False


def test_detectar_cambios_leyes_vigiladas_no_duplica_si_ya_hay_propuesta_pendiente_reciente(db):
    boe_id = "BOE-A-2015-11719"
    ley_trebep = vigilancia_boe.LEYES_VIGILADAS[boe_id]
    oposicion, bloque_id, tema_id = ley_trebep["bloque_tema"][0]
    db.sembrar(
        (coleccion_temario(oposicion), bloque_id, "temas", tema_id, "subbloques", "c1"),
        {"titulo": "TREBEP", "texto": "El plazo es de quince días hábiles."},
    )
    db.sembrar(("cambios_temario_propuestos", "ya_existe"), {
        "boe_id": boe_id, "subbloque_id": "c1", "estado": "pendiente",
        "fecha_deteccion": datetime.utcnow().isoformat(),
    })

    def _get(url, headers=None, timeout=None):
        if "metadatos" in url:
            return _fake_response(_metadatos("2026-01-15"))
        if "texto/indice" in url:
            return _fake_response(_indice(["a1"]))
        if "texto/bloque" in url:
            return _fake_response(_bloque("2026-01-10", "El plazo es de veinte días hábiles."))
        raise AssertionError(f"URL inesperada: {url}")

    with patch("vigilancia_boe.LEYES_VIGILADAS", {boe_id: ley_trebep}), \
         patch("vigilancia_boe.requests.get", side_effect=_get), \
         patch("generador_diff_temario.generar_propuesta_cambio", return_value={
             "chunk_id_afectado": "c1",
             "resumen": "El plazo pasa de quince a veinte días hábiles.",
             "texto_eliminar": "quince días hábiles",
             "texto_anadir": "veinte días hábiles",
         }):
        creadas = vigilancia_boe.detectar_cambios_leyes_vigiladas(db)

    assert creadas == 0
    propuestas = list(db.collection("cambios_temario_propuestos").stream())
    assert len(propuestas) == 1  # solo la ya sembrada, no se duplicó


def test_verificar_bloque_temas_referenciados_sin_faltantes_si_todo_existe(db):
    ley = {
        "nombre": "Ley de prueba",
        "bloque_tema": [("AGE", "bloque_01", "tema_01")],
    }
    db.sembrar(
        (coleccion_temario("AGE"), "bloque_01", "temas", "tema_01", "subbloques", "c1"),
        {"titulo": "x", "texto": "algo de contenido"},
    )

    with patch("vigilancia_boe.LEYES_VIGILADAS", {"BOE-A-TEST": ley}):
        faltantes = vigilancia_boe.verificar_bloque_temas_referenciados(db)

    assert faltantes == []
    estado = db.leer(("config", "vigilancia_boe"))
    assert estado["temas_faltantes"] == []
    assert estado["temas_faltantes_fecha"]


def test_verificar_bloque_temas_referenciados_detecta_tema_inexistente(db):
    ley = {
        "nombre": "Ley de prueba",
        "bloque_tema": [
            ("AGE", "bloque_01", "tema_01"),
            ("GACE", "bloque_09", "tema_99"),  # no existe en el temario
        ],
    }
    db.sembrar(
        (coleccion_temario("AGE"), "bloque_01", "temas", "tema_01", "subbloques", "c1"),
        {"titulo": "x", "texto": "algo de contenido"},
    )

    with patch("vigilancia_boe.LEYES_VIGILADAS", {"BOE-A-TEST": ley}):
        faltantes = vigilancia_boe.verificar_bloque_temas_referenciados(db)

    assert faltantes == [{"oposicion": "GACE", "bloque_id": "bloque_09", "tema_id": "tema_99"}]
    estado = db.leer(("config", "vigilancia_boe"))
    assert estado["temas_faltantes"] == faltantes


def test_verificar_bloque_temas_referenciados_no_duplica_entre_leyes(db):
    # La misma (oposicion, bloque_id, tema_id) referenciada por 2 leyes
    # distintas solo debe contarse una vez en el resultado.
    leyes = {
        "BOE-A-UNO": {"nombre": "Ley uno", "bloque_tema": [("AGE", "bloque_09", "tema_99")]},
        "BOE-A-DOS": {"nombre": "Ley dos", "bloque_tema": [("AGE", "bloque_09", "tema_99")]},
    }
    with patch("vigilancia_boe.LEYES_VIGILADAS", leyes):
        faltantes = vigilancia_boe.verificar_bloque_temas_referenciados(db)

    assert faltantes == [{"oposicion": "AGE", "bloque_id": "bloque_09", "tema_id": "tema_99"}]


class TestFechasARevisar:
    # _fechas_a_revisar es lo que decide qué días de sumario del BOE se
    # miran en cada ejecución -- antes de esto, detectar_avisos_oficiales
    # solo miraba "hoy", y cualquier publicación de un día en que el cron
    # no corrió (el caso real: el workflow se activó el 23/07/2026, un día
    # DESPUÉS del RD 606/2026 del 22/07/2026) se perdía para siempre.

    def test_sin_estado_previo_hace_backfill_maximo(self):
        fechas = vigilancia_boe._fechas_a_revisar({})
        assert len(fechas) == vigilancia_boe._DIAS_MAX_BACKFILL
        assert fechas[-1] == datetime.utcnow().strftime("%Y%m%d")

    def test_con_ultima_fecha_revisada_ayer_solo_devuelve_hoy(self):
        estado = {"avisos_ultima_fecha_revisada": _fecha_hace(1)}
        assert vigilancia_boe._fechas_a_revisar(estado) == [datetime.utcnow().strftime("%Y%m%d")]

    def test_con_hueco_revisa_los_dias_intermedios_sin_pasarse(self):
        # 3 días sin revisar (hace 3, hace 2, hace 1) + hoy = 4 fechas.
        estado = {"avisos_ultima_fecha_revisada": _fecha_hace(4)}
        fechas = vigilancia_boe._fechas_a_revisar(estado)
        assert fechas == [_fecha_hace(3), _fecha_hace(2), _fecha_hace(1), _fecha_hace(0)]

    def test_ya_revisado_hoy_no_devuelve_lista_vacia(self):
        # Una segunda ejecución manual el mismo día no debe romper (ni dejar
        # de revisar hoy) aunque "última revisada" ya sea hoy.
        estado = {"avisos_ultima_fecha_revisada": _fecha_hace(0)}
        assert vigilancia_boe._fechas_a_revisar(estado) == [_fecha_hace(0)]

    def test_backfill_nunca_supera_el_maximo_aunque_el_hueco_sea_enorme(self):
        estado = {"avisos_ultima_fecha_revisada": _fecha_hace(100)}
        fechas = vigilancia_boe._fechas_a_revisar(estado)
        assert len(fechas) == vigilancia_boe._DIAS_MAX_BACKFILL


class TestDetectarAvisosOficialesBackfillYEstado:

    def test_revisa_los_dias_sin_revisar_desde_la_ultima_ejecucion(self, db):
        db.sembrar(("config", "vigilancia_boe"), {"avisos_ultima_fecha_revisada": _fecha_hace(2)})
        with patch("vigilancia_boe.obtener_sumario_dia", return_value=[]) as mock_sumario:
            vigilancia_boe.detectar_avisos_oficiales(db)

        fechas_llamadas = [c.args[0] for c in mock_sumario.call_args_list]
        assert fechas_llamadas == [_fecha_hace(1), _fecha_hace(0)]

    def test_actualiza_fecha_revisada_aunque_no_haya_avisos_nuevos(self, db):
        with patch("vigilancia_boe.obtener_sumario_dia", return_value=[]):
            creados = vigilancia_boe.detectar_avisos_oficiales(db)

        assert creados == 0
        estado = db.leer(("config", "vigilancia_boe"))
        assert estado["avisos_ultima_fecha_revisada"] == _fecha_hace(0)

    def test_no_repite_el_mismo_dia_en_la_siguiente_ejecucion(self, db):
        with patch("vigilancia_boe.obtener_sumario_dia", return_value=[]):
            vigilancia_boe.detectar_avisos_oficiales(db)  # 1ª ejecución: fija "ultima revisada" a hoy

        with patch("vigilancia_boe.obtener_sumario_dia", return_value=[]) as mock_sumario:
            vigilancia_boe.detectar_avisos_oficiales(db)  # 2ª ejecución, mismo día

        # La 2ª ejecución solo debe volver a mirar HOY, no repetir todo el
        # backfill máximo otra vez.
        assert mock_sumario.call_count == 1
        assert mock_sumario.call_args.args[0] == _fecha_hace(0)

    def test_dia_con_fallo_de_consulta_no_avanza_la_fecha_revisada_mas_alla_de_el(self, db):
        # obtener_sumario_dia devuelve None (no []) cuando la consulta falló
        # de verdad (tras agotar los reintentos de _get_json) -- si se
        # tratara como "sin items" se perdería ese día para siempre en vez
        # de reintentarse la próxima vez, el mismo problema que motivó el
        # backfill. hace_hace(2) y hace_hace(1) tienen sumario; "hoy" falla.
        db.sembrar(("config", "vigilancia_boe"), {"avisos_ultima_fecha_revisada": _fecha_hace(3)})
        titulo = "Convocatoria del Cuerpo General Administrativo del Estado"

        def _sumario(fecha):
            if fecha == _fecha_hace(0):
                return None
            return [{"identificador": f"BOE-A-{fecha}", "titulo": titulo, "url_html": "https://www.boe.es/x"}]

        with patch("vigilancia_boe.obtener_sumario_dia", side_effect=_sumario):
            creados = vigilancia_boe.detectar_avisos_oficiales(db)

        # Los avisos de los días que sí se pudieron consultar (hace 2 y
        # hace 1) se guardan igual.
        assert creados == 2
        estado = db.leer(("config", "vigilancia_boe"))
        assert estado["avisos_ultima_fecha_revisada"] == _fecha_hace(1)

    def test_fallo_de_consulta_en_el_primer_dia_no_toca_el_estado(self, db):
        with patch("vigilancia_boe.obtener_sumario_dia", return_value=None):
            creados = vigilancia_boe.detectar_avisos_oficiales(db)

        assert creados == 0
        assert db.leer(("config", "vigilancia_boe")) is None


class TestRelevanciaTemarioConIA:
    # Segunda vía de detección: títulos que NO nombran ningún cuerpo
    # literalmente pero sí un término genérico de Administración/empleo
    # público -- ver _PALABRAS_POSIBLE_RELEVANCIA_TEMARIO. Caso real que la
    # motivó: el RD 606/2026 (Estatuto de la Autoridad Independiente para
    # la Igualdad de Trato y la No Discriminación) modificó el temario de
    # las 3 oposiciones sin mencionar ningún cuerpo en su título.

    def _item(self, identificador, titulo):
        return {"identificador": identificador, "titulo": titulo, "url_html": "https://www.boe.es/x"}

    def test_titulo_sin_cuerpo_ni_termino_generico_no_llega_a_la_ia(self, db):
        item = self._item("BOE-A-2026-1", "Anuncio de licitación de obras de reforma de un edificio")
        with patch("vigilancia_boe.obtener_sumario_dia", return_value=[item]), \
             patch("vigilancia_boe.call_deepseek_api") as mock_ia:
            creados = vigilancia_boe.detectar_avisos_oficiales(db)

        assert creados == 0
        mock_ia.assert_not_called()

    def test_titulo_con_termino_generico_y_la_ia_lo_marca_relevante_crea_aviso(self, db):
        titulo = (
            "Real Decreto 606/2026, de 22 de julio, por el que se aprueba el Estatuto de la Autoridad "
            "Independiente para la Igualdad de Trato y la No Discriminación, A.A.I."
        )
        item = self._item("BOE-A-2026-606", titulo)
        respuesta_ia = (
            '{"resultados": [{"indice": 0, "relevante": true, "oposiciones": ["AGE", "GACE"], '
            '"motivo": "Modifica el régimen de un organismo estudiado en el temario"}]}'
        )
        with patch("vigilancia_boe.obtener_sumario_dia", return_value=[item]), \
             patch("vigilancia_boe.call_deepseek_api", return_value=respuesta_ia) as mock_ia:
            creados = vigilancia_boe.detectar_avisos_oficiales(db)

        assert creados == 1
        mock_ia.assert_called_once()  # una sola llamada para todo el lote del día, no una por título
        avisos = list(db.collection("avisos_oficiales").stream())
        assert len(avisos) == 1
        d = avisos[0].to_dict()
        assert d["tipo"] == "posible_relevancia_temario"
        assert d["oposiciones"] == ["AGE", "GACE"]
        assert d["estado"] == "pendiente"
        assert "Modifica el régimen" in d["resumen"]

    def test_titulo_con_termino_generico_y_la_ia_lo_descarta_no_crea_aviso(self, db):
        titulo = "Resolución sobre subvenciones al sector público en materia de innovación"
        item = self._item("BOE-A-2026-700", titulo)
        respuesta_ia = '{"resultados": [{"indice": 0, "relevante": false}]}'
        with patch("vigilancia_boe.obtener_sumario_dia", return_value=[item]), \
             patch("vigilancia_boe.call_deepseek_api", return_value=respuesta_ia):
            creados = vigilancia_boe.detectar_avisos_oficiales(db)

        assert creados == 0
        assert list(db.collection("avisos_oficiales").stream()) == []

    def test_varios_candidatos_en_un_solo_dia_se_agrupan_en_una_unica_llamada(self, db):
        items = [
            self._item("BOE-A-2026-1", "Real Decreto sobre el Estatuto Básico del empleado público autonómico"),
            self._item("BOE-A-2026-2", "Orden por la que se regula la función pública sanitaria"),
        ]
        respuesta_ia = '{"resultados": []}'
        with patch("vigilancia_boe.obtener_sumario_dia", return_value=items), \
             patch("vigilancia_boe.call_deepseek_api", return_value=respuesta_ia) as mock_ia:
            vigilancia_boe.detectar_avisos_oficiales(db)

        assert mock_ia.call_count == 1
        # Los 2 títulos candidatos deben ir en el mismo prompt de la única llamada.
        mensajes = mock_ia.call_args.kwargs["messages"]
        contenido_user = mensajes[1]["content"]
        assert "Estatuto Básico del empleado público autonómico" in contenido_user
        assert "función pública sanitaria" in contenido_user

    def test_ia_sin_respuesta_no_rompe_el_ciclo(self, db):
        item = self._item("BOE-A-2026-1", "Real Decreto sobre el Estatuto Básico del empleado público")
        with patch("vigilancia_boe.obtener_sumario_dia", return_value=[item]), \
             patch("vigilancia_boe.call_deepseek_api", return_value=None):
            creados = vigilancia_boe.detectar_avisos_oficiales(db)

        assert creados == 0
        assert list(db.collection("avisos_oficiales").stream()) == []

    def test_titulo_con_cuerpo_literal_no_pasa_por_la_ia(self, db):
        # Si ya lo detecta la vía barata (nombre del cuerpo en el título),
        # no hace falta gastar una llamada a la IA para ese título.
        titulo = "Convocatoria del Cuerpo General Administrativo del Estado"
        item = self._item("BOE-A-2026-1", titulo)
        with patch("vigilancia_boe.obtener_sumario_dia", return_value=[item]), \
             patch("vigilancia_boe.call_deepseek_api") as mock_ia:
            creados = vigilancia_boe.detectar_avisos_oficiales(db)

        assert creados == 1
        mock_ia.assert_not_called()

    def test_mas_de_30_candidatos_se_trunca_para_controlar_el_coste(self, db):
        items = [
            self._item(f"BOE-A-2026-{i}", f"Real Decreto {i} sobre el Estatuto Básico del empleado público")
            for i in range(40)
        ]
        with patch("vigilancia_boe.obtener_sumario_dia", return_value=items), \
             patch("vigilancia_boe.call_deepseek_api", return_value='{"resultados": []}') as mock_ia:
            vigilancia_boe.detectar_avisos_oficiales(db)

        assert mock_ia.call_count == 1
        contenido_user = mock_ia.call_args.kwargs["messages"][1]["content"]
        titulos_en_prompt = contenido_user.count("Estatuto Básico del empleado público")
        assert titulos_en_prompt == vigilancia_boe._MAX_CANDIDATOS_RELEVANCIA_IA_POR_CICLO
