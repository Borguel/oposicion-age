import { icono } from "/assets/icons.js";

async function obtenerAuthHeaders() {
  const { obtenerAuthHeaders: fn } = await import("/assets/auth.js");
  return fn();
}

document.querySelectorAll("[data-icon]").forEach((el) => {
  el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 24));
});

let oposicionActual = "";
let todosLosTemas = [];
// Bloque + numeración (romano/arábigo) de cada tema, para poder mostrar
// "Bloque II · Tema 3: ..." bajo cada pregunta -- se calcula una vez al
// cargar los temas, igual que en Estadísticas.
let infoTemasPorId = new Map();
// Cache por pestaña: se pide una sola vez a cada endpoint y el filtro de
// tema se aplica en el cliente sobre lo ya descargado.
const cache = { favoritas: null, falladas: null };
let pestañaActual = "favoritas";

const elLista = document.getElementById("rp-lista");
const elAviso = document.getElementById("rp-aviso");
const elCargando = document.getElementById("rp-cargando");
const elFiltroTema = document.getElementById("rp-filtro-tema");

function mostrarAviso(texto) {
  elAviso.innerHTML = texto;
  elAviso.style.display = "block";
}

function ocultarAviso() {
  elAviso.style.display = "none";
}

function infoTema(temaId) {
  return infoTemasPorId.get(temaId) || null;
}

async function cargarTemas() {
  try {
    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;
    const { obtenerOposicionActual } = await import("/assets/oposicion.js");
    oposicionActual = obtenerOposicionActual();
    const res = await fetch(`https://oposicion-age.onrender.com/temas-disponibles?oposicion=${encodeURIComponent(oposicionActual)}`, { headers: authHeaders });
    const datos = await res.json();
    todosLosTemas = datos.temas || [];
    todosLosTemas.forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t.id;
      opt.textContent = t.titulo;
      elFiltroTema.appendChild(opt);
    });

    const { agruparTemasPorBloque } = await import("/assets/temas-numeracion.js");
    infoTemasPorId = new Map();
    agruparTemasPorBloque(todosLosTemas).forEach((grupo) => {
      grupo.temas.forEach((t) => {
        infoTemasPorId.set(t.id, {
          numeroRomano: grupo.numeroRomano,
          bloqueTitulo: grupo.titulo,
          numeroTema: t.numeroTema,
          titulo: t.titulo,
        });
      });
    });
  } catch (err) {
    console.error("Error cargando temas:", err);
  }
}

async function obtenerLista(tipo) {
  if (cache[tipo]) return cache[tipo];
  const authHeaders = await obtenerAuthHeaders();
  if (!authHeaders) return [];
  const endpoint = tipo === "favoritas" ? "preguntas-favoritas" : "preguntas-falladas";
  const res = await fetch(`https://oposicion-age.onrender.com/${endpoint}?oposicion=${encodeURIComponent(oposicionActual)}`, { headers: authHeaders });
  if (!res.ok) return [];
  const datos = await res.json();
  const lista = datos[tipo] || [];
  cache[tipo] = lista;
  return lista;
}

function tarjetaHTML(pregunta, tipo, indice) {
  const opcionesHTML = Object.entries(pregunta.opciones || {}).map(([letra, texto]) => `
    <div class="rp-opcion" data-letra="${letra}">
      <span class="rp-opcion-letra">${letra}</span>
      <span class="rp-opcion-texto">${escaparHtml(texto)}</span>
    </div>
  `).join("");

  const tema = infoTema(pregunta.tema_id);
  const badgeFallos = tipo === "falladas"
    ? `<span class="rp-badge-fallos" title="Veces que has fallado esta pregunta">${pregunta.veces_fallada || 1}</span>`
    : "";
  const botonQuitar = tipo === "favoritas"
    ? `<button type="button" class="rp-btn-quitar" data-quitar="${indice}" title="Quitar de favoritas">${icono("papelera", 15)} Quitar</button>`
    : "";
  // El tema empieza plegado (solo un botón "Ver tema") para no alargar cada
  // tarjeta con un texto que a veces es largo -- quien quiera verlo lo abre.
  const temaHTML = tema ? `
    <div class="rp-tema-bloque">
      <button type="button" class="rp-tema-toggle" data-tema-toggle aria-expanded="false">
        <span class="rp-tema-chevron">▾</span> Ver tema
      </button>
      <div class="rp-tema-panel" style="display:none;">
        <div class="rp-tema-linea">Bloque ${tema.numeroRomano}: ${escaparHtml(tema.bloqueTitulo)}</div>
        <div class="rp-tema-linea">Tema ${tema.numeroTema}: ${escaparHtml(tema.titulo)}</div>
      </div>
    </div>
  ` : "";

  return `
    <div class="rp-tarjeta" data-indice="${indice}">
      <div class="rp-tarjeta-cabecera">
        ${badgeFallos}
        <div class="rp-tarjeta-pregunta">${escaparHtml(pregunta.pregunta)}</div>
      </div>
      ${temaHTML}
      <div class="rp-opciones">${opcionesHTML}</div>
      <div class="rp-tarjeta-acciones">
        <button type="button" class="rp-btn-ver-respuesta" data-ver="${indice}">${icono("ojo", 15)} Ver respuesta correcta</button>
        ${botonQuitar}
      </div>
      <div class="rp-respuesta-panel" style="display:none;">
        <p class="rp-respuesta-correcta"><strong>Respuesta correcta:</strong> ${escaparHtml(pregunta.respuesta_correcta || "No indicada")}) ${escaparHtml((pregunta.opciones || {})[pregunta.respuesta_correcta] || "")}</p>
        <p class="rp-explicacion"><strong>Explicación:</strong> ${escaparHtml(pregunta.explicacion || "Sin explicación.")}</p>
      </div>
    </div>
  `;
}

function escaparHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto ?? "";
  return div.innerHTML;
}

async function pintarPestaña() {
  ocultarAviso();
  elLista.innerHTML = "";
  elCargando.style.display = "block";

  const lista = await obtenerLista(pestañaActual);
  elCargando.style.display = "none";

  const temaFiltro = elFiltroTema.value;
  const listaFiltrada = temaFiltro ? lista.filter((p) => p.tema_id === temaFiltro) : lista;

  if (listaFiltrada.length === 0) {
    const mensajeVacio = pestañaActual === "favoritas"
      ? `No tienes preguntas favoritas marcadas${temaFiltro ? " en este tema" : ""}. Marca la estrella ${icono("estrella", 14)} durante cualquier test para guardarlas aquí.`
      : `No tienes preguntas falladas pendientes${temaFiltro ? " en este tema" : ""}. ¡Buen trabajo!`;
    mostrarAviso(mensajeVacio);
    return;
  }

  elLista.innerHTML = listaFiltrada.map((p, i) => tarjetaHTML(p, pestañaActual, i)).join("");

  elLista.querySelectorAll("[data-tema-toggle]").forEach((boton) => {
    boton.addEventListener("click", () => {
      const panel = boton.nextElementSibling;
      const abierto = panel.style.display !== "none";
      panel.style.display = abierto ? "none" : "block";
      boton.setAttribute("aria-expanded", String(!abierto));
      boton.innerHTML = `<span class="rp-tema-chevron">${abierto ? "▾" : "▴"}</span> ${abierto ? "Ver tema" : "Ocultar tema"}`;
    });
  });

  elLista.querySelectorAll("[data-ver]").forEach((boton) => {
    boton.addEventListener("click", () => {
      const tarjeta = boton.closest(".rp-tarjeta");
      const panel = tarjeta.querySelector(".rp-respuesta-panel");
      const indice = Number(boton.dataset.ver);
      const pregunta = listaFiltrada[indice];
      const abierto = panel.style.display !== "none";
      panel.style.display = abierto ? "none" : "block";
      boton.innerHTML = abierto ? `${icono("ojo", 15)} Ver respuesta correcta` : `${icono("ojo", 15)} Ocultar respuesta`;
      if (!abierto) {
        tarjeta.querySelectorAll(".rp-opcion").forEach((op) => {
          op.classList.toggle("rp-opcion-correcta", op.dataset.letra === pregunta.respuesta_correcta);
        });
      }
    });
  });

  elLista.querySelectorAll("[data-quitar]").forEach((boton) => {
    boton.addEventListener("click", async () => {
      const indice = Number(boton.dataset.quitar);
      const pregunta = listaFiltrada[indice];
      boton.disabled = true;
      try {
        const { desmarcarFavorita } = await import("/assets/favoritas.js");
        const ok = await desmarcarFavorita(pregunta.pregunta, oposicionActual);
        if (!ok) {
          boton.disabled = false;
          return;
        }
        cache.favoritas = (cache.favoritas || []).filter((p) => p.pregunta !== pregunta.pregunta);
        pintarPestaña();
      } catch (err) {
        console.error("Error quitando de favoritas:", err);
        boton.disabled = false;
      }
    });
  });
}

document.querySelectorAll(".rp-tab").forEach((boton) => {
  boton.addEventListener("click", () => {
    if (boton.dataset.tab === pestañaActual) return;
    document.querySelectorAll(".rp-tab").forEach((b) => {
      b.classList.remove("activa");
      b.setAttribute("aria-selected", "false");
    });
    boton.classList.add("activa");
    boton.setAttribute("aria-selected", "true");
    pestañaActual = boton.dataset.tab;
    pintarPestaña();
  });
});

elFiltroTema.addEventListener("change", pintarPestaña);

window.addEventListener("load", async () => {
  const { protegerPagina } = await import("/assets/plan.js");
  if (!(await protegerPagina("basico"))) return;
  await cargarTemas();
  pintarPestaña();
});
