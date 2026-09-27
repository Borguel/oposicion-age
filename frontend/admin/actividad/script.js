// Página propia "Actividad completa" de un usuario (panel admin). Antes
// vivía apretada dentro de una pestaña del modal de ficha -- aquí tiene
// sitio de sobra para organizarse en secciones claras, con rejilla de
// documentos, lista de tests, y descarga de cada elemento por separado
// además del volcado íntegro. Solo para el admin TOTAL (mismo criterio
// que el backend: /actividad-completa/item y /exportar devuelven 403 a un
// admin con permiso parcial "usuarios").
import { obtenerPermisos, obtenerAuthHeaders, marcarContenidoListo } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { icono } from "/assets/icons.js";

function escapeHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto == null ? "" : String(texto);
  return div.innerHTML;
}

function fechaCorta(valor) {
  return (valor || "").slice(0, 10) || "-";
}

function toast(mensaje, tipo = "ok") {
  const cont = document.getElementById("act-toasts");
  if (!cont) return;
  const el = document.createElement("div");
  el.className = `admin-toast admin-toast-${tipo}`;
  const nombreIcono = tipo === "error" ? "alerta" : tipo === "ok" ? "check" : "informacion";
  el.innerHTML = `<span class="admin-toast-icono">${icono(nombreIcono, 16)}</span><span>${escapeHtml(mensaje)}</span>`;
  cont.appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transform = "translateY(12px)"; }, 3200);
  setTimeout(() => el.remove(), 3600);
}

async function apiGet(ruta) {
  const headers = await obtenerAuthHeaders();
  if (!headers) return null;
  let resp;
  try {
    resp = await fetch(BACKEND_URL + ruta, { headers });
  } catch {
    toast("Sin conexión con el servidor.", "error");
    return null;
  }
  let datos = {};
  try { datos = await resp.json(); } catch { datos = {}; }
  if (!resp.ok) {
    toast(datos.error || "Ha ocurrido un error.", "error");
    return null;
  }
  return datos;
}

function mostrarErrorPanel(contenedor, reintentar) {
  if (!contenedor) return;
  contenedor.innerHTML = `
    <p class="admin-cargando">No se ha podido cargar. Comprueba tu conexión.</p>
    <button type="button" class="age-btn age-btn-outline admin-mini act-reintentar">Reintentar</button>
  `;
  contenedor.querySelector(".act-reintentar").addEventListener("click", reintentar);
}

function fichaPlanBadge(plan, enPrueba) {
  if (enPrueba) return `<span class="ficha-badge ficha-badge-prueba">${icono("reloj", 13)} En prueba (Premium)</span>`;
  const p = (plan || "gratis").toLowerCase();
  const map = { premium: ["Premium", "ficha-badge-premium"], basico: ["Básico", "ficha-badge-basico"], gratis: ["Gratis", "ficha-badge-gratis"] };
  const [txt, cls] = map[p] || map.gratis;
  return `<span class="ficha-badge ${cls}">${txt}</span>`;
}

function descargarTexto(nombreArchivo, texto) {
  const blob = new Blob([texto], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nombreArchivo;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  toast("Descarga iniciada.");
}

function nombreArchivoSeguro(texto) {
  return (texto || "documento").normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^a-zA-Z0-9.-]+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "").slice(0, 80) || "documento";
}

function formatearPreguntas(preguntas) {
  return (preguntas || []).map((p, i) => {
    const lineas = [`  ${i + 1}. [${p.acierto === true ? "✅" : p.acierto === false ? "❌" : "➖"}] ${p.pregunta || ""}`];
    // p.opciones es un objeto por letra ({"A": "...", "B": "..."}), no un
    // array -- bug real: con .join() sobre un objeto esta línea nunca
    // reventaba (un objeto no tiene .length, así que el if se saltaba en
    // silencio) pero tampoco mostraba nunca las opciones.
    const opciones = p.opciones && typeof p.opciones === "object" ? Object.entries(p.opciones).map(([letra, texto]) => `${letra}) ${texto}`) : [];
    if (opciones.length) lineas.push(`     Opciones: ${opciones.join(" | ")}`);
    lineas.push(`     Correcta: ${p.respuesta_correcta ?? "–"} · Respondió: ${p.respuesta_usuario ?? "(en blanco)"}`);
    if (p.explicacion) lineas.push(`     Explicación: ${p.explicacion}`);
    return lineas.join("\n");
  }).join("\n\n");
}

function formatearTarjetas(tarjetas) {
  return (tarjetas || []).map((t, i) => `${i + 1}. P: ${t.pregunta || t.anverso || ""}\n   R: ${t.respuesta || t.reverso || ""}`).join("\n\n");
}

// ---------- Descarga / vista de UN elemento concreto ----------

const _CAMPO_POR_COLECCION = {
  documentos: "texto", resumenes_pdf: "resumen", esquemas_pdf: "esquema",
  tests_pdf: "preguntas", tarjetas_pdf: "tarjetas", tests: "preguntas", esquemas: "contenido",
};

function formatearValorParaTexto(coleccion, valor) {
  if (coleccion === "tests_pdf" || coleccion === "tests") return formatearPreguntas(valor);
  if (coleccion === "tarjetas_pdf") return formatearTarjetas(valor);
  return valor || "";
}

function formatearValorParaHtml(coleccion, valor) {
  // "tests" (Tests hechos) ya NO pasa por aquí -- su "Ver" navega a
  // /admin/actividad/resultado/ (ver itemGeneradoHtml/testCardHtml) para
  // mostrar el resultado real, igual que lo ve el propio usuario.
  // "tests_pdf" (banco de preguntas generado desde un PDF, sin intento
  // real asociado) se sigue desplegando aquí mismo.
  if (coleccion === "tests_pdf") {
    return (valor || []).map(fichaPreguntaHtml).join("") || `<p class="act-nota">Sin preguntas guardadas.</p>`;
  }
  if (coleccion === "tarjetas_pdf") {
    return (valor || []).map((t) => `<p class="ficha-tarjeta">🔹 <strong>${escapeHtml(t.pregunta || t.anverso || "")}</strong><br>${escapeHtml(t.respuesta || t.reverso || "")}</p>`).join("") || `<p class="act-nota">Sin tarjetas.</p>`;
  }
  return `<pre class="ficha-texto-completo">${escapeHtml(valor || "(vacío)")}</pre>`;
}

function fichaPreguntaHtml(p) {
  const acierto = p.acierto === true ? "✅" : p.acierto === false ? "❌" : "➖";
  // p.opciones es un objeto por letra ({"A": "...", "B": "..."}), no un
  // array -- con .map() sobre un objeto esto lanzaba un TypeError sin
  // capturar (bug real reportado: "Ver" en un test se quedaba colgado en
  // "Cargando…" para siempre, ver wireItem).
  const entradas = p.opciones && typeof p.opciones === "object" ? Object.entries(p.opciones) : [];
  const opciones = entradas.map(([letra, texto]) => `<li${letra === p.respuesta_correcta ? ' class="ficha-opcion-correcta"' : ""}${letra === p.respuesta_usuario && letra !== p.respuesta_correcta ? ' class="ficha-opcion-marcada"' : ""}>${escapeHtml(letra)}) ${escapeHtml(texto)}</li>`).join("");
  return `<div class="ficha-pregunta">
    <p class="ficha-pregunta-txt">${acierto} ${escapeHtml(p.pregunta || "")}</p>
    ${opciones ? `<ul class="ficha-opciones">${opciones}</ul>` : ""}
    <p class="ficha-pregunta-meta">Respuesta correcta: <strong>${escapeHtml(p.respuesta_correcta ?? "–")}</strong> · Respondió: <strong>${escapeHtml(p.respuesta_usuario ?? "(en blanco)")}</strong></p>
    ${p.explicacion ? `<p class="ficha-pregunta-exp">${escapeHtml(p.explicacion)}</p>` : ""}
  </div>`;
}

// Caché en memoria del contenido ya pedido de cada elemento (coleccion+id),
// para no volver a pedirlo si se pliega/despliega o se descarga después de
// haberlo visto.
const _cacheItems = {};

async function obtenerContenidoItem(uid, coleccion, id) {
  const clave = `${coleccion}:${id}`;
  if (_cacheItems[clave] !== undefined) return _cacheItems[clave];
  const datos = await apiGet(`/admin/api/usuarios/${uid}/actividad-completa/item?coleccion=${encodeURIComponent(coleccion)}&id=${encodeURIComponent(id)}`);
  if (!datos) return null;
  const campo = _CAMPO_POR_COLECCION[coleccion];
  const valor = datos[campo];
  _cacheItems[clave] = valor;
  return valor;
}

function wireItem(uid, contenedor) {
  const coleccion = contenedor.dataset.coleccion;
  const id = contenedor.dataset.id;
  const nombreDescarga = contenedor.dataset.descarga;
  const btnVer = contenedor.querySelector(".act-item-ver");
  const btnDescargar = contenedor.querySelector(".act-item-descargar");
  const cuerpo = contenedor.querySelector(".act-item-cuerpo");

  btnVer?.addEventListener("click", async () => {
    const abierto = contenedor.classList.toggle("act-item-abierto");
    btnVer.setAttribute("aria-expanded", String(abierto));
    if (!abierto || cuerpo.dataset.cargado) return;
    cuerpo.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
    const valor = await obtenerContenidoItem(uid, coleccion, id);
    if (valor === null) { mostrarErrorPanel(cuerpo, () => { cuerpo.dataset.cargado = ""; btnVer.click(); btnVer.click(); }); return; }
    cuerpo.dataset.cargado = "1";
    cuerpo.innerHTML = formatearValorParaHtml(coleccion, valor);
  });

  btnDescargar?.addEventListener("click", async () => {
    btnDescargar.disabled = true;
    const valor = await obtenerContenidoItem(uid, coleccion, id);
    btnDescargar.disabled = false;
    if (valor === null) return;
    descargarTexto(nombreDescarga, formatearValorParaTexto(coleccion, valor));
  });
}

// ---------- Bloque "ítem generado" (chip con Ver/Descargar) ----------

function itemGeneradoHtml({ etiqueta, coleccion, id, cantidad, nombreDescarga, enlaceVer }) {
  if (!id) return "";
  const sufijo = cantidad != null ? ` (${cantidad.toLocaleString("es")})` : "";
  // enlaceVer (solo tests hechos, ver testCardHtml): en vez de desplegar
  // el contenido en línea, "Ver" navega a la página de resultado real
  // del test -- wireItem no engancha nada especial para este botón (no
  // lleva la clase .act-item-ver), así que el toggle inline solo aplica
  // a los demás tipos de elemento.
  const botonVer = enlaceVer
    ? `<a class="act-icon-btn" href="${escapeHtml(enlaceVer)}" aria-label="Ver ${escapeHtml(etiqueta)} completo">${icono("ojo", 16)}<span>Ver</span></a>`
    : `<button type="button" class="act-icon-btn act-item-ver" aria-expanded="false" aria-label="Ver ${escapeHtml(etiqueta)} completo">${icono("ojo", 16)}<span>Ver</span></button>`;
  return `<div class="act-item" data-coleccion="${escapeHtml(coleccion)}" data-id="${escapeHtml(id)}" data-descarga="${escapeHtml(nombreDescarga)}">
    <div class="act-item-cab">
      <span class="act-item-etiqueta">${escapeHtml(etiqueta)}${sufijo}</span>
      <div class="act-item-acciones">
        ${botonVer}
        <button type="button" class="act-icon-btn act-item-descargar" aria-label="Descargar ${escapeHtml(etiqueta)}">${icono("descargar", 16)}<span>Descargar</span></button>
      </div>
    </div>
    <div class="act-item-cuerpo"></div>
  </div>`;
}

// ---------- Secciones ----------

function documentoCardHtml(d, datos) {
  const resumen = (datos.resumenes_pdf || []).find((r) => r.documento_id === d.id);
  const esquema = (datos.esquemas_pdf || []).find((r) => r.documento_id === d.id);
  const testPdf = (datos.tests_pdf || []).find((r) => r.documento_id === d.id);
  const tarjetas = (datos.tarjetas_pdf || []).find((r) => r.documento_id === d.id);
  const base = nombreArchivoSeguro(d.nombre_archivo || d.titulo);
  return `<article class="act-card">
    <header class="act-card-cab">
      <h3 class="act-card-titulo" title="${escapeHtml(d.nombre_archivo || d.titulo || "")}">${escapeHtml(d.nombre_archivo || d.titulo || "Documento")}</h3>
      <span class="act-card-fecha">${escapeHtml(fechaCorta(d.fecha_subida))}</span>
    </header>
    <p class="act-card-meta">${(d.num_paginas || 0).toLocaleString("es")} páginas</p>
    <div class="act-items-lista">
      ${itemGeneradoHtml({ etiqueta: "Texto extraído del PDF", coleccion: "documentos", id: d.id, cantidad: d.longitud_texto, nombreDescarga: `texto-${base}.txt` })}
      ${resumen ? itemGeneradoHtml({ etiqueta: "Resumen generado", coleccion: "resumenes_pdf", id: resumen.id, cantidad: resumen.longitud, nombreDescarga: `resumen-${base}.txt` }) : ""}
      ${esquema ? itemGeneradoHtml({ etiqueta: "Esquema generado", coleccion: "esquemas_pdf", id: esquema.id, cantidad: esquema.longitud, nombreDescarga: `esquema-${base}.txt` }) : ""}
      ${testPdf ? itemGeneradoHtml({ etiqueta: "Test generado desde este PDF", coleccion: "tests_pdf", id: testPdf.id, cantidad: testPdf.num_preguntas, nombreDescarga: `test-${base}.txt` }) : ""}
      ${tarjetas ? itemGeneradoHtml({ etiqueta: "Tarjetas generadas", coleccion: "tarjetas_pdf", id: tarjetas.id, cantidad: tarjetas.num_tarjetas, nombreDescarga: `tarjetas-${base}.txt` }) : ""}
    </div>
  </article>`;
}

function testCardHtml(t, uid) {
  const resumenResultado = t.estado === "en_progreso" ? "en progreso" : `${t.aciertos || 0}✅ ${t.fallos || 0}❌ ${t.blancos || 0}➖ · ${t.porcentaje_acierto ?? "–"}% · nota ${t.puntuacion_final ?? "–"}`;
  const base = nombreArchivoSeguro(`${t.tipo}-${t.oposicion}-${fechaCorta(t.fecha)}`);
  const enlaceVer = `/admin/actividad/resultado/?uid=${encodeURIComponent(uid)}&coleccion=tests&id=${encodeURIComponent(t.id)}&oposicion=${encodeURIComponent(t.oposicion || "")}&tipo=${encodeURIComponent(t.tipo || "")}&fecha=${encodeURIComponent(t.fecha || "")}`;
  return `<article class="act-card act-card-ancha">
    <header class="act-card-cab">
      <h3 class="act-card-titulo">${escapeHtml(t.tipo || "")} · ${escapeHtml(t.oposicion || "")}</h3>
      <span class="act-card-fecha">${escapeHtml(fechaCorta(t.fecha))}</span>
    </header>
    <p class="act-card-meta act-card-resultado">${escapeHtml(resumenResultado)}</p>
    <div class="act-items-lista">
      ${itemGeneradoHtml({ etiqueta: "Preguntas del test", coleccion: "tests", id: t.id, cantidad: t.num_preguntas, nombreDescarga: `test-${base}.txt`, enlaceVer })}
    </div>
  </article>`;
}

function esquemaCardHtml(e) {
  const base = nombreArchivoSeguro(`esquema-${(e.temas || []).join("-")}-${fechaCorta(e.fecha)}`);
  return `<article class="act-card">
    <header class="act-card-cab">
      <h3 class="act-card-titulo">${escapeHtml((e.temas || []).join(", ") || "Esquema")}</h3>
      <span class="act-card-fecha">${escapeHtml(fechaCorta(e.fecha))}</span>
    </header>
    <p class="act-card-meta">${escapeHtml(e.oposicion || "")}</p>
    <div class="act-items-lista">
      ${itemGeneradoHtml({ etiqueta: "Contenido del esquema", coleccion: "esquemas", id: e.id, cantidad: null, nombreDescarga: `${base}.txt` })}
    </div>
  </article>`;
}

function seccionHtml(id, icono_, titulo, contenidoHtml, vacio) {
  return `<section class="act-seccion" id="${id}">
    <h2 class="act-seccion-titulo"><span class="act-seccion-ico">${icono(icono_, 19)}</span>${titulo}</h2>
    ${contenidoHtml || `<p class="act-nota">${escapeHtml(vacio)}</p>`}
  </section>`;
}

function pintarCuerpo(uid, datos) {
  const cuerpo = document.getElementById("act-cuerpo");
  const docsHtml = (datos.documentos || []).map((d) => documentoCardHtml(d, datos)).join("");
  const testsHtml = (datos.tests || []).map((t) => testCardHtml(t, uid)).join("");
  const esquemasHtml = (datos.esquemas || []).map(esquemaCardHtml).join("");

  cuerpo.innerHTML = [
    seccionHtml("sec-documentos", "documento", "Documentos PDF", docsHtml ? `<div class="act-grid">${docsHtml}</div>` : "", "Todavía no ha subido ningún PDF."),
    seccionHtml("sec-tests", "matraz", "Tests hechos", testsHtml ? `<div class="act-lista">${testsHtml}</div>` : "", "Sin tests hechos."),
    seccionHtml("sec-esquemas", "esquema", "Esquemas (no PDF)", esquemasHtml ? `<div class="act-grid">${esquemasHtml}</div>` : "", "Sin esquemas fuera de PDF."),
  ].join("");

  cuerpo.querySelectorAll(".act-item").forEach((el) => wireItem(uid, el));

  const nav = document.getElementById("act-secciones-nav");
  const secciones = [
    { id: "sec-documentos", label: "Documentos", n: (datos.documentos || []).length },
    { id: "sec-tests", label: "Tests", n: (datos.tests || []).length },
    { id: "sec-esquemas", label: "Esquemas", n: (datos.esquemas || []).length },
  ];
  nav.innerHTML = secciones.map((s) => `<a href="#${s.id}" class="act-nav-chip">${escapeHtml(s.label)} <span>${s.n}</span></a>`).join("");
  nav.hidden = false;
}

function construirTextoCompleto(u, datos) {
  const lineas = [`=== ACTIVIDAD COMPLETA: ${u.email || u.uid} (${u.nombre || "sin nombre"}) ===`, ""];
  lineas.push(`Plan: ${u.plan} · Alta: ${fechaCorta(u.fecha_creacion)} · Última actividad: ${fechaCorta(u.ultima_actividad)}`, "");

  lineas.push("--- DOCUMENTOS PDF ---");
  if (!(datos.documentos || []).length) lineas.push("(ninguno)");
  (datos.documentos || []).forEach((d) => {
    lineas.push("", `# ${d.nombre_archivo || d.titulo} (${d.num_paginas} páginas, subido ${fechaCorta(d.fecha_subida)})`);
    if (d.texto) lineas.push(`[Texto extraído del PDF, ${d.texto.length} caracteres]`, d.texto);
    const resumen = (datos.resumenes_pdf || []).find((r) => r.documento_id === d.id);
    if (resumen) lineas.push(`[Resumen generado, ${resumen.longitud} caracteres]`, resumen.resumen);
    const esquema = (datos.esquemas_pdf || []).find((r) => r.documento_id === d.id);
    if (esquema) lineas.push(`[Esquema generado, ${esquema.longitud} caracteres]`, esquema.esquema);
    const testPdf = (datos.tests_pdf || []).find((r) => r.documento_id === d.id);
    if (testPdf) lineas.push(`[Test generado desde este PDF, ${(testPdf.preguntas || []).length} preguntas]`, formatearPreguntas(testPdf.preguntas));
    const tarjetas = (datos.tarjetas_pdf || []).find((r) => r.documento_id === d.id);
    if (tarjetas) lineas.push(`[Tarjetas generadas, ${(tarjetas.tarjetas || []).length}]`, formatearTarjetas(tarjetas.tarjetas));
  });

  lineas.push("", "--- TESTS HECHOS ---");
  if (!(datos.tests || []).length) lineas.push("(ninguno)");
  (datos.tests || []).forEach((t) => {
    lineas.push("", `# ${fechaCorta(t.fecha)} · ${t.tipo} · ${t.oposicion} · estado: ${t.estado} · ${t.aciertos}✅ ${t.fallos}❌ ${t.blancos}➖ (${t.porcentaje_acierto ?? "–"}%) · nota: ${t.puntuacion_final ?? "–"}`);
    if (t.preguntas && t.preguntas.length) lineas.push(formatearPreguntas(t.preguntas));
  });

  lineas.push("", "--- ESQUEMAS (NO PDF) ---");
  if (!(datos.esquemas || []).length) lineas.push("(ninguno)");
  (datos.esquemas || []).forEach((e) => {
    lineas.push("", `# ${fechaCorta(e.fecha)} · ${(e.temas || []).join(", ")}`, e.contenido || "");
  });

  return lineas.join("\n");
}

function pintarCabecera(u) {
  const inicial = (u.nombre || u.email || "?").trim().charAt(0).toUpperCase() || "?";
  document.getElementById("act-cabecera").innerHTML = `
    <div class="act-cabecera">
      <div class="ficha-avatar">${escapeHtml(inicial)}</div>
      <div class="ficha-id">
        <h1 class="ficha-email">${escapeHtml(u.email || "(sin email)")}</h1>
        ${u.nombre ? `<p class="ficha-nombre">${escapeHtml(u.nombre)}</p>` : ""}
        <div class="ficha-badges">
          ${fichaPlanBadge(u.plan, u.en_prueba)}
          <span class="ficha-badge ${u.email_verificado ? "ficha-badge-ok" : "ficha-badge-warn"}">${u.email_verificado ? icono("check", 13) + " Verificado" : "Sin verificar"}</span>
          ${u.bloqueado ? `<span class="ficha-badge ficha-badge-bloqueo">${icono("prohibido", 13)} Bloqueado</span>` : ""}
        </div>
        <p class="ficha-uid">UID: ${escapeHtml(u.uid)}</p>
      </div>
      <button type="button" class="age-btn age-btn-outline" id="act-descargar-todo">${icono("descargar", 16)} Descargar todo (.txt)</button>
    </div>`;
}

async function cargar(uid) {
  const u = await apiGet(`/admin/api/usuarios/${uid}`);
  document.getElementById("act-cargando-usuario").hidden = true;
  if (!u) {
    mostrarErrorPanel(document.getElementById("act-cabecera"), () => cargar(uid));
    return;
  }
  pintarCabecera(u);

  const cuerpo = document.getElementById("act-cuerpo");
  cuerpo.innerHTML = `<p class="admin-cargando">Cargando actividad…</p>`;
  const datos = await apiGet(`/admin/api/usuarios/${uid}/actividad-completa`);
  if (!datos) {
    mostrarErrorPanel(cuerpo, () => cargar(uid));
    return;
  }
  pintarCuerpo(uid, datos);

  const btn = document.getElementById("act-descargar-todo");
  const textoBoton = btn.innerHTML;
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Generando…";
    const completo = await apiGet(`/admin/api/usuarios/${uid}/actividad-completa/exportar`);
    btn.disabled = false;
    btn.innerHTML = textoBoton;
    if (!completo) return;
    descargarTexto(`actividad-${u.email || u.uid}.txt`, construirTextoCompleto(u, completo));
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  const permisos = await obtenerPermisos();
  if (!permisos.admin) {
    document.getElementById("act-no-autorizado").style.display = "block";
    marcarContenidoListo();
    return;
  }
  const uid = new URLSearchParams(location.search).get("uid");
  if (!uid) {
    document.getElementById("act-cargando-usuario").textContent = "Falta el usuario a mostrar (uid) en la URL.";
    document.getElementById("act-contenido").style.display = "block";
    marcarContenidoListo();
    return;
  }
  document.getElementById("act-contenido").style.display = "block";
  cargar(uid);
  marcarContenidoListo();
});
