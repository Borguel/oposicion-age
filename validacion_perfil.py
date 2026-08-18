"""Validación de los datos de perfil que el propio usuario puede escribir
libremente (nombre, apellidos, teléfono, dirección) vía /registrar-usuario.

Motivo: esos campos, sobre todo "nombre", se muestran después en sitios de
más confianza que el propio usuario -- exportaciones CSV del panel admin
(usuarios.csv, ingresos.csv), listados del panel, correos transaccionales
(el nombre se interpola en el saludo) -- así que antes de guardarlos hay
que impedir que alguien registre una cuenta con un nombre que en realidad
sea un enlace, HTML, o una fórmula de hoja de cálculo (ver también el
escapado de celdas en blueprints/admin.py._celda_csv_segura, que cubre
además cualquier dato ya guardado antes de este cambio).

"nombre"/"apellidos" usan lista blanca (solo letras de cualquier alfabeto,
espacios, guiones y apóstrofes) en vez de lista negra: es más seguro por
construcción, ya que un enlace, una etiqueta HTML o una fórmula de CSV
siempre llevan algún carácter que no es una letra (":", "/", ".", "<",
"=", un dígito...). Se comprueba con str.isalpha() carácter a carácter
(no con un rango de la tabla Unicode tipo A-Za-z) para no rechazar de
más nombres reales fuera del alfabeto latino (cirílico, árabe, chino...),
algo esperable en solicitantes de la administración pública española que
no sean de origen español. "dirección" sí necesita números y puntuación
(portal, piso, código postal), así que ahí se usa lista negra sobre
patrones de enlace/HTML."""

import re

_CARACTERES_EXTRA_NOMBRE = set(" '-")
_LONGITUD_MAXIMA_NOMBRE = 80
_PATRON_TELEFONO = re.compile(r"^[0-9+()\-\s]{3,20}$")
_LONGITUD_MAXIMA_DIRECCION = 200
_PATRON_ENLACE = re.compile(
    r"https?://|www\.|<[a-z!/]|\b[a-z0-9-]+\.(com|net|org|es|io|co|info|biz|xyz|gov|edu)\b",
    re.IGNORECASE,
)


def nombre_valido(texto):
    """True si `texto` es un nombre/apellido plausible: solo letras (de
    cualquier alfabeto) más espacio/apóstrofe/guion, longitud razonable.
    Sin dígitos ni símbolos -- eso descarta por construcción cualquier
    enlace, etiqueta HTML o fórmula de hoja de cálculo. No acepta cadena
    vacía (se comprueba fuera si el campo es opcional)."""
    if not texto or len(texto) > _LONGITUD_MAXIMA_NOMBRE:
        return False
    return all(c.isalpha() or c in _CARACTERES_EXTRA_NOMBRE for c in texto)


def telefono_valido(texto):
    """True si `texto` son solo dígitos y los símbolos habituales de un
    teléfono (+, paréntesis, guiones, espacios)."""
    return bool(_PATRON_TELEFONO.match(texto))


def direccion_valida(texto):
    """True si `texto` no supera la longitud máxima y no contiene ningún
    patrón de enlace/URL/HTML embebido. A diferencia de nombre/teléfono usa
    lista negra: una dirección postal real necesita números, comas, "º/ª",
    etc. que una lista blanca estricta rechazaría de más."""
    if not texto or len(texto) > _LONGITUD_MAXIMA_DIRECCION:
        return False
    return not _PATRON_ENLACE.search(texto)
