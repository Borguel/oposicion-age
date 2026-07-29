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
from auth_utils import requiere_admin, requiere_permiso, PERMISOS_VALIDOS
from planes import resolver_plan_efectivo, prueba_activa
from promociones import leer_promocion, promocion_vigente, PLANES_PROMOCIONABLES
from banco_fallos import _id_pregunta
from coste_ia import resumen_coste_usuario
from oposiciones import OPOSICIONES, OPOSICION_POR_DEFECTO, coleccion_temario, coleccion_examenes_oficiales, oposicion_valida
from blueprints.pagos import MOTIVOS_BAJA_VALIDOS
from limites_uso import cargar_limites_config, guardar_limites_config, TIPOS_META, limites_efectivos, _clave_periodo
from utils import _limpiar_cache_temario
from banco_preguntas_ia import coleccion_banco_preguntas

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
    plan, _sub = resolver_plan_efectivo(datos)
    return plan


def _oposiciones_activas(datos):
    activas = []
    for oid, sub in (datos.get("suscripciones") or {}).items():
        if (sub or {}).get("plan", "gratis") != "gratis":
            activas.append(oid)
    return activas


def _contar_subcoleccion(ref, nombre):
    """Nº de documentos de una subcolección del usuario. Usa la agregación
    count() (barata); si no está disponible, cae a contar el stream. Nunca
    debe romper la ficha."""
    try:
        return int(ref.collection(nombre).count().get()[0][0].value)
    except Exception:
        try:
            return sum(1 for _ in ref.collection(nombre).stream())
        except Exception:
            return 0


def _ficha_actividad(ref, datos):
    """Reúne, para la ficha de cliente del panel, los contadores de contenido
    creado (biblioteca de PDF, tarjetas, resúmenes…), el banco de repaso
    (favoritas/falladas), el rendimiento agregado y el histórico de coste de
    IA. Todo best-effort: cualquier fallo devuelve 0 en ese campo."""
    contenido = {
        "documentos": _contar_subcoleccion(ref, "documentos"),
        "resumenes": _contar_subcoleccion(ref, "resumenes_pdf"),
        "esquemas": _contar_subcoleccion(ref, "esquemas_pdf"),
        "tests_pdf": _contar_subcoleccion(ref, "tests_pdf"),
        "favoritas": _contar_subcoleccion(ref, "preguntas_favoritas"),
        "falladas": _contar_subcoleccion(ref, "preguntas_falladas"),
    }
    # Tarjetas: cada documento de tarjetas_pdf agrupa varias -- sumamos el
    # total real de tarjetas, no el nº de generaciones.
    tarjetas = 0
    try:
        for d in ref.collection("tarjetas_pdf").stream():
            dd = d.to_dict() or {}
            tarjetas += len(dd.get("tarjetas") or []) or int(dd.get("num_tarjetas", 0) or 0)
    except Exception:
        tarjetas = 0
    contenido["tarjetas"] = tarjetas

    # Rendimiento agregado (aciertos/fallos/blancos) sobre todas las
    # oposiciones, a partir de rendimiento_por_tema.
    aciertos = fallos = blancos = 0
    for e in (datos.get("estadisticas") or {}).values():
        for r in ((e or {}).get("rendimiento_por_tema") or {}).values():
            aciertos += (r or {}).get("aciertos", 0) or 0
            fallos += (r or {}).get("fallos", 0) or 0
            blancos += (r or {}).get("blancos", 0) or 0
    contestadas = aciertos + fallos + blancos
    rendimiento = {
        "aciertos": aciertos, "fallos": fallos, "blancos": blancos,
        "contestadas": contestadas,
        "porcentaje": round(aciertos / contestadas * 100) if contestadas else None,
    }

    # Histórico de coste de IA: TODOS los meses ordenados de más antiguo a
    # más reciente. El panel pinta las barras de los últimos meses y usa la
    # serie completa para el buscador por rango de fechas.
    hist = []
    for mes, m in sorted((datos.get("coste_ia") or {}).items()):
        hist.append({
            "mes": mes,
            "coste": round((m or {}).get("coste", 0) or 0, 4),
            "tokens": ((m or {}).get("tokens_in", 0) or 0) + ((m or {}).get("tokens_out", 0) or 0),
            "tokens_in": (m or {}).get("tokens_in", 0) or 0,
            "tokens_out": (m or {}).get("tokens_out", 0) or 0,
            "llamadas": (m or {}).get("llamadas", 0) or 0,
        })

    # Consumo del periodo actual por herramienta (limites_uso) -- para ver de
    # un vistazo cuánta IA está gastando ahora mismo.
    uso = {}
    for tipo, u in (datos.get("limites_uso") or {}).items():
        uso[tipo] = (u or {}).get("contador", 0) or 0

    return contenido, rendimiento, hist, uso


def _uso_herramientas(datos):
    """Consumo real de cada herramienta en el periodo actual frente al límite
    del plan del usuario -- para vigilar desde la ficha quién está tirando
    mucho de la IA. El Test Personalizado se mide en preguntas; el resto en
    usos."""
    plan = _plan_usuario(datos)
    tools = limites_efectivos(db)["tools"]
    usos = datos.get("limites_uso") or {}
    filas = []
    for m in TIPOS_META:
        tipo = m["id"]
        cfg = tools.get(tipo, {}).get(plan) or {"periodo": "mes", "limite": 0}
        periodo, limite = cfg.get("periodo", "mes"), cfg.get("limite", 0)
        u = usos.get(tipo) or {}
        consumido = u.get("contador", 0) if u.get("periodo") == _clave_periodo(periodo) else 0
        filas.append({
            "id": tipo,
            "nombre": m["nombre"],
            "unidad": m.get("unidad", "usos"),
            "consumido": consumido,
            "limite": limite,
            "periodo": periodo,
            "porcentaje": round(consumido / limite * 100) if limite else None,
        })
    return {"plan": plan, "filas": filas}


def _uso_pico(datos, plan, tools):
    """% de uso MÁS ALTO entre todas las herramientas del usuario en su periodo
    actual, y el nombre de esa herramienta. Para el indicador de la lista de
    usuarios (detectar de un vistazo quién apura su cupo)."""
    usos = datos.get("limites_uso") or {}
    pico, nombre = 0, ""
    for m in TIPOS_META:
        cfg = tools.get(m["id"], {}).get(plan) or {}
        limite = cfg.get("limite", 0)
        if not limite:
            continue
        u = usos.get(m["id"]) or {}
        consumido = u.get("contador", 0) if u.get("periodo") == _clave_periodo(cfg.get("periodo", "mes")) else 0
        pct = round(consumido / limite * 100)
        if pct > pico:
            pico, nombre = pct, m["nombre"]
    return pico, nombre


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


def _bajas_agregadas():
    """Agrega los motivos de baja de TODOS los usuarios (collection_group)
    -- solo cifras + comentarios sueltos, sin exponer qué usuario canceló
    qué (mismo criterio de privacidad que _fallos_agregados)."""
    por_motivo = {m: 0 for m in MOTIVOS_BAJA_VALIDOS}
    por_oposicion = {}
    comentarios = []
    total = 0
    for doc in db.collection_group("bajas_motivos").stream():
        datos = doc.to_dict() or {}
        motivo = datos.get("motivo")
        if motivo not in por_motivo:
            continue
        total += 1
        por_motivo[motivo] += 1
        oposicion = datos.get("oposicion") or "(sin oposición)"
        por_oposicion[oposicion] = por_oposicion.get(oposicion, 0) + 1
        comentario = (datos.get("comentario") or "").strip()
        if comentario:
            comentarios.append({
                "motivo": motivo, "comentario": comentario,
                "oposicion": datos.get("oposicion", ""), "fecha": datos.get("fecha", ""),
            })
    comentarios.sort(key=lambda c: c.get("fecha", ""), reverse=True)
    return {"total": total, "por_motivo": por_motivo, "por_oposicion": por_oposicion,
            "comentarios_recientes": comentarios[:50]}


def _titulo_tema(coleccion, tema_id):
    bloque = _bloque_de_tema(tema_id)
    tema = tema_id.split("-", 1)[1] if "-" in (tema_id or "") else ""
    if not bloque or not tema:
        return tema_id
    doc = db.collection(coleccion).document(bloque).collection("temas").document(tema).get()
    return (doc.to_dict() or {}).get("titulo", tema_id) if doc.exists else tema_id


def _titulo_bloque(coleccion, bloque_id):
    if not bloque_id:
        return bloque_id
    doc = db.collection(coleccion).document(bloque_id).get()
    return (doc.to_dict() or {}).get("titulo", bloque_id) if doc.exists else bloque_id


def _contar_coleccion(consulta):
    """Nº de documentos de una colección/consulta cualquiera. Usa la
    agregación count() (barata); si no está disponible, cae a contar el
    stream. Nunca debe romper la página que lo pide."""
    try:
        return int(consulta.count().get()[0][0].value)
    except Exception:
        try:
            return sum(1 for _ in consulta.stream())
        except Exception:
            return 0


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
    coste_ia_mes_total = 0.0
    gastadores = []  # (coste_mes, email, plan, uid)

    for doc in db.collection("usuarios").stream():
        datos = doc.to_dict() or {}
        total_usuarios += 1
        plan = _plan_usuario(datos)
        por_plan[plan] = por_plan.get(plan, 0) + 1
        coste_mes, _coste_total, _tok = resumen_coste_usuario(datos)
        if coste_mes > 0:
            coste_ia_mes_total += coste_mes
            gastadores.append({"uid": doc.id, "email": datos.get("email", ""), "plan": plan, "coste_mes": coste_mes})
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
    ) + sum(
        1 for _ in db.collection("mensajes_soporte").where("estado", "==", "pendiente").stream()
    )
    cambios_temario_pendientes = sum(
        1 for _ in db.collection("cambios_temario_propuestos").where("estado", "==", "pendiente").stream()
    )
    avisos_oficiales_pendientes = sum(
        1 for _ in db.collection("avisos_oficiales").where("estado", "==", "pendiente").stream()
    )
    return jsonify({
        "usuarios_totales": total_usuarios,
        "usuarios_por_plan": por_plan,
        "suscripciones_pago": suscripciones_pago,
        "mrr": round(mrr, 2),
        "coste_ia_mes": round(coste_ia_mes_total, 2),
        "top_gastadores_ia": sorted(gastadores, key=lambda g: g["coste_mes"], reverse=True)[:5],
        "usuarios_nuevos_7_dias": usuarios_nuevos_7,
        "usuarios_nuevos_30_dias": usuarios_nuevos_30,
        "usuarios_activos_7_dias": activos_7,
        "tests_ultimos_7_dias": tests_7,
        "tests_ultimos_30_dias": tests_30,
        "tests_total": tests_total,
        "top_temas_fallados": top_temas,
        "reportes_pendientes": reportes_pendientes,
        "cambios_temario_pendientes": cambios_temario_pendientes,
        "avisos_oficiales_pendientes": avisos_oficiales_pendientes,
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


@bp.route("/admin/api/banco-preguntas", methods=["GET"])
@requiere_permiso("temario")
def banco_preguntas_resumen():
    """Cuántas preguntas de Test Personalizado hay ya acumuladas en el banco
    interno por oposición (ver banco_preguntas_ia.py -- de momento solo
    almacenamiento, nada lo reutiliza todavía), y el desglose por bloque y
    tema de la oposición elegida. Sirve para decidir cuándo hay ya volumen
    suficiente como para empezar a ofrecer tests generados a partir de este
    banco en vez de generar siempre desde cero con DeepSeek."""
    oposicion = request.args.get("oposicion") or OPOSICION_POR_DEFECTO
    if not oposicion_valida(oposicion):
        oposicion = OPOSICION_POR_DEFECTO

    totales_por_oposicion = {
        oid: _contar_coleccion(db.collection(coleccion_banco_preguntas(oid)))
        for oid in OPOSICIONES
    }

    coleccion_temario_actual = coleccion_temario(oposicion)
    conteo_por_tema = {}
    for doc in db.collection(coleccion_banco_preguntas(oposicion)).stream():
        tid = (doc.to_dict() or {}).get("tema_id") or ""
        conteo_por_tema[tid] = conteo_por_tema.get(tid, 0) + 1

    por_tema = []
    conteo_por_bloque = {}
    for tid, total in conteo_por_tema.items():
        bloque_id = _bloque_de_tema(tid)
        titulo_tema = _titulo_tema(coleccion_temario_actual, tid) if bloque_id else "Sin tema identificado"
        titulo_bloque = _titulo_bloque(coleccion_temario_actual, bloque_id) if bloque_id else "Sin bloque identificado"
        por_tema.append({"tema_id": tid, "titulo": titulo_tema, "bloque_titulo": titulo_bloque, "total": total})
        conteo_por_bloque[titulo_bloque] = conteo_por_bloque.get(titulo_bloque, 0) + total
    por_tema.sort(key=lambda t: t["total"], reverse=True)

    por_bloque = [{"titulo": titulo, "total": total} for titulo, total in conteo_por_bloque.items()]
    por_bloque.sort(key=lambda b: b["total"], reverse=True)

    return jsonify({
        "totales_por_oposicion": totales_por_oposicion,
        "oposicion": oposicion,
        "total_oposicion": totales_por_oposicion.get(oposicion, 0),
        "por_bloque": por_bloque,
        "por_tema": por_tema,
    })


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
    tools_efectivos = limites_efectivos(db)["tools"]  # una vez, cacheado

    filtrados = []
    for doc in db.collection("usuarios").stream():
        datos = doc.to_dict() or {}
        email = (datos.get("email") or "").lower()
        plan = _plan_usuario(datos)
        if busqueda and busqueda not in email:
            continue
        if filtro_plan and plan != filtro_plan:
            continue
        uso_pct, uso_tool = _uso_pico(datos, plan, tools_efectivos)
        filtrados.append({
            "uid": doc.id,
            "email": datos.get("email", ""),
            "nombre": datos.get("nombre", ""),
            "plan": plan,
            "en_prueba": prueba_activa(datos),
            "oposiciones_activas": _oposiciones_activas(datos),
            "fecha_creacion": datos.get("fecha_creacion"),
            "ultima_actividad": datos.get("ultima_actividad"),
            "uso_pct": uso_pct,
            "uso_tool": uso_tool,
        })

    orden = request.args.get("orden") or ""
    if orden == "uso":
        filtrados.sort(key=lambda u: u.get("uso_pct") or 0, reverse=True)
    else:
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
    contenido, rendimiento, coste_historico, uso_actual = _ficha_actividad(ref, datos)
    # El coste en € de IA (a diferencia de contenido/rendimiento, que no son
    # datos monetarios y sirven para dar soporte sin más) se oculta a un
    # admin con permiso parcial "usuarios" -- solo lo ve el admin TOTAL
    # (g.es_admin, no el "es_admin" de más abajo, que es del usuario
    # consultado, no de quien consulta).
    if g.es_admin:
        _cim, _cit, _tit = resumen_coste_usuario(datos)
    else:
        _cim = _cit = _tit = None
        coste_historico = None
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
        "en_prueba": prueba_activa(datos),
        "prueba_fin": datos.get("prueba_fin"),
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
        "coste_ia_mes": _cim,
        "coste_ia_total": _cit,
        "tokens_ia_total": _tit,
        "coste_ia_historico": coste_historico,
        "contenido_creado": contenido,
        "rendimiento": rendimiento,
        "uso_actual": uso_actual,
        "uso_herramientas": _uso_herramientas(datos),
        "notas_lista": _notas_lista(datos),
    })


def _notas_lista(datos):
    """Lista de notas internas del usuario. Migra en caliente la nota única
    antigua (notas_admin: str) a un elemento de la lista, para no perder lo
    ya escrito con el sistema viejo."""
    lista = list(datos.get("notas_lista") or [])
    legacy = (datos.get("notas_admin") or "").strip()
    if legacy and not any(n.get("id") == "legacy" for n in lista):
        lista.insert(0, {"id": "legacy", "texto": legacy, "autor": "", "fecha": ""})
    return lista


@bp.route("/admin/api/usuarios/<uid>/notas", methods=["PATCH"])
@requiere_permiso("usuarios")
def usuarios_notas(uid):
    """Compatibilidad: guarda la nota única antigua (notas_admin). El panel
    nuevo usa POST/DELETE sobre la lista de notas."""
    ref = db.collection("usuarios").document(uid)
    if not ref.get().exists:
        return jsonify({"error": "Usuario no encontrado"}), 404
    notas = str((request.get_json(silent=True) or {}).get("notas", ""))[:2000]
    ref.set({"notas_admin": notas}, merge=True)
    _registrar_auditoria("usuario_notas", uid)
    return jsonify({"mensaje": "Nota guardada"})


@bp.route("/admin/api/usuarios/<uid>/notas", methods=["POST"])
@requiere_permiso("usuarios")
def usuarios_notas_anadir(uid):
    """Añade una nota interna nueva a la lista, sin borrar las anteriores.
    Devuelve la nota creada (con su id) para pintarla al momento."""
    ref = db.collection("usuarios").document(uid)
    doc = ref.get()
    if not doc.exists:
        return jsonify({"error": "Usuario no encontrado"}), 404
    texto = str((request.get_json(silent=True) or {}).get("texto", "")).strip()[:2000]
    if not texto:
        return jsonify({"error": "La nota está vacía"}), 400
    nota = {
        "id": datetime.utcnow().strftime("%Y%m%d%H%M%S%f"),
        "texto": texto,
        "autor": getattr(g, "email", "") or "",
        "fecha": datetime.utcnow().isoformat(),
    }
    lista = list((doc.to_dict() or {}).get("notas_lista") or [])
    lista.append(nota)
    ref.set({"notas_lista": lista}, merge=True)
    _registrar_auditoria("usuario_nota_anadir", uid)
    return jsonify({"mensaje": "Nota añadida", "nota": nota}), 201


@bp.route("/admin/api/usuarios/<uid>/notas/<nota_id>", methods=["DELETE"])
@requiere_permiso("usuarios")
def usuarios_notas_eliminar(uid, nota_id):
    """Elimina una nota concreta por su id. 'legacy' borra la nota única
    antigua (notas_admin)."""
    ref = db.collection("usuarios").document(uid)
    doc = ref.get()
    if not doc.exists:
        return jsonify({"error": "Usuario no encontrado"}), 404
    datos = doc.to_dict() or {}
    if nota_id == "legacy":
        ref.set({"notas_admin": ""}, merge=True)
    else:
        lista = [n for n in (datos.get("notas_lista") or []) if n.get("id") != nota_id]
        ref.set({"notas_lista": lista}, merge=True)
    _registrar_auditoria("usuario_nota_eliminar", uid)
    return jsonify({"mensaje": "Nota eliminada"})


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


@bp.route("/admin/api/usuarios/<uid>/prueba", methods=["PATCH"])
@requiere_permiso("usuarios")
def usuarios_otorgar_prueba(uid):
    """Otorga o alarga la prueba gratuita de acceso Premium de un usuario
    (soporte: p. ej. compensar un problema, o dar más margen antes de que
    se bloquee). Vuelve a fijar prueba_fin desde AHORA + `dias`, sin sumar
    a lo que quedara antes."""
    ref = db.collection("usuarios").document(uid)
    if not ref.get().exists:
        return jsonify({"error": "Usuario no encontrado"}), 404
    try:
        dias = int((request.get_json(silent=True) or {}).get("dias", 7))
    except (TypeError, ValueError):
        return jsonify({"error": "Número de días no válido"}), 400
    if dias <= 0:
        return jsonify({"error": "El número de días debe ser mayor que 0"}), 400
    fin = (datetime.utcnow() + timedelta(days=dias)).isoformat()
    ref.set({"prueba_fin": fin}, merge=True)
    _registrar_auditoria("usuario_otorgar_prueba", uid, f"{dias} días")
    return jsonify({"mensaje": f"Prueba otorgada hasta {fin}", "prueba_fin": fin})


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
    try:
        pagina = max(1, int(request.args.get("pagina", 1)))
    except (TypeError, ValueError):
        pagina = 1
    por_pagina = 20
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
    total = len(reportes)
    inicio = (pagina - 1) * por_pagina
    reportes = reportes[inicio:inicio + por_pagina]

    # Adjuntar la pregunta oficial (opciones + correcta) si se localiza, para
    # poder juzgar el reporte sin salir de la pantalla. Se carga el banco de
    # cada oposición implicada una sola vez (no una consulta por reporte) --
    # y solo de las oposiciones que aparecen en ESTA página, no en todos los
    # reportes que existan.
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

    return jsonify({"reportes": reportes, "total": total, "pagina": pagina, "por_pagina": por_pagina})


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
# Cambios de temario propuestos por la vigilancia del BOE (ver
# vigilancia_boe.py + generador_diff_temario.py) -- nunca se aplican solos,
# alguien con permiso "temario" tiene que aprobarlos aquí.
# ============================================================
@bp.route("/admin/api/cambios-temario", methods=["GET"])
@requiere_permiso("temario")
def cambios_temario_listar():
    estado = request.args.get("estado", "pendiente")
    consulta = db.collection("cambios_temario_propuestos")
    if estado and estado != "todos":
        consulta = consulta.where("estado", "==", estado)
    cambios = []
    for doc in consulta.stream():
        d = doc.to_dict() or {}
        cambios.append({
            "id": doc.id,
            "oposicion": d.get("oposicion", ""),
            "bloque_id": d.get("bloque_id", ""),
            "tema_id": d.get("tema_id", ""),
            "subbloque_id": d.get("subbloque_id", ""),
            "ley_nombre": d.get("ley_nombre", ""),
            "boe_id": d.get("boe_id", ""),
            "resumen": d.get("resumen", ""),
            "texto_eliminar": d.get("texto_eliminar", ""),
            "texto_anadir": d.get("texto_anadir", ""),
            "estado": d.get("estado", "pendiente"),
            "fecha_deteccion": d.get("fecha_deteccion", ""),
            "revisado_por_email": d.get("revisado_por_email", ""),
            "fecha_revision": d.get("fecha_revision", ""),
        })
    cambios.sort(key=lambda c: c.get("fecha_deteccion", ""), reverse=True)
    return jsonify({"cambios": cambios})


@bp.route("/admin/api/cambios-temario/<cid>", methods=["PATCH"])
@requiere_permiso("temario")
def cambios_temario_actualizar(cid):
    data = request.get_json(silent=True) or {}
    estado = data.get("estado")
    if estado not in ("pendiente", "aprobado", "descartado"):
        return jsonify({"error": "Estado no válido"}), 400
    ref = db.collection("cambios_temario_propuestos").document(cid)
    doc = ref.get()
    if not doc.exists:
        return jsonify({"error": "Propuesta no encontrada"}), 404
    d = doc.to_dict() or {}

    if estado == "aprobado":
        if not oposicion_valida(d.get("oposicion")):
            return jsonify({"error": "Oposición no válida en la propuesta"}), 400
        chunk_ref = (
            db.collection(coleccion_temario(d["oposicion"])).document(d["bloque_id"])
            .collection("temas").document(d["tema_id"])
            .collection("subbloques").document(d["subbloque_id"])
        )
        chunk_doc = chunk_ref.get()
        if not chunk_doc.exists:
            return jsonify({"error": "El chunk de temario ya no existe"}), 409
        texto_actual = (chunk_doc.to_dict() or {}).get("texto", "")
        texto_eliminar = d.get("texto_eliminar", "")
        if texto_eliminar not in texto_actual:
            # El chunk cambió desde que se detectó la propuesta (alguien lo
            # editó a mano, u otra propuesta ya se aplicó antes) -- aplicar
            # a ciegas podría corromper el texto o no hacer nada; mejor
            # pedir revisión manual que arriesgarse.
            return jsonify({
                "error": "El texto a eliminar ya no coincide con el chunk actual (puede haber cambiado "
                         "desde que se detectó). Revisa y edita el chunk manualmente desde Temario."
            }), 409
        nuevo_texto = texto_actual.replace(texto_eliminar, d.get("texto_anadir", ""), 1)
        chunk_ref.update({"texto": nuevo_texto})
        _limpiar_cache_temario()

    ref.set({
        "estado": estado,
        "revisado_por": g.uid,
        "revisado_por_email": g.email,
        "fecha_revision": datetime.utcnow().isoformat(),
    }, merge=True)
    _registrar_auditoria("cambio_temario_" + estado, cid, d.get("resumen", ""))
    return jsonify({"mensaje": "Propuesta actualizada"})


# ============================================================
# Avisos oficiales detectados en el sumario del BOE (ver vigilancia_boe.py)
# -- nunca se muestran a los usuarios hasta que alguien con permiso
# "reportes" los publica aquí.
# ============================================================
@bp.route("/admin/api/avisos-oficiales", methods=["GET"])
@requiere_permiso("reportes")
def avisos_oficiales_listar():
    estado = request.args.get("estado", "pendiente")
    consulta = db.collection("avisos_oficiales")
    if estado and estado != "todos":
        consulta = consulta.where("estado", "==", estado)
    from publicacion_estatica_boe import _oposiciones_de

    avisos = []
    for doc in consulta.stream():
        d = doc.to_dict() or {}
        avisos.append({
            "id": doc.id,
            "oposiciones": _oposiciones_de(d),
            "tipo": d.get("tipo", ""),
            "tipo_personalizado": d.get("tipo_personalizado", ""),
            "titulo": d.get("titulo", ""),
            "resumen": d.get("resumen", ""),
            "url_boe": d.get("url_boe", ""),
            "url_inap": d.get("url_inap", ""),
            "fecha_boe": d.get("fecha_boe", ""),
            "estado": d.get("estado", "pendiente"),
            "fecha_deteccion": d.get("fecha_deteccion", ""),
            "revisado_por_email": d.get("revisado_por_email", ""),
            "fecha_revision": d.get("fecha_revision", ""),
        })
    avisos.sort(key=lambda a: a.get("fecha_deteccion", ""), reverse=True)
    return jsonify({"avisos": avisos})


def _leer_oposiciones_de_datos(data):
    """Lista de oposiciones de un payload de alta/edición de aviso --
    "oposiciones": [...] es lo normal (checkboxes en el admin), pero se
    acepta también un único "oposicion" suelto por si algún cliente
    antiguo lo manda así todavía."""
    lista = data.get("oposiciones")
    if lista is None and data.get("oposicion"):
        lista = [data["oposicion"]]
    return [op for op in (lista or []) if op]


@bp.route("/admin/api/avisos-oficiales", methods=["POST"])
@requiere_permiso("reportes")
def avisos_oficiales_crear():
    """Alta manual de un aviso oficial -- para lo que vigilancia_boe.py no
    puede detectar solo porque no viene del sumario del BOE (p. ej. una
    resolución publicada solo en el portal de firma del INAP). Se crea
    "pendiente" igual que los detectados automáticamente, así que sigue el
    mismo circuito de aprobación (nunca se publica nada sin que alguien con
    permiso "reportes" le dé al botón). Puede afectar a varias oposiciones
    a la vez (p. ej. un llamamiento extraordinario que menciona a AGE y
    GACE): se publica una sola vez y llega a las páginas/usuarios de
    todas, en vez de tener que darlo de alta una vez por oposición."""
    from publicacion_estatica_boe import ETIQUETA_TIPO_AVISO

    data = request.get_json(silent=True) or {}
    oposiciones = _leer_oposiciones_de_datos(data)
    tipo = data.get("tipo", "")
    titulo = (data.get("titulo") or "").strip()
    if not oposiciones or not all(oposicion_valida(op) for op in oposiciones):
        return jsonify({"error": "Selecciona al menos una oposición válida"}), 400
    if tipo not in ETIQUETA_TIPO_AVISO:
        return jsonify({"error": "Tipo no válido"}), 400
    if not titulo:
        return jsonify({"error": "Falta el título"}), 400

    ref = db.collection("avisos_oficiales").document()
    ref.set({
        "oposiciones": oposiciones,
        "tipo": tipo,
        "tipo_personalizado": (data.get("tipo_personalizado") or "").strip()[:100],
        "titulo": titulo[:300],
        "resumen": (data.get("resumen") or titulo)[:500],
        "url_boe": data.get("url_boe", ""),
        "url_inap": data.get("url_inap", ""),
        "fecha_boe": data.get("fecha_boe") or datetime.utcnow().strftime("%Y%m%d"),
        "fecha_deteccion": datetime.utcnow().isoformat(),
        "estado": "pendiente",
        "creado_manualmente_por": g.uid,
    })
    _registrar_auditoria("aviso_oficial_manual_creado", ref.id, titulo)
    return jsonify({"mensaje": "Aviso creado", "id": ref.id}), 201


@bp.route("/admin/api/avisos-oficiales/<aid>", methods=["PATCH"])
@requiere_permiso("reportes")
def avisos_oficiales_actualizar(aid):
    data = request.get_json(silent=True) or {}
    estado = data.get("estado")
    if estado not in ("pendiente", "publicado", "descartado"):
        return jsonify({"error": "Estado no válido"}), 400
    ref = db.collection("avisos_oficiales").document(aid)
    doc = ref.get()
    if not doc.exists:
        return jsonify({"error": "Aviso no encontrado"}), 404
    aviso_antes = doc.to_dict() or {}

    ref.set({
        "estado": estado,
        "revisado_por": g.uid,
        "revisado_por_email": g.email,
        "fecha_revision": datetime.utcnow().isoformat(),
    }, merge=True)
    _registrar_auditoria("aviso_oficial_" + estado, aid)

    # Publicar la(s) página(s) estática(s) + avisar por email solo la
    # PRIMERA vez que pasa a "publicado" (si ya estaba publicado y se
    # vuelve a guardar, no hace falta repetir el commit ni volver a mandar
    # el email a todo el mundo). Ninguna de las dos cosas debe romper esta
    # respuesta si falla -- ver publicacion_estatica_boe.py.
    if estado == "publicado" and aviso_antes.get("estado") != "publicado":
        # Ninguna de las llamadas falla nunca hacia arriba -- ver docstring
        # de publicacion_estatica_boe.py (capturan y registran su propio
        # fallo por separado, así que un commit fallido no frena a los otros).
        from publicacion_estatica_boe import (
            _oposiciones_de, actualizar_pagina_avisos_general,
            actualizar_pagina_estatica_avisos, notificar_usuarios_aviso_oficial,
        )
        aviso_completo = {**aviso_antes, "estado": estado}
        for op in _oposiciones_de(aviso_completo):
            actualizar_pagina_estatica_avisos(db, op)
        actualizar_pagina_avisos_general(db)
        notificar_usuarios_aviso_oficial(db, aviso_completo)

    return jsonify({"mensaje": "Aviso actualizado"})


@bp.route("/admin/api/avisos-oficiales/<aid>", methods=["PUT"])
@requiere_permiso("reportes")
def avisos_oficiales_editar(aid):
    """Corrige el CONTENIDO de un aviso ya creado -- título, tipo, enlaces,
    oposiciones afectadas... -- por si hubo un error al darlo de alta
    (enlace mal pegado, etc.), a diferencia del PATCH de arriba que solo
    cambia el estado. Se puede editar en cualquier estado, incluido uno ya
    "publicado": si lo está, se regenera la página estática (la propia de
    cada oposición afectada -- antes Y después del cambio, por si se quitó
    o añadió alguna -- más la página común) con el contenido corregido,
    pero DELIBERADAMENTE no se vuelve a mandar el email a los usuarios (ya
    lo recibieron; reenviarlo por corregir una errata sería spam)."""
    from publicacion_estatica_boe import ETIQUETA_TIPO_AVISO, _oposiciones_de

    data = request.get_json(silent=True) or {}
    ref = db.collection("avisos_oficiales").document(aid)
    doc = ref.get()
    if not doc.exists:
        return jsonify({"error": "Aviso no encontrado"}), 404
    aviso_antes = doc.to_dict() or {}

    oposiciones_antes = _oposiciones_de(aviso_antes)
    oposiciones = _leer_oposiciones_de_datos(data) if "oposiciones" in data or "oposicion" in data else oposiciones_antes
    tipo = data.get("tipo", aviso_antes.get("tipo", ""))
    titulo = (data.get("titulo") if "titulo" in data else aviso_antes.get("titulo", "")).strip()
    if not oposiciones or not all(oposicion_valida(op) for op in oposiciones):
        return jsonify({"error": "Selecciona al menos una oposición válida"}), 400
    if tipo not in ETIQUETA_TIPO_AVISO:
        return jsonify({"error": "Tipo no válido"}), 400
    if not titulo:
        return jsonify({"error": "Falta el título"}), 400

    cambios = {
        "oposiciones": oposiciones,
        "tipo": tipo,
        "tipo_personalizado": (data.get("tipo_personalizado", aviso_antes.get("tipo_personalizado", "")) or "").strip()[:100],
        "titulo": titulo[:300],
        "resumen": (data.get("resumen", aviso_antes.get("resumen", "")) or titulo)[:500],
        "url_boe": data.get("url_boe", aviso_antes.get("url_boe", "")),
        "url_inap": data.get("url_inap", aviso_antes.get("url_inap", "")),
        "fecha_boe": data.get("fecha_boe", aviso_antes.get("fecha_boe", "")),
        "editado_por": g.uid,
        "fecha_edicion": datetime.utcnow().isoformat(),
    }
    ref.set(cambios, merge=True)
    _registrar_auditoria("aviso_oficial_editado", aid, titulo)

    if aviso_antes.get("estado") == "publicado":
        from publicacion_estatica_boe import actualizar_pagina_avisos_general, actualizar_pagina_estatica_avisos
        # Unión de antes/después: si se quitó una oposición de la lista,
        # su página también tiene que regenerarse para que el aviso
        # desaparezca de ahí.
        for op in set(oposiciones) | set(oposiciones_antes):
            actualizar_pagina_estatica_avisos(db, op)
        actualizar_pagina_avisos_general(db)

    return jsonify({"mensaje": "Aviso actualizado"})


@bp.route("/admin/api/vigilancia-boe-salud", methods=["GET"])
@requiere_permiso("reportes")
def vigilancia_boe_salud():
    """Resultado del último chequeo de salud de LEYES_VIGILADAS (ver
    vigilancia_boe.verificar_bloque_temas_referenciados, que se ejecuta
    cada día dentro de /tareas/vigilar-boe): qué (oposicion, bloque_id,
    tema_id) referenciados ya no existen en el temario -- por ejemplo si
    se reestructuró y renumeró algún bloque/tema."""
    estado = db.collection("config").document("vigilancia_boe").get().to_dict() or {}
    return jsonify({
        "temas_faltantes": estado.get("temas_faltantes") or [],
        "fecha": estado.get("temas_faltantes_fecha", ""),
    })


# ============================================================
# Mensajes de soporte (consultas/problemas generales desde Mi Cuenta,
# sin pregunta asociada -- reusan el mismo permiso "reportes" que los
# reportes de preguntas, mostrados en la misma pestaña del panel admin)
# ============================================================
@bp.route("/admin/api/soporte", methods=["GET"])
@requiere_permiso("reportes")
def soporte_listar():
    estado = request.args.get("estado", "pendiente")
    consulta = db.collection("mensajes_soporte")
    if estado and estado != "todos":
        consulta = consulta.where("estado", "==", estado)
    mensajes = []
    for doc in consulta.stream():
        d = doc.to_dict() or {}
        mensajes.append({
            "id": doc.id,
            "email": d.get("email", ""),
            "mensaje": d.get("mensaje", ""),
            "estado": d.get("estado", "pendiente"),
            "fecha": d.get("fecha", ""),
        })
    mensajes.sort(key=lambda m: m.get("fecha", ""), reverse=True)
    return jsonify({"mensajes": mensajes})


@bp.route("/admin/api/soporte/<mid>", methods=["PATCH"])
@requiere_permiso("reportes")
def soporte_actualizar(mid):
    data = request.get_json(silent=True) or {}
    estado = data.get("estado")
    if estado not in ("pendiente", "revisado", "descartado"):
        return jsonify({"error": "Estado no válido"}), 400
    ref = db.collection("mensajes_soporte").document(mid)
    if not ref.get().exists:
        return jsonify({"error": "Mensaje no encontrado"}), 404
    ref.set({
        "estado": estado,
        "revisado_por": g.uid,
        "fecha_revision": datetime.utcnow().isoformat(),
    }, merge=True)
    _registrar_auditoria("soporte_" + estado, mid)
    return jsonify({"mensaje": "Mensaje actualizado"})


# ============================================================
# Motivos de baja (por qué cancela la gente)
# ============================================================
@bp.route("/admin/api/bajas", methods=["GET"])
@requiere_permiso("reportes")
def bajas_listar():
    return jsonify(_bajas_agregadas())


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
    # critico=True: si falta, algo de la web NO funciona (rojo). critico=False:
    # servicio opcional; si falta no pasa nada (ámbar, no alarma).
    servicios = [
        {"nombre": "Firebase / Firestore", "ok": True, "critico": True, "detalle": "Conectado (la app arranca con credenciales)."},
        {"nombre": "IA (DeepSeek)", "ok": _hay("DEEPSEEK_API_KEY"), "critico": True, "detalle": "Necesaria para Tu Tutor y generación de tests/resúmenes."},
        {"nombre": "Pagos (Stripe)", "ok": _hay("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"), "critico": True, "detalle": "Clave y webhook para cobros y altas de plan."},
        {"nombre": "Precios de planes", "ok": _hay("STRIPE_PRICE_ID_BASICO", "STRIPE_PRICE_ID_PREMIUM"), "critico": True, "detalle": "IDs de precio de básico y premium."},
        {"nombre": "Email (Brevo)", "ok": _hay("BREVO_API_KEY", "BREVO_FROM_EMAIL"), "critico": True, "detalle": "Bienvenida, verificar correo, recuperar contraseña, cancelación de suscripción y avisos de racha."},
        {"nombre": "Notificaciones push (VAPID)", "ok": _hay("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY"), "critico": False, "detalle": "Avisos push del navegador. Opcional."},
        {"nombre": "Errores (Sentry)", "ok": _hay("SENTRY_DSN"), "critico": False, "detalle": "Captura de errores en producción. Opcional."},
        {"nombre": "Límite de peticiones", "ok": os.environ.get("RATELIMIT_ENABLED", "true").lower() != "false", "critico": False, "detalle": "Protección contra abuso/bots. Activo salvo que lo desactives (RATELIMIT_ENABLED=false)."},
    ]
    criticos_ko = [s["nombre"] for s in servicios if s["critico"] and not s["ok"]]
    opcionales_ko = [s["nombre"] for s in servicios if not s["critico"] and not s["ok"]]

    # Pulso rápido de la web: cosas que conviene vigilar de un vistazo.
    def _contar(consulta):
        try:
            return int(consulta.count().get()[0][0].value)
        except Exception:
            try:
                return sum(1 for _ in consulta.stream())
            except Exception:
                return 0
    reportes_pendientes = (
        _contar(db.collection("reportes_preguntas").where("estado", "==", "pendiente"))
        + _contar(db.collection("mensajes_soporte").where("estado", "==", "pendiente"))
    )
    try:
        banner_doc = db.collection("config").document("banner").get()
        banner_activo = bool((banner_doc.to_dict() or {}).get("activo")) if banner_doc.exists else False
    except Exception:
        banner_activo = False

    return jsonify({
        "servicios": servicios,
        "diagnostico": {
            "todo_ok": not criticos_ko,
            "criticos_ko": criticos_ko,
            "opcionales_ko": opcionales_ko,
            "reportes_pendientes": reportes_pendientes,
            "banner_activo": banner_activo,
        },
    })


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
# Promoción / descuento temporal
# ============================================================
@bp.route("/admin/api/promocion", methods=["GET"])
@requiere_admin
def promocion_obtener():
    return jsonify(leer_promocion())


@bp.route("/admin/api/promocion", methods=["PUT"])
@requiere_admin
def promocion_guardar():
    data = request.get_json(silent=True) or {}
    plan = data.get("plan", "premium")
    if plan not in PLANES_PROMOCIONABLES:
        plan = "premium"
    try:
        descuento_pct = int(data.get("descuento_pct", 0))
    except (TypeError, ValueError):
        descuento_pct = 0
    descuento_pct = max(0, min(descuento_pct, 100))
    fecha_fin = str(data.get("fecha_fin", "")).strip()
    if fecha_fin:
        try:
            datetime.fromisoformat(fecha_fin)
        except ValueError:
            return jsonify({"error": "Fecha de fin no válida (usa formato ISO, ej. 2026-08-01T23:59:00)"}), 400
    promo = {
        "activo": bool(data.get("activo", False)),
        "plan": plan,
        "descuento_pct": descuento_pct,
        "duracion_texto": str(data.get("duracion_texto", "")).strip()[:60],
        "fecha_fin": fecha_fin,
        "stripe_promotion_code": str(data.get("stripe_promotion_code", "")).strip()[:80],
        "mensaje": str(data.get("mensaje", "")).strip()[:200],
    }
    db.collection("config").document("promocion").set(promo)
    _registrar_auditoria(
        "promocion", "",
        ("ON: " if promo["activo"] else "OFF: ") + f"{promo['plan']} -{promo['descuento_pct']}%"
    )
    return jsonify({"mensaje": "Promoción guardada", **promo})


@bp.route("/promocion-activa", methods=["GET"])
def promocion_publica():
    """Lectura pública: el frontend decide si mostrarla según el plan del
    usuario (o si no hay sesión). Solo devuelve datos si sigue vigente --
    pasada la fecha_fin se comporta como si estuviera desactivada, sin
    necesidad de que nadie la apague a mano."""
    promo = leer_promocion()
    if not promocion_vigente(promo):
        return jsonify({"activo": False})
    return jsonify(promo)


# ============================================================
# Límites de uso por plan (editables desde el panel)
# ============================================================
@bp.route("/admin/api/limites", methods=["GET"])
@requiere_admin
def limites_obtener():
    cfg = cargar_limites_config(db)
    return jsonify({
        "tools": cfg["tools"],
        "max_paginas": cfg["max_paginas"],
        "meta": TIPOS_META,
        "planes": ["gratis", "basico", "premium"],
    })


@bp.route("/admin/api/limites", methods=["PUT"])
@requiere_admin
def limites_guardar():
    """Guarda los límites editados. Solo un admin total puede tocarlos, porque
    afectan directamente al gasto en IA de toda la plataforma."""
    data = request.get_json(silent=True) or {}
    cfg = guardar_limites_config(db, data)
    _registrar_auditoria("limites_editar", "", "Límites de uso actualizados")
    return jsonify({"mensaje": "Límites actualizados.", "tools": cfg["tools"], "max_paginas": cfg["max_paginas"]})


# ============================================================
# Registro de auditoría
# ============================================================
@bp.route("/admin/api/auditoria", methods=["GET"])
@requiere_admin
def auditoria_listar():
    """Últimas acciones de administración, de la más reciente a la más
    antigua, paginadas (mismo patrón que /admin/api/usuarios): antes solo
    se veían las últimas 100-200 sin ninguna forma de consultar entradas
    más antiguas. Nota: la lectura sigue siendo de TODA la colección (el
    fake de Firestore de los tests no soporta order_by/cursores, y este
    panel no tiene tanto volumen todavía como para justificar esa
    complejidad) -- lo que arregla la paginación es poder navegar el
    historial completo desde la UI, no el coste de lectura en Firestore."""
    try:
        pagina = max(1, int(request.args.get("pagina", 1)))
    except (TypeError, ValueError):
        pagina = 1
    por_pagina = 50
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
    total = len(entradas)
    inicio = (pagina - 1) * por_pagina
    return jsonify({
        "entradas": entradas[inicio:inicio + por_pagina],
        "total": total, "pagina": pagina, "por_pagina": por_pagina,
    })


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
