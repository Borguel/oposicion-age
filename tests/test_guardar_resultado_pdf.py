"""guardar_resultado_en_firestore para contenido desde PDF (test/resumen/
esquema/tarjetas) reutiliza registro_progreso_usuario.actualizar_estadisticas_pdf
en vez de una copia local propia -- antes había dos implementaciones casi
iguales que divergían para un usuario que aún no existe en Firestore: la
copia local creaba un documento mínimo (solo contadores PDF) y no pasaba
por el inicializador compartido ni mandaba el email de bienvenida.

En producción real esa divergencia NUNCA era observable: todas las rutas
que acaban llamando a actualizar_estadisticas_pdf/guardar_resultado_en_firestore
(los 4 sitios de blueprints/pdf_ia.py, los 2 de save_controller.py y
/actualizar-progreso-pdf en rutas_progreso.py) están detrás de
@requiere_login o @requiere_plan (que envuelve a requiere_login), y ese
decorador ya llama a inicializar_estadisticas_usuario -- con lo que manda
el email de bienvenida y crea "estadisticas"/"suscripciones" -- en la
primera petición autenticada del usuario, mucho antes de que pudiera
llegar a guardar ningún PDF. El test de abajo llama a
actualizar_estadisticas_pdf sin pasar por ese decorador a propósito, para
ejercer la rama "usuario nuevo" como red de seguridad -- no porque ese
camino exista tal cual en producción."""
from unittest.mock import patch

from guardar_resultado import guardar_resultado_en_firestore
from registro_progreso_usuario import actualizar_estadisticas_pdf


def test_primer_pdf_de_un_usuario_nuevo_inicializa_estadisticas_y_manda_bienvenida(db):
    # Llamada directa a actualizar_estadisticas_pdf, sin pasar por
    # requiere_login/requiere_plan (que en producción real siempre se
    # ejecuta antes y ya deja al usuario inicializado) -- así se ejerce de
    # verdad la rama "usuario nuevo" de la función, como cobertura
    # defensiva de un caso límite que hoy no se da en ningún camino real.
    with patch("registro_progreso_usuario.enviar_email_bienvenida") as mock_bienvenida, \
         patch("registro_progreso_usuario.enviar_email_alerta_nuevo_usuario"):
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
