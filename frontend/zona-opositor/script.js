import { idToken, esperarUsuario, marcarContenidoListo } from "/assets/auth.js";
import { obtenerPlan } from "/assets/plan.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { OPOSICIONES, obtenerOposicionActual, establecerOposicionActual } from "/assets/oposicion.js";
import { icono } from "/assets/icons.js";
import { fijarTexto, fijarHTML } from "/assets/dom.js";
import { mostrarErrorGlobal } from "/assets/notificaciones.js";
import { inicializarCuentaAtras } from "/assets/cuenta-atras.js";

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

/**
 * Destello + pulso del icono de racha (07/08/2026, a petición del
 * usuario): un anillo se expande y se apaga detrás del icono mientras este
 * da un pulso rápido y decidido, sin rebote elástico -- solo se llama
 * cuando la racha ha subido de verdad desde la última vez que se vio esta
 * pantalla (ver comparación con localStorage en cargarRacha), no en cada
 * carga de página: es una celebración real, no decoración de entrada.
 * anime.js se importa de forma perezosa (import() dinámico) porque esto
 * solo se dispara cuando la racha ha subido de verdad -- la mayoría de
 * cargas de página no lo necesitan, así que no tiene sentido pagar su
 * descarga siempre.
 */
async function animarSubidaRacha() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const iconoEl = document.getElementById("racha-icono");
  const destello = document.getElementById("racha-destello");
  if (!iconoEl || !destello) return;

  const { default: anime } = await import("/assets/vendor/anime.esm.js");
  anime.set(destello, { opacity: 0.4, scale: 0.6 });
  anime({
    targets: destello,
    opacity: 0,
    scale: 1.9,
    duration: 700,
    easing: "easeOutQuad",
  });
  anime({
    targets: iconoEl,
    scale: [
      { value: 1.3, duration: 220, easing: "easeOutQuad" },
      { value: 1, duration: 280, easing: "cubicBezier(0.16, 1, 0.3, 1)" },
    ],
  });
}

/**
 * Compara la racha recién cargada con la última vez que este navegador vio
 * esta pantalla (guardada en localStorage, por uid -- varios usuarios
 * pueden compartir dispositivo) para saber si hay que celebrar una subida
 * real. La primera vez que se ve la racha (sin valor guardado todavía) no
 * cuenta como "subida": no hay nada con qué compararla.
 */
function comprobarSubidaRacha(uid, rachaActual) {
  try {
    const clave = `racha-vista-${uid}`;
    const previaTexto = localStorage.getItem(clave);
    localStorage.setItem(clave, String(rachaActual));
    if (previaTexto === null) return;
    const previa = Number(previaTexto);
    if (Number.isFinite(previa) && rachaActual > previa) programarAnimacionSubidaRacha();
  } catch {
    // localStorage no disponible (modo privado estricto, etc.) -- sin
    // celebración de subida, pero la racha se sigue mostrando con normalidad.
  }
}

// La tarjeta de racha vive bastante más abajo que la cabecera (accesos +
// onboarding + "qué hacer ahora" van primero) -- si la animación se
// lanzara nada más cargar la página, en la mayoría de los casos habría
// terminado antes de que el usuario llegara a bajar hasta verla, así que
// se perdería siempre. Se espera a que la tarjeta entre en pantalla, mismo
// patrón que animarLineaTiempo() en estadisticas/script.js.
function programarAnimacionSubidaRacha() {
  const tarjeta = document.querySelector(".zona-racha-card");
  if (!tarjeta) return;
  if (!("IntersectionObserver" in window)) {
    animarSubidaRacha();
    return;
  }
  const observador = new IntersectionObserver((entradas) => {
    if (!entradas[0].isIntersecting) return;
    observador.disconnect();
    animarSubidaRacha();
  }, { threshold: 0.4 });
  observador.observe(tarjeta);
}

async function cargarRacha(uid) {
  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/mi-racha`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) return;
    const { racha_actual, racha_maxima } = await res.json();
    fijarTexto("racha-numero", racha_actual);
    fijarTexto("racha-plural", racha_actual === 1 ? "" : "s");
    fijarTexto("racha-mensaje", mensajeParaRacha(racha_actual));
    fijarHTML("racha-icono", racha_actual > 0 ? icono("fuego", 40) : icono("luna", 40));
    if (racha_maxima > racha_actual) {
      fijarTexto("racha-maxima", `Tu mejor racha: ${racha_maxima} día${racha_maxima === 1 ? "" : "s"}`);
      const elMaxima = document.getElementById("racha-maxima");
      if (elMaxima) elMaxima.style.display = "block";
    }
    if (uid) comprobarSubidaRacha(uid, racha_actual);
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
    const [resEstadisticas, resRacha, resTemas, resFecha] = await Promise.all([
      fetch(`${BACKEND_URL}/estadisticas-completas?oposicion=${encodeURIComponent(oposicion)}`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${BACKEND_URL}/mi-racha`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${BACKEND_URL}/temas-disponibles?oposicion=${encodeURIComponent(oposicion)}`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${BACKEND_URL}/fecha-examen?oposicion=${encodeURIComponent(oposicion)}`, { headers: { Authorization: `Bearer ${token}` } })
    ]);
    if (!resEstadisticas.ok) return;
    const { estadisticas } = await resEstadisticas.json();
    if (!estadisticas || estadisticas.error) return;
    const racha = resRacha.ok ? await resRacha.json() : { racha_maxima: 0 };
    const temas = resTemas.ok ? (await resTemas.json()).temas || [] : [];
    const fechaExamen = resFecha.ok ? (await resFecha.json()).fecha_examen : null;

    renderPlanEstudio(estadisticas.rendimiento_por_tema ?? {}, temas, fechaExamen);

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
    fijarTexto("zona-progreso-insignias", `${conseguidas}/${INSIGNIAS_UMBRALES.length}`);
    fijarTexto("zona-progreso-nota", datos.puntuacionMedia.toFixed(1));
    const elProgreso = document.getElementById("zona-progreso");
    if (elProgreso) elProgreso.style.display = "";
  } catch (e) {
    console.error("Error cargando progreso de insignias:", e);
  }
}

// Mismo criterio de "tema flojo" que en Estadísticas: al menos 3 preguntas
// respondidas de ese tema y menos del 60% de acierto. Aquí solo se muestra
// el peor de todos, como aviso directo en el propio panel principal.
const UMBRAL_ACIERTO_FLOJO = 60;
const MINIMO_PREGUNTAS_FLOJO = 3;

function peorTemaFlojo(rendimientoPorTema) {
  return Object.entries(rendimientoPorTema || {})
    .map(([id, r]) => {
      const respondidas = (r.aciertos || 0) + (r.fallos || 0);
      const porcentaje = respondidas > 0 ? Math.round((r.aciertos / respondidas) * 100) : null;
      return { id, respondidas, porcentaje };
    })
    .filter((t) => t.respondidas >= MINIMO_PREGUNTAS_FLOJO && t.porcentaje !== null && t.porcentaje < UMBRAL_ACIERTO_FLOJO)
    .sort((a, b) => a.porcentaje - b.porcentaje)[0];
}

// "Qué hacer ahora": antes eran 3 tarjetas independientes (continuar test,
// preguntas falladas pendientes, tema de hoy/tema flojo) que se mostraban
// u ocultaban cada una por su cuenta según llegaban sus propias respuestas
// async, en cualquier orden. Aquí se guarda cada fila en un estado
// compartido y se repinta la tarjeta entera cada vez que cambia una pieza,
// así el orden de llegada de red no afecta al orden final (continuar >
// repaso pendiente > tema recomendado) ni dejan huecos en blanco.
const ESTADO_HACER_AHORA = { continuar: null, repaso: null, tema: null };

function renderizarQueHacerAhora() {
  const tarjeta = document.getElementById("zona-hacer-ahora");
  const lista = document.getElementById("zona-hacer-ahora-lista");
  const filas = [ESTADO_HACER_AHORA.continuar, ESTADO_HACER_AHORA.repaso, ESTADO_HACER_AHORA.tema].filter(Boolean);
  if (filas.length === 0) {
    tarjeta.style.display = "none";
    return;
  }
  lista.innerHTML = filas.map((fila, i) => (i === 0 ? fila : `<div class="zona-mis-cosas-divisor"></div>${fila}`)).join("");
  tarjeta.style.display = "";
}

// Planificador de estudio: combina la fecha de examen configurada (ver
// cuenta-atras.js/GET /fecha-examen) con qué temas quedan por tocar
// todavía, para sugerir un ritmo aproximado y un "tema de hoy" concreto en
// vez de dejar al usuario adivinar por dónde seguir. "Tocado" usa el mismo
// criterio simple que ya tenía disponible esta página (aparece en
// rendimiento_por_tema), sin traer todo el historial de tests solo para
// esto -- si se necesitase la definición exacta de Estadísticas
// (temas.some) habría que traer también /mis-tests aquí.
function renderPlanEstudio(rendimientoPorTema, todosTemas, fechaExamenISO) {
  const ritmoEl = document.getElementById("zona-plan-ritmo");
  if (!todosTemas.length) {
    ritmoEl.style.display = "none";
    ESTADO_HACER_AHORA.tema = null;
    renderizarQueHacerAhora();
    return;
  }

  const temasTocados = new Set(Object.keys(rendimientoPorTema || {}));
  const pendientes = todosTemas.filter((t) => !temasTocados.has(t.id));

  let ritmo;
  if (!fechaExamenISO) {
    ritmo = pendientes.length > 0
      ? `Te quedan ${pendientes.length} de ${todosTemas.length} temas por tocar. Configura la fecha de tu examen (arriba) para ver un ritmo sugerido.`
      : "Ya has tocado todos los temas al menos una vez. ¡Sigue repasando para consolidarlos!";
  } else {
    const hoy = new Date();
    hoy.setHours(0, 0, 0, 0);
    const diasRestantes = Math.round((new Date(`${fechaExamenISO}T00:00:00`) - hoy) / 86400000);
    if (diasRestantes <= 0) {
      ritmo = pendientes.length > 0 ? `Quedan ${pendientes.length} temas sin tocar y tu examen ya está aquí: repásalos como puedas.` : "Has tocado todos los temas. ¡A por el examen!";
    } else if (pendientes.length === 0) {
      ritmo = `Ya has tocado los ${todosTemas.length} temas. Quedan ${diasRestantes} días: aprovéchalos para repasar y afianzar.`;
    } else {
      const ritmoDias = Math.max(1, Math.floor(diasRestantes / pendientes.length));
      ritmo = `Te quedan ${pendientes.length} temas nuevos y ${diasRestantes} días hasta el examen: te toca ver un tema nuevo aprox. cada ${ritmoDias} día${ritmoDias !== 1 ? "s" : ""} para llegar a verlos todos.`;
    }
  }
  fijarTexto("zona-plan-ritmo", ritmo);
  ritmoEl.style.display = "block";

  const siguienteNuevo = pendientes[0];
  const peorFlojo = peorTemaFlojo(rendimientoPorTema);
  let sugerido = null;
  let motivo = "";
  if (siguienteNuevo) {
    sugerido = siguienteNuevo;
    motivo = "aún no lo has tocado";
  } else if (peorFlojo) {
    sugerido = todosTemas.find((t) => t.id === peorFlojo.id);
    motivo = `${peorFlojo.porcentaje}% de acierto todavía`;
  }

  ESTADO_HACER_AHORA.tema = !sugerido ? null : `
    <a class="zona-mis-cosas-item" href="/test-personalizado/?temas=${encodeURIComponent(sugerido.id)}">
      <span class="zona-mis-cosas-icono">${icono("diana", 26)}</span>
      <span class="zona-mis-cosas-texto">
        <strong>Tema de hoy: <span title="${sugerido.titulo}">${sugerido.titulo}</span></strong>
        <small>${motivo}</small>
      </span>
      <span class="zona-mis-cosas-flecha">→</span>
    </a>
  `;
  renderizarQueHacerAhora();
}

async function iniciarBotonNotificaciones() {
  const boton = document.getElementById("racha-notif-boton");
  const { pushDisponibleEnNavegador, pushConfiguradoEnServidor, notificacionesActivas, activarNotificaciones, desactivarNotificaciones } = await import("/assets/push.js");

  if (!(await pushDisponibleEnNavegador()) || !(await pushConfiguradoEnServidor())) return;

  const pintar = (activas) => {
    boton.innerHTML = activas ? `${icono("campanaOff", 15)} Desactivar avisos` : `${icono("campana", 15)} Avisarme si la pierdo`;
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
      mostrarErrorGlobal(e.message || "No se pudieron activar las notificaciones.");
    } finally {
      boton.disabled = false;
    }
  });
}

const PAGINA_POR_TIPO_TEST = {
  personalizado: "/test-personalizado/",
  oficial: "/test-oficial/",
  repetido: "/repetir-test/",
  falladas: "/preguntas-falladas/",
  favoritas: "/preguntas-favoritas/"
};

async function cargarTestEnProgreso() {
  try {
    const token = await idToken();
    const oposicion = obtenerOposicionActual();
    const res = await fetch(`${BACKEND_URL}/mis-tests?oposicion=${encodeURIComponent(oposicion)}&estado=en_progreso`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) return;
    const { tests } = await res.json();
    if (!Array.isArray(tests) || tests.length === 0) return;

    const test = tests[0]; // ya viene ordenado por fecha descendente
    const pagina = PAGINA_POR_TIPO_TEST[test.tipo] || "/test-generator/";
    const vista = (test.indice_actual || 0) + 1;
    ESTADO_HACER_AHORA.continuar = `
      <a class="zona-mis-cosas-item" href="${pagina}?resume=${test.id}">
        <span class="zona-mis-cosas-icono">${icono("reproducir", 26)}</span>
        <span class="zona-mis-cosas-texto">
          <strong>Continuar tu test a medias</strong>
          <small>Ibas por la pregunta ${vista} de ${test.num_preguntas || "?"}. Retómalo donde lo dejaste.</small>
        </span>
        <span class="zona-mis-cosas-flecha">→</span>
      </a>
    `;
    renderizarQueHacerAhora();
  } catch (e) {
    console.error("Error cargando test en progreso:", e);
  }
}

// Repaso espaciado proactivo: en vez de esperar a que el usuario recuerde
// entrar en /preguntas-falladas/, se avisa aquí en cuanto tiene alguna
// pendiente para esta oposición (banco persistente de banco_fallos.py).
// Ojo con el texto: distinto de "Repasar preguntas" (repaso pasivo, en "Lo
// tuyo") -- esto lleva a HACER UN TEST de las falladas, no a repasarlas sin
// más, así que se evita la palabra "repasar" aquí para no confundir ambas.
async function cargarRepasoPendiente() {
  try {
    const token = await idToken();
    const oposicion = obtenerOposicionActual();
    const res = await fetch(`${BACKEND_URL}/preguntas-pendientes-repaso?oposicion=${encodeURIComponent(oposicion)}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) return;
    const { total_pendientes } = await res.json();
    if (!total_pendientes) return;

    const plural = total_pendientes !== 1 ? "s" : "";
    ESTADO_HACER_AHORA.repaso = `
      <a class="zona-mis-cosas-item" href="/preguntas-falladas/">
        <span class="zona-mis-cosas-icono">${icono("cerebro", 26)}</span>
        <span class="zona-mis-cosas-texto">
          <strong>Preguntas falladas pendientes</strong>
          <small>Tienes ${total_pendientes} pregunta${plural} fallada${plural} sin trabajar -- hazte un test centrado en ellas</small>
        </span>
        <span class="zona-mis-cosas-flecha">→</span>
      </a>
    `;
    renderizarQueHacerAhora();
  } catch (e) {
    console.error("Error cargando preguntas pendientes de repaso:", e);
  }
}

// El título y el enlace de un aviso oficial vienen del BOE (vía la
// vigilancia automática) y se interpolan en innerHTML -- se escapan para
// que un carácter "<" o similar en el texto real de una disposición no se
// interprete como HTML, mismo motivo que resultados-test.js:escaparHtml.
function escapeHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto ?? "";
  return div.innerHTML;
}

// Avisos oficiales reales (convocatorias, listas de admitidos, fechas de
// examen...) para la oposición actual, detectados por la vigilancia del
// BOE y ya aprobados a mano por el dueño desde el panel de admin (ver
// blueprints/temario.py:avisos_oficiales) -- no confundir con AVISOS de
// abajo, que son consejos de uso estáticos, no contenido real.
const ETIQUETA_TIPO_AVISO = {
  convocatoria: "Convocatoria",
  lista_admitidos: "Lista de admitidos",
  tribunal: "Tribunal calificador",
  fecha_examen: "Fecha de examen",
  aprobados: "Relación de aprobados",
  otro: "Aviso oficial",
};

async function cargarAvisosOficiales() {
  try {
    const token = await idToken();
    const oposicion = obtenerOposicionActual();
    const res = await fetch(`${BACKEND_URL}/avisos-oficiales?oposicion=${encodeURIComponent(oposicion)}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) return;
    const { avisos } = await res.json();
    const seccion = document.getElementById("zona-avisos-oficiales");
    const lista = document.getElementById("zona-avisos-oficiales-lista");
    if (!seccion || !lista || !avisos || !avisos.length) return;

    lista.innerHTML = avisos.map((a) => `
      <div class="zona-aviso-oficial-item">
        <span class="zona-aviso-oficial-tipo">${ETIQUETA_TIPO_AVISO[a.tipo] || ETIQUETA_TIPO_AVISO.otro}</span>
        <p class="zona-aviso-oficial-titulo">${escapeHtml(a.titulo)}</p>
        ${a.url_boe ? `<a class="zona-aviso-oficial-link" href="${escapeHtml(a.url_boe)}" target="_blank" rel="noopener">Ver en el BOE ↗</a>` : ""}
      </div>
    `).join("");
    seccion.style.display = "";
  } catch (e) {
    console.error("Error cargando avisos oficiales:", e);
  }
}

// Avisos rotativos con recomendaciones de uso, inspirados en el panel de
// inicio de la competencia (aula.opositatest.com): cada uno enlaza a una
// herramienta real de la web, no son solo texto decorativo.
const AVISOS = [
  {
    iconoNombre: "diana",
    titulo: "Repasa lo que más se te resiste",
    texto: "Identifica tus temas flojos en las estadísticas y genera un Test Personalizado centrado justo en ellos.",
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
    href: "/test-oficial/"
  },
  {
    iconoNombre: "fuego",
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
      <span class="zona-avisos-icono">${icono(a.iconoNombre, 32)}</span>
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

// Checklist de bienvenida: pasos que ayudan a un usuario nuevo a descubrir
// lo esencial de la web. Se oculta sola en cuanto todos los pasos están
// hechos, o si el usuario la cierra manualmente (persistido en
// localStorage, no hace falta seguir preguntando al backend en ese caso).
// Único mecanismo de onboarding de la página -- antes convivía con un tour
// de spotlight aparte (mostrarTourZonaOpositor, ver onboarding-tour.js) que
// señalaba prácticamente las mismas tarjetas, mostrando dos avisos de
// bienvenida distintos y superpuestos en la primera visita.
const CLAVE_ONBOARDING_CERRADO = "age_onboarding_cerrado";

const PASOS_ONBOARDING = [
  { id: "test", texto: "Haz tu primer test", href: "/test-generator/" },
  { id: "ia", texto: "Prueba las Herramientas IA con un PDF", href: "/subida-pdf-pagina-principal/" },
  { id: "tutor", texto: "Pregúntale una duda a Tu Tutor", href: "/tu-tutor/" },
  { id: "estadisticas", texto: "Consulta tus estadísticas", href: "/estadisticas/" }
];

async function comprobarPasosOnboarding(token) {
  const completado = {
    test: false,
    ia: false,
    tutor: localStorage.getItem("age_visito_tutor") === "1",
    estadisticas: localStorage.getItem("age_visito_estadisticas") === "1"
  };
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

  const subtitulo = document.getElementById("zona-onboarding-subtitulo");
  if (subtitulo) {
    const perfil = await obtenerPlan(false);
    subtitulo.style.display = perfil.prueba_activa ? "block" : "none";
  }

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
      renderSwitcher();
      cargarDatosOposicion();
    });
  });
}

const PILL_PLAN = { gratis: "age-pill", basico: "age-pill age-pill-primary", premium: "age-pill age-pill-success" };

function inyectarIconosEstaticos() {
  document.querySelectorAll("[data-icon]").forEach((el) => {
    el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 20));
  });
}

// Todo lo que depende de QUÉ oposición está activa (a diferencia de la
// racha, que es una sola por cuenta, no por oposición -- ver /mi-racha,
// sin parámetro ?oposicion=). Se agrupa aquí para poder llamarlo tanto en
// la carga inicial como al cambiar de oposición con el selector, sin
// recargar la página entera solo para refrescar estos bloques.
//
// Antes de volver a pedir los datos se ocultan/vacían las secciones que
// solo se muestran cuando hay algo que enseñar (progreso, avisos
// oficiales, "qué hacer ahora", onboarding): cada cargarXxx() de más
// abajo se limita a devolver sin hacer nada si la nueva oposición no
// tiene datos para esa sección, así que sin este reseteo previo se vería
// -- hasta que decidas cambiar de opinión sobre alguna sección -- la
// información de la oposición anterior en vez de desaparecer.
function resetSeccionesOposicion() {
  ESTADO_HACER_AHORA.continuar = null;
  ESTADO_HACER_AHORA.repaso = null;
  ESTADO_HACER_AHORA.tema = null;
  renderizarQueHacerAhora();
  const ritmo = document.getElementById("zona-plan-ritmo");
  if (ritmo) ritmo.style.display = "none";
  const progreso = document.getElementById("zona-progreso");
  if (progreso) progreso.style.display = "none";
  const avisosOficiales = document.getElementById("zona-avisos-oficiales");
  if (avisosOficiales) avisosOficiales.style.display = "none";
  const onboarding = document.getElementById("zona-onboarding");
  if (onboarding) onboarding.style.display = "none";
}

async function cargarDatosOposicion() {
  resetSeccionesOposicion();

  const opActual = OPOSICIONES.find((o) => o.id === obtenerOposicionActual());
  document.getElementById("zona-oposicion-nombre").textContent = opActual ? opActual.nombre : "—";

  cargarProgresoInsignias();
  cargarTestEnProgreso();
  cargarRepasoPendiente();
  cargarAvisosOficiales();
  inicializarCuentaAtras();
  renderOnboarding();

  const { nombre, plan } = await obtenerPlan(true);
  if (nombre) document.getElementById("zona-nombre").textContent = nombre;
  const pillPlan = document.getElementById("zona-plan-pill");
  pillPlan.className = PILL_PLAN[plan] || "age-pill";
  pillPlan.textContent = plan || "gratis";
}

async function iniciar() {
  inyectarIconosEstaticos();
  const usuario = await esperarUsuario();
  if (!usuario) {
    window.location.href = "/login/?next=/zona-opositor/";
    return;
  }

  document.getElementById("zona-nombre").textContent = (usuario.email || "").split("@")[0] || "opositor/a";

  cargarRacha(usuario.uid);
  iniciarBotonNotificaciones();
  renderAviso();
  renderSwitcher();
  cargarDatosOposicion();
  document.getElementById("zona-reabrir-onboarding").addEventListener("click", () => {
    localStorage.removeItem(CLAVE_ONBOARDING_CERRADO);
    renderOnboarding();
  });

  // La página se revela en cuanto se confirma la sesión (lo único que
  // de verdad hace falta para no dejar pasar a quien no tiene cuenta) --
  // no se espera aquí a cargarDatosOposicion() (que a su vez espera a
  // obtenerPlan(true), un fetch a /mi-perfil forzado a ignorar la caché
  // de sessionStorage), que antes retrasaba la revelación de TODA la
  // página por un solo dato (nombre + pill de plan) que ya tiene un valor
  // por defecto razonable en el propio HTML ("Cargando…" / "gratis"). El
  // resto de la página (racha, progreso, avisos...) ya se cargaba así,
  // sin bloquear -- esto solo alinea el nombre/plan con ese mismo criterio.
  marcarContenidoListo();
}

iniciar();
