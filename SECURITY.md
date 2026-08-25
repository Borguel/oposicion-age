# Política de seguridad

Domina tu Opo es una plataforma web para preparar oposiciones de la
Administración Pública española (AGE, GACE, Auxiliar Administrativo).
Nos tomamos en serio la seguridad de los datos de nuestros usuarios.

## Reportar una vulnerabilidad

Si has encontrado una vulnerabilidad de seguridad, repórtala de forma
privada a **dominatuopo@gmail.com** — por favor, no abras un issue
público hasta que se haya podido revisar y corregir.

Incluye, si es posible:
- Una descripción del problema y su impacto potencial.
- Pasos para reproducirlo (o una prueba de concepto).
- La URL o el endpoint afectado.

Nos comprometemos a:
- Confirmar la recepción del reporte en un plazo máximo de 5 días hábiles.
- Mantenerte informado del progreso mientras se investiga y corrige.
- Acreditar tu descubrimiento (si lo deseas) una vez publicado el arreglo.

## Alcance

Entra dentro del alcance cualquier vulnerabilidad en:
- `www.dominatuopo.com` y sus subrutas.
- El código fuente de este repositorio.

Quedan fuera de alcance los ataques de denegación de servicio, ingeniería
social contra el equipo, y vulnerabilidades en servicios de terceros de
los que dependemos (Stripe, Firebase, Sentry...) — repórtalas
directamente a esos proveedores.

## Versiones soportadas

No versionamos releases: la rama `main` es siempre la única versión en
producción, y cualquier corrección de seguridad se despliega ahí en
cuanto está lista.
