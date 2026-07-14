"""Reasigna el campo `tema_id` a TODAS las preguntas de exámenes oficiales de
TODAS las oposiciones (AGE, GACE, Auxiliar) a partir de los mapas ya
existentes en datos_examenes/*_temas.json, y AUDITA cuáles se quedan sin
tema.

Motivo: cada examen tenía su propio script de etiquetado que había que lanzar
a mano por año; si algún examen se subió a Firestore pero su etiquetado no se
llegó a ejecutar (o el patrón de doc_id no cuadraba), esas preguntas se
quedaron con tema_id vacío. Una pregunta sin tema NO sale nunca en un test
oficial FILTRADO por temas (sí en uno general), así que conviene tenerlas
todas asignadas.

Este script SOLO rellena las preguntas que no tienen tema: nunca pisa un
tema_id ya asignado (por si se corrigió a mano en el panel). Cubre las tres
oposiciones a la vez, descubriendo los exámenes automáticamente por los
ficheros datos_examenes/*_temas.json. En la práctica solo tocará AGE y
Auxiliar, porque GACE ya está entero etiquetado. Al final lista las preguntas
que SIGAN sin tema (por si hay alguna que ningún mapa cubre).

Por seguridad va en dos pasos, como el resto de scripts de datos:
    python reasignar_temas_examenes.py            # solo AUDITA (no escribe)
    python reasignar_temas_examenes.py --aplicar  # escribe los tema_id

Requiere FIREBASE_CREDENTIALS_JSON (o FIREBASE_KEY_PATH), igual que el resto.
"""
import os
import re
import sys
import glob
import json

import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

from oposiciones import OPOSICIONES, coleccion_examenes_oficiales, coleccion_temario
from utils import obtener_catalogo_temas

load_dotenv()

BASE_DIR = os.path.dirname(__file__)
DIR_DATOS = os.path.join(BASE_DIR, "datos_examenes")

# Códigos de parte del Auxiliar (deben coincidir con cargar_examen_oficial_auxiliar.py)
PARTE_CODIGO = {"primera": "p1", "segunda": "p2"}


def _init_firebase():
    if firebase_admin._apps:
        return
    cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if cred_json:
        cred = credentials.Certificate(json.loads(cred_json))
    else:
        cred = credentials.Certificate(os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json"))
    firebase_admin.initialize_app(cred)


def _pares_docid_tema():
    """Recorre todos los datos_examenes/*_temas.json y devuelve una lista de
    (oposicion, doc_id, tema_id) reconstruyendo el doc_id con el mismo patrón
    que usó el loader de cada oposición. Descubre los exámenes solos, así que
    cualquier examen nuevo que se añada al repo entra sin tocar este script."""
    pares = []
    for ruta in sorted(glob.glob(os.path.join(DIR_DATOS, "*_temas.json"))):
        nombre = os.path.basename(ruta)
        with open(ruta, encoding="utf-8") as f:
            mapa = json.load(f)

        # Ficheros *_docid_temas.json: mapa DIRECTO doc_id -> tema, para
        # exámenes subidos por el importador del panel (doc_id fuera del patrón
        # de los loaders). Estructura: {"oposicion": "AGE", "temas": {doc_id: tema_id}}.
        if nombre.endswith("_docid_temas.json"):
            oposicion = mapa.get("oposicion")
            if oposicion not in OPOSICIONES:
                print(f"AVISO: {nombre} sin oposición válida, lo salto.")
                continue
            for doc_id, tema_id in (mapa.get("temas") or {}).items():
                pares.append((oposicion, doc_id, tema_id))
            continue

        m_age = re.fullmatch(r"age_(.+)_ejercicio_unico_temas\.json", nombre)
        m_gace = re.fullmatch(r"gacel_(.+)_1er_ejercicio_temas\.json", nombre)
        m_aux = re.fullmatch(r"auxiliar_(.+)_ejercicio_unico_temas\.json", nombre)

        if m_age:
            clave = m_age.group(1)
            for numero_str, tema_id in mapa.items():
                doc_id = f"age_{clave}_eu_{int(numero_str):03d}"
                pares.append(("AGE", doc_id, tema_id))
        elif m_gace:
            clave = m_gace.group(1)
            for numero_str, tema_id in mapa.items():
                doc_id = f"gacel_{clave}_1ej_{int(numero_str):03d}"
                pares.append(("GACE", doc_id, tema_id))
        elif m_aux:
            clave = m_aux.group(1)
            for parte_numero, tema_id in mapa.items():
                parte, numero = parte_numero.rsplit("_", 1)
                doc_id = f"auxiliar_{clave}_eu_{PARTE_CODIGO[parte]}_{int(numero):03d}"
                pares.append(("AUXILIAR", doc_id, tema_id))
        else:
            print(f"AVISO: no sé de qué oposición es {nombre}, lo salto.")
    return pares


def _auditar_sin_tema(db):
    """Cuenta y lista las preguntas activas sin tema_id en cada oposición."""
    total = 0
    for oposicion in OPOSICIONES:
        coleccion = coleccion_examenes_oficiales(oposicion)
        sin_tema = []
        for doc in db.collection(coleccion).stream():
            d = doc.to_dict() or {}
            if d.get("tipo") != "pregunta":
                continue
            if d.get("activa", True) is False:
                continue
            if not d.get("tema_id"):
                sin_tema.append((doc.id, (d.get("pregunta") or "")[:70]))
        total += len(sin_tema)
        print(f"\n[{oposicion}] preguntas activas SIN tema: {len(sin_tema)}")
        for doc_id, texto in sin_tema[:40]:
            print(f"   - {doc_id}: {texto}")
        if len(sin_tema) > 40:
            print(f"   ... y {len(sin_tema) - 40} más")
    return total


def _volcar_sin_tema(db, oposicion):
    """Vuelca el catálogo de temas de la oposición y el texto COMPLETO de sus
    preguntas activas sin tema. Sirve para poder mapear a mano exámenes que se
    subieron por el importador del panel (doc_id fuera del patrón de los
    loaders, no cubiertos por ningún *_temas.json)."""
    print("=" * 60)
    print(f"CATÁLOGO DE TEMAS de {oposicion}:")
    for tema in obtener_catalogo_temas(db, coleccion_temario(oposicion)):
        print(f"   {tema['id']}: {tema['titulo']}")

    print("\n" + "=" * 60)
    print(f"PREGUNTAS SIN TEMA de {oposicion} (texto completo):")
    coleccion = coleccion_examenes_oficiales(oposicion)
    for doc in db.collection(coleccion).stream():
        d = doc.to_dict() or {}
        if d.get("tipo") != "pregunta" or d.get("activa", True) is False or d.get("tema_id"):
            continue
        print(f"\n--- {doc.id} ---")
        print((d.get("pregunta") or "").strip())
        for letra, texto in sorted((d.get("opciones") or {}).items()):
            print(f"   {letra}) {texto}")


def main(aplicar):
    _init_firebase()
    db = firestore.client()

    print("=" * 60)
    print("ANTES de reasignar:")
    antes = _auditar_sin_tema(db)

    pares = _pares_docid_tema()
    print("\n" + "=" * 60)
    print(f"Mapas cargados: {len(pares)} asignaciones (numero -> tema) en total.")

    if not aplicar:
        print("\n(modo AUDITORÍA: no se ha escrito nada. Lanza con --aplicar para corregir.)")
        return

    actualizadas = 0
    no_encontradas = []
    for oposicion, doc_id, tema_id in pares:
        ref = db.collection(coleccion_examenes_oficiales(oposicion)).document(doc_id)
        snap = ref.get()
        if not snap.exists:
            no_encontradas.append(doc_id)
            continue
        # Solo se RELLENAN las que no tienen tema. Una pregunta que ya tiene
        # tema_id NO se toca, aunque difiera del mapa, para no pisar una
        # corrección hecha a mano desde el panel ("Editar"). Así en GACE (que
        # ya está entero etiquetado) este script no escribe nada.
        if not (snap.to_dict() or {}).get("tema_id"):
            ref.update({"tema_id": tema_id})
            actualizadas += 1

    print(f"\nReasignadas {actualizadas} preguntas.")
    if no_encontradas:
        print(f"{len(no_encontradas)} doc_id del mapa no existen en Firestore (posible examen no subido):")
        for doc_id in no_encontradas[:20]:
            print(f"   - {doc_id}")
        if len(no_encontradas) > 20:
            print(f"   ... y {len(no_encontradas) - 20} más")

    print("\n" + "=" * 60)
    print("DESPUÉS de reasignar:")
    despues = _auditar_sin_tema(db)
    print("\n" + "=" * 60)
    print(f"Preguntas sin tema: {antes} -> {despues}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--dump" in args:
        _init_firebase()
        _volcar_sin_tema(firestore.client(), "AGE")
    else:
        main(aplicar="--aplicar" in args)
