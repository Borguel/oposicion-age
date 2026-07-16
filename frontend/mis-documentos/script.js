import { idToken } from "/assets/auth.js";
import { mostrarErrorGlobal } from "/assets/notificaciones.js";

const BACKEND_URL = "https://oposicion-age.onrender.com";
const NUEVA_CARPETA = "__nueva__";
// Carpeta especial que agrupa los documentos sin asignar -- no existe como
// tal en el catálogo de carpetas del backend, se calcula aquí a partir de
// qué documentos tienen "carpeta" vacío.
const SIN_CARPETA = "__sin_carpeta__";

let documentos = [];
let carpetas = [];
let carpetaActual = null; // null = viendo el listado de carpetas

function escaparHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto == null ? "" : String(texto);
  return div.innerHTML;
}

function normalizarTexto(texto) {
  return (texto || "").toString().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
}

function formatearFecha(iso) {
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat('es-ES', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(iso));
  } catch (e) {
    return "";
  }
}

function filaContenido({ label, icono, existe, cantidad, urlVer, urlGenerar, urlAleatorias, textoGenerar }) {
  const acciones = [];
  if (existe) {
    acciones.push(`<a class="documento-card-btn principal" href="${urlVer}">Ver</a>`);
    if (urlAleatorias) {
      acciones.push(`<a class="documento-card-btn" href="${urlAleatorias}">10 aleatorias</a>`);
    }
    acciones.push(`<a class="documento-card-btn" href="${urlGenerar}">Generar más</a>`);
  } else {
    acciones.push(`<a class="documento-card-btn principal" href="${urlGenerar}">${textoGenerar}</a>`);
  }
  const etiquetaCantidad = existe && cantidad ? ` (${cantidad})` : "";
  return `
    <div class="documento-card-fila">
      <span class="documento-card-fila-label">${icono} ${label}${etiquetaCantidad}</span>
      <div class="documento-card-fila-acciones">${acciones.join("")}</div>
    </div>
  `;
}

// modoCarpeta: "quitar" (dentro de una carpeta real: botón para sacarlo),
// "mover" (dentro de "Sin carpeta": select para meterlo en una), "etiqueta"
// (resultados de búsqueda: solo texto informativo, sin acción).
function seccionCarpeta(doc, modoCarpeta) {
  if (modoCarpeta === "quitar") {
    return `
      <div class="documento-card-carpeta">
        <button type="button" class="documento-card-quitar" data-id="${doc.id}">Quitar de esta carpeta</button>
      </div>
    `;
  }
  if (modoCarpeta === "mover") {
    const opciones = [
      `<option value="">Mover a una carpeta…</option>`,
      ...carpetas.map((c) => `<option value="${escaparHtml(c)}">${escaparHtml(c)}</option>`),
      `<option value="${NUEVA_CARPETA}">+ Nueva carpeta…</option>`
    ].join("");
    return `
      <div class="documento-card-carpeta">
        <select class="select-carpeta" data-id="${doc.id}">${opciones}</select>
      </div>
    `;
  }
  if (modoCarpeta === "etiqueta") {
    return `<div class="documento-card-carpeta documento-card-carpeta-etiqueta">📁 ${doc.carpeta ? escaparHtml(doc.carpeta) : "Sin carpeta"}</div>`;
  }
  return "";
}

function tarjetaDocumento(doc, modoCarpeta) {
  const nombreCorto = (doc.titulo || doc.nombre_archivo || "Documento").slice(0, 90);
  const meta = [
    doc.nombre_archivo,
    doc.num_paginas ? `${doc.num_paginas} páginas` : null,
    doc.fecha_subida ? `subido el ${formatearFecha(doc.fecha_subida)}` : null
  ].filter(Boolean).join(" · ");

  const filas = [
    filaContenido({
      label: "Resumen", icono: "📄", existe: doc.tiene_resumen,
      urlVer: `/subida-pdf-resumen/?documento_id=${doc.id}&ver=resumen`,
      urlGenerar: `/subida-pdf-resumen/?documento_id=${doc.id}`,
      textoGenerar: "Generar resumen"
    }),
    filaContenido({
      label: "Esquema", icono: "🗂️", existe: doc.tiene_esquema,
      urlVer: `/subida-pdf-esquemas/?documento_id=${doc.id}&ver=esquema`,
      urlGenerar: `/subida-pdf-esquemas/?documento_id=${doc.id}`,
      textoGenerar: "Generar esquema"
    }),
    filaContenido({
      label: "Tarjetas", icono: "🃏", existe: doc.num_tarjetas > 0, cantidad: doc.num_tarjetas,
      urlVer: `/subida-pdf-tarjetas/?documento_id=${doc.id}&ver=tarjetas&modo=todas`,
      urlAleatorias: `/subida-pdf-tarjetas/?documento_id=${doc.id}&ver=tarjetas&modo=aleatorias&cantidad=10`,
      urlGenerar: `/subida-pdf-tarjetas/?documento_id=${doc.id}`,
      textoGenerar: "Generar tarjetas"
    }),
    filaContenido({
      label: "Test", icono: "🧪", existe: doc.num_tests > 0,
      cantidad: doc.num_tests ? `${doc.num_tests} intento${doc.num_tests > 1 ? "s" : ""}` : null,
      urlVer: `/subida-pdf-generar-test/?documento_id=${doc.id}&ver=test`,
      urlGenerar: `/subida-pdf-generar-test/?documento_id=${doc.id}`,
      textoGenerar: "Generar test"
    })
  ].join("");

  return `
    <div class="documento-card" data-id="${doc.id}">
      <div class="documento-card-header">
        <div class="documento-card-icon">📘</div>
        <div>
          <p class="documento-card-titulo">${escaparHtml(nombreCorto)}</p>
          <p class="documento-card-meta">${escaparHtml(meta)}</p>
        </div>
      </div>
      ${seccionCarpeta(doc, modoCarpeta)}
      ${filas}
    </div>
  `;
}

function tarjetaCarpeta(idCarpeta, nombreMostrado, cantidad, esEspecial) {
  return `
    <button type="button" class="carpeta-tile${esEspecial ? " carpeta-tile-especial" : ""}" data-carpeta="${escaparHtml(idCarpeta)}">
      <span class="carpeta-tile-icono">${esEspecial ? "📄" : "📁"}</span>
      <span class="carpeta-tile-nombre">${escaparHtml(nombreMostrado)}</span>
      <span class="carpeta-tile-contador">${cantidad} documento${cantidad === 1 ? "" : "s"}</span>
    </button>
  `;
}

function renderizarCarpetas() {
  const grid = document.getElementById("carpetas-grid");
  const sinCarpetaCount = documentos.filter((d) => !d.carpeta).length;

  const tiles = carpetas.map((nombre) => {
    const cantidad = documentos.filter((d) => d.carpeta === nombre).length;
    return tarjetaCarpeta(nombre, nombre, cantidad, false);
  });

  if (sinCarpetaCount > 0 || carpetas.length === 0) {
    tiles.push(tarjetaCarpeta(SIN_CARPETA, "Sin carpeta", sinCarpetaCount, true));
  }

  grid.innerHTML = tiles.join("");
  grid.querySelectorAll("[data-carpeta]").forEach((boton) => {
    boton.addEventListener("click", () => abrirCarpeta(boton.dataset.carpeta));
  });
}

function renderizarDocumentosDeCarpeta() {
  const contenedor = document.getElementById("carpeta-detalle-lista");
  const esSinCarpeta = carpetaActual === SIN_CARPETA;
  const docsFiltrados = documentos.filter((d) => (esSinCarpeta ? !d.carpeta : d.carpeta === carpetaActual));

  if (docsFiltrados.length === 0) {
    contenedor.innerHTML = `<p class="documentos-carpeta-vacia">No hay documentos aquí todavía.</p>`;
    return;
  }

  contenedor.innerHTML = docsFiltrados.map((d) => tarjetaDocumento(d, esSinCarpeta ? "mover" : "quitar")).join("");

  if (esSinCarpeta) {
    contenedor.querySelectorAll(".select-carpeta").forEach((select) => {
      select.addEventListener("change", onMoverDesdeSinCarpeta);
    });
  } else {
    contenedor.querySelectorAll(".documento-card-quitar").forEach((boton) => {
      boton.addEventListener("click", () => quitarDeCarpeta(boton.dataset.id));
    });
  }
}

function abrirCarpeta(idCarpeta) {
  carpetaActual = idCarpeta;
  const esSinCarpeta = idCarpeta === SIN_CARPETA;

  document.getElementById("vista-carpetas").classList.add("hidden");
  document.getElementById("vista-carpeta-detalle").classList.remove("hidden");
  document.getElementById("carpeta-detalle-titulo").textContent = esSinCarpeta ? "Sin carpeta" : idCarpeta;
  document.getElementById("btn-eliminar-carpeta").classList.toggle("hidden", esSinCarpeta);
  document.getElementById("btn-anadir-documentos").classList.toggle("hidden", esSinCarpeta);

  renderizarDocumentosDeCarpeta();
}

function volverACarpetas() {
  carpetaActual = null;
  document.getElementById("vista-carpeta-detalle").classList.add("hidden");
  document.getElementById("vista-carpetas").classList.remove("hidden");
  renderizarCarpetas();
}

function renderizarBusqueda(query) {
  const grid = document.getElementById("carpetas-grid");
  const resultados = document.getElementById("busqueda-resultados");
  const q = normalizarTexto(query);

  if (!q) {
    grid.classList.remove("hidden");
    resultados.classList.add("hidden");
    return;
  }

  grid.classList.add("hidden");
  resultados.classList.remove("hidden");

  const encontrados = documentos.filter((d) => normalizarTexto(d.titulo || d.nombre_archivo).includes(q));
  if (encontrados.length === 0) {
    resultados.innerHTML = `<p class="documentos-carpeta-vacia">Sin resultados para "${escaparHtml(query)}".</p>`;
    return;
  }
  resultados.innerHTML = encontrados.map((d) => tarjetaDocumento(d, "etiqueta")).join("");
}

async function asignarCarpeta(documentoId, carpeta) {
  const token = await idToken();
  await fetch(`${BACKEND_URL}/documento/${documentoId}/carpeta`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ carpeta })
  });
  const doc = documentos.find((d) => d.id === documentoId);
  if (doc) doc.carpeta = carpeta;
}

async function crearCarpetaEnBackend(nombre) {
  const token = await idToken();
  const res = await fetch(`${BACKEND_URL}/carpetas-documentos`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ nombre })
  });
  const datos = await res.json();
  if (!res.ok) throw new Error(datos.error || "No se pudo crear la carpeta.");
  if (!carpetas.includes(datos.nombre)) carpetas.push(datos.nombre);
  return datos.nombre;
}

async function onMoverDesdeSinCarpeta(evento) {
  const select = evento.target;
  const documentoId = select.dataset.id;
  let nuevaCarpeta = select.value;
  if (!nuevaCarpeta) return;

  if (nuevaCarpeta === NUEVA_CARPETA) {
    const nombre = prompt('Nombre de la nueva carpeta (por ejemplo, "Tema 1"):');
    if (!nombre || !nombre.trim()) {
      renderizarDocumentosDeCarpeta();
      return;
    }
    try {
      nuevaCarpeta = await crearCarpetaEnBackend(nombre.trim());
    } catch (e) {
      mostrarErrorGlobal(e.message || "No se pudo crear la carpeta.");
      renderizarDocumentosDeCarpeta();
      return;
    }
  }

  await asignarCarpeta(documentoId, nuevaCarpeta);
  renderizarDocumentosDeCarpeta();
}

async function quitarDeCarpeta(documentoId) {
  await asignarCarpeta(documentoId, "");
  renderizarDocumentosDeCarpeta();
}

function abrirModalAnadir() {
  document.getElementById("modal-anadir-carpeta-nombre").textContent = carpetaActual;
  const candidatos = documentos.filter((d) => d.carpeta !== carpetaActual);
  const lista = document.getElementById("modal-anadir-lista");

  if (candidatos.length === 0) {
    lista.innerHTML = `<p class="documentos-modal-vacio">Todos tus documentos ya están en esta carpeta.</p>`;
  } else {
    lista.innerHTML = candidatos.map((d) => `
      <label class="documentos-modal-item">
        <input type="checkbox" value="${d.id}" />
        <span class="documentos-modal-item-titulo">${escaparHtml(d.titulo || d.nombre_archivo || "Documento")}</span>
        <span class="documentos-modal-item-carpeta">${d.carpeta ? escaparHtml(d.carpeta) : "Sin carpeta"}</span>
      </label>
    `).join("");
  }
  document.getElementById("modal-anadir-documentos").classList.remove("hidden");
}

function cerrarModalAnadir() {
  document.getElementById("modal-anadir-documentos").classList.add("hidden");
}

async function confirmarAnadirDocumentos() {
  const seleccionados = [...document.querySelectorAll("#modal-anadir-lista input:checked")].map((i) => i.value);
  cerrarModalAnadir();
  if (seleccionados.length === 0) return;
  await Promise.all(seleccionados.map((id) => asignarCarpeta(id, carpetaActual)));
  renderizarDocumentosDeCarpeta();
}

function inicializarEventos() {
  document.getElementById("btn-crear-carpeta").addEventListener("click", async () => {
    const nombre = prompt('Nombre de la nueva carpeta (por ejemplo, "Tema 1"):');
    if (!nombre || !nombre.trim()) return;
    try {
      await crearCarpetaEnBackend(nombre.trim());
      renderizarCarpetas();
    } catch (e) {
      mostrarErrorGlobal(e.message || "No se pudo crear la carpeta.");
    }
  });

  document.getElementById("btn-volver-carpetas").addEventListener("click", volverACarpetas);

  document.getElementById("btn-eliminar-carpeta").addEventListener("click", async () => {
    if (carpetaActual === SIN_CARPETA) return;
    const cantidad = documentos.filter((d) => d.carpeta === carpetaActual).length;
    const mensaje = cantidad > 0
      ? `¿Eliminar la carpeta "${carpetaActual}"? Los ${cantidad} documento${cantidad === 1 ? "" : "s"} que tiene dentro pasarán a "Sin carpeta" (no se borran).`
      : `¿Eliminar la carpeta "${carpetaActual}"?`;
    if (!confirm(mensaje)) return;

    const token = await idToken();
    await fetch(`${BACKEND_URL}/carpetas-documentos`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ nombre: carpetaActual })
    });
    documentos.forEach((d) => { if (d.carpeta === carpetaActual) d.carpeta = ""; });
    carpetas = carpetas.filter((c) => c !== carpetaActual);
    volverACarpetas();
  });

  document.getElementById("btn-anadir-documentos").addEventListener("click", abrirModalAnadir);
  document.getElementById("modal-anadir-cerrar").addEventListener("click", cerrarModalAnadir);
  document.getElementById("modal-anadir-confirmar").addEventListener("click", confirmarAnadirDocumentos);
  document.getElementById("modal-anadir-documentos").addEventListener("click", (evento) => {
    if (evento.target.id === "modal-anadir-documentos") cerrarModalAnadir();
  });

  document.getElementById("filtro-busqueda").addEventListener("input", (evento) => renderizarBusqueda(evento.target.value));
}

async function cargarDocumentos() {
  const token = await idToken();
  if (!token) {
    window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
    return;
  }
  const { protegerPagina } = await import("/assets/plan.js");
  if (!(await protegerPagina("premium"))) return;

  try {
    const res = await fetch(`${BACKEND_URL}/mis-documentos`, { headers: { Authorization: `Bearer ${token}` } });
    document.getElementById("documentos-cargando").classList.add("hidden");
    if (!res.ok) throw new Error("No se pudieron cargar tus documentos.");
    const datos = await res.json();
    documentos = datos.documentos || [];
    carpetas = datos.carpetas || [];

    if (documentos.length === 0) {
      document.getElementById("documentos-vacio").classList.remove("hidden");
      return;
    }

    document.getElementById("documentos-contenido").classList.remove("hidden");
    inicializarEventos();
    renderizarCarpetas();

    const qInicial = new URLSearchParams(window.location.search).get("q");
    if (qInicial) {
      document.getElementById("filtro-busqueda").value = qInicial;
      renderizarBusqueda(qInicial);
    }
  } catch (e) {
    document.getElementById("documentos-cargando").textContent = e.message || "No se pudieron cargar tus documentos.";
    document.getElementById("documentos-cargando").classList.remove("hidden");
  }
}

cargarDocumentos();
