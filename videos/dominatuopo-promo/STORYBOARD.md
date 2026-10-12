---
format: 1080x1920
duration: 36s
message: "Aprueba tu oposición con tests ilimitados e IA — 7 días Premium gratis en dominatuopo.com"
arc: Hook → Pain → Mecanismo (PDF→test) → Prueba (cifras) → Ventajas → Oferta → CTA
audience: opositores a AGE (C1), GACE y Auxiliar que estudian con apuntes sueltos
mode: autonomous
music: none
---

## Video direction

- **Palette (de `frame.md`, preset Broadside):** dos registros planos, una sola superficie por plano. `ink-black` #16181D como fondo base; `fire-orange` #FFA633 como superficie de énfasis (planos 3 y 5) y como único acento sobre oscuro; texto `cream` #FFFFFF. Nada de gradientes morados/azules ni "IA genérica". Sin sombras blandas; solo planos y filetes de 1 px.
- **Tipografía:** Plus Jakarta Sans 800, minúsculas, tracking negativo, gigante (rol display / h1 / stat-value). IBM Plex Mono mayúsculas solo para kickers de 1 línea. La cifra siempre es el elemento más grande del plano.
- **Motion grammar:** curvas de cola larga (`power3`/`expo.out` por defecto), nunca rebotes blandos; entradas con *slam* de palabra (`kinetic-beat-slam`) y *count-up* en cifras. Un único gesto de cámara por plano como máximo. Sin voz: el ritmo lo marca el texto — cada palabra o cifra entra en su "golpe", nunca todo en t=0.
- **Reveal model:** en t=0 solo entra el primer golpe; el resto se revela escalonado a lo largo de la duración del plano, sobre todo en su segunda mitad. Cierre de cada plano en lectura quieta (sin respiración ni deriva).
- **Ritmo / planos quietos:** plano 2 (el "mecanismo") y plano 5 (la oferta) son los de lectura más tranquila; 1, 3 y 4 son los de energía alta. El plano 6 mantiene el CTA quieto los últimos 2 s.
- **Transiciones:** hard cut en el hook, `zoom-through`, `push-slide`, `squeeze` y `blur-crossfade` — variadas, cortas (≤0.5 s).
- **Zona segura 9:16:** contenido en el 83 % superior y dentro de ~7 % de margen lateral (UI de TikTok/Reels). No hay locución ni subtítulos; el texto en pantalla ES la narración.
- **Negative list:** nada de capturas de navegador, barras de navegación, cursores reales, bokeh, gradientes IA, ni cifras inventadas. Nada de "front-load y congelar" ni "salvapantallas" (todo flotando a la vez). Solo cifras reales de la home: +1.655, +12.223, 7 días, 4,99 €, 9,99 €.

## Frame 1 — Hook

- scene: Tres preguntas de dolor se apilan (apuntes, qué repasar, examen) y puente «hay una forma más fácil»
- duration: 6s
- transition_in: cut
- status: animated
- src: compositions/frames/01-hook.html
- type: hook
- persuasion: Pain validation
- beat: tension
- blueprint: kinetic-type-beats (Adapt)

Adapt: se mantiene la palabra que se intercambia en su sitio (signature move: el swap seco); la frase fija es «¿sigues estudiando…» y la palabra final cambia.
Scene 1 (0.0–1.2s): fondo ink-black; kicker mono naranja «oposiciones» arriba; entra de golpe «¿sigues» en display gigante, minúsculas, centrado en el tercio superior.
Scene 2 (1.2–2.4s): bajo ella, slam de «estudiando» y a continuación la palabra variable en naranja se intercambia en el sitio: «a ciegas?» → «sin rumbo?» → «solo?» por hard cut, cada una ~0.4 s. Layout centrado, tipografía ≈60 % del ancho útil.
Scene 3 (2.4–4.0s): la última palabra («solo?») se queda y el resto de la frase se atenúa al 35 %; un filete naranja de 36×2 px se dibuja bajo ella. Lectura quieta hasta el final.

## Frame 2 — Mecanismo: PDF a test

- scene: Un PDF cae en la zona de subida, se genera el test, se marca la correcta y aparece la explicación
- duration: 7.5s
- transition_in: zoom-through
- status: animated
- src: compositions/frames/02-mecanismo.html
- type: product_intro
- persuasion: Mechanism
- beat: relief
- blueprint: prompt-type-submit-generate (Adapt)
- asset_candidates: svgs/logo-brand-favicon.svg
- focal: svgs/logo-brand-favicon.svg
- roles: logo-brand-favicon = supporting (marca pequeña arriba)

Adapt: se mantiene el ciclo escribir→enviar→respuesta; el "prompt" es el nombre de un PDF («apuntes-tema-3.pdf») y la respuesta es una tarjeta de test con 3 opciones; se reconstruye solo la tarjeta, sin interfaz de navegador.
Scene 1 (0.0–1.4s): tarjeta superficie plana ink-black-alt centrada con un campo de entrada mono; se teclea «apuntes-tema-3.pdf» con cursor parpadeante; kicker «sube tu pdf» arriba. Marca (favicon naranja) pequeña en la esquina superior.
Scene 2 (1.4–2.6s): al «enviar», un estado breve («generando test…») con filete naranja que avanza, y la tarjeta se transforma en pregunta de test: «¿cuál es la forma política del estado español?» (texto real de la home).
Scene 3 (2.6–5.0s): aparecen A/B/C en cascada con un golpe de 0.25 s entre cada una; la B «monarquía parlamentaria» se ilumina en naranja con check; titular grande debajo: «tu pdf. tu test.» entra en slam. Lectura quieta los últimos 1.2 s.

## Frame 3 — Test oficial

- scene: Test Oficial: tarjetas GACE/AGE/Auxiliar, simulacro de un clic y lo que obtienes
- duration: 6.5s
- transition_in: push-slide LEFT
- status: animated
- src: compositions/frames/03-cifras.html
- type: social_proof
- persuasion: Proof
- beat: scale
- blueprint: dataviz-countup (Adapt)

Adapt: se mantiene el count-up con escala dinámica y el aterrizaje en una cifra héroe; se sustituye la cámara que atraviesa instrumentos por tres bloques apilados (cifra + etiqueta + filete) que entran uno a uno; sin gráfico decorativo inventado.
Scene 1 (0.0–2.0s): superficie fire-orange (registro orange); kicker mono «lo que ya tienes dentro»; el primer bloque cuenta de 0 a «+1.655» en tinta oscura, enorme, con la etiqueta «preguntas oficiales» debajo y filete de 1 px.
Scene 2 (2.0–4.2s): segundo bloque debajo cuenta hasta «+12.223» con etiqueta «preguntas de opositores»; el primer bloque baja de peso (60 %) pero queda legible.
Scene 3 (4.2–6.0s): tercer bloque, de golpe, «< 1 min» con etiqueta «de cero a tu primer test». Lectura quieta; los tres bloques ocupan ≈75 % de la altura útil, jerarquía por tamaño (3:1) y peso 800.

## Frame 4 — Ventajas

- scene: Cuatro ventajas se ensamblan en una lista tipográfica
- duration: 6s
- transition_in: squeeze
- status: animated
- src: compositions/frames/04-ventajas.html
- type: feature_showcase
- persuasion: Feature → benefit
- beat: desire
- blueprint: grid-card-assemble (Adapt)

Adapt: en lugar de una cuadrícula de tarjetas, una lista vertical de 4 líneas con filete (el signature move sigue siendo el ensamblado escalonado de N elementos); cada línea = beneficio, no función.
Scene 1 (0.0–1.4s): fondo ink-black; kicker «todo en un solo sitio»; título «estudia sin límite» en display, parte alta.
Scene 2 (1.4–5.6s): cuatro líneas entran una a una (≈1 s cada una) con slide-up y filete naranja: «tests ilimitados · oficiales y personalizados», «tu pdf → esquemas, tarjetas y resumen», «tu tutor ia · resuelve dudas del temario», «estadísticas por tema · sabes qué repasar». Cada marcador es un «/» naranja mono.
Scene 3 (5.6–7.0s): las cuatro líneas se mantienen; la primera palabra de cada una pasa a naranja en cascada rápida y el conjunto queda quieto (lectura).

## Frame 5 — Oferta

- scene: 7 días Premium gratis; Básico 4,99 € en segundo plano y Premium 9,99 € destacado
- duration: 5s
- transition_in: blur-crossfade
- status: animated
- src: compositions/frames/05-oferta.html
- type: benefit_highlight
- persuasion: Risk reversal
- beat: relief
- blueprint: titlecard-reveal (Adapt)

Adapt: una sola idea; el número «7» como héroe con un único movimiento; el precio entra al final como letra pequeña de confianza.
Scene 1 (0.0–1.6s): superficie fire-orange; «7 días» en tinta oscura, display gigante, entra en slam desde escala 1.15 con blur que se resuelve; debajo «premium gratis».
Scene 2 (1.6–3.0s): aparece «sin tarjeta · sin permanencia» en mono mayúsculas; filete de 1 px se dibuja a ancho completo.
Scene 3 (3.0–4.0s): línea final pequeña «después desde 4,99 €/mes · cancela cuando quieras». Quieto.

## Frame 6 — CTA

- scene: Marca y llamada a la acción a pantalla completa
- duration: 4s
- transition_in: crossfade
- status: animated
- src: compositions/frames/06-cta.html
- type: cta
- persuasion: CTA
- beat: resolve
- blueprint: logo-assemble-lockup (Adapt)
- asset_candidates: svgs/logo-brand-favicon.svg
- focal: svgs/logo-brand-favicon.svg
- roles: logo-brand-favicon = cutout (marca centrada)

Adapt: el logotipo (favicon naranja) aparece por *spring-pop* y debajo se teclea la URL; se mantiene el aterrizaje del lockup; sin partículas.
Scene 1 (0.0–1.2s): fondo ink-black; el favicon naranja entra con spring-pop en el tercio superior central.
Scene 2 (1.2–2.4s): «domina tu opo» en display bajo el logo, slam de palabra por palabra.
Scene 3 (2.4–4.0s): pastilla naranja con «dominatuopo.com» (texto tinta sobre naranja) y kicker mono «empieza gratis hoy» encima. Mantiene quieto los últimos 1.5 s. Único plano con salida: fundido a negro en los últimos 0.3 s.
