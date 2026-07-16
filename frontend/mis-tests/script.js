import { idToken } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { mostrarErrorGlobal } from "/assets/notificaciones.js";

const TIPO_INFO = {
  personalizado: { icono: "📝", label: "Personalizado" },
  oficial: { icono: "🏛️", label: "Oficial" },
  inteligente: { icono: "🤖", label: "Inteligente IA" },
  repetido: { icono: "🔁", label: "Repetido" },
  falladas: { icono: "❌", label: "Preguntas falladas" },
  favoritas: { icono: "⭐", label: "Preguntas favoritas" },
};

const PAGINA_POR_TIPO = {
  personalizado: "/test-personalizado/",
  oficial: "/test-oficial/",
  inteligente: "/test-inteligente/",
  repetido: "/repetir-test/",
  falladas: "/preguntas-falladas/",
  favoritas: "/preguntas-favoritas/",
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

function pillsTemas(temaIds, testId) {
  if (!temaIds || !temaIds.length) return "";
  const pills = temaIds.map((id) => {
    const titulo = temasPorId.get(id) || id;
    return `<span class="age-pill">${acortarTitulo(titulo)}</span>`;
  }).join("");
  return `
    <button type="button" class="test-card-temas-toggle" data-toggle-temas="${testId}">
      <span>📚 ${temaIds.length} tema${temaIds.length !== 1 ? "s" : ""}</span>
      <span class="test-card-temas-caret">▾</span>
    </button>
    <div class="test-card-temas hidden" id="temas-${testId}">${pills}</div>
  `;
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
    acciones = `
      <a class="age-btn age-btn-primary" href="${pagina}?resume=${t.id}">Continuar</a>
      <button type="button" class="age-btn age-btn-danger" data-borrar-test="${t.id}">Eliminar</button>
    `;
  } else {
    const aprobado = t.resultado === "aprobado";
    bloqueEstado = `
      <span class="age-pill ${aprobado ? "age-pill-success" : "age-pill-danger"}">${aprobado ? "✅ Aprobado" : "❌ Suspendido"}</span>
      <span class="age-pill">${t.porcentaje_acierto ?? 0}% acierto</span>
    `;
    acciones = `
      <a class="age-btn age-btn-outline" href="/repetir-test/?repetir=${t.id}">Repetir</a>
      <a class="age-btn age-btn-primary" href="/mis-tests/resultado/?id=${t.id}">Ver resultados</a>
      <button type="button" class="age-btn age-btn-danger" data-borrar-test="${t.id}">Eliminar</button>
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
      ${pillsTemas(t.temas, t.id)}
      <div class="test-card-acciones">${acciones}</div>
    </div>
  `;
}

function renderizar() {
  const tipoFiltro = document.getElementById("filtro-tipo").value;
  const resultadoFiltro = document.getElementById("filtro-resultado").value;

  const filtrados = tests.filter((t) => {
    if (filtroEstado && (t.estado || "finalizado") !== filtroEstado) return false;
    if (tipoFiltro && t.tipo !== tipoFiltro) return false;
    if (resultadoFiltro && t.resultado !== resultadoFiltro) return false;
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

  lista.querySelectorAll("[data-toggle-temas]").forEach((boton) => {
    boton.addEventListener("click", () => {
      const contenedor = document.getElementById(`temas-${boton.dataset.toggleTemas}`);
      contenedor.classList.toggle("hidden");
      boton.classList.toggle("open", !contenedor.classList.contains("hidden"));
    });
  });

  lista.querySelectorAll("[data-borrar-test]").forEach((boton) => {
    boton.addEventListener("click", () => borrarTest(boton.dataset.borrarTest, boton));
  });
}

async function borrarTest(testId, boton) {
  const test = tests.find((t) => t.id === testId);
  const mensaje = test && test.estado === "en_progreso"
    ? "¿Seguro que quieres eliminar este test a medias? No podrás recuperarlo."
    : "¿Seguro que quieres eliminar este test y su resultado? No podrás recuperarlo.";
  if (!window.confirm(mensaje)) return;

  boton.disabled = true;
  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/mi-test/${encodeURIComponent(testId)}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) throw new Error("No se pudo eliminar el test.");
    tests = tests.filter((t) => t.id !== testId);
    if (tests.length === 0) {
      document.getElementById("tests-contenido").classList.add("hidden");
      document.getElementById("tests-vacio").classList.remove("hidden");
      return;
    }
    renderizar();
  } catch (e) {
    mostrarErrorGlobal(e.message || "No se pudo eliminar el test.");
    boton.disabled = false;
  }
}

// Solo se usa para pintar el título de cada tema en las pills de las
// tarjetas (pillsTemas) -- el filtro por tema se quitó de esta página, se
// filtra por tipo y resultado en su lugar.
async function cargarTemas(oposicion, token) {
  try {
    const res = await fetch(`${BACKEND_URL}/temas-disponibles?oposicion=${encodeURIComponent(oposicion)}`, { headers: { Authorization: `Bearer ${token}` } });
    const datos = await res.json();
    const temas = datos.temas || [];
    temasPorId = new Map(temas.map((t) => [t.id, t.titulo]));
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
  const { protegerPagina } = await import("/assets/plan.js");
  if (!(await protegerPagina("basico"))) return;

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
    document.getElementById("filtro-resultado").addEventListener("change", renderizar);

    renderizar();
  } catch (e) {
    document.getElementById("tests-cargando").textContent = e.message || "No se pudieron cargar tus tests.";
  }
}

inicializar();
