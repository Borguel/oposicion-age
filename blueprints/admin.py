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
import csv
import hmac
import io
import logging
import os
from datetime import datetime, timedelta

from flask import Blueprint, Response, g, jsonify, request
from firebase_admin import auth as firebase_auth

from firebase_setup import db
from auth_utils import requiere_admin, requiere_permiso, PERMISOS_VALIDOS, _mejor_plan
from banco_fallos import _id_pregunta
from oposiciones import OPOSICIONES, coleccion_temario, coleccion_examenes_oficiales, oposicion_valida
from utils import _limpiar_cache_temario

logger = logging.getLogger(__name__)
bp = Blueprint("admin", __name__)

# Precio mensual por plan (€), para estimar los ingresos recurrentes (MRR)
# en el panel. Debe cuadrar con la página de Planes.
_PRECIO_PLAN = {"basico": 4.99, "premium": 9.99}


# ============================================================
# Helpers
# ============================================================
def _respuesta_csv(cabecera, filas, nombre_fichero):
    """Genera un CSV descargable (UTF-8 con BOM para que Excel respete los
    acentos)."""
    buffer = io.StringIO()
    escritor = csv.writer(buffer)
    escritor.writerow(cabecera)
    escritor.writerows(filas)
    datos = "﻿" + buffer.getvalue()
    return Response(datos, mimetype="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{nombre_fichero}"',
    })


def _registrar_auditoria(accion, objetivo="", detalle=""):
    """Deja constancia de una acción de administración en la colección
    admin_auditoria (quién, qué, sobre qué, cuándo). Nunca debe hacer
    fallar la acción principal, así que cualquier error se ignora."""
    try:
        db.collection("admin_auditoria").document().set({
            "accion": accion,
            "objetivo": str(objetivo),
            "detalle": str(detalle)[:500],
            "por": getattr(g, "uid", ""),
            "email_admin": getattr(g, "email", ""),
            "fecha": datetime.utcnow().isoformat(),
        })
    except Exception:
        logger.warning("No se pudo registrar en auditoría: %s", accion, exc_info=True)


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


def _salud_contenido(oposicion):
    """Recorre el árbol del temario de una oposición y devuelve cifras de
    salud del contenido: nº de temas, cuántos están sin fichas (huecos de
    contenido) y cuántos en borrador. Pensado para el panel: de un vistazo
    saber qué falta por rellenar."""
    if not oposicion_valida(oposicion):
        return {"temas_total": 0, "temas_sin_contenido": [], "temas_borrador": 0, "bloques_borrador": 0}
    coleccion = coleccion_temario(oposicion)
    temas_total = 0
    sin_contenido = []
    temas_borrador = 0
    bloques_borrador = 0
    for bloque in db.collection(coleccion).stream():
        bdatos = bloque.to_dict() or {}
        if bdatos.get("publicado", True) is False:
            bloques_borrador += 1
        for tema in db.collection(coleccion).document(bloque.id).collection("temas").stream():
            tdatos = tema.to_dict() or {}
            temas_total += 1
            if tdatos.get("publicado", True) is False:
                temas_borrador += 1
            tiene = any(True for _ in (db.collection(coleccion).document(bloque.id)
                        .collection("temas").document(tema.id).collection("subbloques").limit(1).stream()))
            if not tiene:
                sin_contenido.append({
                    "tema_id": f"{bloque.id}-{tema.id}",
                    "bloque": bloque.id,
                    "tema": tema.id,
                    "titulo": tdatos.get("titulo", tema.id),
                })
    sin_contenido.sort(key=lambda t: t["tema_id"])
    return {
        "temas_total": temas_total,
        "temas_sin_contenido": sin_contenido,
        "temas_borrador": temas_borrador,
        "bloques_borrador": bloques_borrador,
    }


def _preguntas_stats(oposicion):
    """Cuenta preguntas oficiales activas / inactivas / sin explicación."""
    if not oposicion_valida(oposicion):
        return {"activas": 0, "inactivas": 0, "sin_explicacion": 0}
    coleccion = coleccion_examenes_oficiales(oposicion)
    activas = inactivas = sin_explicacion = 0
    for doc in db.collection(coleccion).stream():
        d = doc.to_dict() or {}
        if d.get("tipo") != "pregunta":
            continue
        if d.get("activa", True) is False:
            inactivas += 1
            continue
        activas += 1
        if not (d.get("explicacion") or "").strip():
            sin_explicacion += 1
    return {"activas": activas, "inactivas": inactivas, "sin_explicacion": sin_explicacion}


# ============================================================
# Dashboard
# ============================================================
@bp.route("/admin/api/resumen", methods=["GET"])
@requiere_permiso(*PERMISOS_VALIDOS)  # cualquier miembro del equipo
def resumen():
    oposicion = request.args.get("oposicion") or "AGE"
    ahora = datetime.utcnow()
    hace_7, hace_30 = ahora - timedelta(days=7), ahora - timedelta(days=30)
    total_usuarios = 0
    por_plan = {}
    tests_7 = tests_30 = tests_total = 0
    usuarios_nuevos_7 = usuarios_nuevos_30 = 0
    activos_7 = 0
    suscripciones_pago = 0
    mrr = 0.0

    for doc in db.collection("usuarios").stream():
        datos = doc.to_dict() or {}
        total_usuarios += 1
        plan = _plan_usuario(datos)
        por_plan[plan] = por_plan.get(plan, 0) + 1
        # MRR: se cuenta CADA suscripción de pago (una por oposición).
        for _oid, sub in (datos.get("suscripciones") or {}).items():
            precio = _PRECIO_PLAN.get((sub or {}).get("plan"))
            if precio:
                suscripciones_pago += 1
                mrr += precio
        alta = _parse_fecha(datos.get("fecha_creacion"))
        if alta and alta >= hace_7:
            usuarios_nuevos_7 += 1
        if alta and alta >= hace_30:
            usuarios_nuevos_30 += 1
        ult = _parse_fecha(datos.get("ultima_actividad"))
        if ult and ult >= hace_7:
            activos_7 += 1
        for _op, e in (datos.get("estadisticas") or {}).items():
            for t in (e.get("historial_tests") or []):
                tests_total += 1
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
        "suscripciones_pago": suscripciones_pago,
        "mrr": round(mrr, 2),
        "usuarios_nuevos_7_dias": usuarios_nuevos_7,
        "usuarios_nuevos_30_dias": usuarios_nuevos_30,
        "usuarios_activos_7_dias": activos_7,
        "tests_ultimos_7_dias": tests_7,
        "tests_ultimos_30_dias": tests_30,
        "tests_total": tests_total,
        "top_temas_fallados": top_temas,
        "reportes_pendientes": reportes_pendientes,
        "oposicion": oposicion,
        "salud_contenido": _salud_contenido(oposicion),
        "preguntas_stats": _preguntas_stats(oposicion),
    })


# ============================================================
# Analítica de contenido
# ============================================================
@bp.route("/admin/api/analitica-contenido", methods=["GET"])
@requiere_permiso("temario")
def analitica_contenido():
    """Agrega el rendimiento por tema de TODOS los usuarios de una oposición
    (aciertos/fallos/blancos, solo cifras) para ver qué temas se estudian más
    o menos y en cuáles se acierta peor. Además, qué temas del temario no
    tienen ninguna actividad."""
    oposicion = request.args.get("oposicion") or "AGE"
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400

    agg = {}
    for doc in db.collection("usuarios").stream():
        e = ((doc.to_dict() or {}).get("estadisticas") or {}).get(oposicion) or {}
        for tid, r in (e.get("rendimiento_por_tema") or {}).items():
            a = agg.setdefault(tid, {"aciertos": 0, "fallos": 0, "blancos": 0})
            a["aciertos"] += (r or {}).get("aciertos", 0)
            a["fallos"] += (r or {}).get("fallos", 0)
            a["blancos"] += (r or {}).get("blancos", 0)

    coleccion = coleccion_temario(oposicion)
    temas = []
    for tid, r in agg.items():
        respondidas = r["aciertos"] + r["fallos"]
        intentos = respondidas + r["blancos"]
        temas.append({
            "tema_id": tid,
            "titulo": _titulo_tema(coleccion, tid) if str(tid).startswith("bloque") else tid,
            "intentos": intentos,
            "respondidas": respondidas,
            "aciertos": r["aciertos"],
            "fallos": r["fallos"],
            "blancos": r["blancos"],
            "tasa_acierto": round(100 * r["aciertos"] / respondidas, 1) if respondidas else None,
        })
    temas.sort(key=lambda t: t["intentos"], reverse=True)

    # Temas del temario que no registran ninguna actividad.
    con_actividad = set(agg.keys())
    sin_actividad = []
    for bloque in db.collection(coleccion).stream():
        for tema in db.collection(coleccion).document(bloque.id).collection("temas").stream():
            tid = f"{bloque.id}-{tema.id}"
            if tid not in con_actividad:
                sin_actividad.append({"tema_id": tid, "titulo": (tema.to_dict() or {}).get("titulo", tid)})
    sin_actividad.sort(key=lambda t: t["tema_id"])

    return jsonify({"oposicion": oposicion, "temas": temas, "sin_actividad": sin_actividad})


# ============================================================
# Temario
# ============================================================
@bp.route("/admin/api/temario/<oposicion>", methods=["GET"])
@requiere_permiso("temario")
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
@requiere_permiso("temario")
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
@requiere_permiso("temario")
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
    _registrar_auditoria("temario_anadir_ficha", f"{oposicion}/{bloque}/{tema}", (data.get("titulo") or "")[:80])
    return jsonify({"mensaje": "Chunk añadido", "id": nuevo.id}), 201


@bp.route("/admin/api/temario/<oposicion>/<bloque>/<tema>/<chunk_id>", methods=["PUT"])
@requiere_permiso("temario")
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
        _registrar_auditoria("temario_editar_ficha", f"{oposicion}/{bloque}/{tema}/{chunk_id}")
    return jsonify({"mensaje": "Chunk actualizado"})


@bp.route("/admin/api/temario/<oposicion>/<bloque>/<tema>/<chunk_id>", methods=["DELETE"])
@requiere_permiso("temario")
def temario_borrar_chunk(oposicion, bloque, tema, chunk_id):
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    coleccion = coleccion_temario(oposicion)
    (db.collection(coleccion).document(bloque).collection("temas").document(tema)
     .collection("subbloques").document(chunk_id).delete())
    _limpiar_cache_temario()
    _registrar_auditoria("temario_borrar_ficha", f"{oposicion}/{bloque}/{tema}/{chunk_id}")
    return jsonify({"mensaje": "Chunk eliminado"})


@bp.route("/admin/api/temario/<oposicion>/<bloque>/publicado", methods=["PATCH"])
@requiere_permiso("temario")
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
    destino = f"{oposicion}/{bloque}" + (f"/{tema}" if tema else "")
    _registrar_auditoria("publicado" if publicado else "borrador", destino)
    return jsonify({"mensaje": "Estado de publicación actualizado", "publicado": publicado})


def _id_valido(valor):
    """Valida un id de documento de Firestore sencillo (sin barras ni
    espacios raros). Evita crear rutas inesperadas."""
    return bool(valor) and "/" not in valor and len(valor) <= 60 and valor.strip() == valor


@bp.route("/admin/api/temario/<oposicion>/nuevo-bloque", methods=["POST"])
@requiere_permiso("temario")
def temario_nuevo_bloque(oposicion):
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    data = request.get_json(silent=True) or {}
    bloque_id = (data.get("id") or "").strip()
    if not _id_valido(bloque_id):
        return jsonify({"error": "Id de bloque no válido (ej. bloque_07)"}), 400
    ref = db.collection(coleccion_temario(oposicion)).document(bloque_id)
    if ref.get().exists:
        return jsonify({"error": "Ya existe un bloque con ese id"}), 400
    ref.set({"titulo": (data.get("titulo") or bloque_id).strip(), "publicado": bool(data.get("publicado", False))})
    _limpiar_cache_temario()
    _registrar_auditoria("temario_nuevo_bloque", f"{oposicion}/{bloque_id}", (data.get("titulo") or "")[:80])
    return jsonify({"mensaje": "Bloque creado", "id": bloque_id}), 201


@bp.route("/admin/api/temario/<oposicion>/<bloque>/nuevo-tema", methods=["POST"])
@requiere_permiso("temario")
def temario_nuevo_tema(oposicion, bloque):
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    data = request.get_json(silent=True) or {}
    tema_id = (data.get("id") or "").strip()
    if not _id_valido(tema_id):
        return jsonify({"error": "Id de tema no válido (ej. tema_03)"}), 400
    coleccion = coleccion_temario(oposicion)
    if not db.collection(coleccion).document(bloque).get().exists:
        return jsonify({"error": "El bloque no existe"}), 404
    ref = db.collection(coleccion).document(bloque).collection("temas").document(tema_id)
    if ref.get().exists:
        return jsonify({"error": "Ya existe un tema con ese id"}), 400
    ref.set({"titulo": (data.get("titulo") or tema_id).strip(), "publicado": bool(data.get("publicado", False))})
    _limpiar_cache_temario()
    _registrar_auditoria("temario_nuevo_tema", f"{oposicion}/{bloque}/{tema_id}", (data.get("titulo") or "")[:80])
    return jsonify({"mensaje": "Tema creado", "id": tema_id}), 201


@bp.route("/admin/api/temario/<oposicion>/<bloque>", methods=["PATCH"])
@requiere_permiso("temario")
def temario_renombrar_bloque(oposicion, bloque):
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    titulo = ((request.get_json(silent=True) or {}).get("titulo") or "").strip()
    if not titulo:
        return jsonify({"error": "El título no puede estar vacío"}), 400
    ref = db.collection(coleccion_temario(oposicion)).document(bloque)
    if not ref.get().exists:
        return jsonify({"error": "Bloque no encontrado"}), 404
    ref.set({"titulo": titulo}, merge=True)
    _limpiar_cache_temario()
    _registrar_auditoria("temario_renombrar_bloque", f"{oposicion}/{bloque}", titulo[:80])
    return jsonify({"mensaje": "Bloque renombrado"})


@bp.route("/admin/api/temario/<oposicion>/<bloque>/<tema>/titulo", methods=["PATCH"])
@requiere_permiso("temario")
def temario_renombrar_tema(oposicion, bloque, tema):
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    titulo = ((request.get_json(silent=True) or {}).get("titulo") or "").strip()
    if not titulo:
        return jsonify({"error": "El título no puede estar vacío"}), 400
    ref = db.collection(coleccion_temario(oposicion)).document(bloque).collection("temas").document(tema)
    if not ref.get().exists:
        return jsonify({"error": "Tema no encontrado"}), 404
    ref.set({"titulo": titulo}, merge=True)
    _limpiar_cache_temario()
    _registrar_auditoria("temario_renombrar_tema", f"{oposicion}/{bloque}/{tema}", titulo[:80])
    return jsonify({"mensaje": "Tema renombrado"})


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
@requiere_permiso("temario")
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
@requiere_permiso("temario")
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
    _registrar_auditoria("pregunta_crear", f"{oposicion}/{ref.id}", data["pregunta"][:80])
    return jsonify({"mensaje": "Pregunta creada", "id": ref.id}), 201


@bp.route("/admin/api/preguntas/importar", methods=["POST"])
@requiere_permiso("temario")
def preguntas_importar():
    """Alta por lote de un examen completo. Recibe una lista de preguntas y
    crea las válidas, devolviendo cuántas se crearon y los errores de las
    que no pasaron validación (con su índice)."""
    data = request.get_json(silent=True) or {}
    oposicion = data.get("oposicion") or "AGE"
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    lista = data.get("preguntas")
    if not isinstance(lista, list) or not lista:
        return jsonify({"error": "Falta la lista 'preguntas'."}), 400
    examen_comun = (data.get("examen") or "").strip()
    coleccion = coleccion_examenes_oficiales(oposicion)
    creadas = 0
    errores = []
    for i, p in enumerate(lista):
        if not isinstance(p, dict):
            errores.append({"indice": i, "error": "No es un objeto válido"})
            continue
        error = _validar_pregunta_payload(p)
        if error:
            errores.append({"indice": i, "error": error})
            continue
        db.collection(coleccion).document().set({
            "tipo": "pregunta",
            "pregunta": p["pregunta"].strip(),
            "opciones": {k: str(p["opciones"][k]).strip() for k in ("A", "B", "C", "D")},
            "respuesta_correcta": p["respuesta_correcta"].upper(),
            "explicacion": (p.get("explicacion") or "").strip(),
            "tema_id": (p.get("tema_id") or "").strip(),
            "examen": (p.get("examen") or examen_comun).strip(),
            "numero": p.get("numero", i + 1),
            "psicotecnico": bool(p.get("psicotecnico", False)),
            "activa": True,
            "origen": "admin_import",
            "fecha_creacion": datetime.utcnow().isoformat(),
        })
        creadas += 1
    if creadas:
        _limpiar_cache_temario()
        _registrar_auditoria("preguntas_importar", f"{oposicion}/{examen_comun}", f"{creadas} creadas")
    return jsonify({"creadas": creadas, "errores": errores, "total": len(lista)})


@bp.route("/admin/api/preguntas/<pid>", methods=["PUT"])
@requiere_permiso("temario")
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
    _registrar_auditoria("pregunta_editar", f"{oposicion}/{pid}", data["pregunta"][:80])
    return jsonify({"mensaje": "Pregunta actualizada"})


@bp.route("/admin/api/preguntas/<pid>", methods=["DELETE"])
@requiere_permiso("temario")
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
    _registrar_auditoria("pregunta_desactivar", f"{oposicion}/{pid}")
    return jsonify({"mensaje": "Pregunta desactivada"})


@bp.route("/admin/api/preguntas/<pid>/reactivar", methods=["POST"])
@requiere_permiso("temario")
def preguntas_reactivar(pid):
    """Deshace el soft delete: vuelve a marcar activa=true."""
    oposicion = request.args.get("oposicion") or "AGE"
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    coleccion = coleccion_examenes_oficiales(oposicion)
    ref = db.collection(coleccion).document(pid)
    if not ref.get().exists:
        return jsonify({"error": "Pregunta no encontrada"}), 404
    ref.set({"activa": True}, merge=True)
    _limpiar_cache_temario()
    _registrar_auditoria("pregunta_reactivar", f"{oposicion}/{pid}")
    return jsonify({"mensaje": "Pregunta reactivada"})


@bp.route("/admin/api/preguntas/export", methods=["GET"])
@requiere_permiso("temario")
def preguntas_export():
    """Descarga todas las preguntas de una oposición en CSV."""
    oposicion = request.args.get("oposicion") or "AGE"
    if not oposicion_valida(oposicion):
        return jsonify({"error": "Oposición no válida"}), 400
    coleccion = coleccion_examenes_oficiales(oposicion)
    filas = []
    for doc in db.collection(coleccion).stream():
        d = doc.to_dict() or {}
        if d.get("tipo") != "pregunta":
            continue
        o = d.get("opciones") or {}
        filas.append([
            doc.id, d.get("pregunta", ""),
            o.get("A", ""), o.get("B", ""), o.get("C", ""), o.get("D", ""),
            (d.get("respuesta_correcta") or "").upper(),
            d.get("tema_id", ""), d.get("examen", ""),
            "no" if d.get("activa", True) is False else "si",
        ])
    filas.sort(key=lambda f: (f[7], f[1]))
    cabecera = ["id", "pregunta", "A", "B", "C", "D", "correcta", "tema_id", "examen", "activa"]
    return _respuesta_csv(cabecera, filas, f"preguntas_{oposicion}.csv")


# ============================================================
# Usuarios
# ============================================================
@bp.route("/admin/api/usuarios", methods=["GET"])
@requiere_permiso("usuarios")
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


@bp.route("/admin/api/usuarios/export", methods=["GET"])
@requiere_permiso("usuarios")
def usuarios_export():
    """Descarga todos los usuarios (con los filtros aplicados) en CSV."""
    busqueda = (request.args.get("busqueda") or "").strip().lower()
    filtro_plan = request.args.get("plan") or ""
    filas = []
    for doc in db.collection("usuarios").stream():
        datos = doc.to_dict() or {}
        email = (datos.get("email") or "").lower()
        plan = _plan_usuario(datos)
        if busqueda and busqueda not in email:
            continue
        if filtro_plan and plan != filtro_plan:
            continue
        filas.append([
            doc.id, datos.get("email", ""), datos.get("nombre", ""), plan,
            ", ".join(_oposiciones_activas(datos)),
            (datos.get("fecha_creacion") or "")[:10],
            (datos.get("ultima_actividad") or "")[:10],
        ])
    filas.sort(key=lambda f: f[6], reverse=True)
    cabecera = ["uid", "email", "nombre", "plan", "oposiciones_activas", "alta", "ultima_actividad"]
    return _respuesta_csv(cabecera, filas, "usuarios.csv")


@bp.route("/admin/api/usuarios", methods=["POST"])
@requiere_admin
def usuarios_crear():
    """Da de alta un usuario nuevo (Firebase Auth + documento en Firestore),
    con contraseña y, opcionalmente, admin/roles y un plan de partida. Solo
    un super-admin puede crear usuarios."""
    from registro_progreso_usuario import inicializar_estadisticas_usuario

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = str(data.get("password") or "")
    nombre = (data.get("nombre") or "").strip()
    if not email or "@" not in email:
        return jsonify({"error": "Email no válido"}), 400
    if len(password) < 6:
        return jsonify({"error": "La contraseña debe tener al menos 6 caracteres"}), 400

    try:
        usuario = firebase_auth.create_user(
            email=email, password=password, display_name=nombre or None,
            email_verified=bool(data.get("email_verificado", False)),
        )
    except firebase_auth.EmailAlreadyExistsError:
        return jsonify({"error": "Ya existe un usuario con ese email"}), 400
    except Exception as exc:
        logger.warning("Error creando usuario admin: %s", exc)
        return jsonify({"error": "No se pudo crear el usuario (revisa el email/contraseña)"}), 400

    uid = usuario.uid

    # Claims: admin total y/o roles parciales.
    claims = {}
    if data.get("admin") is True:
        claims["admin"] = True
    permisos = [p for p in (data.get("permisos") or []) if p in PERMISOS_VALIDOS]
    if permisos:
        claims["permisos"] = permisos
    if claims:
        firebase_auth.set_custom_user_claims(uid, claims)

    # Documento del usuario en Firestore (misma inicialización que en el alta
    # normal) + nombre y, si procede, un plan de partida.
    inicializar_estadisticas_usuario(db, uid, email=email)
    doc = {"email": email, "fecha_creacion": datetime.utcnow().isoformat(), "creado_por_admin": g.uid}
    if nombre:
        doc["nombre"] = nombre
    plan = data.get("plan")
    oposicion = data.get("oposicion") or "AGE"
    if plan in ("basico", "premium") and oposicion_valida(oposicion):
        doc[f"suscripciones.{oposicion}.plan"] = plan
        doc[f"suscripciones.{oposicion}.subscription_status"] = "active"
    db.collection("usuarios").document(uid).set(
        {k: v for k, v in doc.items() if "." not in k}, merge=True)
    # Los campos con punto (plan) se aplican con update para respetar el mapa.
    puntos = {k: v for k, v in doc.items() if "." in k}
    if puntos:
        db.collection("usuarios").document(uid).update(puntos)

    _registrar_auditoria("usuario_crear", uid, email + (" [admin]" if claims.get("admin") else ""))
    return jsonify({"mensaje": "Usuario creado", "uid": uid, "email": email}), 201


@bp.route("/admin/api/usuarios/<uid>", methods=["GET"])
@requiere_permiso("usuarios")
def usuarios_detalle(uid):
    """Ficha completa de un usuario para el panel: plan por oposición,
    racha, actividad, nº de tests y último override de soporte."""
    ref = db.collection("usuarios").document(uid)
    doc = ref.get()
    if not doc.exists:
        return jsonify({"error": "Usuario no encontrado"}), 404
    datos = doc.to_dict() or {}

    suscripciones = {}
    for oid, sub in (datos.get("suscripciones") or {}).items():
        suscripciones[oid] = {
            "plan": (sub or {}).get("plan", "gratis"),
            "estado": (sub or {}).get("subscription_status", ""),
        }

    tests_por_oposicion = {}
    tests_total = 0
    ultima_nota = None
    for oid, e in (datos.get("estadisticas") or {}).items():
        historial = e.get("historial_tests") or []
        tests_por_oposicion[oid] = len(historial)
        tests_total += len(historial)
        if historial:
            ultima_nota = historial[-1].get("nota", ultima_nota)

    racha = datos.get("racha") or {}
    bloqueado = False
    try:
        registro = firebase_auth.get_user(uid)
        claims = registro.custom_claims or {}
        es_admin = claims.get("admin") is True
        permisos = [p for p in (claims.get("permisos") or []) if p in PERMISOS_VALIDOS]
        bloqueado = bool(getattr(registro, "disabled", False))
    except Exception:
        es_admin = False
        permisos = []
    return jsonify({
        "uid": uid,
        "es_admin": es_admin,
        "bloqueado": bloqueado,
        "permisos": permisos,
        "permisos_disponibles": list(PERMISOS_VALIDOS),
        "email": datos.get("email", ""),
        "nombre": datos.get("nombre", ""),
        "plan": _plan_usuario(datos),
        "suscripciones": suscripciones,
        "oposiciones_activas": _oposiciones_activas(datos),
        "fecha_creacion": datos.get("fecha_creacion"),
        "ultima_actividad": datos.get("ultima_actividad"),
        "racha_actual": racha.get("racha_actual", 0),
        "racha_maxima": racha.get("racha_maxima", racha.get("racha_actual", 0)),
        "tests_total": tests_total,
        "tests_por_oposicion": tests_por_oposicion,
        "ultima_nota": ultima_nota,
        "email_verificado": bool(datos.get("email_verificado", False)),
        "admin_override": datos.get("admin_override"),
        "notas_admin": datos.get("notas_admin", ""),
    })


@bp.route("/admin/api/usuarios/<uid>/notas", methods=["PATCH"])
@requiere_permiso("usuarios")
def usuarios_notas(uid):
    """Guarda una nota interna de soporte sobre el usuario (no visible para
    él)."""
    ref = db.collection("usuarios").document(uid)
    if not ref.get().exists:
        return jsonify({"error": "Usuario no encontrado"}), 404
    notas = str((request.get_json(silent=True) or {}).get("notas", ""))[:2000]
    ref.set({"notas_admin": notas}, merge=True)
    _registrar_auditoria("usuario_notas", uid)
    return jsonify({"mensaje": "Nota guardada"})


@bp.route("/admin/api/usuarios/<uid>/plan", methods=["PATCH"])
@requiere_permiso("usuarios")
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
    _registrar_auditoria("usuario_cambiar_plan", uid, f"{oposicion} -> {nuevo_plan}: {(data.get('motivo') or '').strip()}")
    return jsonify({"mensaje": "Plan actualizado"})


@bp.route("/admin/api/usuarios/<uid>/admin", methods=["PATCH"])
@requiere_admin
def usuarios_cambiar_admin(uid):
    """Da o quita el custom claim admin a un usuario. Para no quedarse sin
    ningún administrador por error, un admin no puede quitarse el permiso a
    sí mismo desde aquí."""
    data = request.get_json(silent=True) or {}
    quiere_admin = bool(data.get("admin"))
    if uid == g.uid and not quiere_admin:
        return jsonify({"error": "No puedes quitarte a ti mismo el permiso de administrador."}), 400
    try:
        usuario = firebase_auth.get_user(uid)
    except Exception:
        return jsonify({"error": "Usuario no encontrado en Firebase Auth"}), 404
    claims = dict(usuario.custom_claims or {})
    if quiere_admin:
        claims["admin"] = True
    else:
        claims.pop("admin", None)
    firebase_auth.set_custom_user_claims(uid, claims)
    logger.info("Admin %s %s permiso admin a %s", g.uid, "dio" if quiere_admin else "quitó", uid)
    _registrar_auditoria("admin_dar" if quiere_admin else "admin_quitar", uid)
    return jsonify({
        "mensaje": "Permiso de administrador " + ("asignado." if quiere_admin else "revocado."),
        "es_admin": quiere_admin,
        "aviso": "El usuario debe cerrar sesión y volver a entrar para que el cambio surta efecto.",
    })


@bp.route("/admin/api/usuarios/<uid>/roles", methods=["PATCH"])
@requiere_admin
def usuarios_cambiar_roles(uid):
    """Asigna permisos granulares (temario, reportes, usuarios) a un usuario
    del equipo, sin darle admin completo. Solo un super-admin puede hacerlo."""
    data = request.get_json(silent=True) or {}
    pedidos = data.get("permisos") or []
    if not isinstance(pedidos, list):
        return jsonify({"error": "Formato de permisos no válido"}), 400
    permisos = [p for p in pedidos if p in PERMISOS_VALIDOS]
    try:
        usuario = firebase_auth.get_user(uid)
    except Exception:
        return jsonify({"error": "Usuario no encontrado en Firebase Auth"}), 404
    claims = dict(usuario.custom_claims or {})
    if permisos:
        claims["permisos"] = permisos
    else:
        claims.pop("permisos", None)
    firebase_auth.set_custom_user_claims(uid, claims)
    _registrar_auditoria("usuario_roles", uid, ", ".join(permisos) or "(ninguno)")
    return jsonify({
        "mensaje": "Permisos actualizados",
        "permisos": permisos,
        "aviso": "El usuario debe cerrar sesión y volver a entrar para que el cambio surta efecto.",
    })


@bp.route("/admin/api/usuarios/<uid>/resetear-racha", methods=["POST"])
@requiere_permiso("usuarios")
def usuarios_resetear_racha(uid):
    ref = db.collection("usuarios").document(uid)
    if not ref.get().exists:
        return jsonify({"error": "Usuario no encontrado"}), 404
    ref.set({"racha": {"racha_actual": 0, "ultima_fecha": None}}, merge=True)
    _registrar_auditoria("usuario_resetear_racha", uid)
    return jsonify({"mensaje": "Racha reseteada"})


@bp.route("/admin/api/usuarios/<uid>/resetear-limites", methods=["POST"])
@requiere_permiso("usuarios")
def usuarios_resetear_limites(uid):
    """Pone a cero los contadores de uso diario/mensual de las herramientas de
    IA de un usuario (soporte: si se ha quedado sin cupo por un fallo)."""
    ref = db.collection("usuarios").document(uid)
    if not ref.get().exists:
        return jsonify({"error": "Usuario no encontrado"}), 404
    ref.set({"limites_uso": {}}, merge=True)
    _registrar_auditoria("usuario_resetear_limites", uid)
    return jsonify({"mensaje": "Límites de uso reseteados"})


@bp.route("/admin/api/usuarios/<uid>/enlace", methods=["POST"])
@requiere_permiso("usuarios")
def usuarios_generar_enlace(uid):
    """Genera un enlace de restablecer contraseña o de verificación de email
    para el usuario. No lo envía: lo devuelve para que el admin se lo pase
    (así no depende de plantillas de email)."""
    tipo = (request.get_json(silent=True) or {}).get("tipo", "password")
    try:
        registro = firebase_auth.get_user(uid)
    except Exception:
        return jsonify({"error": "Usuario no encontrado en Firebase Auth"}), 404
    email = registro.email
    if not email:
        return jsonify({"error": "El usuario no tiene email"}), 400
    try:
        if tipo == "verificacion":
            enlace = firebase_auth.generate_email_verification_link(email)
        else:
            enlace = firebase_auth.generate_password_reset_link(email)
    except Exception as exc:
        logger.warning("Error generando enlace %s para %s: %s", tipo, uid, exc)
        return jsonify({"error": "No se pudo generar el enlace"}), 400
    _registrar_auditoria("usuario_enlace_" + tipo, uid)
    return jsonify({"enlace": enlace, "email": email, "tipo": tipo})


@bp.route("/admin/api/usuarios/<uid>/bloqueo", methods=["PATCH"])
@requiere_admin
def usuarios_bloqueo(uid):
    """Habilita o deshabilita el acceso de un usuario (Firebase disabled). Un
    usuario deshabilitado no puede iniciar sesión. Solo super-admin, y no
    puede bloquearse a sí mismo."""
    bloquear = bool((request.get_json(silent=True) or {}).get("bloqueado"))
    if uid == g.uid and bloquear:
        return jsonify({"error": "No puedes bloquearte a ti mismo."}), 400
    try:
        firebase_auth.update_user(uid, disabled=bloquear)
    except Exception:
        return jsonify({"error": "Usuario no encontrado en Firebase Auth"}), 404
    _registrar_auditoria("usuario_bloquear" if bloquear else "usuario_desbloquear", uid)
    return jsonify({"mensaje": "Acceso bloqueado" if bloquear else "Acceso restaurado", "bloqueado": bloquear})


@bp.route("/admin/api/usuarios/<uid>", methods=["DELETE"])
@requiere_admin
def usuarios_eliminar(uid):
    """Elimina por completo la cuenta de un usuario (Firebase Auth + todos sus
    datos en Firestore, cancelando su suscripción de Stripe). Irreversible.
    Solo super-admin, y no puede eliminarse a sí mismo."""
    from gestion_cuenta import eliminar_cuenta_usuario
    if uid == g.uid:
        return jsonify({"error": "No puedes eliminar tu propia cuenta desde aquí."}), 400
    if not db.collection("usuarios").document(uid).get().exists:
        return jsonify({"error": "Usuario no encontrado"}), 404
    try:
        eliminar_cuenta_usuario(db, uid)
    except Exception as exc:
        logger.warning("Error eliminando cuenta %s: %s", uid, exc)
        return jsonify({"error": "No se pudo eliminar la cuenta por completo"}), 500
    _registrar_auditoria("usuario_eliminar", uid)
    return jsonify({"mensaje": "Cuenta eliminada"})


# ============================================================
# Reportes de preguntas
# ============================================================
@bp.route("/admin/api/reportes", methods=["GET"])
@requiere_permiso("reportes")
def reportes_listar():
    estado = request.args.get("estado", "pendiente")
    reportes = []
    consulta = db.collection("reportes_preguntas")
    if estado and estado != "todos":
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

    # Adjuntar la pregunta oficial (opciones + correcta) si se localiza, para
    # poder juzgar el reporte sin salir de la pantalla. Se carga el banco de
    # cada oposición implicada una sola vez (no una consulta por reporte).
    oposiciones_impl = {r["oposicion"] for r in reportes if r.get("oposicion")}
    bancos = {}
    for op in oposiciones_impl:
        if not oposicion_valida(op):
            continue
        indice = {}
        for pdoc in db.collection(coleccion_examenes_oficiales(op)).stream():
            pd = pdoc.to_dict() or {}
            if pd.get("tipo") != "pregunta":
                continue
            indice[(pd.get("pregunta") or "").strip()] = {
                "opciones": pd.get("opciones", {}),
                "respuesta_correcta": (pd.get("respuesta_correcta") or "").upper(),
                "explicacion": pd.get("explicacion", ""),
                "activa": pd.get("activa", True) is not False,
            }
        bancos[op] = indice
    for r in reportes:
        encontrada = bancos.get(r.get("oposicion"), {}).get((r.get("pregunta_texto") or "").strip())
        r["pregunta_oficial"] = encontrada  # None si no está en el banco

    return jsonify({"reportes": reportes})


@bp.route("/admin/api/reportes/<rid>", methods=["PATCH"])
@requiere_permiso("reportes")
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
    _registrar_auditoria("reporte_" + estado, rid)
    return jsonify({"mensaje": "Reporte actualizado"})


# ============================================================
# Salud del sistema
# ============================================================
@bp.route("/admin/api/sistema", methods=["GET"])
@requiere_admin
def sistema_estado():
    """Estado de configuración de los servicios externos (solo comprueba que
    las claves están presentes en el entorno, no hace llamadas de red)."""
    def _hay(*nombres):
        return all(bool(os.environ.get(n)) for n in nombres)
    servicios = [
        {"nombre": "Firebase / Firestore", "ok": True, "detalle": "Conectado (la app arranca con credenciales)."},
        {"nombre": "IA (DeepSeek)", "ok": _hay("DEEPSEEK_API_KEY"), "detalle": "Necesaria para Tu Tutor y generación de tests/resúmenes."},
        {"nombre": "Pagos (Stripe)", "ok": _hay("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"), "detalle": "Clave y webhook para cobros y altas de plan."},
        {"nombre": "Precios de planes", "ok": _hay("STRIPE_PRICE_ID_BASICO", "STRIPE_PRICE_ID_PREMIUM"), "detalle": "IDs de precio de básico y premium."},
        {"nombre": "Email (SendGrid)", "ok": _hay("SENDGRID_API_KEY", "SENDGRID_FROM_EMAIL"), "detalle": "Bienvenida, verificación y avisos de racha."},
        {"nombre": "Notificaciones push (VAPID)", "ok": _hay("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY"), "detalle": "Avisos push del navegador."},
        {"nombre": "Errores (Sentry)", "ok": _hay("SENTRY_DSN"), "detalle": "Captura de errores en producción. Opcional."},
        {"nombre": "Límite de peticiones", "ok": os.environ.get("RATELIMIT_ENABLED", "").lower() in ("1", "true", "yes"), "detalle": "Protección contra abuso/bots."},
    ]
    return jsonify({"servicios": servicios})


# ============================================================
# Banner / aviso global del sitio
# ============================================================
def _leer_banner():
    doc = db.collection("config").document("banner").get()
    d = doc.to_dict() or {} if doc.exists else {}
    return {
        "activo": bool(d.get("activo", False)),
        "texto": d.get("texto", ""),
        "tipo": d.get("tipo", "info"),
    }


@bp.route("/admin/api/banner", methods=["GET"])
@requiere_admin
def banner_obtener():
    return jsonify(_leer_banner())


@bp.route("/admin/api/banner", methods=["PUT"])
@requiere_admin
def banner_guardar():
    data = request.get_json(silent=True) or {}
    tipo = data.get("tipo", "info")
    if tipo not in ("info", "aviso", "urgente"):
        tipo = "info"
    banner = {
        "activo": bool(data.get("activo", False)),
        "texto": str(data.get("texto", "")).strip()[:300],
        "tipo": tipo,
    }
    db.collection("config").document("banner").set(banner)
    _registrar_auditoria("banner", "", ("ON: " if banner["activo"] else "OFF: ") + banner["texto"][:80])
    return jsonify({"mensaje": "Banner guardado", **banner})


@bp.route("/banner-global", methods=["GET"])
def banner_publico():
    """Lectura pública del banner (la usa el frontend en todas las páginas).
    Solo devuelve el texto si está activo."""
    banner = _leer_banner()
    if not banner["activo"] or not banner["texto"]:
        return jsonify({"activo": False})
    return jsonify(banner)


# ============================================================
# Registro de auditoría
# ============================================================
@bp.route("/admin/api/auditoria", methods=["GET"])
@requiere_admin
def auditoria_listar():
    """Últimas acciones de administración, de la más reciente a la más
    antigua."""
    try:
        limite = min(200, max(1, int(request.args.get("limite", 100))))
    except (TypeError, ValueError):
        limite = 100
    entradas = []
    for doc in db.collection("admin_auditoria").stream():
        d = doc.to_dict() or {}
        entradas.append({
            "accion": d.get("accion", ""),
            "objetivo": d.get("objetivo", ""),
            "detalle": d.get("detalle", ""),
            "email_admin": d.get("email_admin", ""),
            "fecha": d.get("fecha", ""),
        })
    entradas.sort(key=lambda e: e.get("fecha", ""), reverse=True)
    return jsonify({"entradas": entradas[:limite], "total": len(entradas)})


# ============================================================
# Arranque de un solo uso: asignar el primer admin sin Shell
# ============================================================
# NO lleva requiere_admin (sería el problema del huevo y la gallina: nadie
# es admin todavia). En su lugar se protege con un secreto que SOLO existe
# en la variable de entorno ADMIN_BOOTSTRAP_SECRET de Render. Si esa
# variable no está definida, la ruta responde 404 y no hace nada, así que
# en condiciones normales (sin secreto configurado) es como si no
# existiera. Pensada para usarse una vez y retirarse después.
#
# Acepta POST (cuerpo JSON) y GET (parámetros en la URL), este último para
# poder activarse desde el móvil abriendo un simple enlace en el navegador
# cuando no hay acceso a una terminal. El secreto va en la URL, aceptable
# solo porque es de un único uso y la variable se retira justo después.
@bp.route("/admin/api/bootstrap", methods=["GET", "POST"])
def bootstrap_admin():
    secreto_esperado = os.environ.get("ADMIN_BOOTSTRAP_SECRET", "")
    if not secreto_esperado:
        # Función desactivada: sin secreto configurado no existe.
        return jsonify({"error": "No encontrado"}), 404

    if request.method == "GET":
        secreto_recibido = str(request.args.get("secreto", ""))
        uid = str(request.args.get("uid", "")).strip()
    else:
        data = request.get_json(silent=True) or {}
        secreto_recibido = str(data.get("secreto", ""))
        uid = str(data.get("uid", "")).strip()

    # Comparación en tiempo constante para no filtrar el secreto por timing.
    if not hmac.compare_digest(secreto_recibido, secreto_esperado):
        logger.warning("Intento de bootstrap admin con secreto incorrecto")
        return jsonify({"error": "No autorizado"}), 403
    if not uid:
        return jsonify({"error": "Falta el uid"}), 400

    try:
        usuario = firebase_auth.get_user(uid)
    except Exception:
        return jsonify({"error": "UID no encontrado en Firebase Auth"}), 404

    claims = dict(usuario.custom_claims or {})
    claims["admin"] = True
    firebase_auth.set_custom_user_claims(uid, claims)
    logger.info("Bootstrap admin: claim admin asignado a %s", uid)
    return jsonify({
        "mensaje": "Permiso de administrador asignado.",
        "email": usuario.email,
        "aviso": "Cierra sesión y vuelve a entrar para que tu token recoja el cambio. Retira ya la variable ADMIN_BOOTSTRAP_SECRET.",
    })
