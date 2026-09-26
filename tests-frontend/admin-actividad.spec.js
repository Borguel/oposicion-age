// Verifica la nueva página propia "Actividad completa"
// (frontend/admin/actividad/), que sustituye a la antigua pestaña dentro del
// modal de ficha de usuario. Igual que smoke.spec.js, se sustituye
// /assets/auth.js entero por un stub mínimo (esta página no necesita
// Firebase real, solo obtenerPermisos/obtenerAuthHeaders/marcarContenidoListo)
// y se mockean con page.route() los 4 endpoints del backend que usa:
// /admin/api/usuarios/<uid>, .../actividad-completa, .../actividad-completa/item
// y .../actividad-completa/exportar.
const fs = require("fs");
const { test, expect } = require("@playwright/test");

const AUTH_STUB = `
export const auth = {};
export function esperarUsuario() { return Promise.resolve({ email: "admin@example.com" }); }
export const contenidoListo = Promise.resolve();
export function marcarContenidoListo() {}
export function obtenerAuthHeaders() { return Promise.resolve({ Authorization: "Bearer fake-token" }); }
export function obtenerPermisos() { return Promise.resolve({ admin: true, permisos: ["temario", "reportes", "usuarios"] }); }
`;

const USUARIO = {
  uid: "uid-test-1",
  email: "lemin@example.com",
  nombre: "Lemin Test",
  plan: "premium",
  en_prueba: false,
  email_verificado: true,
  bloqueado: false,
  fecha_creacion: "2026-01-01",
  ultima_actividad: "2026-02-01",
};

// Nombre real (anonimizado en la forma, no en la longitud) que causó un
// bug real reportado por el usuario en móvil: el título de la tarjeta no
// se truncaba con "..." como debía y desbordaba la página en vez de
// cortarse (ver .act-card en style.css).
const NOMBRE_ARCHIVO_LARGO = "BOE-443_Normativa_para_ingreso_en_el_Cuerpo_de_Gestion_de_la_Administracion_Civi.pdf";

const RESUMEN_TEXTO = "Resumen corto de prueba sobre la Constitución.";
const TEXTO_DOCUMENTO = "Texto completo extraído del PDF de prueba.";
// opciones como OBJETO por letra ({"A": "...", "B": "..."}) -- así es como
// lo guarda de verdad el backend (guardar_resultado.py, blueprints/pdf_ia.py)
// y como lo lee el módulo compartido resultados-test.js. La ronda anterior
// de este test usaba un array aquí (["Madrid", "Barcelona"]), la forma
// INCORRECTA -- coincidía con el bug real de frontend/admin/actividad/
// script.js en vez de con el esquema real, así que nunca lo detectó.
const PREGUNTAS_TEST = [
  {
    pregunta: "¿Cuál es la capital de España?",
    opciones: { A: "Madrid", B: "Barcelona" },
    respuesta_correcta: "A",
    respuesta_usuario: "A",
    acierto: true,
    explicacion: "Madrid es la capital.",
  },
  {
    pregunta: "¿En qué año se promulgó la Constitución de 1978?",
    opciones: { A: "1975", B: "1978" },
    respuesta_correcta: "B",
    respuesta_usuario: "A",
    acierto: false,
  },
];

const METADATOS = {
  documentos: [
    {
      id: "doc1",
      nombre_archivo: "ley-test.pdf",
      num_paginas: 12,
      fecha_subida: "2026-01-05",
      longitud_texto: TEXTO_DOCUMENTO.length,
    },
    {
      id: "doc2",
      nombre_archivo: NOMBRE_ARCHIVO_LARGO,
      num_paginas: 14,
      fecha_subida: "2026-01-06",
      longitud_texto: TEXTO_DOCUMENTO.length,
    },
  ],
  resumenes_pdf: [{ id: "res1", documento_id: "doc1", longitud: RESUMEN_TEXTO.length }],
  esquemas_pdf: [],
  tests_pdf: [{ id: "testpdf1", documento_id: "doc1", fecha: "2026-01-05", num_preguntas: PREGUNTAS_TEST.length }],
  tarjetas_pdf: [],
  tests: [
    {
      id: "test1",
      fecha: "2026-02-01",
      tipo: "Test Oficial",
      oposicion: "AGE",
      estado: "finalizado",
      aciertos: 1,
      fallos: 1,
      blancos: 0,
      porcentaje_acierto: 50,
      puntuacion_final: 5,
      num_preguntas: 2,
    },
  ],
  esquemas: [],
};

async function mockPagina(page) {
  await page.route("**/assets/auth.js", (route) =>
    route.fulfill({ contentType: "application/javascript", body: AUTH_STUB })
  );
  await page.route("**/admin/api/usuarios/*", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(USUARIO) })
  );
  await page.route("**/admin/api/usuarios/*/actividad-completa", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(METADATOS) })
  );
  await page.route("**/admin/api/usuarios/*/actividad-completa/item*", (route) => {
    const url = new URL(route.request().url());
    const coleccion = url.searchParams.get("coleccion");
    const id = url.searchParams.get("id");
    const cuerpo = { documentos: { texto: TEXTO_DOCUMENTO }, resumenes_pdf: { resumen: RESUMEN_TEXTO }, tests: { preguntas: PREGUNTAS_TEST }, tests_pdf: { preguntas: PREGUNTAS_TEST } };
    if (!cuerpo[coleccion]) return route.fulfill({ status: 400, contentType: "application/json", body: "{}" });
    void id;
    route.fulfill({ contentType: "application/json", body: JSON.stringify(cuerpo[coleccion]) });
  });
  await page.route("**/temas-disponibles*", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ temas: [{ id: "b1-t1", titulo: "La Constitución" }], oposicion: "AGE" }) })
  );
  await page.route("**/admin/api/usuarios/*/actividad-completa/exportar", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        documentos: [{ ...METADATOS.documentos[0], texto: TEXTO_DOCUMENTO }],
        resumenes_pdf: [{ ...METADATOS.resumenes_pdf[0], resumen: RESUMEN_TEXTO }],
        esquemas_pdf: [],
        tests_pdf: [],
        tarjetas_pdf: [],
        tests: [{ ...METADATOS.tests[0], preguntas: PREGUNTAS_TEST }],
        esquemas: [],
      }),
    })
  );
}

test.describe("Página Actividad completa", () => {
  test("carga la cabecera y las secciones con sus items", async ({ page }) => {
    await mockPagina(page);
    await page.goto("/admin/actividad/?uid=uid-test-1");

    await expect(page.locator(".ficha-email")).toHaveText("lemin@example.com");
    await expect(page.locator("#act-secciones-nav")).toContainText("Documentos");
    await expect(page.locator("#act-secciones-nav")).toContainText("Tests");

    await expect(page.locator('.act-card-titulo[title="ley-test.pdf"]')).toBeVisible();
    await expect(page.locator(".act-item-etiqueta", { hasText: "Resumen generado" })).toBeVisible();
    await expect(page.locator(".act-item-etiqueta", { hasText: "Preguntas del test" })).toBeVisible();
  });

  test('"Ver" despliega el contenido de un elemento bajo demanda', async ({ page }) => {
    await mockPagina(page);
    await page.goto("/admin/actividad/?uid=uid-test-1");

    const itemResumen = page.locator('.act-item[data-coleccion="resumenes_pdf"]');
    await expect(itemResumen.locator(".act-item-cuerpo")).toBeEmpty();

    await itemResumen.locator(".act-item-ver").click();
    await expect(itemResumen.locator(".act-item-cuerpo")).toContainText(RESUMEN_TEXTO);
  });

  test('descargar UN elemento suelto solo incluye su propio contenido', async ({ page }) => {
    await mockPagina(page);
    await page.goto("/admin/actividad/?uid=uid-test-1");

    const itemResumen = page.locator('.act-item[data-coleccion="resumenes_pdf"]');
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      itemResumen.locator(".act-item-descargar").click(),
    ]);

    expect(download.suggestedFilename()).toContain("resumen-ley-test");
    const ruta = await download.path();
    const contenido = fs.readFileSync(ruta, "utf-8");
    expect(contenido).toBe(RESUMEN_TEXTO);
    expect(contenido).not.toContain(TEXTO_DOCUMENTO);
  });

  test('"Ver" en un test navega a la página de resultado en vez de desplegarse en línea', async ({ page }) => {
    // Bug real: con `opciones` como objeto por letra (esquema real), el
    // "Ver" en línea de un test lanzaba un TypeError sin capturar y se
    // quedaba colgado en "Cargando…" para siempre. Ahora "Ver" en un test
    // hecho navega a /admin/actividad/resultado/, que reutiliza el mismo
    // módulo de render que ve un usuario normal.
    await mockPagina(page);
    await page.goto("/admin/actividad/?uid=uid-test-1");

    const itemTest = page.locator('.act-item[data-coleccion="tests"]');
    // Ya no lleva la clase .act-item-ver (esa es solo para el toggle en
    // línea) -- el botón "Ver" de un test es un enlace normal.
    await expect(itemTest.locator(".act-item-ver")).toHaveCount(0);
    const enlaceVer = itemTest.locator("a.act-icon-btn");
    await expect(enlaceVer).toHaveAttribute(
      "href",
      "/admin/actividad/resultado/?uid=uid-test-1&coleccion=tests&id=test1&oposicion=AGE&tipo=Test%20Oficial&fecha=2026-02-01"
    );

    await enlaceVer.click();
    await expect(page).toHaveURL(/\/admin\/actividad\/resultado\//);
  });

  test('"Ver" en un test generado desde un PDF (tests_pdf) sigue desplegándose en línea, sin reventar', async ({ page }) => {
    // Mismo esquema real de "opciones" que un test hecho, pero tests_pdf
    // (banco de preguntas sin intento asociado) se queda con el
    // comportamiento de despliegue en línea -- solo hacía falta arreglar
    // que no lance un TypeError con `opciones` como objeto.
    await mockPagina(page);
    await page.goto("/admin/actividad/?uid=uid-test-1");

    const itemTestPdf = page.locator('.act-item[data-coleccion="tests_pdf"]');
    await itemTestPdf.locator(".act-item-ver").click();
    await expect(itemTestPdf.locator(".act-item-cuerpo")).toContainText("A) Madrid");
  });

  test('"Descargar todo" sigue exportando el volcado íntegro, con las opciones bien formateadas', async ({ page }) => {
    await mockPagina(page);
    await page.goto("/admin/actividad/?uid=uid-test-1");

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#act-descargar-todo").click(),
    ]);

    expect(download.suggestedFilename()).toContain("actividad-lemin@example.com");
    const ruta = await download.path();
    const contenido = fs.readFileSync(ruta, "utf-8");
    expect(contenido).toContain(RESUMEN_TEXTO);
    expect(contenido).toContain(TEXTO_DOCUMENTO);
    expect(contenido).toContain("¿Cuál es la capital de España?");
    // Con `opciones` como objeto, esta línea se omitía en silencio antes
    // del arreglo de formatearPreguntas (ni reventaba ni se veía el fallo
    // salvo comparando el .txt descargado con lo esperado).
    expect(contenido).toContain("Opciones: A) Madrid | B) Barcelona");
  });

  test("se ve sin desbordamiento horizontal en móvil, tablet y escritorio", async ({ page }) => {
    await mockPagina(page);
    for (const ancho of [390, 820, 1440]) {
      await page.setViewportSize({ width: ancho, height: 900 });
      await page.goto("/admin/actividad/?uid=uid-test-1");
      await expect(page.locator(".ficha-email")).toBeVisible();
      const desbordamiento = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(desbordamiento).toBeLessThanOrEqual(1);
    }
  });

  test("el título de un documento con nombre de archivo largo se trunca en vez de desbordar la tarjeta", async ({ page }) => {
    await mockPagina(page);
    await page.setViewportSize({ width: 390, height: 900 });
    await page.goto("/admin/actividad/?uid=uid-test-1");

    const tituloLargo = page.locator(`.act-card-titulo[title="${NOMBRE_ARCHIVO_LARGO}"]`);
    await expect(tituloLargo).toBeVisible();
    // Si .act-card no encoge por debajo del contenido (el bug real), la
    // tarjeta entera crece para caber el nombre y este elemento nunca
    // llega a desbordarse respecto a sí mismo -- en cambio, truncado de
    // verdad, su contenido (el texto completo) es más ancho que su caja
    // visible.
    const trunca = await tituloLargo.evaluate((el) => el.scrollWidth > el.clientWidth);
    expect(trunca).toBe(true);

    const desbordamiento = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(desbordamiento).toBeLessThanOrEqual(1);
  });

  test("sin permisos de admin muestra el aviso de acceso restringido", async ({ page }) => {
    await page.route("**/assets/auth.js", (route) =>
      route.fulfill({
        contentType: "application/javascript",
        body: AUTH_STUB.replace(
          'export function obtenerPermisos() { return Promise.resolve({ admin: true, permisos: ["temario", "reportes", "usuarios"] }); }',
          'export function obtenerPermisos() { return Promise.resolve({ admin: false, permisos: [] }); }'
        ),
      })
    );
    await page.goto("/admin/actividad/?uid=uid-test-1");

    await expect(page.locator("#act-no-autorizado")).toBeVisible();
    await expect(page.locator("#act-contenido")).toBeHidden();
  });
});

test.describe("Página Resultado del test (admin)", () => {
  async function mockResultado(page) {
    await page.route("**/assets/auth.js", (route) =>
      route.fulfill({ contentType: "application/javascript", body: AUTH_STUB })
    );
    await page.route("**/admin/api/usuarios/*/actividad-completa/item*", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify({ preguntas: PREGUNTAS_TEST }) })
    );
    await page.route("**/temas-disponibles*", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify({ temas: [{ id: "b1-t1", titulo: "La Constitución" }], oposicion: "AGE" }) })
    );
  }

  const URL_RESULTADO = "/admin/actividad/resultado/?uid=uid-test-1&coleccion=tests&id=test1&oposicion=AGE&tipo=oficial&fecha=2026-02-01";

  test("pinta el resultado del test igual que lo ve un usuario normal (mismo módulo resultados-test.js)", async ({ page }) => {
    await mockResultado(page);
    await page.goto(URL_RESULTADO);

    await expect(page.locator("#act-res-cargando")).toBeHidden();
    // .resultado-resumen-grid/.tile-acierto/.lista-detalle-preguntas son
    // las clases que pinta /assets/resultados-test.js -- las mismas que
    // usa /mis-tests/resultado/ (la página que ve un usuario normal).
    await expect(page.locator(".resultado-resumen-grid")).toBeVisible();
    await expect(page.locator(".lista-detalle-preguntas")).toContainText("¿Cuál es la capital de España?");
    await expect(page.locator(".lista-detalle-preguntas")).toContainText("A) Madrid");
    await expect(page.locator(".lista-detalle-preguntas")).toContainText("B) Barcelona");
  });

  test('"← Volver" apunta a la actividad de ese usuario', async ({ page }) => {
    await mockResultado(page);
    await page.goto(URL_RESULTADO);
    await expect(page.locator("#act-res-volver")).toHaveAttribute("href", "/admin/actividad/?uid=uid-test-1");
  });

  test("sin uid o id en la URL muestra un mensaje de error en vez de quedarse cargando", async ({ page }) => {
    await mockResultado(page);
    await page.goto("/admin/actividad/resultado/?uid=uid-test-1");
    await expect(page.locator("#act-res-cargando")).toContainText("Falta el usuario o el test");
  });

  test("si el item no carga, muestra un botón de reintentar en vez de quedarse colgado", async ({ page }) => {
    await page.route("**/assets/auth.js", (route) =>
      route.fulfill({ contentType: "application/javascript", body: AUTH_STUB })
    );
    await page.route("**/admin/api/usuarios/*/actividad-completa/item*", (route) =>
      route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: "No encontrado" }) })
    );
    await page.route("**/temas-disponibles*", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify({ temas: [] }) })
    );
    await page.goto(URL_RESULTADO);

    await expect(page.locator(".act-res-reintentar")).toBeVisible();
  });

  test("sin permisos de admin muestra el aviso de acceso restringido", async ({ page }) => {
    await page.route("**/assets/auth.js", (route) =>
      route.fulfill({
        contentType: "application/javascript",
        body: AUTH_STUB.replace(
          'export function obtenerPermisos() { return Promise.resolve({ admin: true, permisos: ["temario", "reportes", "usuarios"] }); }',
          'export function obtenerPermisos() { return Promise.resolve({ admin: false, permisos: [] }); }'
        ),
      })
    );
    await page.goto(URL_RESULTADO);

    await expect(page.locator("#act-res-no-autorizado")).toBeVisible();
    await expect(page.locator("#act-res-contenido")).toBeHidden();
  });
});
