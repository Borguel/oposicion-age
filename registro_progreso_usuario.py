
from datetime import datetime
from google.cloud import firestore

def inicializar_estadisticas_usuario(db, usuario_id):
    doc_ref = db.collection("usuarios").document(usuario_id)
    if not doc_ref.get().exists:
        doc_ref.set({
            "tests_realizados": 0,
            "total_aciertos": 0,
            "total_fallos": 0,
            "esquemas_realizados": 0,
            "temas_test": [],
            "temas_esquemas": [],
            "tiempo_total_dedicado_min": 0,
            "ultimo_test": {},
            "ultima_actividad": None,
            "notas_personales": "",
            "resumen_mensual": {},
            "recomendaciones_ia": [],
            "puntuacion_media_test": 0,
        })

def actualizar_estadisticas_test(db, usuario_id, aciertos, fallos, temas, tiempo_dedicado_min):
    doc_ref = db.collection("usuarios").document(usuario_id)
    usuario = doc_ref.get().to_dict()

    total_tests = usuario.get("tests_realizados", 0) + 1
    total_aciertos = usuario.get("total_aciertos", 0) + aciertos
    total_fallos = usuario.get("total_fallos", 0) + fallos
    temas_test = list(set(usuario.get("temas_test", []) + temas))
    tiempo_total = usuario.get("tiempo_total_dedicado_min", 0) + tiempo_dedicado_min
    puntuacion_media = round(total_aciertos / total_tests, 2) if total_tests else 0

    doc_ref.update({
        "tests_realizados": total_tests,
        "total_aciertos": total_aciertos,
        "total_fallos": total_fallos,
        "temas_test": temas_test,
        "tiempo_total_dedicado_min": tiempo_total,
        "ultimo_test": {
            "aciertos": aciertos,
            "fallos": fallos,
            "temas": temas,
            "tiempo_min": tiempo_dedicado_min,
            "fecha": datetime.utcnow().isoformat()
        },
        "ultima_actividad": datetime.utcnow().isoformat(),
        "puntuacion_media_test": puntuacion_media
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
