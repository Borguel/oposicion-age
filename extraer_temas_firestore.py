
import firebase_admin
from firebase_admin import credentials, firestore
import pprint

# Inicializa Firebase con tu archivo de clave
cred = credentials.Certificate("clave-firebase.json")  # asegúrate de tenerlo en la misma carpeta
firebase_admin.initialize_app(cred)

db = firestore.client()

# Diccionario para almacenar los temas
diccionario_temas = {}

# Ruta base del temario
temario_ref = db.collection("Temario AGE")

# Recorre los bloques y sus temas
for bloque_doc in temario_ref.stream():
    bloque_id = bloque_doc.id  # ej. 'bloque_01'
    temas_ref = temario_ref.document(bloque_id).collection("temas")

    for tema_doc in temas_ref.stream():
        tema_id = tema_doc.id  # ej. 'tema_01'
        datos = tema_doc.to_dict()
        titulo = datos.get("titulo", "").strip()

        if titulo:
            clave = f"{bloque_id}-{tema_id}"
            diccionario_temas[clave] = titulo

# Imprime el diccionario en formato listo para app.py
print("\nDiccionario para pegar en app.py:\n")
print("temas_traducidos = " + pprint.pformat(diccionario_temas, width=120, sort_dicts=True))
