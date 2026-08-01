// Smoke tests de las páginas clave del frontend estático. No hay backend
// real disponible en CI, así que se interceptan los módulos que hablan con
// Firebase/el backend (mismo patrón que se usa para verificar cambios
// manualmente durante el desarrollo): se sirve un /assets/auth.js falso y
// se mockean con page.route() los endpoints que cada página necesita.
const { test, expect } = require("@playwright/test");

const AUTH_STUB = `
export const auth = {};
export function idToken() { return Promise.resolve("fake-token"); }
export function esperarUsuario() { return Promise.resolve({ email: "test@example.com" }); }
export function signOut() { return Promise.resolve(); }
export function obtenerAuthHeaders() { return Promise.resolve({ Authorization: "Bearer fake-token" }); }
export const contenidoListo = Promise.resolve();
export function marcarContenidoListo() {}
`;

const OPOSICION_STUB = `
export function obtenerOposicionActual() { return "age"; }
`;

async function mockAuth(page) {
  await page.route("**/assets/auth.js", (route) =>
    route.fulfill({ contentType: "application/javascript", body: AUTH_STUB })
  );
}

async function mockOposicion(page) {
  await page.route("**/assets/oposicion.js", (route) =>
    route.fulfill({ contentType: "application/javascript", body: OPOSICION_STUB })
  );
}

test("la home carga y muestra la propuesta de valor", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("h1")).toContainText("oposición");
  await expect(page.locator('a[href="/test-generator/"]').first()).toBeVisible();
});

test("la página de login muestra el formulario de email y contraseña", async ({ page }) => {
  await page.goto("/login/");
  await expect(page.locator("#email")).toBeVisible();
  await expect(page.locator("#password")).toBeVisible();
});

test("test personalizado muestra el input de preguntas y el temario numerado", async ({ page }) => {
  await mockAuth(page);
  await mockOposicion(page);
  // protegerPagina("basico") llama a /mi-perfil para resolver el plan antes
  // de pintar nada de la página (ver plan.js) -- sin este mock la petición
  // real falla en CI, cae a plan "gratis" y la pantalla de bloqueo tapa
  // #lista-temas antes de que el test llegue a comprobarlo.
  await page.route("**/mi-perfil*", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ plan: "premium", subscription_status: "active" }) })
  );
  await page.route("**/temas-disponibles*", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        temas: [
          { id: "b1-t1", titulo: "La Constitución", bloque_id: "b1", bloque_titulo: "Organización del Estado" },
          { id: "b1-t2", titulo: "La Corona", bloque_id: "b1", bloque_titulo: "Organización del Estado" },
          { id: "b2-t1", titulo: "El acto administrativo", bloque_id: "b2", bloque_titulo: "Derecho Administrativo" },
        ],
      }),
    })
  );

  // El formulario con número de preguntas + selector de temas vive en
  // /test-personalizado/ desde que /test-generator/ pasó a ser solo el
  // menú de 6 tarjetas hacia las páginas dedicadas de cada tipo de test.
  await page.goto("/test-personalizado/");

  const numPreguntas = page.locator("#num_preguntas");
  await expect(numPreguntas).toBeVisible();
  await expect(numPreguntas).toHaveAttribute("max", "100");

  await expect(page.locator("#lista-temas")).toContainText("I. Organización del Estado");
  await expect(page.locator("#lista-temas")).toContainText("1. La Constitución");
  await expect(page.locator("#lista-temas")).toContainText("II. Derecho Administrativo");
});

test("mi cuenta permite exportar datos y exige escribir ELIMINAR para borrar la cuenta", async ({ page }) => {
  await mockAuth(page);
  await page.route("**/mi-perfil*", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ nombre: "Ana", apellidos: "López", suscripciones: {} }) })
  );
  await page.route("**/mi-racha*", (route) =>
    route.fulfill({ contentType: "application/json", body: '{"racha_actual":0,"racha_maxima":0}' })
  );

  await page.goto("/mi-cuenta/");

  await expect(page.locator("#btn-exportar-datos")).toBeVisible();

  await page.click("#btn-eliminar-cuenta");
  const btnConfirmar = page.locator("#btn-confirmar-eliminar");
  await expect(btnConfirmar).toBeDisabled();

  await page.fill("#campo-confirmar-eliminar", "ELIMINAR");
  await expect(btnConfirmar).toBeEnabled();
});
