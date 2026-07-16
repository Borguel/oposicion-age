"""
Herramienta de solo lectura para investigar el estado real de una cuenta
concreta (Firebase Auth + Firestore) cuando algo no cuadra con lo que el
usuario ve en la web -- por ejemplo, "tenía plan premium y ahora me
aparece sin suscripción". No escribe nada en ningún sitio.

USO:
  python diagnosticar_usuario.py <email>

Variables de entorno necesarias:
  FIREBASE_KEY_PATH (o FIREBASE_CREDENTIALS_JSON)
"""
import argparse
import json
import os

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials, firestore


def conectar_firestore():
    if not firebase_admin._apps:
        cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
        if cred_json:
            cred = credentials.Certificate(json.loads(cred_json))
        else:
            cred = credentials.Certificate(os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json"))
        firebase_admin.initialize_app(cred)
    return firestore.client()


def diagnosticar(db, email):
    print(f"📦 Proyecto Firebase conectado: {firebase_admin.get_app().project_id}")
    print(f"🔎 Buscando \"{email}\"...")
    print()

    # ---- Firebase Auth: identidad, admin, estado de la cuenta ----
    try:
        registro = firebase_auth.get_user_by_email(email)
    except firebase_auth.UserNotFoundError:
        print("❌ No existe ninguna cuenta de Firebase Auth con ese email.")
        return

    print("== Firebase Auth ==")
    print(f"  uid: {registro.uid}")
    print(f"  email verificado: {registro.email_verified}")
    print(f"  cuenta deshabilitada: {registro.disabled}")
    print(f"  creada: {registro.user_metadata.creation_timestamp}")
    print(f"  último login: {registro.user_metadata.last_sign_in_timestamp}")
    print(f"  custom claims: {registro.custom_claims or {}}")
    print()

    # ---- Firestore: suscripciones, prueba, notas de soporte ----
    doc = db.collection("usuarios").document(registro.uid).get()
    if not doc.exists:
        print("❌ No existe usuarios/{uid} en Firestore -- la cuenta de Auth existe pero nunca")
        print("   llegó a hacer una petición autenticada (inicializar_estadisticas_usuario nunca")
        print("   se ha ejecutado para ella).")
        return

    datos = doc.to_dict() or {}
    print("== Firestore (usuarios/{}) ==".format(registro.uid))
    print(f"  email guardado: {datos.get('email')}")
    print(f"  suscripciones: {json.dumps(datos.get('suscripciones', {}), indent=2, ensure_ascii=False)}")
    print(f"  prueba_fin: {datos.get('prueba_fin')}")
    print(f"  stripe_customer_id: {datos.get('stripe_customer_id')}")
    print(f"  admin_override (último cambio de soporte): {datos.get('admin_override')}")
    print()

    print("== Historial de auditoría relevante (admin_auditoria) ==")
    # Sin order_by en la propia consulta para no depender de un índice
    # compuesto (objetivo + fecha) que igual no existe -- se ordena en
    # Python, que con el volumen de una cuenta individual sobra de sobra.
    entradas = [
        e.to_dict()
        for e in db.collection("admin_auditoria").where("objetivo", "==", registro.uid).stream()
    ]
    entradas.sort(key=lambda e: e.get("fecha") or "", reverse=True)
    if not entradas:
        print("  (sin entradas de auditoría con este uid como objetivo)")
    for e in entradas[:20]:
        print(f"  {e.get('fecha')} · {e.get('accion')} · {e.get('detalle')} · por {e.get('email_admin') or e.get('por')}")


def main():
    parser = argparse.ArgumentParser(description="Diagnóstico de solo lectura de una cuenta (Auth + Firestore)")
    parser.add_argument("email", help="Email de la cuenta a investigar")
    args = parser.parse_args()

    db = conectar_firestore()
    diagnosticar(db, args.email)


if __name__ == "__main__":
    main()
