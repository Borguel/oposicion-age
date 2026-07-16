"""
Migración única: antes de este cambio existía un plan "gratis" permanente;
ahora se ha sustituido por una prueba Premium de 7 días (ver planes.py), que
solo se fija automáticamente al REGISTRARSE (inicializar_estadisticas_usuario).
Los usuarios que ya existían antes del cambio y no tienen ningún plan de pago
no tienen ese campo `prueba_fin`, así que con el nuevo gating se encontrarían
bloqueados de golpe sin haber tenido nunca su ventana de prueba.

Este script recorre `usuarios` y, para cada uno donde resolver_plan_efectivo
resuelva por debajo de "basico" Y no tenga ya `prueba_fin`, le da los 7 días
de prueba desde AHORA (no lo hace con quien ya tiene un plan de pago -- no
tiene ningún efecto en ellos -- ni con quien ya tiene `prueba_fin`, para no
alargarle la prueba dos veces si el script se ejecuta más de una vez).

USO:
  python migrar_usuarios_prueba.py            # solo simula, no escribe nada
  python migrar_usuarios_prueba.py --aplicar   # aplica los cambios de verdad

Variables de entorno necesarias:
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)
"""
import argparse
import json
import os
from datetime import datetime, timedelta

import firebase_admin
from firebase_admin import credentials, firestore

from planes import DURACION_PRUEBA_DIAS, ORDEN_PLANES, resolver_plan_efectivo


def conectar_firestore():
    if not firebase_admin._apps:
        cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
        if cred_json:
            cred = credentials.Certificate(json.loads(cred_json))
        else:
            cred = credentials.Certificate(os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json"))
        firebase_admin.initialize_app(cred)
    return firestore.client()


def migrar(db, aplicar=False):
    usuarios = list(db.collection("usuarios").stream())
    print(f"👥 {len(usuarios)} usuarios encontrados")

    migrados = 0
    con_plan_de_pago = 0
    ya_tenian_prueba = 0

    for doc in usuarios:
        datos = doc.to_dict() or {}

        if datos.get("prueba_fin"):
            ya_tenian_prueba += 1
            continue

        plan_actual, _sub = resolver_plan_efectivo(datos)
        if ORDEN_PLANES.get(plan_actual, 0) >= ORDEN_PLANES["basico"]:
            con_plan_de_pago += 1
            continue

        fin = (datetime.utcnow() + timedelta(days=DURACION_PRUEBA_DIAS)).isoformat()
        print(f"  → {doc.id} ({datos.get('email', 'sin email')}): prueba hasta {fin}")

        if aplicar:
            doc.reference.update({"prueba_fin": fin})
        migrados += 1

    print()
    print(f"✅ Migrados a prueba de {DURACION_PRUEBA_DIAS} días: {migrados}  |  "
          f"Ya tenían plan de pago (sin cambios): {con_plan_de_pago}  |  "
          f"Ya tenían prueba fijada (sin cambios): {ya_tenian_prueba}")
    if not aplicar:
        print("👀 Esto ha sido solo una SIMULACIÓN, no se ha escrito nada. Ejecuta con --aplicar para aplicar los cambios de verdad.")


def main():
    parser = argparse.ArgumentParser(description="Da la prueba gratuita de 7 días a usuarios existentes sin plan de pago ni prueba fijada")
    parser.add_argument("--aplicar", action="store_true", help="Aplica los cambios de verdad (si no, solo simula)")
    args = parser.parse_args()

    db = conectar_firestore()
    migrar(db, aplicar=args.aplicar)


if __name__ == "__main__":
    main()
