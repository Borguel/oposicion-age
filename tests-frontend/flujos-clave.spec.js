// E2E de los flujos que más importan de verdad (auditoría de agosto de
// 2026, hallazgo "tests E2E de frontend son solo humo"): smoke.spec.js
// comprueba que las páginas cargan, pero no que el checkout de Stripe ni
// la generación de un test lleguen de principio a fin. Mismo patrón de
// mocks que el resto de tests-frontend/ (sin backend real en CI).
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
export function obtenerOposicionActual() { return "AGE"; }
export function establecerOposicionActual() {}
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

test.describe("checkout de Stripe (/planes/)", () => {
  test("elegir un plan llama a crear-sesion-checkout con el plan/oposición correctos y sigue la redirección", async ({ page }) => {
    await mockAuth(page);

    await page.route("**/mi-perfil*", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify({ plan: "gratis", subscription_status: "inactive", oposicion_activada: true }) })
    );

    let cuerpoRecibido = null;
    await page.route("**/crear-sesion-checkout", (route) => {
      cuerpoRecibido = route.request().postDataJSON();
      // URL de la misma vuelta al server de test en vez de a stripe.com de
      // verdad -- lo que importa es que el frontend siga la redirección que
      // le mande el backend, no probar el checkout real de Stripe.
      route.fulfill({ contentType: "application/json", body: JSON.stringify({ url: "/checkout-mock-ok" }) });
    });
    await page.route("**/checkout-mock-ok", (route) =>
      route.fulfill({ contentType: "text/html", body: "<h1>checkout ok</h1>" })
    );

    await page.goto("/planes/");

    // El selector de oposición no viene preseleccionado a propósito (ver
    // planes/script.js) -- hay que elegir una antes de poder pagar.
    await page.locator("#selector-oposicion").selectOption("AGE");
    await page.locator('[data-plan-btn="premium"]').click();

    await page.waitForURL("**/checkout-mock-ok");
    expect(cuerpoRecibido).toEqual({ plan: "premium", oposicion: "AGE" });
  });

  test("si crear-sesion-checkout falla, se avisa y el botón vuelve a estar disponible", async ({ page }) => {
    await mockAuth(page);
    await page.route("**/mi-perfil*", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify({ plan: "gratis", subscription_status: "inactive", oposicion_activada: true }) })
    );
    await page.route("**/crear-sesion-checkout", (route) =>
      route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: "Error creando sesión de Stripe Checkout" }) })
    );

    await page.goto("/planes/");
    await page.locator("#selector-oposicion").selectOption("AGE");
    const btn = page.locator('[data-plan-btn="premium"]');

    // mostrarErrorGlobal cae a un alert() nativo del navegador en esta
    // página (no carga SweetAlert2) -- Playwright necesita capturar el
    // diálogo explícitamente o se queda bloqueado esperándolo.
    //
    // El manejador se registra ANTES de disparar la acción y acepta el
    // diálogo dentro del propio callback (mismo turno del event loop en
    // el que aparece), en vez de esperarlo con waitForEvent y aceptarlo
    // en una línea aparte -- ese patrón deja una ventana entre "el
    // diálogo ya apareció" y "se acepta" en la que, bajo carga real de
    // CI (varios spec files en paralelo), la página/contexto puede
    // cerrarse de por medio (fallo real visto dos veces seguidas:
    // "dialog.accept: Target page, context or browser has been closed",
    // 22/08/2026). Registrar y aceptar en un solo paso es el patrón que
    // recomienda la propia documentación de Playwright para diálogos.
    let mensajeDialogo = null;
    page.once("dialog", async (dialogo) => {
      mensajeDialogo = dialogo.message();
      await dialogo.accept();
    });
    await btn.click();
    await expect(btn).toBeEnabled();
    expect(mensajeDialogo).toContain("Stripe Checkout");
  });
});

test.describe("generación del Test Oficial (/test-oficial/)", () => {
  test("generar un test muestra la primera pregunta con sus opciones", async ({ page }) => {
    await mockAuth(page);
    await mockOposicion(page);

    await page.route("**/mi-perfil*", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify({ plan: "premium", subscription_status: "active" }) })
    );
    await page.route("**/temas-disponibles*", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify({ temas: [] }) })
    );
    await page.route("**/oposiciones-disponibles*", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify({ oposiciones: [{ id: "AGE" }] }) })
    );
    await page.route("**/preguntas-favoritas*", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify({ preguntas: [] }) })
    );

    let cuerpoRecibido = null;
    await page.route("**/generar-test-oficial", (route) => {
      cuerpoRecibido = route.request().postDataJSON();
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          test: [{
            pregunta: "1. ¿Qué artículo de la Constitución regula la Corona?",
            opciones: { A: "Artículo 56", B: "Artículo 12", C: "Artículo 99", D: "Artículo 1" },
            respuesta_correcta: "A",
            explicacion: "El artículo 56 de la Constitución regula la Corona.",
          }],
        }),
      });
    });

    await page.goto("/test-oficial/");
    await page.locator("#num_preguntas").fill("1");
    await page.locator("#form-generar-test button[type=submit]").click();

    await expect(page.locator("#form-pregunta")).toContainText("¿Qué artículo de la Constitución regula la Corona?");
    // El radio nativo se oculta con opacity:0 a propósito (el círculo con la
    // letra es el que se ve, ver test-generator/style.css) -- no está
    // "visible" para Playwright aunque sí es interactivo vía la label.
    await expect(page.locator('input[name="respuesta"][value="A"]')).toBeAttached();
    await expect(page.locator(".opcion-texto").first()).toContainText("Artículo 56");
    expect(cuerpoRecibido.num_preguntas).toBe(1);
  });

  test("un 429 (límite de uso alcanzado) muestra el aviso y el enlace a planes", async ({ page }) => {
    await mockAuth(page);
    await mockOposicion(page);
    await page.route("**/mi-perfil*", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify({ plan: "basico", subscription_status: "active" }) })
    );
    await page.route("**/temas-disponibles*", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify({ temas: [] }) })
    );
    await page.route("**/oposiciones-disponibles*", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify({ oposiciones: [{ id: "AGE" }] }) })
    );
    await page.route("**/generar-test-oficial", (route) =>
      route.fulfill({ status: 429, contentType: "application/json", body: JSON.stringify({ error: "Has alcanzado el límite de uso diario de esta herramienta." }) })
    );

    await page.goto("/test-oficial/");
    await page.locator("#form-generar-test button[type=submit]").click();

    await expect(page.locator("#contenedor-test")).toContainText("límite de uso diario");
    await expect(page.locator("#contenedor-test a[href='/planes/']")).toBeVisible();
  });
});
