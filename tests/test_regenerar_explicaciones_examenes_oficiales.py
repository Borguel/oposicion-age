"""Comprueba las funciones puras (sin Firestore/DeepSeek real) de
regenerar_explicaciones_examenes_oficiales: detectar si una explicación ya
repasa las 4 opciones (para no tocarla ni gastar dinero regenerándola),
que el prompt de generación incluye todo lo necesario para generar una
buena (incluido el feedback de una revisión previa), que el prompt de
verificación incluye la explicación a revisar, y que ambos usan el texto
legal real del tema (vía utils.obtener_subbloques_individuales, con un
doble en vez de Firestore real) como respaldo cuando hay cobertura de
temario."""
import regenerar_explicaciones_examenes_oficiales as mod
from regenerar_explicaciones_examenes_oficiales import (
    _prompt_explicacion,
    _prompt_verificacion,
    _tiene_formato_bueno,
)

# Ejemplo real (anonimizado en la forma, no en el fondo) que motivó esta
# tarea: la explicación solo justifica la opción correcta.
EXPLICACION_POBRE_REAL = (
    "La Ley 47/2003 General Presupuestaria define el reconocimiento de la "
    "obligación como el acto mediante el cual se declara la existencia de "
    "un crédito exigible contra la Hacienda Pública estatal, derivado de "
    "un gasto aprobado y comprometido."
)

EXPLICACION_BUENA = (
    "A) es correcta porque el art. 73 LGP define así el reconocimiento de "
    "la obligación. B) es incorrecta porque describe el compromiso del "
    "gasto, no el reconocimiento. C) es incorrecta porque describe la "
    "autorización del gasto, una fase anterior. D) es incorrecta porque "
    "el reconocimiento de la obligación no es un ingreso ni un pago."
)


def test_explicacion_pobre_no_tiene_formato_bueno():
    assert _tiene_formato_bueno(EXPLICACION_POBRE_REAL) is False


def test_explicacion_vacia_no_tiene_formato_bueno():
    assert _tiene_formato_bueno("") is False
    assert _tiene_formato_bueno(None) is False


def test_explicacion_con_las_4_opciones_tiene_formato_bueno():
    assert _tiene_formato_bueno(EXPLICACION_BUENA) is True


def test_explicacion_con_solo_3_opciones_no_es_suficiente():
    # Le falta "D)" -- no debe colarse como "ya buena".
    sin_d = EXPLICACION_BUENA.rsplit("D)", 1)[0]
    assert _tiene_formato_bueno(sin_d) is False


def test_prompt_incluye_pregunta_las_4_opciones_y_la_correcta():
    opciones = {
        "A": "El acto mediante el que se declara la existencia de un crédito exigible.",
        "B": "El acto mediante el cual se acuerda la realización de gastos previamente aprobados.",
        "C": "El acto mediante el cual se autoriza la realización de un gasto determinado.",
        "D": "El ingreso del pago.",
    }
    prompt = _prompt_explicacion(
        "De acuerdo con la Ley 47/2003, el reconocimiento de la obligación es:",
        opciones,
        "A",
    )
    assert "reconocimiento de la obligación" in prompt
    for letra, texto in opciones.items():
        assert f"{letra}) {texto}" in prompt
    assert "Respuesta correcta: A)" in prompt
    # Pide el formato por opción y advierte de no inventar citas legales.
    assert "es correcta/incorrecta porque" in prompt
    assert "no inventes ninguna referencia legal" in prompt


def test_prompt_sin_problemas_previos_no_menciona_ninguna_revision():
    opciones = {"A": "uno", "B": "dos", "C": "tres", "D": "cuatro"}
    prompt = _prompt_explicacion("¿Pregunta?", opciones, "A")
    assert "revisor jurídico" not in prompt


def test_prompt_con_problemas_previos_los_incluye_como_pista():
    opciones = {"A": "uno", "B": "dos", "C": "tres", "D": "cuatro"}
    problemas = [
        "La línea de D) afirma una clasificación legal que no es exacta.",
        "La línea de B) solo repite el enunciado.",
    ]
    prompt = _prompt_explicacion("¿Pregunta?", opciones, "A", problemas_previos=problemas)
    assert "revisor jurídico" in prompt
    for problema in problemas:
        assert problema in prompt


def test_prompt_verificacion_incluye_pregunta_opciones_y_explicacion_a_revisar():
    opciones = {
        "A": "Al Gobierno y al Congreso.",
        "B": "Al Congreso y al Senado.",
        "C": "Al Gobierno, al Congreso y al Senado.",
        "D": "Al Gobierno, al Congreso, al Senado y a las Asambleas de las Comunidades Autónomas.",
    }
    explicacion = (
        "A) es incorrecta porque omite al Senado. B) es incorrecta porque excluye al Gobierno. "
        "C) es incorrecta porque no incluye a las Asambleas. D) es correcta porque el art. 166 CE "
        "remite al 87.2, que atribuye la iniciativa a los cuatro."
    )
    prompt = _prompt_verificacion(
        "Señale a quién corresponde la iniciativa de la reforma constitucional:",
        opciones, "D", explicacion,
    )
    assert "iniciativa de la reforma constitucional" in prompt
    for letra, texto in opciones.items():
        assert f"{letra}) {texto}" in prompt
    assert "Respuesta correcta: D)" in prompt
    assert explicacion in prompt
    # Pide el mismo formato JSON que ya usa la verificación de Test Personalizado.
    assert '{"valido": true, "problemas": []}' in prompt


def test_prompt_verificacion_no_marca_una_cita_solo_por_no_ser_literal():
    # Bug real (973/2194 marcadas inválidas, la inmensa mayoría por citar un
    # artículo más específico que el enunciado -- p. ej. "art. 20.1 de la
    # Ley 7/1985" para una pregunta que solo menciona "la Ley 7/1985") --
    # eso es precisión deseable, no una invención, y el prompt debe decirlo
    # explícitamente para no perder citas correctas al regenerar.
    opciones = {"A": "uno", "B": "dos", "C": "tres", "D": "cuatro"}
    prompt = _prompt_verificacion("¿Pregunta?", opciones, "A", "A) es correcta... B) ... C) ... D) ...")
    assert "no aparece de forma literal en el enunciado" in prompt
    assert "es normal y deseable que la explicación sea más precisa que la pregunta" in prompt


# ---------- Respaldo con texto legal real (tema_id -> temario) ----------
#
# _subbloques_del_tema: solo la lectura de Firestore (sin truncar ni
# localizar nada). _texto_legal_para_pregunta: la localización, pura,
# sobre subbloques ya en memoria -- sin Firestore de por medio, así que
# estos tests no necesitan monkeypatch.

def test_subbloques_del_tema_sin_guion_devuelve_lista_vacia_sin_llamar_a_firestore(monkeypatch):
    llamado = []
    monkeypatch.setattr(mod, "obtener_subbloques_individuales", lambda *a, **k: llamado.append(1) or [])
    assert mod._subbloques_del_tema(db=None, oposicion="AGE", tema_id="no_tiene_guion") == []
    assert llamado == []  # ni siquiera intenta leer Firestore con un tema_id con formato inválido


def test_subbloques_del_tema_devuelve_lo_que_da_obtener_subbloques_individuales(monkeypatch):
    subbloques = [{"etiqueta": "s1", "titulo": "Ley 7/1985", "texto": "Artículo 3. ..."}]
    monkeypatch.setattr(mod, "obtener_subbloques_individuales", lambda *a, **k: subbloques)
    assert mod._subbloques_del_tema(db=None, oposicion="AGE", tema_id="bloque_01-tema_02") == subbloques


def test_texto_legal_para_pregunta_sin_subbloques_devuelve_none():
    assert mod._texto_legal_para_pregunta([], "¿Pregunta?", {"A": "uno"}) is None


def test_texto_legal_para_pregunta_sin_cita_de_articulo_cae_al_contexto_general_del_tema():
    # Pregunta descriptiva, sin ningún "artículo N" detectable -- no hay
    # nada concreto que localizar, así que sigue el comportamiento
    # anterior: contexto general del tema (concatenado).
    subbloques = [
        {"etiqueta": "s1", "titulo": "Ley 7/1985", "texto": "Artículo 3. Las entidades locales..."},
        {"etiqueta": "s2", "titulo": "Ley 7/1985", "texto": "Artículo 20. La organización municipal..."},
    ]
    texto = mod._texto_legal_para_pregunta(subbloques, "¿Qué es la Administración Local?", {"A": "uno"})
    assert "Artículo 3. Las entidades locales" in texto
    assert "Artículo 20. La organización municipal" in texto


def test_texto_legal_para_pregunta_respeta_el_tope_de_caracteres_sin_cita():
    subbloque_grande = {"etiqueta": "s1", "titulo": "Norma", "texto": "x" * (mod.MAX_CARACTERES_TEXTO_LEGAL_TEMA + 500)}
    otro = {"etiqueta": "s2", "titulo": "Norma", "texto": "ESTE FRAGMENTO NO DEBE APARECER"}
    texto = mod._texto_legal_para_pregunta([subbloque_grande, otro], "¿Pregunta descriptiva sin artículo?", {})
    assert "ESTE FRAGMENTO NO DEBE APARECER" not in texto


def test_texto_legal_para_pregunta_localiza_el_articulo_citado_aunque_no_sea_el_primero():
    # El bug real que motivó este arreglo: concatenar-y-truncar hacia el
    # principio del tema deja fuera el artículo 20 si no es de los
    # primeros subbloques -- localizarlo por número debe encontrarlo esté
    # donde esté.
    subbloques = [
        {"etiqueta": "s1", "titulo": "Ley 7/1985", "texto": "Artículo 3. Las entidades locales territoriales son el municipio, la provincia y la isla."},
        {"etiqueta": "s2", "titulo": "Ley 7/1985", "texto": "Artículo 20. El Ayuntamiento, integrado por el Alcalde y los Concejales, ejerce el gobierno municipal."},
    ]
    pregunta = "Según el artículo 20 de la Ley 7/1985, el Ayuntamiento está integrado por:"
    texto = mod._texto_legal_para_pregunta(subbloques, pregunta, {"A": "uno"})
    assert "Artículo 20" in texto
    assert "Alcalde y los Concejales" in texto
    assert "Artículo 3" not in texto  # no se cita, no debe colarse


def test_texto_legal_para_pregunta_filtra_por_norma_para_no_confundir_el_mismo_numero_de_articulo():
    # El tema mezcla dos normas -- ambas tienen un "Artículo 3", pero la
    # pregunta cita la Ley 7/1985 explícitamente, así que debe localizar
    # ESE artículo 3, no el de la otra norma.
    subbloques = [
        {"etiqueta": "s1", "titulo": "Ley 40/2015", "texto": "Artículo 3. Principios generales de la Administración."},
        {"etiqueta": "s2", "titulo": "Ley 7/1985", "texto": "Artículo 3. Las entidades locales territoriales son el municipio, la provincia y la isla."},
    ]
    pregunta = "Según el artículo 3 de la Ley 7/1985, son entidades locales territoriales:"
    texto = mod._texto_legal_para_pregunta(subbloques, pregunta, {"A": "uno"})
    assert "entidades locales territoriales" in texto
    assert "Principios generales de la Administración" not in texto


def test_texto_legal_para_pregunta_cita_no_encontrada_devuelve_none():
    # Hay cita de artículo, pero ningún subbloque del tema la contiene --
    # nunca se debe devolver un texto que no la respalda de verdad.
    subbloques = [{"etiqueta": "s1", "titulo": "Ley 7/1985", "texto": "Artículo 20. La organización municipal..."}]
    pregunta = "Según el artículo 53 de la Constitución Española, pueden ser objeto de tutela:"
    assert mod._texto_legal_para_pregunta(subbloques, pregunta, {"A": "uno"}) is None


def test_texto_legal_para_pregunta_detecta_cita_en_las_opciones_no_solo_en_la_pregunta():
    subbloques = [
        {"etiqueta": "s1", "titulo": "Ley 39/2015", "texto": "Artículo 43. La notificación por medios electrónicos se entenderá cumplida en la fecha de acceso."},
    ]
    pregunta = "¿Cuándo se entiende cumplida la obligación de notificar?"
    opciones = {"A": "Según el artículo 43 de la Ley 39/2015, en la fecha de acceso al contenido.", "B": "otra"}
    texto = mod._texto_legal_para_pregunta(subbloques, pregunta, opciones)
    assert "fecha de acceso" in texto


def test_prompt_explicacion_sin_texto_legal_usa_las_instrucciones_de_siempre():
    opciones = {"A": "uno", "B": "dos", "C": "tres", "D": "cuatro"}
    prompt = _prompt_explicacion("¿Pregunta?", opciones, "A")
    assert "TEXTO LEGAL" not in prompt
    assert "no inventes ninguna referencia legal" in prompt


def test_prompt_explicacion_con_texto_legal_lo_incluye_y_exige_basarse_en_el():
    opciones = {"A": "uno", "B": "dos", "C": "tres", "D": "cuatro"}
    texto_legal = "Ley 7/1985, Artículo 3: Son entidades locales territoriales..."
    prompt = _prompt_explicacion("¿Pregunta?", opciones, "A", texto_legal=texto_legal)
    assert texto_legal in prompt
    assert "EXCLUSIVAMENTE en ese texto" in prompt


def test_prompt_verificacion_sin_texto_legal_usa_la_autocritica_de_siempre():
    opciones = {"A": "uno", "B": "dos", "C": "tres", "D": "cuatro"}
    prompt = _prompt_verificacion("¿Pregunta?", opciones, "A", "A) ... B) ... C) ... D) ...")
    assert "TEXTO LEGAL" not in prompt
    assert "revisor jurídico escéptico" in prompt


def test_prompt_verificacion_con_texto_legal_lo_incluye_y_pide_comparar_contra_el():
    opciones = {"A": "uno", "B": "dos", "C": "tres", "D": "cuatro"}
    texto_legal = "Ley 7/1985, Artículo 3: Son entidades locales territoriales..."
    explicacion = "A) ... B) ... C) ... D) ..."
    prompt = _prompt_verificacion("¿Pregunta?", opciones, "A", explicacion, texto_legal=texto_legal)
    assert texto_legal in prompt
    assert "verificador jurídico independiente" in prompt
    assert "palabra por palabra" in prompt
