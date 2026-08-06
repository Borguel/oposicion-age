"""Regenera frontend/sitemap.xml a partir de las páginas públicas reales.

No se ejecuta como parte de ningún despliegue (Render no tiene build
para el sitio estático, ver render.yaml) -- es un script de mantenimiento
puntual, igual que crear_admin.py o generar_claves_vapid.py, pensado para
correrlo a mano cada vez que se añada o quite una página pública. Así se
evita el riesgo de acoplar los despliegues del frontend a un script que
no tiene nada que ver con el resto de cambios que se quieran publicar.

Qué hace:
1. Lee frontend/robots.txt y saca los prefijos Disallow (fuente de verdad
   de qué NO es público, en vez de mantener una lista aparte).
2. Recorre frontend/ buscando cada index.html, descartando admin/ y
   cualquier ruta bajo un prefijo Disallow.
3. Por cada página que queda, saca la URL de su <link rel="canonical">.
4. lastmod = fecha del último commit real de ese archivo (git log), no la
   fecha de hoy -- para que refleje cuándo cambió el contenido de verdad.
5. priority/changefreq: mismos valores que ya tenía el sitemap actual
   (ajustados a mano en su momento), con un valor por defecto para
   cualquier página nueva que aún no esté en el diccionario.

Uso: python generar_sitemap.py   (revisa el diff con git antes de hacer commit)
"""
import re
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
FRONTEND = RAIZ / "frontend"
BASE_URL = "https://www.dominatuopo.com"

# Mismos valores que ya tenía frontend/sitemap.xml antes de automatizarlo
# -- para no perder el ajuste fino ya hecho a mano. Clave = ruta tal cual
# aparece en la URL (con barras finales).
PRIORIDADES = {
    "/": ("1.0", "weekly"),
    "/planes/": ("0.9", "weekly"),
    "/demo/": ("0.8", "monthly"),
    "/login/": ("0.5", "monthly"),
    "/oposiciones/": ("0.7", "monthly"),
    "/blog/": ("0.7", "weekly"),
    "/oposicion-administrativo-estado-c1/": ("0.8", "monthly"),
    "/oposicion-gace/": ("0.8", "monthly"),
    "/oposicion-auxiliar-administrativo-estado/": ("0.8", "monthly"),
    "/comparativa-oposiciones-estado/": ("0.7", "monthly"),
    "/sueldo-funcionario-administracion-estado/": ("0.6", "monthly"),
    "/como-estudiar-oposicion-trabajando/": ("0.6", "monthly"),
    "/estudiar-oposiciones-con-inteligencia-artificial/": ("0.7", "monthly"),
    "/como-funciona/": ("0.7", "monthly"),
    "/aviso-legal/": ("0.3", "yearly"),
    "/privacidad/": ("0.3", "yearly"),
    "/cookies/": ("0.3", "yearly"),
    "/terminos/": ("0.3", "yearly"),
}
PRIORIDAD_POR_DEFECTO = ("0.5", "monthly")
# Subpáginas de /como-funciona/*: mismo valor que ya tenían todas.
PRIORIDAD_COMO_FUNCIONA_SUB = ("0.6", "monthly")


def _prefijos_disallow():
    """P. ej. 'Disallow: /subida-pdf-*/' -> prefijo '/subida-pdf-' (todo lo
    anterior al primer '*', sea cual sea su posición en el patrón)."""
    robots = (FRONTEND / "robots.txt").read_text(encoding="utf-8")
    prefijos = []
    for linea in robots.splitlines():
        m = re.match(r"Disallow:\s*(\S+)", linea.strip())
        if m:
            prefijos.append(m.group(1).split("*")[0])
    return prefijos


def _es_publica(ruta_relativa, prefijos_disallow):
    if ruta_relativa.startswith("/admin/"):
        return False
    return not any(ruta_relativa.startswith(p) for p in prefijos_disallow)


def _canonical(contenido):
    m = re.search(r'<link rel="canonical" href="([^"]+)"\s*/?>', contenido)
    return m.group(1) if m else None


def _lastmod(archivo):
    try:
        salida = subprocess.run(
            ["git", "log", "-1", "--format=%cd", "--date=short", "--", str(archivo)],
            cwd=RAIZ, capture_output=True, text=True, check=True,
        ).stdout.strip()
        if salida:
            return salida
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return None  # archivo nuevo sin commit todavía, o git no disponible


def _prioridad(ruta_relativa):
    if ruta_relativa in PRIORIDADES:
        return PRIORIDADES[ruta_relativa]
    if ruta_relativa.startswith("/como-funciona/") and ruta_relativa != "/como-funciona/":
        return PRIORIDAD_COMO_FUNCIONA_SUB
    return PRIORIDAD_POR_DEFECTO


def generar():
    prefijos_disallow = _prefijos_disallow()
    entradas = []
    for archivo in sorted(FRONTEND.rglob("index.html")):
        carpeta = archivo.relative_to(FRONTEND).parent
        ruta_relativa = "/" if carpeta == Path(".") else f"/{carpeta.as_posix()}/"
        if not _es_publica(ruta_relativa, prefijos_disallow):
            continue
        contenido = archivo.read_text(encoding="utf-8")
        canonical = _canonical(contenido)
        if not canonical:
            print(f"AVISO: {archivo} no tiene <link rel=\"canonical\">, se omite.")
            continue
        lastmod = _lastmod(archivo)
        prioridad, changefreq = _prioridad(ruta_relativa)
        entradas.append((canonical, lastmod, changefreq, prioridad))

    # Mismo orden que tenía el sitemap a mano: por prioridad descendente.
    entradas.sort(key=lambda e: (-float(e[3]), e[0]))

    lineas = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod, changefreq, prioridad in entradas:
        lineas.append("  <url>")
        lineas.append(f"    <loc>{loc}</loc>")
        if lastmod:
            lineas.append(f"    <lastmod>{lastmod}</lastmod>")
        lineas.append(f"    <changefreq>{changefreq}</changefreq>")
        lineas.append(f"    <priority>{prioridad}</priority>")
        lineas.append("  </url>")
    lineas.append("</urlset>")
    lineas.append("")

    destino = FRONTEND / "sitemap.xml"
    destino.write_text("\n".join(lineas), encoding="utf-8")
    print(f"Escritas {len(entradas)} páginas en {destino}")


if __name__ == "__main__":
    generar()
