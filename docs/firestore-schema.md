# Esquema de datos en Firestore

No hay ningún esquema formal (Firestore no lo exige); este documento
recoge la forma real de las colecciones tal y como las usa el código, a
partir de los comentarios ya repartidos por `registro_progreso_usuario.py`,
`oposiciones.py`, `documentos_pdf.py`, etc. Sin garantía de estar
100% completo -- ante la duda, el código es la fuente de verdad.

## `usuarios/{uid}`

Un documento por usuario (uid = Firebase Auth UID). Se crea/inicializa en
`registro_progreso_usuario.inicializar_estadisticas_usuario`, llamada
desde `auth_utils.requiere_login` en la primera petición autenticada de
cada usuario (así que siempre existe ya con esta forma antes de que
pueda llegar a guardar ningún contenido).

Campos de identidad:
- `email`, `nombre`, `apellidos`, `telefono`, `direccion`
- `fecha_creacion` (ISO 8601, UTC)

Racha de estudio (`registro_progreso_usuario.registrar_actividad_racha`):
```
racha: { ultima_fecha, racha_actual, racha_maxima }
```

Suscripciones -- **una entrada por oposición**, porque cada oposición se
contrata y se paga por separado (`registro_progreso_usuario.actualizar_suscripcion`):
```
stripe_customer_id: str | null   # un único cliente de Stripe, global
suscripciones: {
  "AGE": { plan, stripe_subscription_id, subscription_status, plan_updated_at, current_period_end },
  "GACE": { ... }
}
```
`plan` es uno de `gratis|basico|premium`. Ver `auth_utils.ORDEN_PLANES`.

Estadísticas de test/esquema -- **también una entrada por oposición**
(`registro_progreso_usuario.actualizar_estadisticas_test`/`actualizar_estadisticas_esquema`):
```
estadisticas: {
  "AGE": {
    tests_realizados, total_aciertos, total_fallos,
    tests_aprobados, tests_suspendidos, tiempo_total,
    puntuacion_media_test, temas_test: [...],
    rendimiento_por_tema: { "<tema_id>": { aciertos, fallos, blancos } },
    historial_tests: [ {fecha, aciertos, fallos, blancos, temas, tiempo, tipo, puntuacion_final, resultado}, ... ]  # recortado a los últimos 50
    ultimo_test: { ...mismo shape que una entrada de historial_tests },
    esquemas_realizados, temas_esquemas: [...]
  }
}
ultima_actividad: ISO 8601   # de cualquier tipo de actividad, no depende de la oposición
```

Herramientas sobre PDF propio -- **globales, no dependen de ninguna
oposición** (`registro_progreso_usuario.actualizar_estadisticas_pdf`):
```
tests_pdf_realizados, resumenes_pdf_realizados,
esquemas_pdf_realizados, tarjetas_pdf_realizados,
total_archivos_procesados
```

Otros campos: `notas_personales`, `resumen_mensual`, `recomendaciones_ia`.

### Subcolecciones de `usuarios/{uid}`

- `tests/{id}` -- un test finalizado (o autoguardado `en_progreso`, ver
  `test-progreso.js`/`rutas_progreso.py`): `fecha`, `tipo`
  (`personalizado|oficial|inteligente|repetido|falladas|favoritas`),
  `oposicion`, `estado`, `num_preguntas`, `aciertos`, `fallos`,
  `blancos`, `porcentaje_acierto`, `puntuacion_final`, `tiempo`, `temas`,
  `resultado` (`aprobado|suspendido`), `preguntas: [...]`.
- `esquemas/{id}` -- `fecha`, `temas`, `oposicion`, `contenido`.
- `tests_pdf/{id}`, `resumenes_pdf/{id}`, `esquemas_pdf/{id}`,
  `tarjetas_pdf/{id}` -- contenido generado desde un PDF propio, cada uno
  con `fecha`, `nombre_archivo`, `documento_id` (referencia a
  `documentos/{id}`) y el contenido propiamente dicho.
- `documentos/{id}` -- biblioteca "Mis Documentos"
  (`documentos_pdf.py`): `titulo`, `nombre_archivo`, `fecha_subida`,
  `num_paginas`, `texto` (extraído del PDF), `hash_texto` (para
  deduplicar si se sube el mismo PDF dos veces), `carpeta`, flags
  `tiene_resumen`/`tiene_esquema`/etc.
- `preguntas_falladas/{id}` -- banco de fallos deduplicado
  (`banco_fallos.py`), para repasar por tema.
- `preguntas_favoritas/{id}` -- preguntas marcadas para repasar
  (`banco_favoritas.py`).

## Temario oficial

Una colección por oposición (`oposiciones.coleccion_temario`, p. ej.
`"Temario AGE"`, `"Temario GACE"`, `"Temario Auxiliar"`):
```
{coleccion}/{bloque_id}                     -> { titulo }
{coleccion}/{bloque_id}/temas/{tema_id}     -> { titulo, contenido, ... }
```
`bloque_id`/`tema_id` siguen el patrón `bloque_01`, `tema_01`... El id
combinado `"{bloque_id}-{tema_id}"` es el identificador que viaja por el
resto de la app (tests, estadísticas, banco de fallos).

## Exámenes oficiales

Una colección por oposición (`oposiciones.coleccion_examenes_oficiales`,
p. ej. `examenes_oficiales_AGE`): un documento por pregunta real de un
examen ya celebrado, con `pregunta`, `opciones`, `respuesta_correcta`,
`explicacion`, `tema_id` (mapeado a mano al temario, ver
`etiquetar_temas_examenes_*.py`), y metadatos de la convocatoria de
origen.

## `datos_convocatoria/{oposicion}`

Un documento por oposición con un único campo `texto`: datos oficiales
de la convocatoria vigente (plazas, estructura de ejercicios, tiempos,
penalización, calificación), redactado a mano a partir del BOE para que
Tu Tutor no tenga que inventarlos.

## `stripe_events/{event_id}`

Candado de idempotencia del webhook de Stripe (`blueprints/pagos.py`):
`{ type, processed_at }`. Si el documento ya existe, el evento no se
vuelve a procesar (Stripe reintenta en caso de que la respuesta de la
primera vez no llegara a tiempo).

## Notas

- No hay backup/exportación automatizada -- ver
  `.github/workflows/backup-firestore.yml` (requiere que se configure un
  bucket de GCS y una cuenta de servicio antes de que funcione de
  verdad).
- No hay reglas de seguridad de Firestore documentadas aquí porque todo
  el acceso pasa por el backend (con su propia verificación de token +
  gating por plan en `auth_utils.py`), no por el SDK cliente de
  Firestore directamente.
