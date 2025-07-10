import os
import random
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# Módulos personalizados
from test_generator import generar_test_avanzado
from chat_controller import responder_chat
from chat_controller import consultar_asistente_examen_AGE
from esquema_generator import generar_esquema
from save_controller import guardar_test_route, guardar_esquema_route
from rutas_progreso import registrar_rutas_progreso

# Cargar variables de entorno
load_dotenv()
print("🔑 Clave OpenAI:", os.getenv("OPENAI_API_KEY"))

# Inicializar Firebase
firebase_key_path = os.getenv("FIREBASE_KEY_PATH", "clave-firebase.json")
if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_key_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Inicializar Flask
app = Flask(__name__)
CORS(app, origins=["https://lightslategray-caribou-622401.hostingersite.com"])
print("✅ CORS activado para tu WordPress")

@app.route("/chat", methods=["POST"])
def chat_route():
    data = request.get_json()
    mensaje = data.get("mensaje")
    temas = data.get("temas", [])
    respuesta = responder_chat(mensaje=mensaje, temas=temas, db=db)
    return jsonify({"respuesta": respuesta})

@app.route("/consultar-asistente-examen", methods=["POST"])
def ruta_asistente_examen():
    data = request.get_json()
    mensaje = data.get("mensaje", "")
    if not mensaje:
        return jsonify({"error": "Falta el mensaje"}), 400
    try:
        respuesta = consultar_asistente_examen_AGE(mensaje)
        return jsonify({"respuesta": respuesta})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/generar-test-avanzado", methods=["POST"])
def generar_test_avanzado_route():
    data = request.get_json()
    print(f"📅 Petición recibida en /generar-test-avanzado: {data}")

    temas = data.get("temas", [])
    num_preguntas = data.get("num_preguntas", 5)

    print(f"📋 Temas extraídos: {temas}")
    print(f"🧪 Número de preguntas solicitadas: {num_preguntas}")

    resultado = generar_test_avanzado(temas=temas, db=db, num_preguntas=num_preguntas)
    print(f"📄 Resultado del test: {resultado}")
    return jsonify(resultado)

@app.route("/generar-esquema", methods=["POST"])
def generar_esquema_route():
    data = request.get_json(silent=True)
    if not data:
        print("❌ No se ha recibido JSON en la petición")
        return jsonify({"error": "No se ha recibido un cuerpo JSON válido"}), 400

    print("📩 Datos recibidos en /generar-test-inteligente:", data)
    temas = data.get("temas", [])
    instrucciones = data.get("instrucciones", "Resume los contenidos clave.")
    nivel = data.get("nivel", "general")
    resultado = generar_esquema(temas=temas, db=db, instrucciones=instrucciones, nivel=nivel)
    return jsonify({"esquema": resultado})

@app.route("/generar-test-oficial", methods=["POST"])
def generar_test_oficial():
    data = request.get_json()
    print("✅ Ruta /generar-test-oficial llamada")
    print("📥 Datos recibidos:", data)

    num_preguntas = data.get("num_preguntas", 10)
    examenes_filtrados = data.get("examenes", [])
    print("🔍 Número de preguntas solicitado:", num_preguntas)
    print("📚 Exámenes filtrados:", examenes_filtrados)

    try:
        docs = db.collection("examenes_oficiales_AGE").stream()
    except Exception as e:
        print("❌ Error accediendo a Firestore:", e)
        return jsonify({"error": "No se pudo acceder a Firestore"}), 500

    preguntas = []
    for doc in docs:
        d = doc.to_dict()
        print("📄 Documento encontrado:", d.get("examen"), "| tipo:", d.get("tipo"))

        if d.get("tipo") != "pregunta":
            continue

        if examenes_filtrados:
            if d.get("examen", "").lower() not in [e.lower() for e in examenes_filtrados]:
                continue

        opciones_originales = d.get("opciones", {})
        opciones_mayus = {k.upper(): v for k, v in opciones_originales.items()}

        preguntas.append({
            "pregunta": d.get("pregunta", ""),
            "opciones": opciones_mayus,
            "respuesta_correcta": d.get("respuesta_correcta", "").upper(),
            "explicacion": d.get("explicacion", ""),
            "examen": d.get("examen", ""),
            "numero": d.get("numero", 0)
        })

    print(f"✅ Preguntas encontradas tras filtro: {len(preguntas)}")
    if not preguntas:
        return jsonify({"test": [], "mensaje": "No se encontraron preguntas"}), 404

    seleccionadas = random.sample(preguntas, min(num_preguntas, len(preguntas)))
    print(f"🎯 Preguntas seleccionadas aleatoriamente: {len(seleccionadas)}")

    return jsonify({"test": seleccionadas})

@app.route("/guardar-test-oficial", methods=["POST"])
def guardar_test_oficial():
    data = request.get_json()
    print("💾 Guardando test oficial:", data)

    usuario_id = data.get("usuario_id")
    contenido = data.get("contenido")
    respuestas = data.get("respuestas")
    metadatos = data.get("metadatos", {})

    if not usuario_id or not contenido or not respuestas:
        return jsonify({"error": "Faltan datos requeridos"}), 400

    try:
        doc_ref = db.collection("test_oficiales").document()
        doc_ref.set({
            "usuario_id": usuario_id,
            "contenido": contenido,
            "respuestas": respuestas,
            "metadatos": metadatos
        })
        print("✅ Test oficial guardado correctamente")
        return jsonify({"mensaje": "Test oficial guardado correctamente"}), 200
    except Exception as e:
        print("❌ Error al guardar test oficial:", e)
        return jsonify({"error": str(e)}), 500

# Guardado y progreso
app.add_url_rule("/guardar-test", view_func=guardar_test_route(db), methods=["POST"])
app.add_url_rule("/guardar-esquema", view_func=guardar_esquema_route(db), methods=["POST"])
registrar_rutas_progreso(app, db)

@app.route("/temas-disponibles", methods=["GET"])
def obtener_temas_disponibles():
    temas_disponibles = []
    bloques = db.collection("Temario AGE").stream()
    for bloque in bloques:
        bloque_id = bloque.id
        temas_ref = db.collection("Temario AGE").document(bloque_id).collection("temas").stream()
        for tema in temas_ref:
            tema_data = tema.to_dict()
            tema_id = tema.id
            titulo = tema_data.get("titulo", f"{tema_id}")
            temas_disponibles.append({
                "id": f"{bloque_id}-{tema_id}",
                "titulo": titulo
            })
    return jsonify({"temas": temas_disponibles})

@app.route("/progreso-usuario", methods=["GET"])
def progreso_usuario():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "Falta el parámetro user_id"}), 400

    doc_user = db.collection("usuarios").document(user_id)
    progreso = doc_user.get().to_dict()

    if not progreso:
        return jsonify({"error": "Usuario no encontrado"}), 404

    return jsonify({
        "tests_realizados": progreso.get("tests_realizados", 0),
        "puntuacion_media_test": progreso.get("puntuacion_media_test", 0),
        "ultimo_test": progreso.get("ultimo_test", {}),
        "total_aciertos": progreso.get("total_aciertos", 0),
        "esquemas_generados": progreso.get("esquemas_generados", 0)
    })

@app.route("/", methods=["GET"])
def listar_rutas():
    rutas = [rule.rule for rule in app.url_map.iter_rules()]
    return jsonify({"rutas_disponibles": rutas})


from openai import OpenAI
import json

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def traducir_temas_para_IA(lista_codigos):
    traducciones = {
        "bloque_01-tema_01": "Constitución Española",
        "bloque_01-tema_02": "La Jefatura del Estado. La Corona. Funciones constitucionales del Rey. Sucesión y regencia.",
        "bloque_01-tema_03": "Las Cortes Generales. Composición, atribuciones y funcionamiento del Congreso de los Diputados y del Senado.",
        "bloque_01-tema_04": "EL PODER JUDICIAL",
        "bloque_01-tema_05": "EL GOBIERNO Y LA ADMINISTRACIÓN.",
        "bloque_01-tema_06": "El Gobierno Abierto, Agenda 2030 y Digitalización",
        "bloque_01-tema_07": "LA LEY 19/2013, DE 9 DE DICIEMBRE, DE TRANSPARENCIA, ACCESO A LA INFORMACIÓN PÚBLICA Y BUEN GOBIERNO. EL CONSEJO DE TRANSPARENCIA Y BUEN GOBIERNO: FUNCIONES.",
        "bloque_01-tema_08": "Administración General del Estado",
        "bloque_01-tema_09": "LA ORGANIZACIÓN TERRITORIAL DEL ESTADO: LAS COMUNIDADES AUTÓNOMAS. CONSTITUCIÓN Y DISTRIBUCIÓN DE COMPETENCIAS ENTRE EL ESTADO Y LAS COMUNIDADES AUTÓNOMAS. ESTATUTOS DE AUTONOMÍA.",
        "bloque_01-tema_10": "LA ADMINISTRACIÓN LOCAL: ENTIDADES QUE LA INTEGRAN. LA PROVINCIA, EL MUNICIPIO Y LA ISLA.",
        "bloque_01-tema_11": "LA ORGANIZACIÓN DE LA UNIÓN EUROPEA. EL CONSEJO EUROPEO, EL CONSEJO, EL PARLAMENTO EUROPEO, LA COMISIÓN EUROPEA Y EL TRIBUNAL DE JUSTICIA DE LA UNIÓN EUROPEA. EFECTOS DE LA INTEGRACIÓN EUROPEA SOBRE LA ORGANIZACIÓN DEL ESTADO ESPAÑOL.",
        "bloque_02-tema_01": "ATENCION AL PUBLICO",
        "bloque_02-tema_02": "REGISTRO Y ARCHIVO",
        "bloque_02-tema_03": "ADMINISTRACION ELECTRONICA",
        "bloque_02-tema_04": "PROTECCION DE DATOS PERSONALES",
        "bloque_03-tema_01": "FUENTES DEL DERECHO ADMINISTRATIVO",
        "bloque_03-tema_02": "EL ACTO ADMINISTRATIVO",
        "bloque_03-tema_03": "EL PROCEDIMIENTO ADMINISTRATIVO COMÚN",
        "bloque_03-tema_04": "CONTRATOS DEL SECTOR PÚBLICO",
        "bloque_03-tema_05": "LA ACTIVIDAD ADMINISTRATIVA.",
        "bloque_03-tema_06": "RESPONSABILIDAD PATRIMONIAL (VACIO)",
        "bloque_03-tema_07": "IGUALDAD DE GÉNERO (VACIO)"
    }
    return [traducciones.get(codigo, codigo) for codigo in lista_codigos]


@app.route("/generar-test-inteligente", methods=["POST"])
def generar_test_inteligente():
    data = request.get_json(silent=True)
    if not data:
        print("❌ No se ha recibido JSON en la petición")
        return jsonify({"error": "No se ha recibido un cuerpo JSON válido"}), 400

    print("📩 Datos recibidos en /generar-test-inteligente:", data)
    temas = data.get("temas", [])
    num_preguntas = data.get("num_preguntas", 5)

    if not temas:
        return jsonify({"error": "No se han proporcionado temas"}), 400

    temas_legibles = traducir_temas_para_IA(temas)
    prompt = f"""
Eres un generador experto de preguntas tipo test para oposiciones del Cuerpo General Administrativo del Estado (grupo C1).

Crea {num_preguntas} preguntas tipo test con el estilo oficial de exámenes del INAP: realistas, bien redactadas y con trampas habituales.

Temas seleccionados: {', '.join(temas_legibles)}

Cada pregunta debe tener:
- Enunciado claro
- Opciones A, B, C y D (sin ambigüedades)
- Una única opción correcta
- Explicación técnica o jurídica breve

Devuelve solo un array JSON como este:

[
  {{
    "pregunta": "...",
    "opciones": {{
      "A": "...",
      "B": "...",
      "C": "...",
      "D": "..."
    }},
    "respuesta_correcta": "B",
    "explicacion": "..."
  }},
  ...
]
"""

    try:
        respuesta = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
        )
        generado = respuesta.choices[0].message.content.strip()
        preguntas = json.loads(generado)
        return jsonify({"test": preguntas})
    except Exception as e:
        print("❌ Error al generar test inteligente:", e)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))






