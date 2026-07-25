// Burbuja flotante de Tu Tutor: aparece abajo a la derecha en las páginas de
// estudio para que el usuario pueda abrir el chat sin salir de donde está
// (haciendo un test, viendo estadísticas, subiendo un PDF...). Reutiliza el
// mismo endpoint de streaming, la misma persistencia en Firestore (chat_id) y
// el mismo saludo proactivo que la página completa /tu-tutor/, así que las
// conversaciones abiertas desde aquí también salen en el histórico de allí.
//
// Se monta desde auth.js (montarWidgetTutor) solo para usuarios logueados y en
// las páginas de estudio -- nunca en la propia /tu-tutor/, ni en login/admin.
import { BACKEND_URL } from "/assets/firebase-config.js";
import { obtenerAuthHeaders } from "/assets/auth.js";
import { obtenerOposicionActual } from "/assets/oposicion.js";
import { icono } from "/assets/icons.js";
import { leerStreamConTimeout } from "/assets/stream-utils.js";

const ERROR_TECNICO = "El tutor ha tenido un problema técnico. Vuelve a intentarlo en unos segundos.";

function escapeHtml(text) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };
  return String(text == null ? "" : text).replace(/[&<>"']/g, (m) => map[m]);
}

function aplicarEnfasis(texto) {
  return texto
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>");
}

// Markdown ligero (mismo criterio que la página completa): se escapa TODO el
// HTML primero y solo después se traduce la sintaxis básica del modelo.
function formatearMensajeBot(texto) {
  const lineas = escapeHtml(texto).split("\n");
  let html = "";
  let enLista = false;
  const cerrarLista = () => { if (enLista) { html += "</ul>"; enLista = false; } };
  for (const original of lineas) {
    const linea = original.trim();
    const encabezado = linea.match(/^#{1,6}\s+(.*)$/);
    const item = linea.match(/^[-*]\s+(.*)$/);
    if (encabezado) { cerrarLista(); html += `<h4>${aplicarEnfasis(encabezado[1])}</h4>`; }
    else if (item) { if (!enLista) { html += "<ul>"; enLista = true; } html += `<li>${aplicarEnfasis(item[1])}</li>`; }
    else if (linea === "") { cerrarLista(); }
    else { cerrarLista(); html += `<p>${aplicarEnfasis(linea)}</p>`; }
  }
  cerrarLista();
  return html;
}

// Lee la pregunta que el usuario tiene AHORA en pantalla si está haciendo un
// test (las 6 páginas de test comparten este marcado: .pregunta-en-negrita +
// .opcion-respuesta con .opcion-letra/.opcion-texto). Devuelve un objeto que
// se manda al backend como `contexto_pagina` para que el tutor pueda resolver
// "ayúdame con esta pregunta" sin que el usuario la copie y pegue. Si no hay
// pregunta a la vista (no es página de test, o aún no ha empezado), null.
function leerPreguntaEnPantalla() {
  // Solo la pregunta ACTIVA de un test en curso (dentro de #form-pregunta),
  // no las de la lista de la pantalla de resultados (que también usan
  // .pregunta-en-negrita).
  const form = document.getElementById("form-pregunta");
  if (!form) return null;
  const bloque = form.querySelector(".pregunta-en-negrita");
  if (!bloque) return null;
  const span = bloque.querySelector("span");
  // Se quita la numeración inicial ("12. ") que añade la vista del test.
  const enunciado = (span ? span.textContent : "").replace(/^\s*\d+\s*[.)]\s*/, "").trim();
  if (!enunciado) return null;
  const opciones = {};
  form.querySelectorAll(".opcion-respuesta").forEach((label) => {
    const letra = label.querySelector(".opcion-letra")?.textContent.trim();
    const texto = label.querySelector(".opcion-texto")?.textContent.trim();
    if (letra && texto) opciones[letra] = texto;
  });
  // La página de test ya guarda aquí (vía data-*) la respuesta correcta y la
  // explicación que ya conoce desde que cargó/generó la pregunta -- así Tu
  // Tutor puede darla como dato verificado en vez de razonarla desde cero.
  const marcada = form.querySelector('input[name="respuesta"]:checked')?.value || "";
  return {
    tipo: "test",
    enunciado,
    opciones,
    respuesta_correcta: bloque.dataset.respuestaCorrecta || "",
    explicacion: bloque.dataset.explicacion || "",
    respuesta_usuario: marcada,
  };
}

let montado = false;

export function montarWidgetTutor() {
  // onAuthStateChanged puede dispararse varias veces por carga: solo se monta
  // una vez. Si ya existe el nodo (p. ej. reinyección de la nav), no duplicar.
  if (montado || document.getElementById("tutor-widget")) return;
  montado = true;

  const raiz = document.createElement("div");
  raiz.id = "tutor-widget";
  raiz.className = "tutor-widget";
  raiz.innerHTML = `
    <button type="button" class="tutor-widget-fab" aria-label="Abrir Tu Tutor" title="Pregúntale a Tu Tutor">
      <img src="/assets/tutor-avatar.svg" alt="" width="34" height="34" />
      <span class="tutor-widget-fab-punto" aria-hidden="true"></span>
    </button>
    <section class="tutor-widget-panel" role="dialog" aria-label="Chat con Tu Tutor" aria-hidden="true">
      <span class="tutor-widget-resize" role="separator" aria-label="Cambiar el tamaño del chat" title="Arrastra para cambiar el tamaño (doble clic para restablecer)"></span>
      <header class="tutor-widget-cabecera">
        <div class="tutor-widget-cabecera-info">
          <img src="/assets/tutor-avatar.svg" alt="" width="28" height="28" />
          <div>
            <strong>Tu Tutor</strong>
            <span class="tutor-widget-estado">Aquí para ayudarte</span>
          </div>
        </div>
        <div class="tutor-widget-cabecera-acciones">
          <button type="button" class="tutor-widget-accion tutor-widget-nueva" aria-label="Nueva conversación" title="Nueva conversación">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>
          </button>
          <button type="button" class="tutor-widget-accion tutor-widget-historial-btn" aria-label="Ver conversaciones anteriores" title="Conversaciones anteriores">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9 9 0 0 0-6.7 3M3 4v4h4"/><path d="M12 8v4l3 2"/></svg>
          </button>
          <a href="/tu-tutor/" class="tutor-widget-accion tutor-widget-expandir" aria-label="Abrir el chat completo" title="Abrir chat completo">⤢</a>
          <button type="button" class="tutor-widget-accion tutor-widget-cerrar" aria-label="Cerrar">${icono("cruz", 16)}</button>
        </div>
      </header>
      <div class="tutor-widget-pin" hidden>
        <span class="tutor-widget-pin-texto"></span>
        <button type="button" class="tutor-widget-pin-quitar" aria-label="Quitar pregunta fijada" title="Dejar de hablar de esta pregunta">×</button>
      </div>
      <div class="tutor-widget-mensajes" id="tutor-widget-mensajes"></div>
      <div class="tutor-widget-typing" hidden><span></span><span></span><span></span></div>
      <div class="tutor-widget-historial-panel" hidden>
        <div class="tutor-widget-historial-cabecera">
          <button type="button" class="tutor-widget-historial-volver" aria-label="Volver al chat">←</button>
          <span>Tus conversaciones</span>
        </div>
        <ul class="tutor-widget-historial-lista"></ul>
      </div>
      <form class="tutor-widget-form">
        <textarea class="tutor-widget-input" rows="1" placeholder="Escribe tu duda…" aria-label="Mensaje para Tu Tutor"></textarea>
        <button type="submit" class="tutor-widget-enviar" aria-label="Enviar">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z"/></svg>
        </button>
      </form>
    </section>
  `;
  document.body.appendChild(raiz);

  const fab = raiz.querySelector(".tutor-widget-fab");
  const panel = raiz.querySelector(".tutor-widget-panel");
  const cerrar = raiz.querySelector(".tutor-widget-cerrar");
  const mensajesEl = raiz.querySelector("#tutor-widget-mensajes");
  const typing = raiz.querySelector(".tutor-widget-typing");
  const form = raiz.querySelector(".tutor-widget-form");
  const input = raiz.querySelector(".tutor-widget-input");
  const btnNueva = raiz.querySelector(".tutor-widget-nueva");
  const btnHistorial = raiz.querySelector(".tutor-widget-historial-btn");
  const panelHistorial = raiz.querySelector(".tutor-widget-historial-panel");
  const listaHistorial = raiz.querySelector(".tutor-widget-historial-lista");
  const btnVolverHistorial = raiz.querySelector(".tutor-widget-historial-volver");
  const pin = raiz.querySelector(".tutor-widget-pin");
  const pinTexto = raiz.querySelector(".tutor-widget-pin-texto");
  const btnQuitarPin = raiz.querySelector(".tutor-widget-pin-quitar");

  // Cada apertura del widget arranca en una conversación NUEVA (no se
  // restaura la última): así, al abrirlo mientras haces un test, no se cuela
  // el historial de una pregunta anterior y "¿cuál es la correcta?" se
  // responde sobre la pregunta que tienes en pantalla, no sobre otra. Las
  // conversaciones anteriores siguen accesibles desde el botón de historial.
  let chatId = null;
  let sugerenciaPedida = false;
  let enviando = false;
  // Enunciado de la última pregunta de test sobre la que se preguntó: si
  // cambia (el usuario pasa a otra pregunta del test), se arranca una
  // conversación nueva para que el tutor no arrastre el historial de la
  // pregunta anterior y responda justo sobre la que tiene delante.
  let ultimoEnunciado = null;
  // Pregunta fijada desde fuera (p. ej. la pantalla de resultados manda "¿por
  // qué he fallado esta?" con la respuesta correcta). Mientras esté puesta,
  // se usa como contexto en vez de leer el DOM. Se limpia al empezar otra
  // conversación o al cargar una del historial.
  let contextoOverride = null;

  // Posición a la que el usuario ha arrastrado el chat (desplazamiento
  // respecto a su esquina por defecto). Se guarda para respetarla entre
  // aperturas. La burbuja cerrada siempre vuelve a su esquina; solo el panel
  // abierto se coloca donde el usuario lo dejó.
  const CLAVE_POS = "tutorWidgetPos";
  let posX = 0, posY = 0;
  try {
    const guardada = JSON.parse(localStorage.getItem(CLAVE_POS) || "null");
    if (guardada && window.innerWidth > 560) { posX = guardada.x || 0; posY = guardada.y || 0; }
  } catch { /* posición por defecto */ }

  // Tamaño al que el usuario ha estirado/encogido el chat. Se guarda para
  // respetarlo entre aperturas. Solo aplica en escritorio; en móvil el panel
  // ocupa siempre casi toda la pantalla, así que no se redimensiona.
  const CLAVE_TAM = "tutorWidgetTam";
  let anchoChat = null, altoChat = null;
  try {
    const g = JSON.parse(localStorage.getItem(CLAVE_TAM) || "null");
    if (g && window.innerWidth > 560) { anchoChat = g.w || null; altoChat = g.h || null; }
  } catch { /* tamaño por defecto */ }

  // Límites: ni tan pequeño que no se pueda leer, ni más grande que la ventana.
  function limitesTam() {
    return {
      minW: 300,
      minH: 380,
      maxW: Math.max(300, window.innerWidth - 32),
      maxH: Math.max(380, window.innerHeight - 90),
    };
  }
  // Pastilla visible en la cabecera mientras contextoOverride está fijado
  // (p. ej. viniendo del botón "Pregúntale a Tu Tutor" de una pregunta de
  // resultados): así, si el tutor alguna vez se queda "enganchado" a una
  // pregunta antigua, es fácil detectarlo a simple vista -- y quitarlo con
  // el botón "×" en vez de tener que abrir una conversación nueva.
  function mostrarPin(enunciado) {
    const extracto = (enunciado || "").slice(0, 60) + (enunciado.length > 60 ? "…" : "");
    pinTexto.textContent = "Hablando de: " + extracto;
    pin.hidden = false;
  }
  function ocultarPin() {
    pin.hidden = true;
    pinTexto.textContent = "";
  }
  btnQuitarPin.addEventListener("click", () => {
    contextoOverride = null;
    ocultarPin();
  });

  function aplicarTamano() {
    if (window.innerWidth <= 560) { panel.style.width = ""; panel.style.height = ""; return; }
    const { minW, minH, maxW, maxH } = limitesTam();
    panel.style.width = anchoChat ? Math.min(Math.max(anchoChat, minW), maxW) + "px" : "";
    panel.style.height = altoChat ? Math.min(Math.max(altoChat, minH), maxH) + "px" : "";
  }

  function aplicarPosicion(activa) {
    // En móvil el panel es `position: fixed` a pantalla completa; NUNCA se le
    // pone transform al contenedor, porque un transform (aunque sea de 0px)
    // convierte a `.tutor-widget` en el bloque contenedor del panel fijo y este
    // dejaría de anclarse a la ventana (se iría hacia la derecha, fuera de
    // pantalla). En móvil, mover el chat no aplica.
    if (window.innerWidth <= 560) { raiz.style.transform = ""; return; }
    raiz.style.transform = (activa && (posX || posY)) ? `translate(${posX}px, ${posY}px)` : "";
  }

  // Reencaja el panel dentro de la pantalla (por si la ventana se ha hecho
  // más pequeña desde la última vez que se arrastró) dejando un margen. En
  // móvil no hace nada: el panel ya ocupa toda la pantalla y aplicar cualquier
  // transform lo descolocaría (ver aplicarPosicion).
  function corregirDentroDePantalla() {
    if (window.innerWidth <= 560) { raiz.style.transform = ""; return; }
    const r = panel.getBoundingClientRect();
    const m = 8;
    if (r.left < m) posX += (m - r.left);
    if (r.top < m) posY += (m - r.top);
    if (r.right > window.innerWidth - m) posX -= (r.right - (window.innerWidth - m));
    if (r.bottom > window.innerHeight - m) posY -= (r.bottom - (window.innerHeight - m));
    aplicarPosicion(true);
  }

  const scrollAbajo = () => { mensajesEl.scrollTop = mensajesEl.scrollHeight; };
  // Mientras el bot está escribiendo en streaming, solo se sigue bajando el
  // scroll automáticamente si el usuario ya estaba abajo del todo -- si ha
  // subido a leer desde el principio de la respuesta, no se le fuerza hacia
  // abajo con cada trocito de texto que va llegando (dejaría de poder leer).
  const yaEstabaAbajo = () => mensajesEl.scrollHeight - mensajesEl.scrollTop - mensajesEl.clientHeight < 60;

  function abrir() {
    panel.classList.add("abierto");
    panel.setAttribute("aria-hidden", "false");
    fab.classList.add("oculto");
    raiz.querySelector(".tutor-widget-fab-punto")?.remove();
    aplicarTamano();
    aplicarPosicion(true);
    requestAnimationFrame(corregirDentroDePantalla);
    if (!sugerenciaPedida) { sugerenciaPedida = true; cargarSugerencia(); }
    setTimeout(() => input.focus(), 120);
  }
  function cerrarPanel() {
    panel.classList.remove("abierto");
    panel.setAttribute("aria-hidden", "true");
    fab.classList.remove("oculto");
    aplicarPosicion(false); // la burbuja vuelve siempre a su esquina
  }

  // Arrastre del chat por su cabecera (solo en pantallas grandes; en móvil el
  // panel ya ocupa casi toda la pantalla). No interfiere con los botones de la
  // cabecera. Doble clic en la cabecera devuelve el chat a su esquina.
  (function habilitarArrastre() {
    const cabecera = raiz.querySelector(".tutor-widget-cabecera");
    let arrastrando = false, iniX = 0, iniY = 0, baseX = 0, baseY = 0;
    cabecera.addEventListener("pointerdown", (e) => {
      if (window.innerWidth <= 560) return;
      if (e.target.closest(".tutor-widget-accion")) return; // pulsar un botón no arrastra
      arrastrando = true;
      iniX = e.clientX; iniY = e.clientY; baseX = posX; baseY = posY;
      cabecera.setPointerCapture(e.pointerId);
      cabecera.classList.add("arrastrando");
    });
    cabecera.addEventListener("pointermove", (e) => {
      if (!arrastrando) return;
      posX = baseX + (e.clientX - iniX);
      posY = baseY + (e.clientY - iniY);
      aplicarPosicion(true);
    });
    const fin = () => {
      if (!arrastrando) return;
      arrastrando = false;
      cabecera.classList.remove("arrastrando");
      corregirDentroDePantalla();
      try { localStorage.setItem(CLAVE_POS, JSON.stringify({ x: posX, y: posY })); } catch { /* nada */ }
    };
    cabecera.addEventListener("pointerup", fin);
    cabecera.addEventListener("pointercancel", fin);
    cabecera.addEventListener("dblclick", (e) => {
      if (e.target.closest(".tutor-widget-accion")) return;
      posX = 0; posY = 0; aplicarPosicion(false);
      try { localStorage.removeItem(CLAVE_POS); } catch { /* nada */ }
    });
    window.addEventListener("resize", () => { if (panel.classList.contains("abierto")) { aplicarTamano(); corregirDentroDePantalla(); } });
  })();

  // Redimensionar el chat tirando de la esquina superior izquierda (la libre,
  // porque el panel está anclado abajo-derecha): así el usuario lo agranda para
  // leer mejor o lo encoge para que no le tape el test. Doble clic restablece
  // el tamaño por defecto. Solo en escritorio; en móvil ocupa toda la pantalla.
  (function habilitarRedimension() {
    const asa = raiz.querySelector(".tutor-widget-resize");
    if (!asa) return;
    let activo = false, iniX = 0, iniY = 0, baseW = 0, baseH = 0;
    asa.addEventListener("pointerdown", (e) => {
      if (window.innerWidth <= 560) return;
      e.preventDefault();
      const r = panel.getBoundingClientRect();
      activo = true;
      iniX = e.clientX; iniY = e.clientY; baseW = r.width; baseH = r.height;
      asa.setPointerCapture(e.pointerId);
      asa.classList.add("activo");
    });
    asa.addEventListener("pointermove", (e) => {
      if (!activo) return;
      const { minW, minH, maxW, maxH } = limitesTam();
      // Anclado abajo-derecha: mover el asa hacia arriba-izquierda agranda.
      anchoChat = Math.min(Math.max(baseW + (iniX - e.clientX), minW), maxW);
      altoChat = Math.min(Math.max(baseH + (iniY - e.clientY), minH), maxH);
      panel.style.width = anchoChat + "px";
      panel.style.height = altoChat + "px";
    });
    const finRedim = () => {
      if (!activo) return;
      activo = false;
      asa.classList.remove("activo");
      corregirDentroDePantalla();
      try { localStorage.setItem(CLAVE_TAM, JSON.stringify({ w: anchoChat, h: altoChat })); } catch { /* nada */ }
    };
    asa.addEventListener("pointerup", finRedim);
    asa.addEventListener("pointercancel", finRedim);
    asa.addEventListener("dblclick", () => {
      anchoChat = null; altoChat = null;
      panel.style.width = ""; panel.style.height = "";
      try { localStorage.removeItem(CLAVE_TAM); } catch { /* nada */ }
    });
  })();

  fab.addEventListener("click", abrir);
  cerrar.addEventListener("click", cerrarPanel);
  btnNueva.addEventListener("click", nuevaConversacion);
  btnHistorial.addEventListener("click", abrirHistorial);
  btnVolverHistorial.addEventListener("click", cerrarHistorial);
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!panelHistorial.hidden) { cerrarHistorial(); return; }
    if (panel.classList.contains("abierto")) cerrarPanel();
  });

  // Empieza una conversación nueva (vacía): borra los mensajes en pantalla y
  // suelta el chat_id, para que el siguiente mensaje NO arrastre nada de la
  // conversación anterior. Es lo que evita que, al abrir el widget en un test,
  // conteste sobre una pregunta de antes.
  function nuevaConversacion() {
    cerrarHistorial();
    chatId = null;
    enviando = false;
    contextoOverride = null;
    ocultarPin();
    ultimoEnunciado = null;
    mensajesEl.innerHTML = "";
    sugerenciaPedida = true;
    cargarSugerencia();
    setTimeout(() => input.focus(), 60);
  }

  async function abrirHistorial() {
    listaHistorial.innerHTML = `<li class="tw-hist-cargando">Cargando…</li>`;
    panelHistorial.hidden = false;
    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;
    let conversaciones = [];
    try {
      const res = await fetch(`${BACKEND_URL}/conversaciones`, { headers: authHeaders });
      if (res.ok) conversaciones = (await res.json()).conversaciones || [];
    } catch { /* se muestra el vacío de abajo */ }

    if (!conversaciones.length) {
      listaHistorial.innerHTML = `<li class="tw-hist-vacio">Aún no tienes conversaciones guardadas.</li>`;
      return;
    }
    listaHistorial.innerHTML = "";
    conversaciones.forEach((conv) => {
      const li = document.createElement("li");
      li.className = "tw-hist-item";
      li.setAttribute("role", "button");
      li.setAttribute("tabindex", "0");
      li.textContent = conv.titulo || "Conversación";
      const abrir = () => cargarConversacion(conv.id);
      li.addEventListener("click", abrir);
      li.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); abrir(); } });
      listaHistorial.appendChild(li);
    });
  }

  function cerrarHistorial() {
    panelHistorial.hidden = true;
  }

  async function cargarConversacion(id) {
    cerrarHistorial();
    contextoOverride = null;
    ocultarPin();
    ultimoEnunciado = null;
    mensajesEl.innerHTML = `<div class="tw-msg tw-msg-bot"><div class="tw-msg-bot-contenido"><p>Cargando…</p></div></div>`;
    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;
    try {
      const res = await fetch(`${BACKEND_URL}/conversacion/${encodeURIComponent(id)}`, { headers: authHeaders });
      if (!res.ok) throw new Error("no");
      const data = await res.json();
      chatId = id;
      sugerenciaPedida = true; // no meter el saludo proactivo encima de una conversación cargada
      mensajesEl.innerHTML = "";
      (data.mensajes || []).forEach((m) => {
        if (m.role === "user") agregarUsuario(m.content);
        else agregarBotSimple(m.content);
      });
      scrollAbajo();
    } catch {
      mensajesEl.innerHTML = "";
      agregarBotSimple("No se pudo cargar la conversación.", "cruz");
    }
  }

  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 90) + "px";
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener("submit", (e) => { e.preventDefault(); enviarMensaje(); });

  function agregarUsuario(texto) {
    const div = document.createElement("div");
    div.className = "tw-msg tw-msg-user";
    div.textContent = texto;
    mensajesEl.appendChild(div);
    scrollAbajo();
  }

  function crearBurbujaBot() {
    const div = document.createElement("div");
    div.className = "tw-msg tw-msg-bot";
    div.innerHTML = `<div class="tw-msg-bot-contenido"></div>`;
    mensajesEl.appendChild(div);
    scrollAbajo();
    return { div, contenido: div.querySelector(".tw-msg-bot-contenido") };
  }

  function pintarBot(burbuja, texto) {
    const seguirAbajo = yaEstabaAbajo();
    burbuja.contenido.innerHTML = formatearMensajeBot(texto);
    if (seguirAbajo) scrollAbajo();
  }

  // iconoPrefijo (opcional): nombre de icono de /assets/icons.js que se
  // antepone al primer bloque del mensaje. Se inserta como SVG de confianza
  // DESPUÉS de que pintarBot()/formatearMensajeBot() ya hayan escapado el
  // texto, igual que en /tu-tutor/script.js -- así el icono nunca puede
  // colarse como HTML crudo si "texto" llegase a venir de fuera.
  function agregarBotSimple(texto, iconoPrefijo) {
    const b = crearBurbujaBot();
    pintarBot(b, texto);
    if (iconoPrefijo) {
      const primerBloque = b.contenido.querySelector("p, h4, li");
      if (primerBloque) primerBloque.insertAdjacentHTML("afterbegin", `${icono(iconoPrefijo, 15)} `);
    }
    return b;
  }

  function mostrarTyping(v) { typing.hidden = !v; if (v) scrollAbajo(); }

  // Saludo proactivo con la recomendación personalizada (tema flojo /
  // pendiente...). Si falla, se queda un saludo estático -- nunca bloquea.
  async function cargarSugerencia() {
    if (mensajesEl.children.length > 0) return; // ya hay conversación en curso
    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;
    let sugerencia = null;
    try {
      const oposicion = obtenerOposicionActual();
      const res = await fetch(`${BACKEND_URL}/tu-tutor/sugerencia-inicial?oposicion=${encodeURIComponent(oposicion)}`, { headers: authHeaders });
      if (res.ok) sugerencia = await res.json();
    } catch { /* saludo estático */ }

    const saludo = sugerencia?.saludo || "¡Hola!";
    const mensaje = sugerencia?.mensaje || "Soy Tu Tutor. Pregúntame cualquier duda sobre el temario o tu estudio.";
    agregarBotSimple(`**${saludo}**\n\n${mensaje}`, "mano");

    const sugerencias = Array.isArray(sugerencia?.sugerencias) ? sugerencia.sugerencias : ["¿Qué me recomiendas estudiar hoy?"];
    if (sugerencias.length) {
      const cont = document.createElement("div");
      cont.className = "tw-sugerencias";
      sugerencias.slice(0, 3).forEach((txt) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "tw-sugerencia-btn";
        btn.textContent = txt;
        btn.addEventListener("click", () => { input.value = txt; enviarMensaje(); });
        cont.appendChild(btn);
      });
      mensajesEl.appendChild(cont);
      scrollAbajo();
    }
  }

  async function enviarMensaje() {
    const texto = input.value.trim();
    if (!texto || enviando) return;
    enviando = true;
    // Las sugerencias iniciales dejan de tener sentido una vez se escribe.
    mensajesEl.querySelector(".tw-sugerencias")?.remove();
    agregarUsuario(texto);
    input.value = "";
    input.style.height = "auto";

    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) { enviando = false; return; }

    mostrarTyping(true);
    const oposicion = obtenerOposicionActual();

    // Si está haciendo un test, se adjunta la pregunta que tiene en pantalla
    // para que el tutor pueda ayudarle con ella sin copiarla. Y si ha pasado a
    // una pregunta distinta desde el último mensaje, se empieza conversación
    // nueva (chatId=null) para no arrastrar el historial de la anterior.
    const contextoPagina = contextoOverride || leerPreguntaEnPantalla();
    if (contextoPagina) {
      if (chatId && contextoPagina.enunciado !== ultimoEnunciado) chatId = null;
      ultimoEnunciado = contextoPagina.enunciado;
    }

    // Si el contexto viene de una lectura en vivo de la pregunta en pantalla
    // (no de un contextoOverride fijo, como el de "¿por qué he fallado esta?"
    // desde resultados), se puede comprobar más adelante -- mientras dura el
    // streaming -- si el usuario ha pasado a otra pregunta antes de que
    // llegue la respuesta.
    const veniaDePantalla = !contextoOverride && !!contextoPagina && contextoPagina.tipo === "test";
    const enunciadoDeEstaPeticion = contextoPagina ? contextoPagina.enunciado : null;

    // La pastilla "Hablando de..." también se muestra para la pregunta que
    // el usuario tiene delante en un test EN CURSO, no solo para el
    // contextoOverride fijado desde la pantalla de resultados.
    if (veniaDePantalla) {
      mostrarPin(contextoPagina.enunciado);
    } else if (!contextoOverride) {
      ocultarPin();
    }

    let respuesta;
    try {
      respuesta = await fetch(`${BACKEND_URL}/tu-tutor/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ mensaje: texto, chat_id: chatId, oposicion, contexto_pagina: contextoPagina }),
        signal: AbortSignal.timeout(60000),
      });
    } catch {
      mostrarTyping(false);
      agregarBotSimple("Error al conectar con el servidor.", "cruz");
      enviando = false;
      return;
    }

    mostrarTyping(false);

    if (respuesta.status === 403) {
      agregarBotSimple("Tu Tutor forma parte del plan Premium. Actívalo en la página de [Planes](/planes/) para poder chatear.", "candado");
      // El markdown-lite no genera <a>; se pone un enlace real aparte.
      const enlace = document.createElement("a");
      enlace.className = "tw-cta-planes";
      enlace.href = "/planes/";
      enlace.textContent = "Ver planes";
      mensajesEl.appendChild(enlace);
      scrollAbajo();
      enviando = false;
      return;
    }
    if (respuesta.status === 429) {
      const datos = await respuesta.json().catch(() => ({}));
      agregarBotSimple(datos.error || "Has alcanzado el límite de uso del chat por ahora.", "arena");
      const enlace = document.createElement("a");
      enlace.className = "tw-cta-planes";
      enlace.href = "/planes/";
      enlace.textContent = "Ver planes";
      mensajesEl.appendChild(enlace);
      scrollAbajo();
      enviando = false;
      return;
    }
    if (!respuesta.ok || !respuesta.body) {
      agregarBotSimple(ERROR_TECNICO, "alerta");
      enviando = false;
      return;
    }

    const burbuja = crearBurbujaBot();
    const lector = respuesta.body.getReader();
    const decodificador = new TextDecoder();
    let buffer = "";
    let acumulado = "";
    let huboError = false;
    let respuestaDesactualizada = false;

    try {
      while (true) {
        const { done, value } = await leerStreamConTimeout(lector);
        if (done) break;
        buffer += decodificador.decode(value, { stream: true });
        const bloques = buffer.split("\n\n");
        buffer = bloques.pop();
        for (const bloque of bloques) {
          const linea = bloque.trim();
          if (!linea.startsWith("data: ")) continue;
          let evento;
          try { evento = JSON.parse(linea.slice(6)); } catch { continue; }
          if (evento.tipo === "delta") {
            acumulado += evento.texto;
            pintarBot(burbuja, acumulado);
            // El streaming tarda varios segundos: si el usuario ha pasado a
            // otra pregunta mientras tanto, la respuesta que se está pintando
            // ya no corresponde a lo que tiene delante -- se sigue pintando
            // igual (ya ha consumido cupo y puede seguir siendo útil), pero
            // se avisa al terminar.
            if (veniaDePantalla && !respuestaDesactualizada) {
              const preguntaActual = leerPreguntaEnPantalla();
              if (!preguntaActual || preguntaActual.enunciado !== enunciadoDeEstaPeticion) {
                respuestaDesactualizada = true;
              }
            }
          }
          else if (evento.tipo === "fin") { chatId = evento.chat_id; }
          else if (evento.tipo === "error") { huboError = true; }
        }
      }
    } catch { huboError = true; }

    if (huboError && !acumulado) {
      burbuja.div.remove();
      agregarBotSimple(ERROR_TECNICO, "alerta");
    } else if (huboError && acumulado) {
      const aviso = document.createElement("div");
      aviso.className = "tw-aviso-cortada";
      aviso.innerHTML = `${icono("alerta", 15)} Respuesta incompleta`;
      burbuja.div.appendChild(aviso);
    } else if (respuestaDesactualizada) {
      const aviso = document.createElement("div");
      aviso.className = "tw-aviso-cortada";
      aviso.innerHTML = `${icono("alerta", 15)} Esta respuesta era sobre la pregunta anterior -- si quieres ayuda con la que tienes ahora delante, vuelve a preguntar.`;
      burbuja.div.appendChild(aviso);
    }
    enviando = false;
  }

  // API pública para que otras partes de la web abran el chat con una pregunta
  // concreta ya cargada (p. ej. la pantalla de resultados: "¿por qué he
  // fallado esta?"). Fija la pregunta como contexto y, si se pasa un mensaje
  // inicial, lo envía solo.
  window.tutorWidget = {
    abrir,
    abrirConPregunta(pregunta = {}) {
      const opciones = pregunta.opciones && typeof pregunta.opciones === "object" ? pregunta.opciones : {};
      contextoOverride = {
        tipo: "test",
        enunciado: String(pregunta.enunciado || ""),
        opciones,
        respuesta_correcta: pregunta.respuestaCorrecta || pregunta.respuesta_correcta || "",
        respuesta_usuario: pregunta.respuestaUsuario || pregunta.respuesta_usuario || "",
        explicacion: pregunta.explicacion || "",
      };
      // No se reinicia chatId: si ya se venía hablando de otra pregunta en
      // esta misma sesión (sin recargar la página), esta también se guarda
      // en la MISMA conversación -- así en "Tus conversaciones" no aparece
      // una entrada nueva por cada pregunta del test, sino una sola con
      // todo lo hablado. Esto es seguro porque el backend ya trata cada
      // pregunta de test como autocontenida (no le mete el historial de
      // mensajes anteriores al construir la respuesta, ver chat_controller
      // "Una pregunta de test pegada es autocontenida"), así que el tutor
      // no arrastra ni se confunde con la pregunta anterior aunque
      // compartan chat_id.
      ultimoEnunciado = contextoOverride.enunciado;
      sugerenciaPedida = true;   // no meter el saludo proactivo encima
      mensajesEl.innerHTML = "";
      mostrarPin(contextoOverride.enunciado);
      abrir();
      if (pregunta.mensajeInicial) {
        input.value = pregunta.mensajeInicial;
        enviarMensaje();
      }
    },
  };
}
