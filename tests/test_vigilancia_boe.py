"""Pruebas de vigilancia_boe.py: nunca publica/aplica nada sola -- solo
crea documentos "pendiente" en avisos_oficiales / cambios_temario_propuestos
para que el dueño los revise desde el panel de admin."""
from unittest.mock import MagicMock, patch

import vigilancia_boe
from oposiciones import coleccion_temario


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
    assert d["oposicion"] == "AGE"
    assert d["tipo"] == "convocatoria"
    assert d["estado"] == "pendiente"
    assert d["titulo"] == titulo


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
