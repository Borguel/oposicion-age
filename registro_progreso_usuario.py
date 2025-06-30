from datetime import datetime
from google.cloud import firestore

def inicializar_estadisticas_usuario(db, usuario_id):
    doc_ref = db.collection("usuarios").document(usuario_id)
    if not doc_ref.get().exists:
        doc_ref.set({
            "tests_realizados": 0,
            "total_aciertos": 0,
            "total_fallos": 0,
            "tests_aprobados": 0,
            "tests_suspendidos": 0,
            "esquemas_realizados": 0,
            "temas_test": [],
            "temas_esquemas": [],
            "tiempo_total_dedicado_min": 0,
            "ultimo_test": {},
            "historial_tests": [],
            "ultima_actividad": None,
            "notas_personales": "",
            "resumen_mensual": {},
            "recomendaciones_ia": [],
            "puntuacion_media_test": 0
        })

def actualizar_estadisticas_test(db, usuario_id, aciertos, fallos, temas, tiempo_en_segundos):
    doc_ref = db.collection("usuarios").document(usuario_id)
    usuario = doc_ref.get().to_dict()

    tiempo_en_min = round(tiempo_en_segundos / 60, 2)

    total_tests = usuario.get("tests_realizados", 0) + 1
    total_aciertos = usuario.get("total_aciertos", 0) + aciertos
    total_fallos = usuario.get("total_fallos", 0) + fallos
    temas_test = list(set(usuario.get("temas_test", []) + temas))
    tiempo_total = usuario.get("tiempo_total_dedicado_min", 0) + tiempo_en_min
    puntuacion_media = round(total_aciertos / total_tests, 2) if total_tests else 0

    aprobados = usuario.get("tests_aprobados", 0)
    suspendidos = usuario.get("tests_suspendidos", 0)
    total_preguntas = aciertos + fallos
    ratio = aciertos / total_preguntas if total_preguntas else 0
    if ratio >= 0.5:
        aprobados += 1
    else:
        suspendidos += 1

    historial = usuario.get("historial_tests", [])
    historial.append({
        "fecha": datetime.utcnow().isoformat(),
        "aciertos": aciertos,
        "fallos": fallos,
        "temas": temas,
        "tiempo": tiempo_en_segundos
    })
    if len(historial) > 50:
        historial = historial[-50:]

    doc_ref.update({
        "tests_realizados": total_tests,
        "total_aciertos": total_aciertos,
        "total_fallos": total_fallos,
        "tests_aprobados": aprobados,
        "tests_suspendidos": suspendidos,
        "temas_test": temas_test,
        "tiempo_total_dedicado_min": tiempo_total,
        "puntuacion_media_test": puntuacion_media,
        "historial_tests": historial,
        "ultimo_test": {
            "aciertos": aciertos,
            "fallos": fallos,
            "temas": temas,
            "tiempo_min": tiempo_en_min,
            "fecha": datetime.utcnow().isoformat()
        },
        "ultima_actividad": datetime.utcnow().isoformat()
    })

def actualizar_estadisticas_esquema(db, usuario_id, temas):
    doc_ref = db.collection("usuarios").document(usuario_id)
    usuario = doc_ref.get().to_dict()

    total_esquemas = usuario.get("esquemas_realizados", 0) + 1
    temas_esquemas = list(set(usuario.get("temas_esquemas", []) + temas))

    doc_ref.update({
        "esquemas_realizados": total_esquemas,
        "temas_esquemas": temas_esquemas,
        "ultima_actividad": datetime.utcnow().isoformat()
    })

# ✅ NUEVA RUTA PARA /resumen-progreso
def obtener_resumen_progreso(db, usuario_id):
    doc_ref = db.collection("usuarios").document(usuario_id)
    doc = doc_ref.get()
    if not doc.exists:
        return {}

    datos = doc.to_dict()

    resumen = {
        "tests_realizados": datos.get("tests_realizados", 0),
        "tests_aprobados": datos.get("tests_aprobados", 0),
        "tests_suspendidos": datos.get("tests_suspendidos", 0),
        "total_aciertos": datos.get("total_aciertos", 0),
        "total_fallos": datos.get("total_fallos", 0),
        "puntuacion_media_test": datos.get("puntuacion_media_test", 0),
        "esquemas_realizados": datos.get("esquemas_realizados", 0),
        "tiempo_total_dedicado_min": datos.get("tiempo_total_dedicado_min", 0),
        "temas_test": datos.get("temas_test", []),
        "temas_esquemas": datos.get("temas_esquemas", []),
        "ultimo_test": datos.get("ultimo_test", {}),
        "historial_tests": datos.get("historial_tests", []),
        "ultima_actividad": datos.get("ultima_actividad", None)
    }

    return resumen

