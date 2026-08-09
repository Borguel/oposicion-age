"""
Migración única (transición al modelo de prueba/visibilidad por oposición,
ver planes.py y blueprints/temario.py:_oposiciones_visibles_para_la_peticion):
antes de este cambio TODA cuenta veía y podía usar las 3 oposiciones
públicas (AGE/GACE/Auxiliar) a la vez, con una única prueba gratuita de 7
días compartida por toda la cuenta. Ahora cada cuenta solo ve las
oposiciones que tiene en `suscripciones`, y cada una tiene su propia prueba
-- sin este script, los usuarios ya existentes que nunca llegaron a pagar
nada (suscripciones={}) se encontrarían de golpe sin ver ninguna oposición
la próxima vez que entraran.

Este script da a TODOS los usuarios existentes el plan Premium activo (sin
ninguna suscripción de Stripe real detrás, igual que un alta manual desde
el panel admin -- ver /admin/api/usuarios/<uid>/plan) en las 3 oposiciones
públicas, para que nadie pierda el día de este cambio el acceso que ya
tenía. Las cuentas nuevas a partir de aquí ya NO reciben esto: solo ven la
oposición que activan ellas mismas (ver activar_oposicion_usuario en
registro_progreso_usuario.py).

No toca ninguna entrada que YA tenga una suscripción de pago real detrás
(subscription_status distinto de "gratis" Y con stripe_subscription_id) --
no tiene sentido "regalarle" Premium a quien ya paga esa misma oposición, y
así el script es seguro de volver a ejecutar sin pisar suscripciones reales
de Stripe si se lanza más de una vez.

USO:
  python migrar_usuarios_premium_existente.py            # solo simula, no escribe nada
  python migrar_usuarios_premium_existente.py --aplicar   # aplica los cambios de verdad

Variables de entorno necesarias:
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)
"""
import argparse
import json
import os
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore

from oposiciones import OPOSICIONES

OPOSICIONES_A_OTORGAR = [oid for oid, datos in OPOSICIONES.items() if not datos.get("oculta")]


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
    print(f"📋 Oposiciones a otorgar: {', '.join(OPOSICIONES_A_OTORGAR)}")
    print()

    usuarios_tocados = 0
    entradas_otorgadas = 0
    entradas_respetadas = 0

    for doc in usuarios:
        datos = doc.to_dict() or {}
        suscripciones = datos.get("suscripciones", {}) or {}
        campos = {}
        otorgadas_este_usuario = []

        for oid in OPOSICIONES_A_OTORGAR:
            sub = suscripciones.get(oid) or {}
            plan_actual = sub.get("plan", "gratis")
            tiene_pago_real = plan_actual != "gratis" and bool(sub.get("stripe_subscription_id"))
            if tiene_pago_real:
                entradas_respetadas += 1
                continue
            campos[f"suscripciones.{oid}.plan"] = "premium"
            campos[f"suscripciones.{oid}.subscription_status"] = "active"
            campos[f"suscripciones.{oid}.plan_updated_at"] = datetime.utcnow().isoformat()
            otorgadas_este_usuario.append(oid)
            entradas_otorgadas += 1

        if not campos:
            continue
        print(f"  → {doc.id} ({datos.get('email', 'sin email')}): {', '.join(otorgadas_este_usuario)}")
        if aplicar:
            doc.reference.update(campos)
        usuarios_tocados += 1

    print()
    print(f"✅ Usuarios tocados: {usuarios_tocados}  |  Entradas Premium otorgadas: {entradas_otorgadas}  |  "
          f"Entradas respetadas (ya tenían una suscripción de pago real): {entradas_respetadas}")
    if not aplicar:
        print("👀 Esto ha sido solo una SIMULACIÓN, no se ha escrito nada. Ejecuta con --aplicar para aplicar los cambios de verdad.")


def main():
    parser = argparse.ArgumentParser(
        description="Da Premium activo en AGE/GACE/Auxiliar a todos los usuarios existentes "
                     "(transición al modelo de prueba/visibilidad por oposición)")
    parser.add_argument("--aplicar", action="store_true", help="Aplica los cambios de verdad (si no, solo simula)")
    args = parser.parse_args()

    db = conectar_firestore()
    migrar(db, aplicar=args.aplicar)


if __name__ == "__main__":
    main()
