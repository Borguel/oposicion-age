from flask import request, jsonify, g
from guardar_resultado import guardar_resultado_en_firestore
from auth_utils import requiere_login, obtener_oposicion_solicitada

def guardar_test_route(db):
    @requiere_login(db)
    def guardar_test():
        datos = request.get_json()
        contenido = datos.get("contenido", [])
        metadatos = datos.get("metadatos", {})
        metadatos["respuestas"] = datos.get("respuestas", [])

        resultado = guardar_resultado_en_firestore(
            db=db,
            tipo="test",
            contenido=contenido,
            usuario_id=g.uid,
            metadatos=metadatos,
            oposicion=obtener_oposicion_solicitada(),
            test_id=datos.get("test_id")
        )
        return jsonify({"mensaje": "Test guardado correctamente"})

    guardar_test.__name__ = "guardar_test"
    return guardar_test

def guardar_esquema_route(db):
    @requiere_login(db)
    def guardar_esquema():
        datos = request.get_json()
        resultado = guardar_resultado_en_firestore(
            db=db,
            tipo="esquema",
            contenido=datos.get("contenido", {}),
            usuario_id=g.uid,
            metadatos=datos.get("metadatos", {}),
            oposicion=obtener_oposicion_solicitada()
        )
        return jsonify({"mensaje": "Esquema guardado correctamente"})

    guardar_esquema.__name__ = "guardar_esquema"
    return guardar_esquema
