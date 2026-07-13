"""Panel de administración. TODAS las rutas van protegidas con
requiere_admin: es la única barrera real (el frontend solo oculta el
enlace del panel, no protege nada).

Convenciones de datos que usa (ya existentes en el proyecto):
- Temario:    {coleccion_temario}/{bloque}/temas/{tema}/subbloques/{chunk}
              (cada "chunk"/"artículo" es un subbloque con titulo + texto)
- Preguntas:  examenes_oficiales_{OPOSICION}/{doc} con tipo="pregunta"
- Falladas:   usuarios/{uid}/preguntas_falladas/{hash} (subcolección por
              usuario -> se agrega con collection_group, sin exponer qué
              usuario individual falló qué)
- Reportes:   reportes_preguntas/{id} (colección global, nueva)
"""
import logging
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request

from firebase_setup import db
from auth_utils import requiere_admin, _mejor_plan
from banco_fallos import _id_pregunta
from oposiciones import OPOSICIONES, coleccion_temario, coleccion_examenes_oficiales, oposicion_valida
from utils import _limpiar_cache_temario

logger = logging.getLogger(__name__)
bp = Blueprint("admin", __name__)


# ============================================================
# Helpers
# ============================================================
def _parse_fecha(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _bloque_de_tema(tema_id):
    """'bloque_06-tema_01' -> 'bloque_06'. Vacío si no tiene ese formato."""
    return tema_id.split("-", 1)[0] if tema_id and "-" in tema_id else ""


def _plan_usuario(datos):
    plan, _sub = _mejor_plan(datos.get("suscripciones") or {})
    return plan


def _oposiciones_activas(datos):
    activas = []
    for oid, sub in (datos.get("suscripciones") or {}).items():
        if (sub or {}).get("plan", "gratis") != "gratis":
            activas.append(oid)
    return activas


def _fallos_agregados(oposicion=None):
    """Agrega el banco de falladas de TODOS los usuarios (collection_group)
    -- solo cifras agregadas, nunca qué usuario falló qué. Devuelve
    (fallos_por_tema, fallos_por_hash_de_pregunta)."""
    fallos_por_tema = {}
    fallos_por_hash = {}
    for doc in db.collection_group("preguntas_falladas").stream():
        datos = doc.to_dict() or {}
        if oposicion and datos.get("oposicion") != oposicion:
            continue
        veces = datos.get("veces_fallada", 1) or 1
        tema = datos.get("tema_id") or "(sin tema)"
        fallos_por_tema[tema] = fallos_por_tema.get(tema, 0) + veces
        fallos_por_hash[doc.id] = fallos_por_hash.get(doc.id, 0) + veces
    return fallos_por_tema, fallos_por_hash


def _titulo_tema(coleccion, tema_id):
    bloque = _bloque_de_tema(tema_id)
    tema = tema_id.split("-", 1)[1] if "-" in (tema_id or "") else ""
    if not bloque or not tema:
        return tema_id
    doc = db.collection(coleccion).document(bloque).collection("temas").document(tema).get()
    return (doc.to_dict() or {}).get("titulo", tema_id) if doc.exists else tema_id


# ============================================================
# Dashboard
# ============================================================
@bp.route("/admin/api/resumen", methods=["GET"])
@requiere_admin
def resumen():
    ahora = datetime.utcnow()
    hace_7, hace_30 = ahora - timedelta(days=7), ahora - timedelta(days=30)
    total_usuarios = 0
    por_plan = {}
    tests_7 = tests_30 = 0

    for doc in db.collection("usuarios").stream():
        datos = doc.to_dict() or {}
        total_usuarios += 1
        plan = _plan_usuario(datos)
        por_plan[plan] = por_plan.get(plan, 0) + 1
        for _op, e in (datos.get("estadisticas") or {}).items():
            for t in (e.get("historial_tests") or []):
                fecha = _parse_fecha(t.get("fecha"))
                if not fecha:
                    continue
                if fecha >= hace_7:
                    tests_7 += 1
                if fecha >= hace_30:
                    tests_30 += 1

    fallos_por_tema, _ = _fallos_agregados()
    top_temas = [
        {"tema_id": tid, "titulo": _titulo_tema(coleccion_temario("AGE"), tid) if tid.startswith("bloque") else tid, "fallos": n}
        for tid, n in sorted(fallos_por_tema.items(), key=lambda kv: kv[1], reverse=True)[:5]
    ]
    reportes_pendientes = sum(
        1 for _ in db.collection("reportes_preguntas").where("estado", "==", "pendiente").stream()
    )
    return jsonify({
        "usuarios_totales": total_usuarios,
        "usuarios_por_plan": por_plan,
        "tests_ultimos_7_dias": tests_7,
        "tests_ultimos_30_dias": tests_30,
        "top_temas_fallados": top_temas,
        "reportes_pendientes": reportes_pendientes,
    })


# ============================================================
# Temario
# ============================================================
@bp.route("/admin/api/temario/<oposicion>", methods=["GET"])
@requiere_admin
def temario_arbol(oposicion):
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    coleccion = coleccion_temario(oposicion)
    bloques = []
    for bloque in db.collection(coleccion).stream():
        bdatos = bloque.to_dict() or {}
        temas = []
        for tema in db.collection(coleccion).document(bloque.id).collection("temas").stream():
            tdatos = tema.to_dict() or {}
            n_chunks = sum(1 for _ in db.collection(coleccion).document(bloque.id)
                           .collection("temas").document(tema.id).collection("subbloques").stream())
            temas.append({
                "id": tema.id,
                "titulo": tdatos.get("titulo", tema.id),
                "num_chunks": n_chunks,
                "publicado": tdatos.get("publicado", True),
            })
        temas.sort(key=lambda t: t["id"])
        bloques.append({
            "id": bloque.id,
            "titulo": bdatos.get("titulo", bloque.id),
            "publicado": bdatos.get("publicado", True),
            "temas": temas,
        })
    bloques.sort(key=lambda b: b["id"])
    return jsonify({"oposicion": oposicion, "bloques": bloques})


@bp.route("/admin/api/temario/<oposicion>/<bloque>/<tema>", methods=["GET"])
@requiere_admin
def temario_tema(oposicion, bloque, tema):
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    coleccion = coleccion_temario(oposicion)
    ref = db.collection(coleccion).document(bloque).collection("temas").document(tema)
    chunks = []
    for sub in ref.collection("subbloques").stream():
        d = sub.to_dict() or {}
        chunks.append({
            "id": sub.id,
            "titulo": d.get("titulo", ""),
            "texto": d.get("texto", ""),
            "fuente": d.get("fuente", ""),
            "fecha_ingesta": d.get("fecha_ingesta", ""),
        })
    chunks.sort(key=lambda c: c["id"])
    return jsonify({"chunks": chunks})


@bp.route("/admin/api/temario/<oposicion>/<bloque>/<tema>", methods=["POST"])
@requiere_admin
def temario_anadir_chunk(oposicion, bloque, tema):
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    data = request.get_json(silent=True) or {}
    texto = (data.get("texto") or "").strip()
    if not texto:
        return jsonify({"error": "El texto no puede estar vacío"}), 400
    coleccion = coleccion_temario(oposicion)
    ref = db.collection(coleccion).document(bloque).collection("temas").document(tema).collection("subbloques")
    nuevo = ref.document()
    nuevo.set({
        "titulo": (data.get("titulo") or "").strip(),
        "texto": texto,
        "fuente": (data.get("fuente") or "manual (admin)").strip(),
        "fecha_ingesta": datetime.utcnow().isoformat(),
    })
    _limpiar_cache_temario()
    return jsonify({"mensaje": "Chunk añadido", "id": nuevo.id}), 201


@bp.route("/admin/api/temario/<oposicion>/<bloque>/<tema>/<chunk_id>", methods=["PUT"])
@requiere_admin
def temario_editar_chunk(oposicion, bloque, tema, chunk_id):
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    data = request.get_json(silent=True) or {}
    coleccion = coleccion_temario(oposicion)
    ref = (db.collection(coleccion).document(bloque).collection("temas").document(tema)
           .collection("subbloques").document(chunk_id))
    if not ref.get().exists:
        return jsonify({"error": "Chunk no encontrado"}), 404
    actualizacion = {}
    if "texto" in data:
        actualizacion["texto"] = str(data["texto"]).strip()
    if "titulo" in data:
        actualizacion["titulo"] = str(data["titulo"]).strip()
    if actualizacion:
        ref.update(actualizacion)
        _limpiar_cache_temario()
    return jsonify({"mensaje": "Chunk actualizado"})


@bp.route("/admin/api/temario/<oposicion>/<bloque>/<tema>/<chunk_id>", methods=["DELETE"])
@requiere_admin
def temario_borrar_chunk(oposicion, bloque, tema, chunk_id):
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    coleccion = coleccion_temario(oposicion)
    (db.collection(coleccion).document(bloque).collection("temas").document(tema)
     .collection("subbloques").document(chunk_id).delete())
    _limpiar_cache_temario()
    return jsonify({"mensaje": "Chunk eliminado"})


@bp.route("/admin/api/temario/<oposicion>/<bloque>/publicado", methods=["PATCH"])
@requiere_admin
def temario_publicar(oposicion, bloque):
    """Marca un bloque (o un tema concreto, si viene 'tema' en el cuerpo) como
    publicado o borrador. Los que estén en borrador (publicado=false) no
    aparecen en la navegación normal de usuarios (ver /temas-disponibles)."""
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    data = request.get_json(silent=True) or {}
    publicado = bool(data.get("publicado", True))
    tema = data.get("tema")
    coleccion = coleccion_temario(oposicion)
    if tema:
        ref = db.collection(coleccion).document(bloque).collection("temas").document(tema)
    else:
        ref = db.collection(coleccion).document(bloque)
    if not ref.get().exists:
        return jsonify({"error": "No encontrado"}), 404
    ref.set({"publicado": publicado}, merge=True)
    _limpiar_cache_temario()
    return jsonify({"mensaje": "Estado de publicación actualizado", "publicado": publicado})


# ============================================================
# Preguntas oficiales
# ============================================================
_CAMPOS_PREGUNTA = ("pregunta", "opciones", "respuesta_correcta", "explicacion",
                    "oposicion", "tema_id", "examen", "numero", "psicotecnico")


def _validar_pregunta_payload(data):
    pregunta = (data.get("pregunta") or "").strip()
    opciones = data.get("opciones") or {}
    correcta = (data.get("respuesta_correcta") or "").upper()
    if not pregunta:
        return "Falta el enunciado de la pregunta."
    if not isinstance(opciones, dict) or not all(k in opciones and str(opciones[k]).strip() for k in ("A", "B", "C", "D")):
        return "Hacen falta las 4 opciones (A, B, C, D) con contenido."
    if correcta not in ("A", "B", "C", "D"):
        return "La respuesta correcta debe ser A, B, C o D."
    return None


@bp.route("/admin/api/preguntas", methods=["GET"])
@requiere_admin
def preguntas_listar():
    oposicion = request.args.get("oposicion") or "AGE"
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    bloque = request.args.get("bloque")
    tema = request.args.get("tema")
    anio = request.args.get("anio")
    _fallos_tema, fallos_por_hash = _fallos_agregados(oposicion)

    coleccion = coleccion_examenes_oficiales(oposicion)
    resultado = []
    for doc in db.collection(coleccion).stream():
        d = doc.to_dict() or {}
        if d.get("tipo") != "pregunta":
            continue
        tema_id = d.get("tema_id") or ""
        if tema and tema_id != tema:
            continue
        if bloque and _bloque_de_tema(tema_id) != bloque:
            continue
        if anio and str(d.get("examen", "")).find(str(anio)) == -1:
            continue
        hash_pregunta = _id_pregunta(oposicion, d.get("pregunta", ""))
        resultado.append({
            "id": doc.id,
            "pregunta": d.get("pregunta", ""),
            "opciones": d.get("opciones", {}),
            "respuesta_correcta": (d.get("respuesta_correcta") or "").upper(),
            "explicacion": d.get("explicacion", ""),
            "tema_id": tema_id,
            "examen": d.get("examen", ""),
            "numero": d.get("numero", 0),
            "psicotecnico": bool(d.get("psicotecnico", False)),
            "activa": d.get("activa", True) is not False,
            "veces_fallada": fallos_por_hash.get(hash_pregunta, 0),
        })
    resultado.sort(key=lambda p: p["veces_fallada"], reverse=True)
    return jsonify({"preguntas": resultado, "total": len(resultado)})


@bp.route("/admin/api/preguntas", methods=["POST"])
@requiere_admin
def preguntas_crear():
    data = request.get_json(silent=True) or {}
    oposicion = data.get("oposicion") or "AGE"
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    error = _validar_pregunta_payload(data)
    if error:
        return jsonify({"error": error}), 400
    coleccion = coleccion_examenes_oficiales(oposicion)
    ref = db.collection(coleccion).document()
    ref.set({
        "tipo": "pregunta",
        "pregunta": data["pregunta"].strip(),
        "opciones": {k: str(data["opciones"][k]).strip() for k in ("A", "B", "C", "D")},
        "respuesta_correcta": data["respuesta_correcta"].upper(),
        "explicacion": (data.get("explicacion") or "").strip(),
        "tema_id": (data.get("tema_id") or "").strip(),
        "examen": (data.get("examen") or "").strip(),
        "numero": data.get("numero", 0),
        "psicotecnico": bool(data.get("psicotecnico", False)),
        "activa": True,
        "origen": "admin",
        "fecha_creacion": datetime.utcnow().isoformat(),
    })
    _limpiar_cache_temario()  # la caché de preguntas oficiales vive en el mismo store
    return jsonify({"mensaje": "Pregunta creada", "id": ref.id}), 201


@bp.route("/admin/api/preguntas/<pid>", methods=["PUT"])
@requiere_admin
def preguntas_editar(pid):
    data = request.get_json(silent=True) or {}
    oposicion = data.get("oposicion") or "AGE"
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    error = _validar_pregunta_payload(data)
    if error:
        return jsonify({"error": error}), 400
    coleccion = coleccion_examenes_oficiales(oposicion)
    ref = db.collection(coleccion).document(pid)
    if not ref.get().exists:
        return jsonify({"error": "Pregunta no encontrada"}), 404
    ref.set({
        "pregunta": data["pregunta"].strip(),
        "opciones": {k: str(data["opciones"][k]).strip() for k in ("A", "B", "C", "D")},
        "respuesta_correcta": data["respuesta_correcta"].upper(),
        "explicacion": (data.get("explicacion") or "").strip(),
        "tema_id": (data.get("tema_id") or "").strip(),
        "examen": (data.get("examen") or "").strip(),
        "numero": data.get("numero", 0),
        "psicotecnico": bool(data.get("psicotecnico", False)),
    }, merge=True)
    _limpiar_cache_temario()
    return jsonify({"mensaje": "Pregunta actualizada"})


@bp.route("/admin/api/preguntas/<pid>", methods=["DELETE"])
@requiere_admin
def preguntas_desactivar(pid):
    """Soft delete: marca activa=false en vez de borrar, para no romper el
    histórico de tests ya realizados que la incluyeron."""
    oposicion = request.args.get("oposicion") or "AGE"
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    coleccion = coleccion_examenes_oficiales(oposicion)
    ref = db.collection(coleccion).document(pid)
    if not ref.get().exists:
        return jsonify({"error": "Pregunta no encontrada"}), 404
    ref.set({"activa": False}, merge=True)
    _limpiar_cache_temario()
    return jsonify({"mensaje": "Pregunta desactivada"})


# ============================================================
# Usuarios
# ============================================================
@bp.route("/admin/api/usuarios", methods=["GET"])
@requiere_admin
def usuarios_listar():
    busqueda = (request.args.get("busqueda") or "").strip().lower()
    filtro_plan = request.args.get("plan") or ""
    try:
        pagina = max(1, int(request.args.get("pagina", 1)))
    except (TypeError, ValueError):
        pagina = 1
    por_pagina = 20

    filtrados = []
    for doc in db.collection("usuarios").stream():
        datos = doc.to_dict() or {}
        email = (datos.get("email") or "").lower()
        plan = _plan_usuario(datos)
        if busqueda and busqueda not in email:
            continue
        if filtro_plan and plan != filtro_plan:
            continue
        filtrados.append({
            "uid": doc.id,
            "email": datos.get("email", ""),
            "nombre": datos.get("nombre", ""),
            "plan": plan,
            "oposiciones_activas": _oposiciones_activas(datos),
            "fecha_creacion": datos.get("fecha_creacion"),
            "ultima_actividad": datos.get("ultima_actividad"),
        })

    filtrados.sort(key=lambda u: u.get("ultima_actividad") or "", reverse=True)
    total = len(filtrados)
    inicio = (pagina - 1) * por_pagina
    return jsonify({
        "usuarios": filtrados[inicio:inicio + por_pagina],
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
    })


@bp.route("/admin/api/usuarios/<uid>/plan", methods=["PATCH"])
@requiere_admin
def usuarios_cambiar_plan(uid):
    """Cambia el plan de un usuario manualmente (soporte). Deja SIEMPRE
    constancia de quién lo hizo, cuándo y por qué en admin_override, por
    trazabilidad."""
    data = request.get_json(silent=True) or {}
    nuevo_plan = data.get("plan")
    oposicion = data.get("oposicion") or "AGE"
    if nuevo_plan not in ("gratis", "basico", "premium"):
        return jsonify({"error": "Plan no válido"}), 400
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    ref = db.collection("usuarios").document(uid)
    if not ref.get().exists:
        return jsonify({"error": "Usuario no encontrado"}), 404
    ref.update({
        f"suscripciones.{oposicion}.plan": nuevo_plan,
        f"suscripciones.{oposicion}.subscription_status": "active" if nuevo_plan != "gratis" else "canceled",
        "admin_override": {
            "por": g.uid,
            "email_admin": g.email,
            "fecha": datetime.utcnow().isoformat(),
            "motivo": (data.get("motivo") or "").strip(),
            "cambio": f"{oposicion} -> {nuevo_plan}",
        },
    })
    return jsonify({"mensaje": "Plan actualizado"})


@bp.route("/admin/api/usuarios/<uid>/resetear-racha", methods=["POST"])
@requiere_admin
def usuarios_resetear_racha(uid):
    ref = db.collection("usuarios").document(uid)
    if not ref.get().exists:
        return jsonify({"error": "Usuario no encontrado"}), 404
    ref.set({"racha": {"racha_actual": 0, "ultima_fecha": None}}, merge=True)
    return jsonify({"mensaje": "Racha reseteada"})


# ============================================================
# Reportes de preguntas
# ============================================================
@bp.route("/admin/api/reportes", methods=["GET"])
@requiere_admin
def reportes_listar():
    estado = request.args.get("estado", "pendiente")
    reportes = []
    consulta = db.collection("reportes_preguntas")
    if estado:
        consulta = consulta.where("estado", "==", estado)
    for doc in consulta.stream():
        d = doc.to_dict() or {}
        reportes.append({
            "id": doc.id,
            "pregunta_id": d.get("pregunta_id", ""),
            "pregunta_texto": d.get("pregunta_texto", ""),
            "oposicion": d.get("oposicion", ""),
            "motivo": d.get("motivo", ""),
            "estado": d.get("estado", "pendiente"),
            "fecha": d.get("fecha", ""),
        })
    reportes.sort(key=lambda r: r.get("fecha", ""), reverse=True)
    return jsonify({"reportes": reportes})


@bp.route("/admin/api/reportes/<rid>", methods=["PATCH"])
@requiere_admin
def reportes_actualizar(rid):
    data = request.get_json(silent=True) or {}
    estado = data.get("estado")
    if estado not in ("pendiente", "revisado", "descartado"):
        return jsonify({"error": "Estado no válido"}), 400
    ref = db.collection("reportes_preguntas").document(rid)
    if not ref.get().exists:
        return jsonify({"error": "Reporte no encontrado"}), 404
    ref.set({
        "estado": estado,
        "revisado_por": g.uid,
        "fecha_revision": datetime.utcnow().isoformat(),
    }, merge=True)
    return jsonify({"mensaje": "Reporte actualizado"})
