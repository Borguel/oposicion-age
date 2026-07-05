"""
Migración única: antes de que la web soportara varias oposiciones, cada
usuario tenía un solo campo "plan" plano en su documento. Ahora cada
oposición tiene su propia suscripción bajo usuarios/{uid}.suscripciones.{ID}.

Este script copia el "plan" (y los demás campos de suscripción) de cada
usuario existente a suscripciones.AGE -- la única oposición que existía
cuando se contrató -- para que nadie pierda acceso ni tenga que volver a
pagar. También intenta actualizar la metadata de su Subscription en Stripe
(si tiene una activa) para que quede grabado que es de "AGE"; así los
futuros webhooks de Stripe (customer.subscription.updated/deleted) ya la
reconocen sin depender del valor por defecto.

USO:
  python migrar_usuarios_a_suscripciones.py            # solo simula, no escribe nada
  python migrar_usuarios_a_suscripciones.py --aplicar   # aplica los cambios de verdad

Variables de entorno necesarias:
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)
  STRIPE_SECRET_KEY   (opcional, solo para actualizar metadata en Stripe)
"""
import argparse
import json
import os

import firebase_admin
from firebase_admin import credentials, firestore

try:
    import stripe
except ImportError:
    stripe = None


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
    if stripe and os.getenv("STRIPE_SECRET_KEY"):
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

    usuarios = list(db.collection("usuarios").stream())
    print(f"👥 {len(usuarios)} usuarios encontrados")

    migrados = 0
    ya_migrados = 0
    sin_plan = 0

    for doc in usuarios:
        datos = doc.to_dict() or {}
        if "AGE" in (datos.get("suscripciones") or {}):
            ya_migrados += 1
            continue
        if "plan" not in datos:
            sin_plan += 1
            continue

        suscripcion_age = {
            "plan": datos.get("plan", "gratis"),
            "stripe_subscription_id": datos.get("stripe_subscription_id"),
            "subscription_status": datos.get("subscription_status"),
            "current_period_end": datos.get("current_period_end"),
            "plan_updated_at": datos.get("plan_updated_at"),
        }
        print(f"  → {doc.id}: plan={suscripcion_age['plan']!r} estado={suscripcion_age['subscription_status']!r}")

        if aplicar:
            doc.reference.update({
                "suscripciones.AGE": suscripcion_age,
                "plan": firestore.DELETE_FIELD,
                "stripe_subscription_id": firestore.DELETE_FIELD,
                "subscription_status": firestore.DELETE_FIELD,
                "current_period_end": firestore.DELETE_FIELD,
                "plan_updated_at": firestore.DELETE_FIELD,
            })
            sub_id = suscripcion_age["stripe_subscription_id"]
            if sub_id and stripe and stripe.api_key:
                try:
                    stripe.Subscription.modify(
                        sub_id,
                        metadata={"uid": doc.id, "plan": suscripcion_age["plan"], "oposicion": "AGE"}
                    )
                except Exception as e:
                    print(f"    ⚠️ No se pudo actualizar metadata en Stripe para {sub_id}: {e}")
        migrados += 1

    print()
    print(f"✅ Migrados: {migrados}  |  Ya migrados antes: {ya_migrados}  |  Sin plan (usuarios ya nuevos): {sin_plan}")
    if not aplicar:
        print("👀 Esto ha sido solo una SIMULACIÓN, no se ha escrito nada. Ejecuta con --aplicar para aplicar los cambios de verdad.")


def main():
    parser = argparse.ArgumentParser(description="Migra usuarios con 'plan' plano a suscripciones.AGE")
    parser.add_argument("--aplicar", action="store_true", help="Aplica los cambios de verdad (si no, solo simula)")
    args = parser.parse_args()

    db = conectar_firestore()
    migrar(db, aplicar=args.aplicar)


if __name__ == "__main__":
    main()
