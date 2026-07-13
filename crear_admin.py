"""Script PUNTUAL (no forma parte de la app) para dar permisos de
administrador a un usuario de Firebase Auth, asignándole el custom claim
`admin: true` con el Admin SDK.

Uso:
    python crear_admin.py <UID>          # dar admin
    python crear_admin.py <UID> --quitar # revocar admin

El UID se saca de la consola de Firebase (Authentication > Users) o del
propio documento usuarios/{uid} en Firestore. Tras ejecutarlo, el usuario
debe cerrar sesión y volver a entrar (o el token se refresca solo en ~1h)
para que su ID token lleve el nuevo claim.

Reutiliza firebase_setup.py, así que necesita las mismas credenciales que
el resto de la app (FIREBASE_CREDENTIALS_JSON o el fichero de clave).
"""
import sys

from firebase_admin import auth as firebase_auth

# Importar firebase_setup inicializa firebase_admin con las credenciales.
import firebase_setup  # noqa: F401


def asignar_admin(uid, es_admin=True):
    # get_user valida de paso que el UID existe (lanza si no) antes de tocar
    # los claims, para no crear un claim "huérfano" por un UID mal copiado.
    usuario = firebase_auth.get_user(uid)
    claims = dict(usuario.custom_claims or {})
    if es_admin:
        claims["admin"] = True
    else:
        claims.pop("admin", None)
    firebase_auth.set_custom_user_claims(uid, claims)
    return usuario.email


def main():
    if len(sys.argv) < 2:
        print("Uso: python crear_admin.py <UID> [--quitar]")
        sys.exit(1)

    uid = sys.argv[1].strip()
    quitar = "--quitar" in sys.argv[2:]
    email = asignar_admin(uid, es_admin=not quitar)

    accion = "revocado" if quitar else "asignado"
    print(f"Permiso de administrador {accion} para {email} ({uid}).")
    print("El usuario debe cerrar sesión y volver a entrar para que su token recoja el cambio.")


if __name__ == "__main__":
    main()
