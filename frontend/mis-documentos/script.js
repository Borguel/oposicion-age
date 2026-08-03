import { idToken, marcarContenidoListo } from "/assets/auth.js";
import { mostrarErrorGlobal } from "/assets/notificaciones.js";
import { icono } from "/assets/icons.js";

const BACKEND_URL = "https://oposicion-age.onrender.com";
const NUEVA_CARPETA = "__nueva__";
// Carpeta especial que agrupa los documentos sin asignar -- no existe como
// tal en el catálogo de carpetas del backend, se calcula aquí a partir de
// qué documentos tienen "carpeta" vacío.
const SIN_CARPETA = "__sin_carpeta__";

document.querySelectorAll("[data-icon]").forEach((el) => {
  el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 24));
});

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

function filaContenido({ label, iconoHtml, existe, cantidad, urlVer, urlGenerar, urlAleatorias, textoGenerar, urlContinuar }) {
  const acciones = [];
  // "Continuar" (test autoguardado sin terminar, ver
  // obtener_tests_en_progreso_por_documento en documentos_pdf.py) se
  // ofrece SIEMPRE que exista, incluso si todavía no hay ningún test
  // finalizado de este documento -- antes, un test empezado y no acabado
  // no aparecía por ningún sitio en la biblioteca, solo "Ver"/"Generar
  // más" (que dependen de haber finalizado al menos uno) o "Generar test"
  // desde cero.
  if (urlContinuar) {
    acciones.push(`<a class="documento-card-btn principal" href="${urlContinuar}">Continuar</a>`);
  }
  if (existe) {
    acciones.push(`<a class="documento-card-btn${urlContinuar ? "" : " principal"}" href="${urlVer}">Ver</a>`);
    if (urlAleatorias) {
      acciones.push(`<a class="documento-card-btn" href="${urlAleatorias}">10 aleatorias</a>`);
    }
    acciones.push(`<a class="documento-card-btn" href="${urlGenerar}">Generar más</a>`);
  } else {
    acciones.push(`<a class="documento-card-btn${urlContinuar ? "" : " principal"}" href="${urlGenerar}">${textoGenerar}</a>`);
  }
  const etiquetaCantidad = existe && cantidad ? ` (${cantidad})` : "";
  return `
    <div class="documento-card-fila">
      <span class="documento-card-fila-label">${iconoHtml} ${label}${etiquetaCantidad}</span>
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
    return `<div class="documento-card-carpeta documento-card-carpeta-etiqueta">${icono("carpeta", 16)} ${doc.carpeta ? escaparHtml(doc.carpeta) : "Sin carpeta"}</div>`;
  }
  return "";
}

// Banco de preguntas/tarjetas pre-generado (03/08/2026): a diferencia de
// las filas "Tarjetas"/"Test" de arriba (una sesión concreta ya generada
// y guardada), esto es un POOL generado en segundo plano hasta agotar el
// contenido distinto del documento (ver generar_banco_preguntas_
// adaptativo/generar_banco_tarjetas_adaptativo en el backend), del que el
// usuario puede sacar tantas veces como quiera un test/repaso de tamaño
// N o de todo lo generado, sin volver a gastar en IA cada vez.
function filaBanco(doc, tipo) {
  const estado = doc[`banco_${tipo}_estado`];
  const total = doc[`banco_${tipo}_total`] || 0;
  const esPreguntas = tipo === "preguntas";
  const label = esPreguntas ? "Banco de preguntas" : "Banco de tarjetas";
  const nombreItem = esPreguntas ? "pregunta" : "tarjeta";
  const iconoHtml = icono(esPreguntas ? "matraz" : "tarjeta", 16);
  const rutaPractica = esPreguntas ? "/subida-pdf-generar-test/" : "/subida-pdf-tarjetas/";
  const paramVer = esPreguntas ? "banco" : "banco-tarjetas";
  const etiquetaAccion = esPreguntas ? "Test" : "Repasar";

  const acciones = [];
  if (!estado || estado === "sin_generar") {
    acciones.push(`<button type="button" class="documento-card-btn principal" data-banco-generar="${tipo}" data-id="${doc.id}">Generar banco de ${tipo}</button>`);
  } else {
    if (estado === "generando") {
      // Sin el tope interno (antes "1/100"): el usuario no tiene por qué
      // saber cuál es el techo de seguridad del banco, solo cuántas lleva
      // generadas hasta ahora -- este número se actualiza en vivo según
      // van llegando eventos de progreso (ver iniciarBanco).
      acciones.push(`<span class="documento-card-banco-estado">Generando… ${total} ${nombreItem}${total === 1 ? "" : "s"} hasta ahora</span>`);
    } else if (estado === "completo") {
      // Aviso explícito de que la generación YA terminó (03/08/2026, a
      // petición del usuario: antes, al pasar de "generando" a completo,
      // no había ninguna señal clara de que el sistema hubiera acabado de
      // trabajar -- solo aparecían los botones de practicar, fáciles de
      // confundir con "sigue generando").
      acciones.push(`<span class="documento-card-banco-estado documento-card-banco-completo">${icono("check", 14)} ${total} ${nombreItem}${total === 1 ? "" : "s"} generada${total === 1 ? "" : "s"}</span>`);
    } else if (estado === "error") {
      acciones.push(`<span class="documento-card-banco-estado documento-card-banco-error">No se pudo generar</span>`);
      acciones.push(`<button type="button" class="documento-card-btn" data-banco-generar="${tipo}" data-id="${doc.id}">Reintentar</button>`);
    }
    if (total > 0) {
      if (total > 1) {
        // Cantidad libre (03/08/2026, a petición del usuario: antes era un
        // botón fijo "de 10") -- el usuario elige cuántas de las "total"
        // disponibles quiere en esta sesión, entre 1 y el total del banco.
        acciones.push(`
          <span class="documento-card-banco-cantidad">
            <input type="number" class="documento-card-banco-input" min="1" max="${total}"
                   value="${Math.min(10, total)}" data-banco-cantidad="${tipo}"
                   aria-label="Cantidad de ${label.toLowerCase()}">
            <button type="button" class="documento-card-btn" data-banco-empezar="${tipo}" data-id="${doc.id}">${etiquetaAccion}</button>
          </span>
        `);
      }
      acciones.push(`<a class="documento-card-btn${estado === "completo" ? " principal" : ""}" href="${rutaPractica}?documento_id=${doc.id}&ver=${paramVer}">${etiquetaAccion} de todas (${total})</a>`);
    }
  }

  // Sin el tope interno en la etiqueta tampoco -- mismo motivo que arriba.
  const etiquetaCantidad = total > 0 ? ` (${total})` : "";
  return `
    <div class="documento-card-fila">
      <span class="documento-card-fila-label">${iconoHtml} ${label}${etiquetaCantidad}</span>
      <div class="documento-card-fila-acciones">${acciones.join("")}</div>
    </div>
  `;
}

// Lee la cantidad elegida en el input de al lado del botón pulsado (dentro
// de la misma fila de acciones) y navega a la herramienta correspondiente
// pidiendo un test/repaso de ese tamaño sobre el banco ya generado.
function irABanco(evento, documentoId, tipo) {
  const fila = evento.currentTarget.closest(".documento-card-fila-acciones");
  const input = fila?.querySelector("input[data-banco-cantidad]");
  const doc = documentos.find((d) => d.id === documentoId);
  const total = doc ? (doc[`banco_${tipo}_total`] || 0) : 0;
  let cantidad = parseInt(input?.value, 10);
  if (!Number.isFinite(cantidad) || cantidad < 1) cantidad = 1;
  if (total && cantidad > total) cantidad = total;
  const rutaPractica = tipo === "preguntas" ? "/subida-pdf-generar-test/" : "/subida-pdf-tarjetas/";
  const paramVer = tipo === "preguntas" ? "banco" : "banco-tarjetas";
  window.location.href = `${rutaPractica}?documento_id=${documentoId}&ver=${paramVer}&cantidad=${cantidad}`;
}

async function iniciarBanco(documentoId, tipo) {
  const doc = documentos.find((d) => d.id === documentoId);
  if (doc) doc[`banco_${tipo}_estado`] = "generando";
  const refrescar = () => {
    if (carpetaActual !== null) renderizarDocumentosDeCarpeta();
    const query = document.getElementById("filtro-busqueda")?.value;
    if (query) renderizarBusqueda(query);
  };
  refrescar();

  try {
    const token = await idToken();
    const ruta = tipo === "preguntas" ? "generar-banco-preguntas-desde-pdf" : "generar-banco-tarjetas-desde-pdf";
    const formData = new FormData();
    formData.append("documento_id", documentoId);
    const res = await fetch(`${BACKEND_URL}/${ruta}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData
    });
    if (!res.ok || !res.body) {
      const datos = await res.json().catch(() => ({}));
      throw new Error(datos.error || "No se pudo iniciar la generación del banco.");
    }

    const lector = res.body.getReader();
    const decodificador = new TextDecoder();
    let buffer = "";
    let terminado = false;
    while (!terminado) {
      const { done, value } = await lector.read();
      if (done) break;
      buffer += decodificador.decode(value, { stream: true });
      const bloques = buffer.split("\n\n");
      buffer = bloques.pop();
      for (const bloque of bloques) {
        const linea = bloque.trim();
        if (!linea.startsWith("data: ")) continue;
        let evento;
        try { evento = JSON.parse(linea.slice(6)); } catch { continue; }
        if (evento.tipo === "progreso") {
          if (doc) {
            doc[`banco_${tipo}_total`] = evento.completadas;
            doc[`banco_${tipo}_objetivo`] = evento.objetivo;
          }
          refrescar();
        } else if (evento.tipo === "fin") {
          terminado = true;
          if (doc) {
            doc[`banco_${tipo}_total`] = evento.total ?? doc[`banco_${tipo}_total`];
            doc[`banco_${tipo}_estado`] = evento.total ? "completo" : "error";
          }
        }
      }
    }
  } catch (e) {
    if (doc) doc[`banco_${tipo}_estado`] = "error";
    mostrarErrorGlobal(e.message || "No se pudo generar el banco.");
  } finally {
    refrescar();
  }
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
      label: "Resumen", iconoHtml: icono("documento", 16), existe: doc.tiene_resumen,
      urlVer: `/subida-pdf-resumen/?documento_id=${doc.id}&ver=resumen`,
      urlGenerar: `/subida-pdf-resumen/?documento_id=${doc.id}`,
      textoGenerar: "Generar resumen"
    }),
    filaContenido({
      label: "Esquema", iconoHtml: icono("esquema", 16), existe: doc.tiene_esquema,
      urlVer: `/subida-pdf-esquemas/?documento_id=${doc.id}&ver=esquema`,
      urlGenerar: `/subida-pdf-esquemas/?documento_id=${doc.id}`,
      textoGenerar: "Generar esquema"
    }),
    filaContenido({
      label: "Tarjetas", iconoHtml: icono("tarjeta", 16), existe: doc.num_tarjetas > 0, cantidad: doc.num_tarjetas,
      urlVer: `/subida-pdf-tarjetas/?documento_id=${doc.id}&ver=tarjetas&modo=todas`,
      urlAleatorias: `/subida-pdf-tarjetas/?documento_id=${doc.id}&ver=tarjetas&modo=aleatorias&cantidad=10`,
      urlGenerar: `/subida-pdf-tarjetas/?documento_id=${doc.id}`,
      textoGenerar: "Generar tarjetas"
    }),
    filaContenido({
      label: "Test", iconoHtml: icono("matraz", 16), existe: doc.num_tests > 0,
      cantidad: doc.num_tests ? `${doc.num_tests} intento${doc.num_tests > 1 ? "s" : ""}` : null,
      urlVer: `/subida-pdf-generar-test/?documento_id=${doc.id}&ver=test`,
      urlGenerar: `/subida-pdf-generar-test/?documento_id=${doc.id}`,
      urlContinuar: doc.test_en_progreso ? `/subida-pdf-generar-test/?resume=${doc.test_en_progreso}` : null,
      textoGenerar: "Generar test"
    }),
    filaBanco(doc, "preguntas"),
    filaBanco(doc, "tarjetas")
  ].join("");

  return `
    <div class="documento-card" data-id="${doc.id}">
      <div class="documento-card-header">
        <div class="documento-card-icon">${icono("libro", 26)}</div>
        <div>
          <p class="documento-card-titulo">
            ${escaparHtml(nombreCorto)}
            <button type="button" class="documento-card-renombrar" data-id="${doc.id}" aria-label="Renombrar documento" title="Renombrar documento">${icono("lapiz", 14)}</button>
            <button type="button" class="documento-card-eliminar" data-id="${doc.id}" aria-label="Eliminar documento" title="Eliminar documento">${icono("papelera", 14)}</button>
          </p>
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
      <span class="carpeta-tile-icono">${esEspecial ? icono("documento", 26) : icono("carpeta", 26)}</span>
      <span class="carpeta-tile-nombre">${escaparHtml(nombreMostrado)}</span>
      <span class="carpeta-tile-contador">${cantidad} documento${cantidad === 1 ? "" : "s"}</span>
    </button>
  `;
}

// Un documento sin carpeta se muestra directamente con su propio nombre
// (no agrupado detrás de una única tarjeta genérica "Sin carpeta"), con
// "Sin carpeta" como subtítulo -- así se ve de un vistazo de qué documento
// se trata sin tener que entrar. Sigue llevando a la misma vista de "Sin
// carpeta" al pulsarlo (donde puede moverse a una carpeta real).
function tarjetaDocumentoSuelto(doc) {
  const nombre = (doc.titulo || doc.nombre_archivo || "Documento").slice(0, 60);
  return `
    <button type="button" class="carpeta-tile carpeta-tile-especial" data-carpeta="${SIN_CARPETA}">
      <span class="carpeta-tile-icono">${icono("documento", 26)}</span>
      <span class="carpeta-tile-nombre">${escaparHtml(nombre)}</span>
      <span class="carpeta-tile-contador">Sin carpeta</span>
    </button>
  `;
}

function renderizarCarpetas() {
  const grid = document.getElementById("carpetas-grid");
  const sinCarpetaDocs = documentos.filter((d) => !d.carpeta);

  const tiles = carpetas.map((nombre) => {
    const cantidad = documentos.filter((d) => d.carpeta === nombre).length;
    return tarjetaCarpeta(nombre, nombre, cantidad, false);
  });

  sinCarpetaDocs.forEach((doc) => tiles.push(tarjetaDocumentoSuelto(doc)));

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
  contenedor.querySelectorAll(".documento-card-renombrar").forEach((boton) => {
    boton.addEventListener("click", () => renombrarDocumento(boton.dataset.id));
  });
  contenedor.querySelectorAll(".documento-card-eliminar").forEach((boton) => {
    boton.addEventListener("click", () => eliminarDocumento(boton.dataset.id));
  });
  contenedor.querySelectorAll("[data-banco-generar]").forEach((boton) => {
    boton.addEventListener("click", () => iniciarBanco(boton.dataset.id, boton.dataset.bancoGenerar));
  });
  contenedor.querySelectorAll("[data-banco-empezar]").forEach((boton) => {
    boton.addEventListener("click", (evento) => irABanco(evento, boton.dataset.id, boton.dataset.bancoEmpezar));
  });
  contenedor.querySelectorAll("input[data-banco-cantidad]").forEach((input) => {
    input.addEventListener("keydown", (evento) => {
      if (evento.key !== "Enter") return;
      evento.target.closest(".documento-card-fila-acciones")?.querySelector("[data-banco-empezar]")?.click();
    });
  });
}

async function renombrarDocumento(documentoId) {
  const doc = documentos.find((d) => d.id === documentoId);
  if (!doc) return;
  const nuevoNombre = prompt("Nuevo nombre del documento:", doc.titulo || doc.nombre_archivo || "");
  if (nuevoNombre === null) return;
  const limpio = nuevoNombre.trim();
  if (!limpio) return;
  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/documento/${documentoId}/titulo`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ titulo: limpio })
    });
    const datos = await res.json();
    if (!res.ok) throw new Error(datos.error || "No se pudo renombrar el documento.");
    doc.titulo = datos.titulo || limpio;
    if (carpetaActual !== null) renderizarDocumentosDeCarpeta();
    const query = document.getElementById("filtro-busqueda")?.value;
    if (query) renderizarBusqueda(query);
  } catch (e) {
    mostrarErrorGlobal(e.message || "No se pudo renombrar el documento.");
  }
}

async function eliminarDocumento(documentoId) {
  const doc = documentos.find((d) => d.id === documentoId);
  if (!doc) return;
  const nombre = doc.titulo || doc.nombre_archivo || "este documento";
  // No borra en cascada lo ya generado a partir de él (ver
  // documentos_pdf.eliminar_documento) -- se avisa para que no se
  // interprete como "esto borra también mis tests/resúmenes".
  const confirmado = confirm(
    `¿Eliminar "${nombre}" de tu biblioteca? Los resúmenes, esquemas, tarjetas o tests que ya hubieras generado a partir de él no se borran, pero dejarán de aparecer agrupados aquí.`
  );
  if (!confirmado) return;
  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/documento/${documentoId}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` }
    });
    const datos = await res.json();
    if (!res.ok) throw new Error(datos.error || "No se pudo eliminar el documento.");
    documentos = documentos.filter((d) => d.id !== documentoId);
    if (carpetaActual !== null) renderizarDocumentosDeCarpeta();
    const query = document.getElementById("filtro-busqueda")?.value;
    if (query) renderizarBusqueda(query);
  } catch (e) {
    mostrarErrorGlobal(e.message || "No se pudo eliminar el documento.");
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
  resultados.querySelectorAll(".documento-card-renombrar").forEach((boton) => {
    boton.addEventListener("click", () => renombrarDocumento(boton.dataset.id));
  });
  resultados.querySelectorAll(".documento-card-eliminar").forEach((boton) => {
    boton.addEventListener("click", () => eliminarDocumento(boton.dataset.id));
  });
  resultados.querySelectorAll("[data-banco-generar]").forEach((boton) => {
    boton.addEventListener("click", () => iniciarBanco(boton.dataset.id, boton.dataset.bancoGenerar));
  });
  resultados.querySelectorAll("[data-banco-empezar]").forEach((boton) => {
    boton.addEventListener("click", (evento) => irABanco(evento, boton.dataset.id, boton.dataset.bancoEmpezar));
  });
  resultados.querySelectorAll("input[data-banco-cantidad]").forEach((input) => {
    input.addEventListener("keydown", (evento) => {
      if (evento.key !== "Enter") return;
      evento.target.closest(".documento-card-fila-acciones")?.querySelector("[data-banco-empezar]")?.click();
    });
  });
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

// Sondeo del progreso de bancos en generación (03/08/2026): cuando se
// llega aquí redirigido desde "Subir PDF" (ver subida-pdf-generar-test/
// subida-pdf-tarjetas), la conexión SSE que iba retransmitiendo el
// progreso se queda en la página anterior -- se pierde al navegar. Para
// que el contador siga actualizándose SOLO, sin que el usuario tenga que
// refrescar a mano, se vuelve a pedir /mis-documentos cada pocos segundos
// mientras algún banco siga "generando", y se para en cuanto no quede
// ninguno.
let temporizadorSondeoBancos = null;

function hayBancosGenerando() {
  return documentos.some((d) => d.banco_preguntas_estado === "generando" || d.banco_tarjetas_estado === "generando");
}

function detenerSondeoBancos() {
  if (temporizadorSondeoBancos) {
    clearTimeout(temporizadorSondeoBancos);
    temporizadorSondeoBancos = null;
  }
}

async function sondearBancosEnGeneracion() {
  temporizadorSondeoBancos = null;
  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/mis-documentos`, { headers: { Authorization: `Bearer ${token}` } });
    if (res.ok) {
      const datos = await res.json();
      const porId = new Map((datos.documentos || []).map((d) => [d.id, d]));
      documentos.forEach((doc) => {
        const actualizado = porId.get(doc.id);
        if (!actualizado) return;
        doc.banco_preguntas_estado = actualizado.banco_preguntas_estado;
        doc.banco_preguntas_total = actualizado.banco_preguntas_total;
        doc.banco_preguntas_objetivo = actualizado.banco_preguntas_objetivo;
        doc.banco_tarjetas_estado = actualizado.banco_tarjetas_estado;
        doc.banco_tarjetas_total = actualizado.banco_tarjetas_total;
        doc.banco_tarjetas_objetivo = actualizado.banco_tarjetas_objetivo;
      });
      if (carpetaActual !== null) renderizarDocumentosDeCarpeta();
      const query = document.getElementById("filtro-busqueda")?.value;
      if (query) renderizarBusqueda(query);
    }
  } catch (e) {
    // Sondeo silencioso: un fallo puntual (red, token) no debe interrumpir
    // nada -- se reintenta en el siguiente ciclo mientras siga haciendo falta.
  }
  iniciarSondeoBancosSiHaceFalta();
}

function iniciarSondeoBancosSiHaceFalta() {
  if (temporizadorSondeoBancos || !hayBancosGenerando()) return;
  temporizadorSondeoBancos = setTimeout(sondearBancosEnGeneracion, 4000);
}

// Llegada desde "Subir PDF" con ?destacar=<documento_id> (03/08/2026): en
// vez de dejar al usuario buscando en qué carpeta cayó el documento recién
// subido, se abre directamente la vista donde está (o "Sin carpeta") y se
// resalta su tarjeta un momento, para que sea evidente de un vistazo dónde
// seguir el progreso de su banco.
function destacarDocumentoDesdeUrl() {
  const id = new URLSearchParams(window.location.search).get("destacar");
  if (!id) return;
  const doc = documentos.find((d) => d.id === id);
  if (!doc) return;
  abrirCarpeta(doc.carpeta || SIN_CARPETA);
  requestAnimationFrame(() => {
    const tarjeta = document.querySelector(`.documento-card[data-id="${CSS.escape(id)}"]`);
    if (!tarjeta) return;
    tarjeta.scrollIntoView({ behavior: "smooth", block: "center" });
    tarjeta.classList.add("documento-card-destacada");
    setTimeout(() => tarjeta.classList.remove("documento-card-destacada"), 3000);
  });
}

async function cargarDocumentos() {
  const token = await idToken();
  if (!token) {
    window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
    return;
  }
  const { protegerPagina } = await import("/assets/plan.js");
  if (!(await protegerPagina("premium"))) {
    marcarContenidoListo();
    return;
  }

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
    } else {
      destacarDocumentoDesdeUrl();
    }
    iniciarSondeoBancosSiHaceFalta();
  } catch (e) {
    document.getElementById("documentos-cargando").textContent = e.message || "No se pudieron cargar tus documentos.";
    document.getElementById("documentos-cargando").classList.remove("hidden");
  } finally {
    marcarContenidoListo();
  }
}

cargarDocumentos();
