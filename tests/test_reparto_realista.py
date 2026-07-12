"""Pruebas del reparto "realista" de preguntas entre temas (opción del
usuario en Test Personalizado/Test Oficial, frente al reparto "equitativo"
de siempre): en vez de una cuota igual por tema, reparte primero entre
bloques según su peso real en exámenes oficiales ya cargados."""
from utils import (
    calcular_pesos_reales_por_bloque,
    obtener_preguntas_examenes_oficiales,
    repartir_cupos_por_tema_realista,
    seleccionar_preguntas_con_cuota,
    _limpiar_cache_temario,
)


def test_calcular_pesos_reales_por_bloque_vacio_sin_examenes(db):
    assert calcular_pesos_reales_por_bloque(db, "AGE") == {}


def test_calcular_pesos_reales_por_bloque_cuenta_por_bloque(db):
    db.sembrar(("examenes_oficiales_AGE", "p1"), {"tipo": "pregunta", "tema_id": "bloque_01-tema_01"})
    db.sembrar(("examenes_oficiales_AGE", "p2"), {"tipo": "pregunta", "tema_id": "bloque_01-tema_02"})
    db.sembrar(("examenes_oficiales_AGE", "p3"), {"tipo": "pregunta", "tema_id": "bloque_06-tema_01"})
    db.sembrar(("examenes_oficiales_AGE", "p4"), {"tipo": "pregunta", "tema_id": "bloque_06-tema_02"})
    db.sembrar(("examenes_oficiales_AGE", "meta"), {"tipo": "otra_cosa"})  # se ignora: no es "pregunta"

    pesos = calcular_pesos_reales_por_bloque(db, "AGE")
    assert pesos == {"bloque_01": 0.5, "bloque_06": 0.5}


def test_calcular_pesos_reales_por_bloque_usa_cache(db):
    db.sembrar(("examenes_oficiales_AGE", "p1"), {"tipo": "pregunta", "tema_id": "bloque_01-tema_01"})
    primero = calcular_pesos_reales_por_bloque(db, "AGE")
    db.sembrar(("examenes_oficiales_AGE", "p2"), {"tipo": "pregunta", "tema_id": "bloque_06-tema_01"})
    # Sin limpiar la caché, sigue viendo el resultado de antes de sembrar p2.
    assert calcular_pesos_reales_por_bloque(db, "AGE") == primero
    _limpiar_cache_temario()
    assert calcular_pesos_reales_por_bloque(db, "AGE") == {"bloque_01": 0.5, "bloque_06": 0.5}


def test_obtener_preguntas_examenes_oficiales_filtra_por_tipo(db):
    db.sembrar(("examenes_oficiales_AGE", "p1"), {"tipo": "pregunta", "pregunta": "1+1"})
    db.sembrar(("examenes_oficiales_AGE", "p2"), {"tipo": "pregunta", "pregunta": "2+2"})
    db.sembrar(("examenes_oficiales_AGE", "meta"), {"tipo": "otra_cosa"})

    preguntas = obtener_preguntas_examenes_oficiales(db, "AGE")

    assert len(preguntas) == 2
    assert {p["pregunta"] for p in preguntas} == {"1+1", "2+2"}


def test_obtener_preguntas_examenes_oficiales_usa_cache(db):
    db.sembrar(("examenes_oficiales_AGE", "p1"), {"tipo": "pregunta", "pregunta": "1+1"})
    primero = obtener_preguntas_examenes_oficiales(db, "AGE")
    db.sembrar(("examenes_oficiales_AGE", "p2"), {"tipo": "pregunta", "pregunta": "2+2"})
    # Sin limpiar la caché, sigue viendo el resultado de antes de sembrar p2.
    assert obtener_preguntas_examenes_oficiales(db, "AGE") == primero
    _limpiar_cache_temario()
    assert len(obtener_preguntas_examenes_oficiales(db, "AGE")) == 2


def test_repartir_cupos_por_tema_realista_respeta_el_peso_del_bloque():
    temas_ids = ["bloque_01-tema_01", "bloque_06-tema_01"]
    pesos_por_bloque = {"bloque_01": 0.2, "bloque_06": 0.8}
    cupos = repartir_cupos_por_tema_realista(temas_ids, 10, pesos_por_bloque)
    assert cupos == {"bloque_01-tema_01": 2, "bloque_06-tema_01": 8}


def test_repartir_cupos_por_tema_realista_reparte_igual_dentro_del_bloque():
    temas_ids = ["bloque_01-tema_01", "bloque_01-tema_02", "bloque_06-tema_01"]
    pesos_por_bloque = {"bloque_01": 0.5, "bloque_06": 0.5}
    cupos = repartir_cupos_por_tema_realista(temas_ids, 10, pesos_por_bloque)
    # bloque_01 se lleva 5 preguntas repartidas entre sus 2 temas (2+3 o 3+2),
    # bloque_06 se lleva las otras 5 con su único tema.
    assert cupos["bloque_01-tema_01"] + cupos["bloque_01-tema_02"] == 5
    assert cupos["bloque_06-tema_01"] == 5


def test_repartir_cupos_por_tema_realista_bloque_sin_datos_recibe_peso_medio():
    temas_ids = ["bloque_01-tema_01", "bloque_02-tema_01"]
    # Solo hay dato real para bloque_01; bloque_02 no aparece en pesos_por_bloque.
    cupos = repartir_cupos_por_tema_realista(temas_ids, 10, {"bloque_01": 0.9})
    # bloque_02 recibe el peso medio de los bloques conocidos (0.9), no 0 --
    # así que el reparto sigue siendo razonable (~mitad y mitad aquí, ya que
    # solo hay un peso conocido y se usa igual para ambos).
    assert sum(cupos.values()) == 10
    assert all(c > 0 for c in cupos.values())


def test_repartir_cupos_por_tema_realista_todos_sin_datos_reparte_igual():
    temas_ids = ["bloque_01-tema_01", "bloque_02-tema_01"]
    cupos = repartir_cupos_por_tema_realista(temas_ids, 10, {})
    assert cupos == {"bloque_01-tema_01": 5, "bloque_02-tema_01": 5}


def test_seleccionar_preguntas_con_cuota_modo_realista_prioriza_el_bloque_de_mas_peso():
    preguntas = (
        [{"pregunta": f"p1-{i}", "tema_id": "bloque_01-tema_01"} for i in range(20)]
        + [{"pregunta": f"p6-{i}", "tema_id": "bloque_06-tema_01"} for i in range(20)]
    )
    pesos_por_bloque = {"bloque_01": 0.1, "bloque_06": 0.9}
    seleccionadas = seleccionar_preguntas_con_cuota(
        preguntas, 10, temas_filtro=["bloque_01-tema_01", "bloque_06-tema_01"],
        modo_reparto="realista", pesos_por_bloque=pesos_por_bloque,
    )
    de_bloque_06 = sum(1 for p in seleccionadas if p["tema_id"] == "bloque_06-tema_01")
    assert len(seleccionadas) == 10
    assert de_bloque_06 == 9  # 90% de 10, redondeado


def test_seleccionar_preguntas_con_cuota_modo_equitativo_por_defecto():
    preguntas = (
        [{"pregunta": f"p1-{i}", "tema_id": "bloque_01-tema_01"} for i in range(20)]
        + [{"pregunta": f"p6-{i}", "tema_id": "bloque_06-tema_01"} for i in range(20)]
    )
    seleccionadas = seleccionar_preguntas_con_cuota(
        preguntas, 10, temas_filtro=["bloque_01-tema_01", "bloque_06-tema_01"],
    )
    de_bloque_01 = sum(1 for p in seleccionadas if p["tema_id"] == "bloque_01-tema_01")
    assert de_bloque_01 == 5
