import { idToken } from "/assets/auth.js";

const BACKEND_URL = "https://oposicion-age.onrender.com";
const SIN_CARPETA = "__sin_carpeta__";
const NUEVA_CARPETA = "__nueva__";

let documentos = [];

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

function opcionesCarpeta(doc, todasLasCarpetas) {
  const opciones = [`<option value="${SIN_CARPETA}" ${!doc.carpeta ? "selected" : ""}>Sin carpeta</option>`];
  todasLasCarpetas.forEach((carpeta) => {
    opciones.push(`<option value="${carpeta}" ${doc.carpeta === carpeta ? "selected" : ""}>${carpeta}</option>`);
  });
  opciones.push(`<option value="${NUEVA_CARPETA}">+ Nueva carpeta…</option>`);
  return opciones.join("");
}

function tarjetaDocumento(doc, todasLasCarpetas) {
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
          <p class="documento-card-titulo">${nombreCorto}</p>
          <p class="documento-card-meta">${meta}</p>
        </div>
      </div>
      <div class="documento-card-carpeta">
        <select class="select-carpeta" data-id="${doc.id}">
          ${opcionesCarpeta(doc, todasLasCarpetas)}
        </select>
      </div>
      ${filas}
    </div>
  `;
}

function nombreCarpetaMostrado(carpeta) {
  return carpeta ? `📁 ${carpeta}` : "📂 Sin carpeta";
}

function normalizarTexto(texto) {
  return (texto || "").toString().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
}

function renderizar(filtroCarpeta) {
  const todasLasCarpetas = [...new Set(documentos.map(d => d.carpeta).filter(Boolean))].sort();

  const selectFiltro = document.getElementById('filtro-carpeta');
  const valorPrevio = filtroCarpeta ?? selectFiltro.value ?? "";
  selectFiltro.innerHTML = [
    `<option value="">Todas las carpetas</option>`,
    ...todasLasCarpetas.map(c => `<option value="${c}">${c}</option>`),
    `<option value="${SIN_CARPETA}">Sin carpeta</option>`
  ].join("");
  selectFiltro.value = valorPrevio || "";

  const busqueda = normalizarTexto(document.getElementById('filtro-busqueda').value);

  const documentosFiltrados = documentos.filter(d => {
    if (selectFiltro.value === SIN_CARPETA && d.carpeta) return false;
    if (selectFiltro.value && selectFiltro.value !== SIN_CARPETA && d.carpeta !== selectFiltro.value) return false;
    if (busqueda && !normalizarTexto(d.titulo || d.nombre_archivo).includes(busqueda)) return false;
    return true;
  });

  // Agrupar por carpeta (las que no tienen, al final)
  const grupos = new Map();
  documentosFiltrados.forEach((doc) => {
    const clave = doc.carpeta || "";
    if (!grupos.has(clave)) grupos.set(clave, []);
    grupos.get(clave).push(doc);
  });
  const clavesOrdenadas = [...grupos.keys()].sort((a, b) => {
    if (!a) return 1;
    if (!b) return -1;
    return a.localeCompare(b);
  });

  const contenedor = document.getElementById('documentos-grupos');
  contenedor.innerHTML = clavesOrdenadas.map((clave) => {
    const docsDelGrupo = grupos.get(clave);
    return `
      <div class="documentos-grupo">
        <h2 class="documentos-grupo-titulo">${nombreCarpetaMostrado(clave)} <span class="contador">(${docsDelGrupo.length})</span></h2>
        <div class="documentos-lista">
          ${docsDelGrupo.map(d => tarjetaDocumento(d, todasLasCarpetas)).join("")}
        </div>
      </div>
    `;
  }).join("");

  contenedor.querySelectorAll('.select-carpeta').forEach((select) => {
    select.addEventListener('change', onCambiarCarpeta);
  });
}

async function onCambiarCarpeta(evento) {
  const select = evento.target;
  const documentoId = select.dataset.id;
  let nuevaCarpeta = select.value;

  if (nuevaCarpeta === NUEVA_CARPETA) {
    const nombre = prompt("Nombre de la nueva carpeta (por ejemplo, \"Tema 1\"):");
    if (!nombre || !nombre.trim()) {
      renderizar();
      return;
    }
    nuevaCarpeta = nombre.trim();
  } else if (nuevaCarpeta === SIN_CARPETA) {
    nuevaCarpeta = "";
  }

  const token = await idToken();
  if (!token) return;
  try {
    const res = await fetch(`${BACKEND_URL}/documento/${documentoId}/carpeta`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ carpeta: nuevaCarpeta })
    });
    if (!res.ok) throw new Error("No se pudo mover el documento.");
    const doc = documentos.find(d => d.id === documentoId);
    if (doc) doc.carpeta = nuevaCarpeta;
    renderizar();
  } catch (e) {
    alert(e.message || "No se pudo mover el documento.");
    renderizar();
  }
}

async function cargarDocumentos() {
  const token = await idToken();
  if (!token) {
    window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
    return;
  }

  try {
    const res = await fetch(`${BACKEND_URL}/mis-documentos`, { headers: { Authorization: `Bearer ${token}` } });
    document.getElementById('documentos-cargando').classList.add('hidden');
    if (!res.ok) throw new Error("No se pudieron cargar tus documentos.");
    const datos = await res.json();
    documentos = datos.documentos || [];

    if (documentos.length === 0) {
      document.getElementById('documentos-vacio').classList.remove('hidden');
      return;
    }

    document.getElementById('documentos-contenido').classList.remove('hidden');
    document.getElementById('filtro-carpeta').addEventListener('change', () => renderizar());

    const inputBusqueda = document.getElementById('filtro-busqueda');
    const qInicial = new URLSearchParams(window.location.search).get('q');
    if (qInicial) inputBusqueda.value = qInicial;
    inputBusqueda.addEventListener('input', () => renderizar());

    renderizar();
  } catch (e) {
    document.getElementById('documentos-cargando').textContent = e.message || "No se pudieron cargar tus documentos.";
    document.getElementById('documentos-cargando').classList.remove('hidden');
  }
}

cargarDocumentos();
