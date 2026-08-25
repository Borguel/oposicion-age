"""Rutas de consulta del catálogo de oposiciones y su temario."""
from flask import Blueprint, g, jsonify, request

from firebase_setup import db
from auth_utils import requiere_plan, requiere_login, obtener_oposicion_solicitada, obtener_identidad_desde_token
from oposiciones import OPOSICIONES, coleccion_temario, oposicion_valida
from utils import calcular_pesos_reales_por_bloque, tiene_preguntas_psicotecnicas, tiene_prueba_psicotecnica, obtener_temas_navegables

bp = Blueprint("temario", __name__)


def _oposiciones_visibles_para_la_peticion():
    """(ids_visibles, alguna_activada): IDs de OPOSICIONES que debe ver
    quien hace la petición, y si tiene realmente AL MENOS una oposición
    pública activada de verdad (o si ids_visibles es solo el catálogo para
    elegir, sin haber activado nada todavía).

    Sin sesión (o sesión sin ninguna oposición activada todavía): el
    catálogo público completo (AGE/GACE/Auxiliar -- todo lo que no esté
    marcado "oculta"), para poder elegir la primera -- ver
    /activar-oposicion. Las "oculta" (p. ej. METRO) NUNCA entran por aquí
    salvo que ya estén activadas, se activan solo a mano desde el panel
    admin.

    Con sesión y ya con AL MENOS una oposición pública activada
    (suscripciones.<ID>, ver activar_oposicion_usuario): solo las que el
    usuario ha activado él mismo -- ni el resto de públicas sin activar ni
    ninguna oculta que no se le haya concedido. Así cada cuenta ve solo la
    oposición (o las oposiciones) que ha elegido estudiar, no las 3 a la vez
    por defecto.

    alguna_activada (11/08/2026, bug real reportado por un usuario: al
    registrarse, su pareja nunca vio la pantalla de "elige tu oposición" --
    ver zona-opositor/script.js): antes de este campo, el frontend
    intentaba distinguir "cuenta nueva sin elegir" de "ya tiene N
    activadas" mirando solo la LONGITUD de ids_visibles -- pero para una
    cuenta nueva esta función YA devuelve el catálogo completo (para poder
    elegir), así que esa longitud nunca es 0 y el frontend nunca detectaba
    que era una cuenta nueva. alguna_activada da la señal real y sin
    ambigüedad que hacía falta.

    Bug real (25/08/2026, reportado por el usuario: martaaresti@gmail.com,
    con solo METRO activada, recibía el correo de "llevas 14 días sin
    estudiar" y al pinchar en él Zona Opositor le enseñaba la pantalla de
    "elige tu oposición" en vez de su panel de METRO): esto comprobaba
    "alguna_activada" mirando solo activadas_publicas, ignorando por
    completo activadas_ocultas -- para una cuenta con SOLO una oposición
    oculta activada (el único caso hoy: METRO, concedida a mano desde el
    panel admin), activadas_publicas queda vacío y alguna_activada salía
    False, aunque la cuenta sí tuviera una oposición activada de verdad.
    Zona Opositor trataba entonces la cuenta como nueva y mostraba la
    pantalla de elegir oposición -- que ni siquiera ofrece METRO, al ser
    oculta -- en vez de su panel normal."""
    publicas = {oid for oid, datos in OPOSICIONES.items() if not datos.get("oculta")}
    identidad = obtener_identidad_desde_token(request)
    if not identidad:
        return publicas, False
    uid = identidad[0]
    doc = db.collection("usuarios").document(uid).get()
    activadas = set((doc.to_dict() or {}).get("suscripciones", {}).keys()) if doc.exists else set()
    activadas_publicas = activadas & publicas
    activadas_ocultas = activadas - publicas
    if not activadas:
        return publicas | activadas_ocultas, False
    return activadas_publicas | activadas_ocultas, True


@bp.route("/oposiciones-disponibles", methods=["GET"])
def obtener_oposiciones_disponibles():
    ids_visibles, alguna_activada = _oposiciones_visibles_para_la_peticion()
    return jsonify({
        "alguna_activada": alguna_activada,
        "oposiciones": [
            {
                "id": oid,
                "nombre": datos["nombre"],
                "simulacro_oficial": datos.get("simulacro_oficial"),
                # Si hay exámenes oficiales cargados y etiquetados con
                # tema_id para esta oposición, el frontend puede ofrecer el
                # reparto "realista" (ver utils.calcular_pesos_reales_por_bloque)
                # en Test Personalizado/Test Oficial -- si no (p. ej.
                # Auxiliar, sin exámenes cargados todavía), solo tiene
                # sentido el reparto equitativo.
                "tiene_pesos_reales": bool(calcular_pesos_reales_por_bloque(db, oid)),
                # Solo Auxiliar tiene preguntas psicotécnicas en su examen
                # oficial (ver cargar_examen_oficial_auxiliar.py) -- el
                # frontend usa esta flag para ofrecer el filtro "excluir
                # psicotécnicas" únicamente donde tiene sentido.
                "tiene_psicotecnicas": tiene_preguntas_psicotecnicas(db, oid),
                # Oposiciones con una prueba psicotécnica PROPIA y separada
                # (hoy, solo Metro -- ver oposiciones.coleccion_psicotecnico):
                # el frontend usa esta flag para mostrar la tarjeta
                # "Psicotécnico" en /test-generator/, distinta de
                # "tiene_psicotecnicas" (que es el filtro dentro de Test
                # Oficial, solo para Auxiliar).
                "tiene_prueba_psicotecnica": tiene_prueba_psicotecnica(db, oid),
            }
            for oid, datos in OPOSICIONES.items()
            if oid in ids_visibles
        ]
    })


@bp.route("/activar-oposicion", methods=["POST"])
@requiere_login(db)
def activar_oposicion():
    """Autoservicio: el propio usuario elige "quiero estudiar esta
    oposición" (p. ej. desde el selector de primeros pasos de Zona
    opositor) y eso da de alta suscripciones.<OP> con el plan gratis y
    arranca su prueba de 7 días PARA ESA OPOSICIÓN, sin que el admin tenga
    que hacer nada -- a diferencia de METRO (oculta, solo se concede a mano
    desde el panel), cualquier oposición pública puede activarse así.
    Idempotente: si ya la tenía activada, no hace nada (ver
    activar_oposicion_usuario)."""
    from registro_progreso_usuario import activar_oposicion_usuario

    data = request.get_json(silent=True) or {}
    oposicion = data.get("oposicion")
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    activar_oposicion_usuario(
        db, g.uid, oposicion,
        email=g.email, email_verificado=getattr(g, "email_verificado", True),
    )
    return jsonify({"mensaje": "Oposición activada"})


@bp.route("/temas-disponibles", methods=["GET"])
@requiere_plan(db, "basico", global_check=False)
def obtener_temas_disponibles():
    oposicion = obtener_oposicion_solicitada()
    coleccion = coleccion_temario(oposicion)
    # Bloques/temas marcados como borrador desde el panel admin
    # (publicado=false) no aparecen en la navegación normal de usuarios --
    # por defecto (sin el campo) se consideran publicados, para no ocultar
    # lo ya visible. Cacheada (ver utils.obtener_temas_navegables): antes
    # esta consulta N+1 (una lectura de "temas" por bloque) se repetía sin
    # caché en cada carga de Test Oficial/Test Personalizado.
    temas_disponibles = obtener_temas_navegables(db, coleccion)
    return jsonify({"temas": temas_disponibles, "oposicion": oposicion})


@bp.route("/avisos-oficiales", methods=["GET"])
@requiere_login(db)
def avisos_oficiales():
    """Avisos oficiales ya publicados (convocatorias, listas de admitidos,
    fechas de examen...) para la oposición pedida -- detectados por la
    vigilancia del BOE y aprobados a mano desde el panel de admin (ver
    vigilancia_boe.py); nunca llegan aquí sin ese OK previo."""
    from publicacion_estatica_boe import _oposiciones_de

    oposicion = obtener_oposicion_solicitada()
    avisos = []
    consulta = db.collection("avisos_oficiales").where("estado", "==", "publicado")
    for doc in consulta.stream():
        d = doc.to_dict() or {}
        if oposicion not in _oposiciones_de(d):
            continue
        avisos.append({
            "id": doc.id,
            "tipo": d.get("tipo", ""),
            "titulo": d.get("titulo", ""),
            "resumen": d.get("resumen", ""),
            "url_boe": d.get("url_boe", ""),
            "fecha_boe": d.get("fecha_boe", ""),
        })
    avisos.sort(key=lambda a: a.get("fecha_boe", ""), reverse=True)
    return jsonify({"avisos": avisos[:5]})
