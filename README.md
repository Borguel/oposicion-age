# Domina tu Opo

Plataforma web de preparación de oposiciones (AGE, GACE, Auxiliar/C2...):
tests sobre el temario oficial y sobre exámenes reales, herramientas de
IA sobre PDF propio (resumen, esquema, test, tarjetas de memoria), un
tutor conversacional con IA, seguimiento de progreso/estadísticas y
suscripciones de pago vía Stripe.

Backend en Flask + Firestore, frontend estático (HTML/CSS/JS sin
framework, una carpeta por página).

## Arrancar en local

### Backend

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env              # y rellena las claves que necesites
python app.py                     # sirve en http://localhost:5000
```

`.env.example` documenta cada variable y qué pasa si se deja vacía --
la mayoría de integraciones opcionales (Sentry, notificaciones push,
plantillas de SendGrid) se desactivan solas sin bloquear el arranque.
Sin credenciales reales de Firebase/Stripe/DeepSeek el servidor arranca
pero esas funciones fallarán al usarlas; para desarrollar sin ninguna
credencial real, los tests (más abajo) usan un doble en memoria de
Firestore y no necesitan red.

### Frontend

Es HTML/CSS/JS estático, sin build. Basta un servidor estático apuntando
a `frontend/`:

```bash
python3 -m http.server 8080 --directory frontend
```

Y abrir `http://localhost:8080`. `CORS_ORIGINS` en `.env` debe incluir
ese origen (ya viene así por defecto).

### Tests

```bash
python3 -m pytest -q
```

No requieren credenciales ni red: `conftest.py` sustituye Firebase
Admin/Firestore por un doble en memoria (`tests/fakes.py`) antes de
importar la app.

## Estructura del repo

- `app.py` -- crea la app Flask, registra los blueprints, rutas sueltas
  (`/`, `/health`).
- `blueprints/` -- una ruta por dominio: `temario.py` (catálogo/temas),
  `test_ia.py` (generación de tests con IA), `pdf_ia.py` (herramientas
  sobre PDF propio), `tu_tutor.py` (chat), `pagos.py` (Stripe + perfil),
  `ranking.py`, `tareas_programadas.py` (cron).
- `save_controller.py` / `rutas_progreso.py` -- guardado de
  tests/esquemas y progreso, registradas directamente sobre `app` (mismo
  patrón "función que recibe `app` y `db`" que los blueprints).
- Módulos de dominio en la raíz: `registro_progreso_usuario.py`
  (estadísticas/racha/suscripciones), `limites_uso.py` (cuota de IA por
  plan), `deepseek_utils.py` (cliente de la API de DeepSeek),
  `auth_utils.py` (verificación de token + gating por plan),
  `utils.py` (temario, generación de tests), `documentos_pdf.py`,
  `banco_fallos.py`, `email_utils.py`, `oposiciones.py` (catálogo de
  oposiciones soportadas).
- `frontend/` -- una carpeta por página (`estadisticas/`,
  `zona-opositor/`, `test-generator/`...), cada una con su propio
  `index.html` + `script.js` (+ `style.css` cuando no comparte el
  sistema de diseño de `assets/theme.css`). `frontend/assets/` tiene los
  módulos JS compartidos entre páginas (auth, notificaciones, DOM,
  iconos...).
- `tests/` -- suite de pytest; `tests/fakes.py` es el doble en memoria de
  Firestore que usan todos los tests.
- `.github/workflows/` -- CI (tests + `node --check` del frontend) y
  cron jobs externos (recordatorio de racha, comprobación de `/health`,
  carga de temario/convocatorias).
- `docs/` -- documentación adicional (ver `docs/firestore-schema.md`
  para el modelo de datos).

## Desplegar

`render.yaml` define dos servicios (backend Flask + frontend estático)
en Render. El `buildCommand` del backend corre la suite de tests como
parte del propio build: si algo falla, el build falla y Render mantiene
la versión anterior en vez de sustituirla.
