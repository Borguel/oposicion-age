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

// El chat_id vive en sessionStorage para que, al navegar de una página de
// estudio a otra, se siga la MISMA conversación en vez de empezar una nueva
// cada vez. Se borra al cerrar la pestaña (sessionStorage), no se acumula.
const CLAVE_CHAT_ID = "tutorWidgetChatId";

const ERROR_TECNICO = "⚠️ El tutor ha tenido un problema técnico. Vuelve a intentarlo en unos segundos.";

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
  const bloque = document.querySelector(".pregunta-en-negrita");
  if (!bloque) return null;
  const span = bloque.querySelector("span");
  // Se quita la numeración inicial ("12. ") que añade la vista del test.
  const enunciado = (span ? span.textContent : "").replace(/^\s*\d+\s*[.)]\s*/, "").trim();
  if (!enunciado) return null;
  const opciones = {};
  document.querySelectorAll(".opcion-respuesta").forEach((label) => {
    const letra = label.querySelector(".opcion-letra")?.textContent.trim();
    const texto = label.querySelector(".opcion-texto")?.textContent.trim();
    if (letra && texto) opciones[letra] = texto;
  });
  return { tipo: "test", enunciado, opciones };
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
      <header class="tutor-widget-cabecera">
        <div class="tutor-widget-cabecera-info">
          <img src="/assets/tutor-avatar.svg" alt="" width="28" height="28" />
          <div>
            <strong>Tu Tutor</strong>
            <span class="tutor-widget-estado">Aquí para ayudarte</span>
          </div>
        </div>
        <div class="tutor-widget-cabecera-acciones">
          <a href="/tu-tutor/" class="tutor-widget-expandir" aria-label="Abrir el chat completo" title="Abrir chat completo">⤢</a>
          <button type="button" class="tutor-widget-cerrar" aria-label="Cerrar">✕</button>
        </div>
      </header>
      <div class="tutor-widget-mensajes" id="tutor-widget-mensajes"></div>
      <div class="tutor-widget-typing" hidden><span></span><span></span><span></span></div>
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

  let chatId = sessionStorage.getItem(CLAVE_CHAT_ID) || null;
  let sugerenciaPedida = false;
  let enviando = false;

  const scrollAbajo = () => { mensajesEl.scrollTop = mensajesEl.scrollHeight; };

  function abrir() {
    panel.classList.add("abierto");
    panel.setAttribute("aria-hidden", "false");
    fab.classList.add("oculto");
    raiz.querySelector(".tutor-widget-fab-punto")?.remove();
    if (!sugerenciaPedida) { sugerenciaPedida = true; cargarSugerencia(); }
    setTimeout(() => input.focus(), 120);
  }
  function cerrarPanel() {
    panel.classList.remove("abierto");
    panel.setAttribute("aria-hidden", "true");
    fab.classList.remove("oculto");
  }

  fab.addEventListener("click", abrir);
  cerrar.addEventListener("click", cerrarPanel);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && panel.classList.contains("abierto")) cerrarPanel();
  });

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
    burbuja.contenido.innerHTML = formatearMensajeBot(texto);
    scrollAbajo();
  }

  function agregarBotSimple(texto) {
    const b = crearBurbujaBot();
    pintarBot(b, texto);
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

    const saludo = sugerencia?.saludo || "¡Hola! 👋";
    const mensaje = sugerencia?.mensaje || "Soy Tu Tutor. Pregúntame cualquier duda sobre el temario o tu estudio.";
    agregarBotSimple(`**${saludo}**\n\n${mensaje}`);

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
    // para que el tutor pueda ayudarle con ella sin copiarla.
    const contextoPagina = leerPreguntaEnPantalla();

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
      agregarBotSimple("❌ Error al conectar con el servidor.");
      enviando = false;
      return;
    }

    mostrarTyping(false);

    if (respuesta.status === 403) {
      agregarBotSimple("🔒 Tu Tutor forma parte del plan Premium. Actívalo en la página de [Planes](/planes/) para poder chatear.");
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
      agregarBotSimple(`⏳ ${datos.error || "Has alcanzado el límite de uso del chat por ahora."}`);
      enviando = false;
      return;
    }
    if (!respuesta.ok || !respuesta.body) {
      agregarBotSimple(ERROR_TECNICO);
      enviando = false;
      return;
    }

    const burbuja = crearBurbujaBot();
    const lector = respuesta.body.getReader();
    const decodificador = new TextDecoder();
    let buffer = "";
    let acumulado = "";
    let huboError = false;

    try {
      while (true) {
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
          if (evento.tipo === "delta") { acumulado += evento.texto; pintarBot(burbuja, acumulado); }
          else if (evento.tipo === "fin") { chatId = evento.chat_id; if (chatId) sessionStorage.setItem(CLAVE_CHAT_ID, chatId); }
          else if (evento.tipo === "error") { huboError = true; }
        }
      }
    } catch { huboError = true; }

    if (huboError && !acumulado) {
      burbuja.div.remove();
      agregarBotSimple(ERROR_TECNICO);
    } else if (huboError && acumulado) {
      const aviso = document.createElement("div");
      aviso.className = "tw-aviso-cortada";
      aviso.textContent = "⚠️ Respuesta incompleta";
      burbuja.div.appendChild(aviso);
    }
    enviando = false;
  }
}
