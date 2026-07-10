"""guardar_resultado_en_firestore para contenido desde PDF (test/resumen/
esquema/tarjetas) reutiliza registro_progreso_usuario.actualizar_estadisticas_pdf
en vez de una copia local propia -- antes había dos implementaciones casi
iguales que divergían para un usuario que aún no existe en Firestore: la
copia local creaba un documento mínimo (solo contadores PDF) y no pasaba
por el inicializador compartido ni mandaba el email de bienvenida.

Esa divergencia solo era observable llamando a la función de actualización
de estadísticas SIN haber pasado antes por registrar_actividad_racha (que
sí crea un documento mínimo con "racha" para CUALQUIER tipo de actividad,
no solo PDF) -- es justo lo que hace /actualizar-progreso-pdf
(rutas_progreso.py), que llama a actualizar_estadisticas_pdf directamente."""
from unittest.mock import patch

from guardar_resultado import guardar_resultado_en_firestore
from registro_progreso_usuario import actualizar_estadisticas_pdf


def test_primer_pdf_de_un_usuario_nuevo_inicializa_estadisticas_y_manda_bienvenida(db):
    # Llamada directa (como hace /actualizar-progreso-pdf), sin
    # registrar_actividad_racha antes -- así el usuario todavía no existe
    # en absoluto en Firestore y se ejerce de verdad la rama "usuario
    # nuevo" que antes divergía entre las dos implementaciones.
    with patch("registro_progreso_usuario.enviar_email_bienvenida") as mock_bienvenida:
        actualizar_estadisticas_pdf(db, "u_nuevo", "resumen_pdf")

    usuario = db.leer(("usuarios", "u_nuevo"))
    # Antes (con la copia local), un usuario nuevo se quedaba SOLO con los
    # contadores de PDF, sin "estadisticas"/"suscripciones" ni bienvenida.
    assert "estadisticas" in usuario
    assert "suscripciones" in usuario
    assert usuario["resumenes_pdf_realizados"] == 1
    assert usuario["total_archivos_procesados"] == 1
    mock_bienvenida.assert_called_once()


def test_los_4_tipos_de_pdf_incrementan_su_propio_contador(db):
    db.sembrar(("usuarios", "u1"), {})
    guardar_resultado_en_firestore(db, "test_pdf", [{"pregunta": "?"}], usuario_id="u1", metadatos={})
    guardar_resultado_en_firestore(db, "resumen_pdf", "texto", usuario_id="u1", metadatos={})
    guardar_resultado_en_firestore(db, "esquema_pdf", "texto", usuario_id="u1", metadatos={})
    guardar_resultado_en_firestore(db, "tarjetas_pdf", [{"a": "1"}], usuario_id="u1", metadatos={})

    usuario = db.leer(("usuarios", "u1"))
    assert usuario["tests_pdf_realizados"] == 1
    assert usuario["resumenes_pdf_realizados"] == 1
    assert usuario["esquemas_pdf_realizados"] == 1
    assert usuario["tarjetas_pdf_realizados"] == 1
    assert usuario["total_archivos_procesados"] == 4
