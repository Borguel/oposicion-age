"""Comprueba que reasignar_temas_examenes reconstruye los doc_id de Firestore
con el MISMO patrón que usan los loaders (cargar_examen_oficial_*), a partir
de los mapas datos_examenes/*_temas.json. Si un loader cambia el patrón y este
script no, el reetiquetado dejaría de encontrar las preguntas -- este test lo
pillaría."""
import re

from reasignar_temas_examenes import _pares_docid_tema


def test_reconstruccion_de_doc_ids_por_oposicion():
    pares = _pares_docid_tema()
    assert len(pares) > 1000  # hay muchos exámenes cargados

    por_op = {}
    for oposicion, doc_id, tema_id in pares:
        por_op.setdefault(oposicion, []).append((doc_id, tema_id))
        # Todo tema_id apunta a un bloque-tema del temario.
        assert re.fullmatch(r"bloque_\d+-tema_\d+", tema_id), tema_id

    assert set(por_op) == {"AGE", "GACE", "AUXILIAR"}

    # Los patrones de doc_id coinciden con los de cada loader. Los exámenes
    # subidos por el importador del panel (mapas *_docid_temas.json) llevan un
    # doc_id fuera de ese patrón (p. ej. modelo_a_2024_pregunta_NN), así que se
    # aceptan también esos: lo importante es que el doc_id no venga vacío.
    def es_docid_directo(d):
        return bool(re.fullmatch(r"[a-z0-9_]+_pregunta_[a-z0-9_]+", d))

    assert all(re.fullmatch(r"age_.+_eu_\d{3}", d) or es_docid_directo(d)
               for d, _ in por_op["AGE"])
    assert all(re.fullmatch(r"gacel_.+_1ej_\d{3}", d) or es_docid_directo(d)
               for d, _ in por_op["GACE"])
    assert all(re.fullmatch(r"auxiliar_.+_eu_p[12]_\d{3}", d) or es_docid_directo(d)
               for d, _ in por_op["AUXILIAR"])

    # El examen modelo_a_2024 (subido por el importador) está mapeado: sus 75
    # preguntas tienen tema asignado por el fichero *_docid_temas.json.
    directos = [d for d, _ in por_op["AGE"] if d.startswith("modelo_a_2024_")]
    assert len(directos) == 75
