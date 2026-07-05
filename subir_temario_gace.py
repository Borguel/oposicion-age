import firebase_admin
from firebase_admin import credentials, firestore

# Inicializa Firebase
cred = credentials.Certificate("clave-firebase.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Estructura GACE (puedes editar o ampliar aquí)
temario_gace = [
    {
        "bloque": "Bloque I. Organización del Estado y de la Administración Pública",
        "temas": [
            "La Constitución Española de 1978",
            "Derechos y deberes fundamentales",
            "El Tribunal Constitucional",
            "La Corona",
            "El Poder Legislativo: Las Cortes Generales",
            "El Poder Ejecutivo",
            "El Poder Judicial",
            "La Administración General del Estado",
            "El sector público institucional",
            "Organización territorial (I): Las Comunidades Autónomas",
            "Organización territorial (II): La Administración local"
        ]
    },
    {
        "bloque": "Bloque II. La Unión Europea",
        "temas": [
            "La Unión Europea",
            "La organización de la Unión Europea (I)",
            "La organización de la Unión Europea (II)",
            "Las fuentes del derecho de la Unión Europea",
            "El presupuesto comunitario",
            "Políticas de la Unión Europea"
        ]
    },
    {
        "bloque": "Bloque III. Políticas Públicas",
        "temas": [
            "Políticas de modernización de la Administración General del Estado",
            "Política económica actual",
            "Política ambiental",
            "La Seguridad Social",
            "La evolución del empleo en España",
            "Política de inmigración",
            "El Gobierno Abierto",
            "La protección de datos personales",
            "Políticas de igualdad y contra la violencia de género",
            "Otras políticas públicas"
        ]
    },
    {
        "bloque": "Bloque IV. Derecho Administrativo General",
        "temas": [
            "Las fuentes del derecho administrativo",
            "La ley",
            "El reglamento",
            "El acto administrativo",
            "Los contratos del sector público",
            "Los contratos regulados por la Ley de Contratos del Sector Público",
            "Procedimientos y formas de la actividad administrativa",
            "La expropiación forzosa",
            "El régimen patrimonial de las Administraciones Públicas",
            "La responsabilidad patrimonial de las Administraciones públicas",
            "Las Leyes del Procedimiento Administrativo Común de las Administraciones Públicas y del Régimen Jurídico del Sector Público",
            "Los derechos de los ciudadanos en el procedimiento administrativo",
            "La jurisdicción contencioso-administrativa"
        ]
    },
    {
        "bloque": "Bloque V. Administración de recursos humanos",
        "temas": [
            "El personal al servicio de las Administraciones públicas",
            "Derechos y deberes del personal al servicio de las Administraciones Públicas",
            "Planificación de recursos humanos",
            "Formas de provisión de puestos de trabajo y movilidad en la Administración del Estado",
            "Situaciones administrativas del personal al servicio de las administraciones públicas",
            "El sistema de retribuciones de los funcionarios",
            "El personal laboral al servicio de las Administraciones públicas",
            "Negociación colectiva, representación y participación institucional de los empleados públicos",
            "El régimen especial de la Seguridad Social de los funcionarios civiles del Estado",
            "Acceso al empleo público y provisión de puestos de trabajo de las personas con discapacidad"
        ]
    },
    {
        "bloque": "Bloque VI. Gestión financiera y Seguridad Social",
        "temas": [
            "El presupuesto",
            "Las leyes anuales de presupuestos",
            "Gastos plurianuales",
            "Control del gasto público en España",
            "El procedimiento administrativo de ejecución del presupuesto de gasto",
            "Gastos para la compra de bienes y servicios",
            "Los ingresos públicos",
            "Retribuciones de los funcionarios públicos"
        ]
    }
]

# Crea la estructura en Firestore
coleccion_raiz = "Temario_GACE"

for i_bloque, bloque in enumerate(temario_gace, 1):
    bloque_id = f"bloque_{i_bloque:02d}"
    bloque_ref = db.collection(coleccion_raiz).document(bloque_id)
    bloque_ref.set({
        "titulo": bloque["bloque"]
    })
    # Subcolección temas
    temas_ref = bloque_ref.collection("temas")
    for i_tema, tema in enumerate(bloque["temas"], 1):
        tema_id = f"tema_{i_tema:02d}"
        temas_ref.document(tema_id).set({
            "titulo": tema
        })

print("Estructura Temario_GACE creada correctamente en Firestore.")
