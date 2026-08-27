// Verifica el rediseño de la barra de navegación pública (.age-nav):
// grupo de utilidades (buscador + oposición + modo oscuro) en escritorio,
// cajón móvil con esas mismas piezas más los enlaces y la fila de modo
// oscuro, y el comportamiento común de los popovers (exclusividad,
// cierre por click-fuera/Escape, aria-expanded).
//
// A diferencia de smoke.spec.js (que sustituye /assets/auth.js entero por
// un stub mínimo), aquí se deja correr el auth.js real -- es el que
// construye la nav -- y solo se mockean el SDK de Firebase (vía las URLs
// exactas que importa) y los endpoints del backend que toca en el camino.
const { test, expect } = require("@playwright/test");

function moduloFirebaseAuth(usuarioExpr, veces = 1, retrasoRepeticionMs = 0) {
  // veces > 1 simula que Firebase vuelve a disparar onAuthStateChanged con
  // el MISMO usuario -- lo que pasa de verdad al restaurar una página
  // desde la caché de "atrás" del navegador (bfcache), ver el bug real
  // corregido en construirMenuCuenta (auth.js). retrasoRepeticionMs separa
  // en el tiempo la 2ª llamada en adelante de la 1ª, para poder interactuar
  // con la página (abrir el menú) ANTES de que se repita.
  //
  // auth.js registra MÁS de una suscripción a onAuthStateChanged (la de
  // inyectarNav -- la que nos interesa -- y la de analítica, entre otras).
  // Solo se repite en la PRIMERA (inyectarNav, la primera que se registra):
  // las demás se comportan como siempre (una sola llamada), para que el
  // test no dependa de cuántas suscripciones haya ni de en qué orden
  // terminen sus timers.
  return `
    let _numSuscripciones = 0;
    export function getAuth() { return {}; }
    export function onAuthStateChanged(auth, cb) {
      _numSuscripciones++;
      const vecesReal = _numSuscripciones === 1 ? ${veces} : 1;
      for (let i = 0; i < vecesReal; i++) {
        if (i === 0) queueMicrotask(() => cb(${usuarioExpr}));
        else setTimeout(() => cb(${usuarioExpr}), ${retrasoRepeticionMs});
      }
      return () => {};
    }
    export function signInWithEmailAndPassword() { return Promise.reject(new Error("no mockeado")); }
    export function createUserWithEmailAndPassword() { return Promise.reject(new Error("no mockeado")); }
    export function signInWithPopup() { return Promise.reject(new Error("no mockeado")); }
    export class GoogleAuthProvider { static credentialFromError() { return null; } }
    export class EmailAuthProvider { static credential() { return {}; } }
    export function getAdditionalUserInfo() { return null; }
    export function linkWithCredential() { return Promise.reject(new Error("no mockeado")); }
    export function verifyBeforeUpdateEmail() { return Promise.reject(new Error("no mockeado")); }
    export function reauthenticateWithCredential() { return Promise.reject(new Error("no mockeado")); }
    export function updatePassword() { return Promise.reject(new Error("no mockeado")); }
    export function signOut() { return Promise.resolve(); }
  `;
}

const USUARIO_FALSO = `{
  uid: "uid-test-1",
  email: "test@example.com",
  emailVerified: true,
  providerData: [{ providerId: "password" }],
  getIdToken: () => Promise.resolve("fake-token"),
  getIdTokenResult: () => Promise.resolve({ claims: {} }),
}`;

async function mockNav(page, { conSesion, veces = 1, retrasoRepeticionMs = 0 }) {
  await page.route("**/firebase-app.js", (route) =>
    route.fulfill({ contentType: "application/javascript", body: "export function initializeApp() { return {}; }" })
  );
  await page.route("**/firebase-auth.js", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: moduloFirebaseAuth(conSesion ? USUARIO_FALSO : "null", veces, retrasoRepeticionMs),
    })
  );
  await page.route("**/assets/tutor-widget.js", (route) =>
    route.fulfill({ contentType: "application/javascript", body: "export function montarWidgetTutor() {}" })
  );
  await page.route("**/banner-global*", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ activo: false }) })
  );
  await page.route("**/mi-perfil*", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ plan: "premium", subscription_status: "active", prueba_activa: false, nombre: "Test" }) })
  );
  await page.route("**/temas-disponibles*", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ temas: [{ id: "b1-t1", titulo: "La Constitución" }] }) })
  );
  await page.route("**/mis-documentos*", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ documentos: [] }) })
  );
  // Usuario de prueba sin ninguna oposición oculta activada (ver
  // oposicion.js _anadirOposicionesOcultasDelUsuario) -- solo las 3
  // públicas, igual que devolvería el backend real para alguien sin
  // suscripciones.METRO.
  await page.route("**/oposiciones-disponibles*", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ oposiciones: [{ id: "AGE" }, { id: "GACE" }, { id: "AUXILIAR" }] }) })
  );
}

async function clicFuera(page) {
  await page.evaluate(() => document.body.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}

test.describe("nav -- escritorio, con sesión", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("buscador, oposición y cuenta son popovers mutuamente excluyentes", async ({ page }) => {
    await mockNav(page, { conSesion: true });
    await page.goto("/zona-opositor/");

    const utilidades = page.locator(".age-nav-utilidades");
    await expect(utilidades).toBeVisible();

    const botonBuscador = utilidades.locator(".age-buscador [data-popover-toggle]");
    const botonOposicion = utilidades.locator(".age-oposicion-popover [data-popover-toggle]");
    const panelBuscador = utilidades.locator(".age-buscador-panel");
    const panelOposicion = utilidades.locator(".age-popover-menu");
    const botonCuenta = page.locator(".age-account-btn");
    const menuCuenta = page.locator(".age-account-menu");

    await expect(botonBuscador).toHaveAttribute("aria-expanded", "false");
    await botonBuscador.click();
    await expect(panelBuscador).toBeVisible();
    await expect(botonBuscador).toHaveAttribute("aria-expanded", "true");

    // Abrir oposición cierra el buscador (exclusividad).
    await botonOposicion.click();
    await expect(panelOposicion).toBeVisible();
    await expect(panelBuscador).toBeHidden();
    await expect(botonBuscador).toHaveAttribute("aria-expanded", "false");

    // Abrir cuenta cierra oposición.
    await botonCuenta.click();
    await expect(menuCuenta).toBeVisible();
    await expect(panelOposicion).toBeHidden();

    // Click fuera cierra el que quede abierto.
    await clicFuera(page);
    await expect(menuCuenta).toBeHidden();
    await expect(botonCuenta).toHaveAttribute("aria-expanded", "false");

    // Escape también cierra.
    await botonCuenta.click();
    await expect(menuCuenta).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(menuCuenta).toBeHidden();
  });

  // Bug real (27/08/2026, detectado analizando la sesión de un usuario que
  // acabó eliminando su cuenta): Firebase dispara onAuthStateChanged otra
  // vez con el MISMO usuario al restaurar una página desde la caché de
  // "atrás" del navegador (bfcache) -- construirMenuCuenta destruía y
  // recreaba el botón de cuenta cada vez que esto pasaba, aunque nada
  // hubiera cambiado. Si esa reconstrucción caía justo mientras el usuario
  // tenía el menú abierto (o a mitad de un clic), el menú se cerraba solo
  // o el clic se perdía contra un nodo que estaba siendo sustituido. Se
  // reproduce aquí abriendo el menú y dejando que la 2ª llamada (con el
  // mismo usuario) llegue MIENTRAS sigue abierto -- sin el guard de
  // acc.dataset.uid en auth.js, el menú se cerraría solo.
  test("un onAuthStateChanged tardío con el mismo usuario no cierra el menú de cuenta ya abierto", async ({ page }) => {
    await mockNav(page, { conSesion: true, veces: 2, retrasoRepeticionMs: 500 });
    await page.goto("/zona-opositor/");

    const botonCuenta = page.locator(".age-account-btn");
    const menuCuenta = page.locator(".age-account-menu");
    await botonCuenta.click();
    await expect(menuCuenta).toBeVisible();

    // Espera a que llegue la 2ª llamada (mismo usuario) mientras el menú
    // sigue abierto.
    await page.waitForTimeout(700);
    await expect(menuCuenta).toBeVisible();
    await expect(page.locator(".age-account-btn")).toHaveCount(1);
  });

  test("el selector de oposición marca la opción actual y cambia de oposición al elegir otra", async ({ page }) => {
    await mockNav(page, { conSesion: true });
    await page.goto("/zona-opositor/");

    await page.locator(".age-oposicion-popover [data-popover-toggle]").click();
    const opciones = page.locator(".age-popover-opcion");
    await expect(opciones).toHaveCount(3);
    await expect(page.locator(".age-popover-opcion-actual")).toContainText("AGE");

    const navegacion = page.waitForEvent("framenavigated");
    await page.locator('.age-popover-opcion[data-op="GACE"]').click();
    await navegacion;
    expect(await page.evaluate(() => localStorage.getItem("age_oposicion_actual"))).toBe("GACE");
  });
});

test.describe("nav -- móvil, con sesión", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("el grupo de utilidades se oculta y el cajón contiene búsqueda, oposición, enlaces y modo oscuro en orden", async ({ page }) => {
    await mockNav(page, { conSesion: true });
    await page.goto("/zona-opositor/");

    await expect(page.locator(".age-nav-utilidades")).toBeHidden();
    await expect(page.locator(".age-account-btn")).toBeVisible();

    const burger = page.locator(".age-nav-burger");
    await burger.click();
    await expect(burger).toHaveAttribute("aria-expanded", "true");

    const drawer = page.locator(".age-nav-links");
    await expect(drawer).toBeVisible();

    const clases = await drawer.locator(":scope > *").evaluateAll((nodos) => nodos.map((n) => n.className));
    const primero = clases.findIndex((c) => c.includes("age-buscador-movil"));
    const segundo = clases.findIndex((c) => c.includes("age-oposicion-movil"));
    const ultimo = clases.findIndex((c) => c.includes("age-tema-movil"));

    expect(primero).toBe(0);
    expect(segundo).toBe(1);
    expect(ultimo).toBe(clases.length - 1);
    expect(primero).toBeLessThan(segundo);
    expect(segundo).toBeLessThan(ultimo);

    await expect(drawer.locator(".age-buscador-movil input")).toBeVisible();
    await expect(drawer.locator(".age-oposicion-movil select")).toBeVisible();
  });
});

test.describe("nav -- sin sesión", () => {
  test("no se pintan ni buscador ni selector de oposición (ni en escritorio ni en el cajón)", async ({ page }) => {
    await mockNav(page, { conSesion: false });
    await page.goto("/");

    await expect(page.locator(".age-buscador")).toHaveCount(0);
    await expect(page.locator(".age-oposicion-popover")).toHaveCount(0);
    await expect(page.locator(".age-buscador-movil")).toHaveCount(0);
    await expect(page.locator(".age-oposicion-movil")).toHaveCount(0);

    // Sin sesión, el bloque de cuenta es un botón de "Iniciar sesión".
    await expect(page.locator(".age-account a.age-btn-primary")).toContainText("Iniciar sesión");
  });
});

// Reproduce el bug del hallazgo P0 de la auditoría: si el SDK de Firebase
// (gstatic.com) no carga -- red corporativa, bloqueador de anuncios,
// extensión de privacidad, blip del CDN -- la web entera se quedaba en
// blanco sin nav, sin footer y sin ningún mensaje de error, porque
// auth.js tenía imports ESTÁTICOS de firebase-app.js/firebase-auth.js: un
// fallo ahí tiraba abajo la evaluación de todo el módulo. Ahora son
// import() dinámicos protegidos con try/catch (ver auth.js), así que el
// resto de la web debe seguir en pie en modo "sin sesión".
test.describe("nav -- Firebase no carga (red bloqueada)", () => {
  test("la nav, el footer y el banner de cookies se pintan igual en modo degradado", async ({ page }) => {
    await page.route("**/firebase-app.js", (route) => route.abort("failed"));
    await page.route("**/firebase-auth.js", (route) => route.abort("failed"));
    await page.route("**/banner-global*", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify({ activo: false }) })
    );
    await page.route("**/promocion-activa*", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify({ activo: false }) })
    );

    await page.goto("/");

    // Nav en modo "sin sesión": enlaces públicos + botón de login, nada de
    // pantalla en blanco.
    await expect(page.locator(".age-nav-links-items a")).toHaveText(["Inicio", "Oposiciones", "Blog", "Cómo funciona", "Planes"]);
    await expect(page.locator(".age-account a.age-btn-primary")).toContainText("Iniciar sesión");
    await expect(page.locator(".age-skip-link")).toBeAttached();

    // Footer y banner de cookies no dependen de Firebase en absoluto.
    await expect(page.locator(".age-footer")).toBeVisible();
    await expect(page.locator(".age-cookies-banner")).toBeVisible();
  });
});

// Los enlaces principales varían según haya sesión o no (ver
// actualizarEnlacesNav en auth.js): antes eran los mismos 9 siempre, la
// mitad de ellos inaccesibles sin cuenta, y además desbordaban la barra en
// anchos de escritorio comunes sin ninguna pista visual de que hubiera más
// enlaces con scroll. Estas pruebas fijan el juego de enlaces correcto por
// sesión y que la barra no desborda en un ancho típico de portátil.
test.describe("nav -- enlaces principales según sesión", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("sin sesión solo se ven los enlaces de marketing, sin desbordar la barra", async ({ page }) => {
    await mockNav(page, { conSesion: false });
    await page.goto("/");

    const enlaces = page.locator(".age-nav-links-items a");
    await expect(enlaces).toHaveText(["Inicio", "Oposiciones", "Blog", "Cómo funciona", "Planes"]);

    const overflow = await page.locator(".age-nav-links").evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("con sesión se ven los enlaces de la aplicación, sin desbordar la barra", async ({ page }) => {
    await mockNav(page, { conSesion: true });
    await page.goto("/zona-opositor/");

    const enlaces = page.locator(".age-nav-links-items a");
    await expect(enlaces).toHaveText(["Zona opositor", "Tests", "Herramientas IA", "Tu Tutor", "Estadísticas", "Planes"]);

    const overflow = await page.locator(".age-nav-links").evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
