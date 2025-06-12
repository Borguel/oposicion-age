from flask import request, jsonify
from guardar_resultado import guardar_resultado_en_firestore

def guardar_test_route(db):
    def guardar_test():
        datos = request.get_json()
        resultado = guardar_resultado_en_firestore(
            db=db,
            tipo="test",
            contenido=datos.get("contenido", {}),
            usuario_id=datos.get("usuario_id", "usuario_prueba"),
            metadatos=datos.get("metadatos", {})
        )
        return jsonify({"mensaje": "Test guardado correctamente"})

    guardar_test.__name__ = "guardar_test"
    return guardar_test

def guardar_esquema_route(db):
    def guardar_esquema():
        datos = request.get_json()
        resultado = guardar_resultado_en_firestore(
            db=db,
            tipo="esquema",
            contenido=datos.get("contenido", {}),
            usuario_id=datos.get("usuario_id", "usuario_prueba"),
            metadatos=datos.get("metadatos", {})
        )
        return jsonify({"mensaje": "Esquema guardado correctamente"})

    guardar_esquema.__name__ = "guardar_esquema"
    return guardar_esquema