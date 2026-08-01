# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Personas preparando oposiciones del Estado español (empleo público de la Administración General del Estado): AGE (Cuerpo General Administrativo, C1), GACE (Cuerpo de Gestión de la Administración Civil del Estado, A2) y Auxiliar Administrativo (C2). Estudian de forma autónoma, a menudo compaginando la preparación con trabajo o estudios, sesión tras sesión durante meses, y vuelven a la app con frecuencia (varias veces por semana) como su herramienta principal de repaso.

## Product Purpose

Domina tu Opo es una plataforma de preparación de oposiciones con tests generados a partir de exámenes oficiales reales de convocatorias anteriores y del temario oficial de cada cuerpo, más herramientas de estudio con IA (generación de tests personalizados, resúmenes/esquemas/tarjetas desde PDF propio, chat tutor sobre el temario). Éxito = el usuario mantiene una racha de estudio constante, ve progreso real por tema (estadísticas de acierto), y llega al examen mejor preparado que con material genérico.

## Positioning

A diferencia de los bancos de preguntas genéricos de la competencia, los tests se generan sobre el temario oficial verificado y sobre exámenes oficiales reales ya publicados (con años y convocatorias concretas), con una capa de IA que analiza el rendimiento por tema y ajusta tests personalizados a los puntos débiles del usuario. Además de estudiar con el temario del propio Domina tu Opo, cualquier plan Premium permite subir apuntes propios en PDF y convertirlos en resumen, esquema, tarjetas de memoria y test — no solo "hacer tests", sino un flujo completo de estudio sobre material propio.

## Operating Context

Suscripción con tres oposiciones independientes (AGE, GACE, Auxiliar): cada una tiene su propio plan/progreso, un usuario puede estar suscrito a varias a la vez. Prueba gratuita de 7 días con acceso Premium completo sin tarjeta al registrarse; pasado ese plazo, sin plan de pago la cuenta queda bloqueada (datos y progreso se conservan). Dos planes de pago (Básico y Premium, con límites de uso diario/mensual distintos por herramienta), pago recurrente vía Stripe, cancelable en cualquier momento desde "Mi cuenta". El uso típico es sesiones cortas y frecuentes (un test de camino al trabajo, un repaso rápido) más sesiones largas de estudio con IA sobre el propio PDF de apuntes.

## Capabilities and Constraints

- Zona opositor (panel principal): racha de estudio, accesos rápidos, avisos oficiales del BOE relevantes para el temario.
- Test Oficial (preguntas de exámenes reales por convocatoria/año) y Test Personalizado (generado por IA sobre el temario, ajustado a temas flojos).
- Herramientas sobre PDF propio (solo Premium): resumir, esquematizar, generar tarjetas de memoria y generar test desde un documento subido por el usuario; chat sobre ese PDF.
- Tu Tutor: chat con IA sobre el temario oficial (RAG), disponible como widget flotante en varias páginas y como página de chat completa.
- Estadísticas de progreso por tema/bloque, ranking opcional entre usuarios, preguntas falladas/favoritas para repaso dirigido.
- Backend Flask + Firebase (Auth/Firestore) + Stripe (pagos) + DeepSeek (generación IA). Frontend 100% estático (HTML/CSS/JS sin framework, sin build step) — ver `docs/` y `frontend/assets/theme.css`.
- Panel de administración interno (`/admin/`) con permisos granulares, fuera del alcance de las páginas de usuario final orientadas a diseño.
- Constraint deliberada: no se permite que las preguntas/tarjetas generadas por IA remitan al documento de origen ("según el texto...") — deben tener sentido leídas de forma aislada.

## Brand Commitments

Nombre del producto: "Domina tu Opo" (dominatuopo.com). Tono cercano y directo en español de España, sin anglicismos innecesarios en la interfaz. Sin mascota ni personaje de marca definido. Paleta e identidad visual ya establecidas en `frontend/assets/theme.css` (tokens `--age-*`: naranja primario, navy como color secundario/oscuro) — tratar como sistema de diseño incumbente a extender, no a reemplazar, salvo que se pida explícitamente un rediseño.

## Evidence on Hand

Datos reales de exámenes oficiales ya cargados (JSON en `datos_examenes/`, PDF fuente organizados en `temario-examenes/` por oposición) para AGE, GACE y Auxiliar, con varias convocatorias/años reales por cuerpo. No hay testimonios de usuarios, casos de estudio ni cifras de clientes que se puedan mostrar como prueba social — no inventar ninguno.

## Product Principles

1. El contenido generado por IA se ancla siempre en fuentes reales (temario oficial, exámenes ya publicados) — nunca preguntas inventadas sin base verificable.
2. Cada oposición (AGE/GACE/Auxiliar) es una experiencia independiente con su propio progreso, plan y contenido — nunca se mezclan datos entre ellas.
3. La app es una herramienta de estudio recurrente, no una landing de conversión única: prioriza velocidad, escaneo rápido y fricción mínima en el uso diario (Operate) sobre el impacto visual de una sola visita.
4. Nada se bloquea o se cobra sin que el usuario lo sepa de antemano: los límites de plan y el fin de la prueba gratuita se comunican con claridad antes de topar con ellos.
5. Sin build step ni framework de frontend: cualquier mejora de diseño debe funcionar como HTML/CSS/JS estático servido tal cual, reutilizando los tokens `--age-*` ya existentes.

## Accessibility & Inclusion

Sin requisito de accesibilidad específico documentado hasta ahora (no hay auditoría WCAG previa conocida). Público general adulto en español; sin necesidades de accesibilidad concretas confirmadas por el usuario.
