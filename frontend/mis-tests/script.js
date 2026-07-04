import { idToken } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";

const TIPO_INFO = {
  personalizado: { icono: "📝", label: "Personalizado" },
  oficial: { icono: "🏛️", label: "Oficial" },
  inteligente: { icono: "🤖", label: "Inteligente IA" },
  repetido: { icono: "🔁", label: "Repetido" },
  falladas: { icono: "❌", label: "Preguntas falladas" },
};

const PAGINA_POR_TIPO = {
  personalizado: "/test-generator/",
  oficial: "/test-generator/",
  inteligente: "/test-generator/",
  repetido: "/repetir-test/",
  falladas: "/preguntas-falladas/",
};

let tests = [];
let temasPorId = new Map();
let filtroEstado = "";

function tipoInfo(tipo) {
  return TIPO_INFO[tipo] || { icono: "🧪", label: tipo || "Test" };
}

function formatearFecha(iso) {
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
  } catch (e) {
    return "";
  }
}

// Los títulos de tema oficiales pueden ser largos; se acortan para que la
// tarjeta no se estire, igual que ya se hace en la tabla de resultados.
function acortarTitulo(titulo, maxLength = 42) {
  if (!titulo || titulo.length <= maxLength) return titulo || "";
  return titulo.slice(0, maxLength - 1).trim() + "…";
}

function pillsTemas(temaIds) {
  if (!temaIds || !temaIds.length) return "";
  return `<div class="test-card-temas">${temaIds.map((id) => {
    const titulo = temasPorId.get(id) || id;
    return `<span class="age-pill">${acortarTitulo(titulo)}</span>`;
  }).join("")}</div>`;
}

function tarjetaTest(t) {
  const info = tipoInfo(t.tipo);
  const pagina = PAGINA_POR_TIPO[t.tipo] || "/test-generator/";
  const partes = [`${t.num_preguntas || 0} pregunta${(t.num_preguntas || 0) !== 1 ? "s" : ""}`];
  if (t.fecha) partes.push(formatearFecha(t.fecha));

  let bloqueEstado;
  let acciones;
  if (t.estado === "en_progreso") {
    const vistas = (t.indice_actual || 0) + 1;
    bloqueEstado = `<span class="age-pill age-pill-primary">🕐 En progreso — pregunta ${vistas}/${t.num_preguntas || "?"}</span>`;
    acciones = `<a class="age-btn age-btn-primary" href="${pagina}?resume=${t.id}">Continuar</a>`;
  } else {
    const aprobado = t.resultado === "aprobado";
    bloqueEstado = `
      <span class="age-pill ${aprobado ? "age-pill-success" : "age-pill-danger"}">${aprobado ? "✅ Aprobado" : "❌ Suspendido"}</span>
      <span class="age-pill">${t.porcentaje_acierto ?? 0}% acierto</span>
    `;
    acciones = `
      <a class="age-btn age-btn-outline" href="/repetir-test/?repetir=${t.id}">Repetir</a>
      <button type="button" class="age-btn age-btn-primary" data-ver-resultados="${t.id}">Ver resultados</button>
    `;
  }

  return `
    <div class="test-card" data-id="${t.id}">
      <div class="test-card-header">
        <div class="test-card-icon">${info.icono}</div>
        <div>
          <p class="test-card-titulo">${info.label}</p>
          <p class="test-card-meta">${partes.join(" · ")}</p>
        </div>
      </div>
      <div class="test-card-estado">${bloqueEstado}</div>
      ${pillsTemas(t.temas)}
      <div class="test-card-acciones">${acciones}</div>
      <div class="test-card-resultados hidden" id="resultados-${t.id}"></div>
    </div>
  `;
}

function renderizar() {
  const tipoFiltro = document.getElementById("filtro-tipo").value;
  const temaFiltro = document.getElementById("filtro-tema").value;

  const filtrados = tests.filter((t) => {
    if (filtroEstado && (t.estado || "finalizado") !== filtroEstado) return false;
    if (tipoFiltro && t.tipo !== tipoFiltro) return false;
    if (temaFiltro && !(t.temas || []).includes(temaFiltro)) return false;
    return true;
  });

  const lista = document.getElementById("tests-lista");
  const sinResultados = document.getElementById("tests-sin-resultados");
  if (filtrados.length === 0) {
    lista.innerHTML = "";
    sinResultados.classList.remove("hidden");
    return;
  }
  sinResultados.classList.add("hidden");
  lista.innerHTML = filtrados.map(tarjetaTest).join("");

  lista.querySelectorAll("[data-ver-resultados]").forEach((boton) => {
    boton.addEventListener("click", () => alternarResultados(boton.dataset.verResultados, boton));
  });
}

async function alternarResultados(testId, boton) {
  const contenedor = document.getElementById(`resultados-${testId}`);
  if (!contenedor.classList.contains("hidden")) {
    contenedor.classList.add("hidden");
    boton.textContent = "Ver resultados";
    return;
  }
  boton.disabled = true;
  boton.textContent = "Cargando…";
  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/mi-test/${testId}`, { headers: { Authorization: `Bearer ${token}` } });
    const datos = await res.json();
    if (!res.ok || !datos.test) throw new Error(datos.error || "No se pudo cargar el test.");
    const preguntas = datos.test.preguntas || [];
    const respuestasUsuario = preguntas.map((p) => p.respuesta_usuario ?? null);
    const { renderizarResultadosTest } = await import("/assets/resultados-test.js");
    contenedor.innerHTML = "";
    renderizarResultadosTest({
      contenedor,
      preguntas,
      respuestasUsuario,
      listaTemas: Array.from(temasPorId, ([id, titulo]) => ({ id, titulo }))
    });
    contenedor.classList.remove("hidden");
    boton.textContent = "Ocultar resultados";
  } catch (e) {
    contenedor.innerHTML = `<p>${e.message || "No se pudieron cargar los resultados."}</p>`;
    contenedor.classList.remove("hidden");
    boton.textContent = "Ver resultados";
  } finally {
    boton.disabled = false;
  }
}

async function cargarTemas(oposicion, token) {
  try {
    const res = await fetch(`${BACKEND_URL}/temas-disponibles?oposicion=${encodeURIComponent(oposicion)}`, { headers: { Authorization: `Bearer ${token}` } });
    const datos = await res.json();
    const temas = datos.temas || [];
    temasPorId = new Map(temas.map((t) => [t.id, t.titulo]));
    const select = document.getElementById("filtro-tema");
    select.innerHTML = `<option value="">Todos</option>` + temas.map((t) => `<option value="${t.id}">${acortarTitulo(t.titulo, 60)}</option>`).join("");
  } catch (e) {
    console.error("No se pudieron cargar los temas:", e);
  }
}

async function cargarTests(oposicion, token) {
  const res = await fetch(`${BACKEND_URL}/mis-tests?oposicion=${encodeURIComponent(oposicion)}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error("No se pudieron cargar tus tests.");
  const datos = await res.json();
  tests = datos.tests || [];
}

async function inicializar() {
  const token = await idToken();
  if (!token) {
    window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
    return;
  }

  try {
    const { obtenerOposicionActual } = await import("/assets/oposicion.js");
    const oposicion = obtenerOposicionActual();

    await Promise.all([cargarTemas(oposicion, token), cargarTests(oposicion, token)]);
    document.getElementById("tests-cargando").classList.add("hidden");

    if (tests.length === 0) {
      document.getElementById("tests-vacio").classList.remove("hidden");
      return;
    }

    document.getElementById("tests-contenido").classList.remove("hidden");

    document.querySelectorAll(".tests-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".tests-tab").forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        filtroEstado = tab.dataset.estado;
        renderizar();
      });
    });
    document.getElementById("filtro-tipo").addEventListener("change", renderizar);
    document.getElementById("filtro-tema").addEventListener("change", renderizar);

    renderizar();
  } catch (e) {
    document.getElementById("tests-cargando").textContent = e.message || "No se pudieron cargar tus tests.";
  }
}

inicializar();
