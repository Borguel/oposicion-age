"""
Corrección única: el campo "resultado" (aprobado/suspendido) de un test se
calculaba en 3 sitios distintos que no siempre coincidían -- el peor de
ellos (registro_progreso_usuario.py) comparaba la puntuación en puntos
brutos (aciertos - fallos/3) contra un umbral fijo de 0.5 en vez de
normalizarla por el número de preguntas, así que prácticamente cualquier
test salía "aprobado" en las estadísticas agregadas sin importar cuántas
preguntas tuviera. Los tres sitios ya usan ahora la misma fórmula oficial
(utils.calcular_resultado_test), pero eso solo corrige los tests que se
guarden A PARTIR de ahora -- este script recalcula lo que ya estaba mal
guardado para cada usuario existente.

Qué toca (deliberadamente quirúrgico, no reescribe estadísticas enteras):
  - usuarios/{uid}/tests/{id}.resultado -- recalculado desde los
    aciertos/fallos/blancos YA guardados en cada test (esos siempre
    fueron correctos; solo el booleano derivado estaba mal).
  - usuarios/{uid}.estadisticas.{oposicion}.tests_aprobados/
    tests_suspendidos -- recontados desde cero iterando los tests
    finalizados de esa oposición con la fórmula correcta.
  - usuarios/{uid}.estadisticas.{oposicion}.historial_tests[].resultado
    -- recalculado por entrada (si a una entrada antigua le falta
    "blancos", se asume 0, que es lo que había realmente antes de
    empezar a guardar ese campo).
No se toca tests_realizados/total_aciertos/total_fallos/
rendimiento_por_tema/tiempo_total/puntuacion_media_test/temas_test: esos
campos no tienen el bug, y recalcularlos desde cero podría dar cifras
distintas por motivos ajenos a este arreglo (p. ej. tests borrados desde
entonces), que no es lo que se pide corregir aquí.

USO:
  python corregir_resultados_tests.py            # solo simula, no escribe nada
  python corregir_resultados_tests.py --aplicar   # aplica los cambios de verdad

Variables de entorno necesarias:
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)
"""
import argparse
import json
import os

import firebase_admin
from firebase_admin import credentials, firestore

from utils import calcular_resultado_test


def conectar_firestore():
    if not firebase_admin._apps:
        cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
        if cred_json:
            cred = credentials.Certificate(json.loads(cred_json))
        else:
            cred = credentials.Certificate(os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json"))
        firebase_admin.initialize_app(cred)
    return firestore.client()


def corregir(db, aplicar=False):
    usuarios = list(db.collection("usuarios").stream())
    print(f"👥 {len(usuarios)} usuarios encontrados")

    tests_corregidos = 0
    tests_ya_bien = 0
    usuarios_con_contadores_corregidos = 0

    for doc_usuario in usuarios:
        datos_usuario = doc_usuario.to_dict() or {}
        tests_ref = doc_usuario.reference.collection("tests")
        tests_docs = list(tests_ref.stream())

        # Recontar aprobados/suspendidos por oposición, iterando solo los
        # tests finalizados (los "en_progreso" no tienen un resultado real
        # todavía).
        aprobados_por_oposicion = {}
        suspendidos_por_oposicion = {}

        for doc_test in tests_docs:
            t = doc_test.to_dict() or {}
            if t.get("estado", "finalizado") != "finalizado":
                continue
            oposicion = t.get("oposicion")
            aciertos = t.get("aciertos", 0) or 0
            fallos = t.get("fallos", 0) or 0
            blancos = t.get("blancos", 0) or 0
            _, _, resultado_correcto = calcular_resultado_test(aciertos, fallos, blancos)

            if resultado_correcto == "aprobado":
                aprobados_por_oposicion[oposicion] = aprobados_por_oposicion.get(oposicion, 0) + 1
            else:
                suspendidos_por_oposicion[oposicion] = suspendidos_por_oposicion.get(oposicion, 0) + 1

            if t.get("resultado") != resultado_correcto:
                print(f"  → {doc_usuario.id}/tests/{doc_test.id}: resultado {t.get('resultado')!r} -> {resultado_correcto!r} "
                      f"(aciertos={aciertos}, fallos={fallos}, blancos={blancos})")
                tests_corregidos += 1
                if aplicar:
                    doc_test.reference.update({"resultado": resultado_correcto})
            else:
                tests_ya_bien += 1

        # Corregir los contadores agregados y el historial de cada
        # oposición que el usuario tenga en sus estadísticas.
        estadisticas = datos_usuario.get("estadisticas", {}) or {}
        actualizacion_usuario = {}
        contadores_cambiaron = False

        for oposicion, stats in estadisticas.items():
            aprobados_correctos = aprobados_por_oposicion.get(oposicion, 0)
            suspendidos_correctos = suspendidos_por_oposicion.get(oposicion, 0)

            if stats.get("tests_aprobados") != aprobados_correctos or stats.get("tests_suspendidos") != suspendidos_correctos:
                print(f"  → {doc_usuario.id} [{oposicion}]: aprobados {stats.get('tests_aprobados')!r}->{aprobados_correctos!r}, "
                      f"suspendidos {stats.get('tests_suspendidos')!r}->{suspendidos_correctos!r}")
                actualizacion_usuario[f"estadisticas.{oposicion}.tests_aprobados"] = aprobados_correctos
                actualizacion_usuario[f"estadisticas.{oposicion}.tests_suspendidos"] = suspendidos_correctos
                contadores_cambiaron = True

            historial = stats.get("historial_tests", []) or []
            historial_corregido = []
            historial_cambio = False
            for entrada in historial:
                _, _, resultado_correcto = calcular_resultado_test(
                    entrada.get("aciertos", 0) or 0, entrada.get("fallos", 0) or 0, entrada.get("blancos", 0) or 0
                )
                if entrada.get("resultado") != resultado_correcto:
                    historial_cambio = True
                nueva_entrada = dict(entrada)
                nueva_entrada["resultado"] = resultado_correcto
                historial_corregido.append(nueva_entrada)
            if historial_cambio:
                actualizacion_usuario[f"estadisticas.{oposicion}.historial_tests"] = historial_corregido
                contadores_cambiaron = True

        if contadores_cambiaron:
            usuarios_con_contadores_corregidos += 1
            if aplicar:
                doc_usuario.reference.update(actualizacion_usuario)

    print()
    print(f"✅ Tests corregidos: {tests_corregidos}  |  Ya estaban bien: {tests_ya_bien}")
    print(f"✅ Usuarios con contadores/historial corregidos: {usuarios_con_contadores_corregidos}")
    if not aplicar:
        print("👀 Esto ha sido solo una SIMULACIÓN, no se ha escrito nada. Ejecuta con --aplicar para aplicar los cambios de verdad.")


def main():
    parser = argparse.ArgumentParser(description="Recalcula aprobado/suspendido con la fórmula oficial en tests y estadísticas ya guardados")
    parser.add_argument("--aplicar", action="store_true", help="Aplica los cambios de verdad (si no, solo simula)")
    args = parser.parse_args()

    db = conectar_firestore()
    corregir(db, aplicar=args.aplicar)


if __name__ == "__main__":
    main()
