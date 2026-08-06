"""Script PUNTUAL (no forma parte de la app) para dar de alta en Firestore,
como avisos ya "publicado", el histórico de la convocatoria 2025 (AGE, GACE
y Auxiliar) que ya se añadió a mano como HTML estático en
frontend/avisos-oficiales/ y en cada frontend/oposicion-*/ (ver el commit
que introdujo este script).

Por qué hace falta esto además del HTML ya escrito a mano: la próxima vez
que se apruebe un aviso NUEVO desde el panel de admin,
publicacion_estatica_boe.actualizar_pagina_estatica_avisos regenera esas
secciones ENTERAS a partir de lo que haya en Firestore -- y como estos
avisos históricos no existen en Firestore, desaparecerían del HTML en ese
momento. Ejecutar este script una vez (con credenciales reales) los deja
también en Firestore, para que la próxima regeneración los conserve.

A propósito NO llama a notificar_usuarios_aviso_oficial (solo a
actualizar_pagina_estatica_avisos/actualizar_pagina_avisos_general): estos
avisos son historial de relleno de una convocatoria ya conocida, no
noticias nuevas, así que no debe salir ningún email por ellos.

Idempotente: si un aviso con el mismo título ya existe (publicado o no), se
salta en vez de duplicarlo -- se puede volver a ejecutar sin miedo.

Uso:
    python seed_avisos_historicos.py            # aplica los cambios
    python seed_avisos_historicos.py --preview   # solo imprime qué haría

Requiere las mismas credenciales que el resto de la app (FIREBASE_CREDENTIALS_JSON
o el fichero de clave, ver .env.example).
"""
import sys
from datetime import datetime, timezone

import firebase_setup  # noqa: F401  (inicializa firebase_admin)
from firebase_setup import db
from publicacion_estatica_boe import (
    actualizar_pagina_avisos_general,
    actualizar_pagina_estatica_avisos,
)

# Genérica a propósito: un aviso solo tiene UN url_inap en Firestore (el
# mismo para las 3 oposiciones que afecta, ver publicacion_estatica_boe.py),
# así que no puede apuntar a la vez a las páginas específicas de AGE, GACE Y
# Auxiliar. El HTML estático de cada frontend/oposicion-*/ (ver el commit
# que corrige el enlace equivocado que tenía antes) sí usa el enlace
# específico de esa oposición como excepción manual -- si se ejecuta este
# script, la próxima regeneración desde Firestore sustituye esos enlaces
# específicos por este genérico. Es una limitación real del modelo de
# datos, no un descuido.
_URL_INAP_GENERAL = "https://www.inap.es/es/seleccion/procesos-selectivos-de-cuerposescalas-generales"

# Mismos datos (mismo orden, mismos textos) que el HTML ya escrito a mano en
# el frontend -- ver el commit que introdujo este script para el HTML
# equivalente generado con publicacion_estatica_boe.generar_html_avisos*.
AVISOS_HISTORICOS = [
    {
        "oposiciones": ["AGE", "GACE", "AUXILIAR"],
        "tipo": "convocatoria",
        "titulo": "Convocatoria conjunta 2025 del Cuerpo General Administrativo, GACE y Cuerpo General Auxiliar",
        "resumen": (
            "Resolución de 18 de diciembre de 2025 de la Secretaría de Estado de Función "
            "Pública por la que se convocan los procesos selectivos de ingreso en los Cuerpos "
            "de la Administración General del Estado, encargando su realización a la Comisión "
            "Permanente de Selección. Plazo de presentación de solicitudes: del 23 de diciembre "
            "de 2025 al 22 de enero de 2026."
        ),
        "url_boe": "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2025-26262",
        "url_inap": _URL_INAP_GENERAL,
        "fecha_boe": "20251218",
    },
    {
        "oposiciones": ["AGE", "GACE", "AUXILIAR"],
        "tipo": "lista_admitidos",
        "titulo": "Listas provisionales de admitidos y excluidos, con fecha y lugar del examen",
        "resumen": (
            "Resolución de 12 de marzo de 2026 del INAP por la que se aprueba la relación "
            "provisional de personas admitidas y excluidas y se anuncia fecha y lugar de "
            "celebración del ejercicio único (AGE y Auxiliar) y del primer ejercicio (GACE): "
            "sábado 23 de mayo de 2026, 10:00h en la península y 9:00h en Canarias. Las "
            "personas excluidas u omitidas disponen de 10 días hábiles para subsanar defectos "
            "en su solicitud."
        ),
        "url_boe": "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-6249",
        "url_inap": _URL_INAP_GENERAL,
        "fecha_boe": "20260317",
    },
    {
        "oposiciones": ["AGE", "GACE", "AUXILIAR"],
        "tipo": "lista_admitidos",
        "titulo": "Listas definitivas de personas admitidas y excluidas — mayo 2026",
        "resumen": (
            "El Instituto Nacional de Administración Pública aprueba las listas definitivas de "
            "personas admitidas y excluidas para el Cuerpo General Administrativo (AGE), el "
            "Cuerpo de Gestión de la Administración Civil del Estado (GACE) y el Cuerpo General "
            "Auxiliar, una vez resueltas las alegaciones presentadas contra las listas "
            "provisionales."
        ),
        # Sin url_boe: no se ha podido verificar el BOE-A concreto de esta
        # resolución (a diferencia de las otras dos) -- mejor omitirlo que
        # inventar un enlace que no existe. Queda el enlace a INAP.
        "url_boe": "",
        "url_inap": _URL_INAP_GENERAL,
        "fecha_boe": "20260506",
    },
]


def _ya_existe(titulo):
    return any(
        True
        for _ in db.collection("avisos_oficiales")
        .where("titulo", "==", titulo)
        .limit(1)
        .stream()
    )


def sembrar(preview=False):
    creados = []
    for aviso in AVISOS_HISTORICOS:
        if _ya_existe(aviso["titulo"]):
            print(f"Ya existe, se salta: {aviso['titulo']!r}")
            continue
        if preview:
            print(f"[preview] Crearía: {aviso['titulo']!r} ({', '.join(aviso['oposiciones'])})")
            continue
        ref = db.collection("avisos_oficiales").document()
        ref.set({
            **aviso,
            "tipo_personalizado": "",
            "fecha_deteccion": datetime.now(timezone.utc).isoformat(),
            "estado": "publicado",
            "creado_manualmente_por": "seed_avisos_historicos.py",
            "revisado_por": "seed_avisos_historicos.py",
            "fecha_revision": datetime.now(timezone.utc).isoformat(),
        })
        creados.append(aviso)
        print(f"Creado: {aviso['titulo']!r}")

    if preview or not creados:
        return

    # Regenera el HTML estático a partir de Firestore -- debe quedar igual
    # al que ya se escribió a mano, ahora respaldado por Firestore. A
    # propósito NO se llama a notificar_usuarios_aviso_oficial.
    for op in ("AGE", "GACE", "AUXILIAR"):
        ok = actualizar_pagina_estatica_avisos(db, op)
        print(f"Página estática {op}: {'OK' if ok else 'sin cambios o fallo (ver log)'}")
    ok = actualizar_pagina_avisos_general(db)
    print(f"Página estática general: {'OK' if ok else 'sin cambios o fallo (ver log)'}")


if __name__ == "__main__":
    sembrar(preview="--preview" in sys.argv)
