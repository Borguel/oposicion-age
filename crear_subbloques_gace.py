import firebase_admin
from firebase_admin import credentials, firestore

# Inicializa Firebase
cred = credentials.Certificate("clave-firebase.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Parámetros
coleccion_raiz = "Temario_GACE"
nombre_subcoleccion = "subbloques"  # Puedes poner "sub_divs" si lo prefieres
num_subdivisiones = 20

# Obtiene todos los bloques
bloques = db.collection(coleccion_raiz).stream()
for bloque in bloques:
    # Por cada bloque, obtiene todos los temas
    temas = db.collection(coleccion_raiz).document(bloque.id).collection("temas").stream()
    for tema in temas:
        subbloques_ref = (
            db.collection(coleccion_raiz)
            .document(bloque.id)
            .collection("temas")
            .document(tema.id)
            .collection(nombre_subcoleccion)
        )
        # Crea 20 subbloques
        for i in range(1, num_subdivisiones + 1):
            sub_id = f"sub_div_{i:02d}"
            subbloques_ref.document(sub_id).set({
                "titulo": f"Subdivisión {i}",
                "texto": ""
            })
        print(f"Subbloques creados para {bloque.id}/{tema.id}")

print("¡Todos los subbloques creados correctamente en cada tema de Temario_GACE!")
