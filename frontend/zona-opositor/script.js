import { idToken, esperarUsuario } from "/assets/auth.js";
import { obtenerPlan } from "/assets/plan.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { OPOSICIONES, obtenerOposicionActual, establecerOposicionActual } from "/assets/oposicion.js";
import { icono } from "/assets/icons.js";

const MENSAJES_RACHA = [
  { minimo: 0, texto: "Empieza hoy tu racha: haz un test o repasa algo para arrancar." },
  { minimo: 1, texto: "¡Buen comienzo! Vuelve mañana para no perder la racha." },
  { minimo: 3, texto: "Llevas varios días seguidos, ¡vas genial!" },
  { minimo: 7, texto: "¡Una semana entera estudiando! Imparable." },
  { minimo: 14, texto: "Dos semanas de constancia. Tu esfuerzo se nota." },
  { minimo: 30, texto: "¡Un mes seguido! Nivel opositor de verdad." },
  { minimo: 60, texto: "Una racha así solo la consigue quien de verdad se lo toma en serio." }
];

function mensajeParaRacha(dias) {
  let elegido = MENSAJES_RACHA[0];
  for (const m of MENSAJES_RACHA) {
    if (dias >= m.minimo) elegido = m;
  }
  return elegido.texto;
}

async function cargarRacha() {
  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/mi-racha`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) return;
    const { racha_actual, racha_maxima } = await res.json();
    document.getElementById("racha-numero").textContent = racha_actual;
    document.getElementById("racha-plural").textContent = racha_actual === 1 ? "" : "s";
    document.getElementById("racha-mensaje").textContent = mensajeParaRacha(racha_actual);
    document.getElementById("racha-icono").textContent = racha_actual > 0 ? "🔥" : "💤";
    if (racha_maxima > racha_actual) {
      const elMaxima = document.getElementById("racha-maxima");
      elMaxima.textContent = `Tu mejor racha: ${racha_maxima} día${racha_maxima === 1 ? "" : "s"}`;
      elMaxima.style.display = "block";
    }
  } catch (e) {
    console.error("Error cargando racha:", e);
  }
}

// Adelanto de las insignias/nota media que se ven completas en
// Estadísticas: mismos umbrales que INSIGNIAS en estadisticas/script.js,
// reutilizando el mismo endpoint (no se crea uno nuevo).
const INSIGNIAS_UMBRALES = [
  (d) => d.testsRealizados >= 1,
  (d) => d.rachaMaxima >= 3,
  (d) => d.rachaMaxima >= 7,
  (d) => d.rachaMaxima >= 30,
  (d) => d.testsRealizados >= 10,
  (d) => d.testsRealizados >= 50,
  (d) => d.testsAprobados >= 10,
  (d) => d.puntuacionMedia >= 8,
  (d) => d.esquemas >= 5,
  (d) => d.totalArchivos >= 3
];

async function cargarProgresoInsignias() {
  try {
    const token = await idToken();
    const oposicion = obtenerOposicionActual();
    const [resEstadisticas, resRacha] = await Promise.all([
      fetch(`${BACKEND_URL}/estadisticas-completas?oposicion=${encodeURIComponent(oposicion)}`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${BACKEND_URL}/mi-racha`, { headers: { Authorization: `Bearer ${token}` } })
    ]);
    if (!resEstadisticas.ok) return;
    const { estadisticas } = await resEstadisticas.json();
    if (!estadisticas || estadisticas.error) return;
    const racha = resRacha.ok ? await resRacha.json() : { racha_maxima: 0 };

    const datos = {
      testsRealizados: estadisticas.tests_realizados ?? 0,
      testsAprobados: estadisticas.tests_aprobados ?? 0,
      rachaMaxima: racha.racha_maxima ?? 0,
      puntuacionMedia: estadisticas.puntuacion_media_test ?? 0,
      esquemas: estadisticas.esquemas_realizados ?? 0,
      totalArchivos: estadisticas.total_archivos_procesados ?? 0
    };
    if (datos.testsRealizados === 0) return; // nada que mostrar todavía

    const conseguidas = INSIGNIAS_UMBRALES.filter((cumple) => cumple(datos)).length;
    document.getElementById("zona-progreso-insignias").textContent = `${conseguidas}/${INSIGNIAS_UMBRALES.length}`;
    document.getElementById("zona-progreso-nota").textContent = datos.puntuacionMedia.toFixed(1);
    document.getElementById("zona-progreso").style.display = "";
  } catch (e) {
    console.error("Error cargando progreso de insignias:", e);
  }
}

async function iniciarBotonNotificaciones() {
  const boton = document.getElementById("racha-notif-boton");
  const { pushDisponibleEnNavegador, pushConfiguradoEnServidor, notificacionesActivas, activarNotificaciones, desactivarNotificaciones } = await import("/assets/push.js");

  if (!(await pushDisponibleEnNavegador()) || !(await pushConfiguradoEnServidor())) return;

  const pintar = (activas) => {
    boton.textContent = activas ? "🔕 Desactivar avisos" : "🔔 Avisarme si la pierdo";
  };
  pintar(await notificacionesActivas());
  boton.style.display = "";

  boton.addEventListener("click", async () => {
    boton.disabled = true;
    try {
      if (await notificacionesActivas()) {
        await desactivarNotificaciones();
        pintar(false);
      } else {
        await activarNotificaciones();
        pintar(true);
      }
    } catch (e) {
      alert(e.message || "No se pudieron activar las notificaciones.");
    } finally {
      boton.disabled = false;
    }
  });
}

function formatearCuentaAtras(fechaISO) {
  const hoy = new Date();
  hoy.setHours(0, 0, 0, 0);
  const fechaExamen = new Date(`${fechaISO}T00:00:00`);
  const dias = Math.round((fechaExamen - hoy) / 86400000);
  if (dias > 1) return { numero: `${dias} días`, mensaje: "para tu examen" };
  if (dias === 1) return { numero: "Mañana", mensaje: "es tu examen. ¡Mucho ánimo!" };
  if (dias === 0) return { numero: "¡Hoy!", mensaje: "es el día de tu examen. ¡A por ello!" };
  return { numero: "Ya pasó", mensaje: "la fecha que configuraste" };
}

async function cargarCuentaAtras() {
  const numeroEl = document.getElementById("cuenta-atras-numero");
  const mensajeEl = document.getElementById("cuenta-atras-mensaje");
  const boton = document.getElementById("cuenta-atras-boton");
  const form = document.getElementById("cuenta-atras-form");
  const input = document.getElementById("cuenta-atras-input");
  const quitar = document.getElementById("cuenta-atras-quitar");
  const token = await idToken();
  const oposicion = obtenerOposicionActual();

  const pintar = (fecha) => {
    if (fecha) {
      const { numero, mensaje } = formatearCuentaAtras(fecha);
      numeroEl.textContent = numero;
      mensajeEl.textContent = mensaje;
      boton.textContent = "Cambiar fecha";
      quitar.style.display = "";
    } else {
      numeroEl.textContent = "—";
      mensajeEl.textContent = "Configura la fecha de tu examen para ver la cuenta atrás.";
      boton.textContent = "Configurar";
      quitar.style.display = "none";
    }
  };

  let fechaActual = null;
  try {
    const res = await fetch(`${BACKEND_URL}/fecha-examen?oposicion=${encodeURIComponent(oposicion)}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (res.ok) {
      const datos = await res.json();
      fechaActual = datos.fecha_examen || null;
    }
  } catch (e) {
    console.error("Error cargando fecha de examen:", e);
  }
  pintar(fechaActual);

  boton.addEventListener("click", () => {
    input.value = fechaActual || "";
    form.style.display = form.style.display === "none" ? "flex" : "none";
  });

  form.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    try {
      await fetch(`${BACKEND_URL}/fecha-examen?oposicion=${encodeURIComponent(oposicion)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ fecha_examen: input.value })
      });
      fechaActual = input.value;
      pintar(fechaActual);
      form.style.display = "none";
    } catch (e) {
      console.error("Error guardando fecha de examen:", e);
    }
  });

  quitar.addEventListener("click", async () => {
    try {
      await fetch(`${BACKEND_URL}/fecha-examen?oposicion=${encodeURIComponent(oposicion)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ fecha_examen: "" })
      });
      fechaActual = null;
      pintar(fechaActual);
      form.style.display = "none";
    } catch (e) {
      console.error("Error quitando fecha de examen:", e);
    }
  });
}

// Avisos rotativos con recomendaciones de uso, inspirados en el panel de
// inicio de la competencia (aula.opositatest.com): cada uno enlaza a una
// herramienta real de la web, no son solo texto decorativo.
const AVISOS = [
  {
    iconoNombre: "diana",
    titulo: "Repasa lo que más se te resiste",
    texto: "Identifica tus temas flojos en las estadísticas y genera un test inteligente centrado justo en ellos.",
    cta: "Ver mis estadísticas",
    href: "/estadisticas/"
  },
  {
    iconoNombre: "carpeta",
    titulo: "Convierte cualquier PDF en material de estudio",
    texto: "Sube tus apuntes y genera resúmenes, esquemas o tarjetas de memoria en segundos.",
    cta: "Probar Herramientas IA",
    href: "/subida-pdf-pagina-principal/"
  },
  {
    iconoNombre: "edificio",
    titulo: "Practica con exámenes oficiales reales",
    texto: "Ponte a prueba con convocatorias reales de tu oposición, tal y como caerán el día del examen.",
    cta: "Hacer un test oficial",
    href: "/test-generator/"
  },
  {
    emoji: "🔥",
    titulo: "No rompas tu racha de estudio",
    texto: "Cada día que practicas cuenta. Haz aunque sea un test corto para mantener viva tu racha.",
    cta: "Hacer un test",
    href: "/test-generator/"
  }
];

let avisoActual = 0;

function renderAviso() {
  const contenedor = document.getElementById("zona-avisos");
  const a = AVISOS[avisoActual];
  contenedor.innerHTML = `
    <div class="zona-avisos-card">
      <span class="zona-avisos-icono">${a.emoji || icono(a.iconoNombre, 32)}</span>
      <div class="zona-avisos-texto">
        <h3>${a.titulo}</h3>
        <p>${a.texto}</p>
        <a href="${a.href}" class="age-btn age-btn-primary">${a.cta}</a>
      </div>
    </div>
    <div class="zona-avisos-nav">
      <button type="button" class="zona-avisos-flecha" id="zona-aviso-prev" aria-label="Aviso anterior">‹</button>
      <div class="zona-avisos-dots">${AVISOS.map((_, i) => `<span class="zona-avisos-dot${i === avisoActual ? " activo" : ""}"></span>`).join("")}</div>
      <button type="button" class="zona-avisos-flecha" id="zona-aviso-next" aria-label="Siguiente aviso">›</button>
    </div>
  `;
  document.getElementById("zona-aviso-prev").addEventListener("click", () => {
    avisoActual = (avisoActual - 1 + AVISOS.length) % AVISOS.length;
    renderAviso();
  });
  document.getElementById("zona-aviso-next").addEventListener("click", () => {
    avisoActual = (avisoActual + 1) % AVISOS.length;
    renderAviso();
  });
}

// Checklist de bienvenida: 3 pasos que ayudan a un usuario nuevo a
// descubrir lo esencial de la web. Se oculta sola en cuanto los 3 pasos
// están hechos, o si el usuario la cierra manualmente (persistido en
// localStorage, no hace falta seguir preguntando al backend en ese caso).
const CLAVE_ONBOARDING_CERRADO = "age_onboarding_cerrado";

const PASOS_ONBOARDING = [
  { id: "test", texto: "Haz tu primer test", href: "/test-generator/" },
  { id: "ia", texto: "Prueba las Herramientas IA con un PDF", href: "/subida-pdf-pagina-principal/" },
  { id: "estadisticas", texto: "Consulta tus estadísticas", href: "/estadisticas/" }
];

async function comprobarPasosOnboarding(token) {
  const completado = { test: false, ia: false, estadisticas: localStorage.getItem("age_visito_estadisticas") === "1" };
  try {
    const oposicion = obtenerOposicionActual();
    const [resTests, resDocs] = await Promise.all([
      fetch(`${BACKEND_URL}/mis-tests?oposicion=${encodeURIComponent(oposicion)}&estado=finalizado`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${BACKEND_URL}/mis-documentos`, { headers: { Authorization: `Bearer ${token}` } })
    ]);
    if (resTests.ok) {
      const { tests } = await resTests.json();
      completado.test = Array.isArray(tests) && tests.length > 0;
    }
    if (resDocs.ok) {
      const { documentos } = await resDocs.json();
      completado.ia = Array.isArray(documentos) && documentos.length > 0;
    }
  } catch (e) {
    console.error("Error comprobando progreso de onboarding:", e);
  }
  return completado;
}

async function renderOnboarding() {
  const tarjeta = document.getElementById("zona-onboarding");
  if (localStorage.getItem(CLAVE_ONBOARDING_CERRADO) === "1") return;

  const token = await idToken();
  const completado = await comprobarPasosOnboarding(token);
  if (PASOS_ONBOARDING.every((p) => completado[p.id])) return;

  const lista = document.getElementById("zona-onboarding-lista");
  lista.innerHTML = PASOS_ONBOARDING.map((p) => `
    <li class="zona-onboarding-paso${completado[p.id] ? " completado" : ""}">
      <a href="${p.href}">
        <span class="zona-onboarding-check">${icono("check", 14)}</span>
        <span class="zona-onboarding-texto">${p.texto}</span>
      </a>
    </li>
  `).join("");
  tarjeta.style.display = "";

  document.getElementById("zona-onboarding-cerrar").addEventListener("click", () => {
    localStorage.setItem(CLAVE_ONBOARDING_CERRADO, "1");
    tarjeta.style.display = "none";
  });
}

function renderSwitcher() {
  const contenedor = document.getElementById("zona-oposicion-switcher");
  const actual = obtenerOposicionActual();
  contenedor.innerHTML = OPOSICIONES.map((o) => `
    <button type="button" class="zona-switch-pill${o.id === actual ? " activo" : ""}" data-op="${o.id}">${o.siglas || o.nombre}</button>
  `).join("");
  contenedor.querySelectorAll("[data-op]").forEach((boton) => {
    boton.addEventListener("click", () => {
      if (boton.dataset.op === actual) return;
      establecerOposicionActual(boton.dataset.op);
      sessionStorage.clear();
      window.location.reload();
    });
  });
}

const PILL_PLAN = { gratis: "age-pill", basico: "age-pill age-pill-primary", premium: "age-pill age-pill-success" };

async function iniciar() {
  const usuario = await esperarUsuario();
  if (!usuario) {
    window.location.href = "/login/?next=/zona-opositor/";
    return;
  }

  document.getElementById("zona-nombre").textContent = (usuario.email || "").split("@")[0] || "opositor/a";

  cargarRacha();
  cargarProgresoInsignias();
  iniciarBotonNotificaciones();
  cargarCuentaAtras();
  renderAviso();
  renderSwitcher();
  renderOnboarding();
  document.getElementById("zona-reabrir-onboarding").addEventListener("click", () => {
    localStorage.removeItem(CLAVE_ONBOARDING_CERRADO);
    renderOnboarding();
  });

  const { nombre, plan } = await obtenerPlan(true);
  if (nombre) document.getElementById("zona-nombre").textContent = nombre;

  const opActual = OPOSICIONES.find((o) => o.id === obtenerOposicionActual());
  document.getElementById("zona-oposicion-nombre").textContent = opActual ? opActual.nombre : "—";

  const pillPlan = document.getElementById("zona-plan-pill");
  pillPlan.className = PILL_PLAN[plan] || "age-pill";
  pillPlan.textContent = plan || "gratis";
}

iniciar();
