// ===== AUTENTICACIÓN =====
async function obtenerAuthHeaders() {
  const { idToken } = await import("/assets/auth.js");
  const token = await idToken();
  if (!token) {
    window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
    return null;
  }
  return { "Authorization": "Bearer " + token };
}

// El chat en sí (historial, ajustes, mensajes) se podía ver y usar entero
// sin haber iniciado sesión -- solo se pedía login al primer intento de
// enviar un mensaje. Ahora se exige nada más cargar la página.
obtenerAuthHeaders();

// ===== FUNCIONES AUXILIARES =====
function escapeHtml(text) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return text.replace(/[&<>"']/g, m => map[m]);
}

// Markdown ligero para las respuestas de la IA: escapa todo el HTML primero
// (nunca se inyecta HTML crudo del modelo) y luego traduce solo la sintaxis
// básica que el modelo suele usar (encabezados, negrita, cursiva, listas) a
// las mismas etiquetas que ya tiene estilizadas .bubble-bot en el CSS.
function formatearMensajeBot(texto) {
  const lineas = escapeHtml(texto).split("\n");
  let html = "";
  let dentroDeLista = false;
  const cerrarLista = () => {
    if (dentroDeLista) {
      html += "</ul>";
      dentroDeLista = false;
    }
  };
  for (const lineaOriginal of lineas) {
    const linea = lineaOriginal.trim();
    const encabezado = linea.match(/^#{1,6}\s+(.*)$/);
    const item = linea.match(/^[-*]\s+(.*)$/);
    if (encabezado) {
      cerrarLista();
      html += `<h3>${aplicarEnfasis(encabezado[1])}</h3>`;
    } else if (item) {
      if (!dentroDeLista) {
        html += "<ul>";
        dentroDeLista = true;
      }
      html += `<li>${aplicarEnfasis(item[1])}</li>`;
    } else if (linea === "") {
      cerrarLista();
    } else {
      cerrarLista();
      html += `<p>${aplicarEnfasis(linea)}</p>`;
    }
  }
  cerrarLista();
  return html;
}

function aplicarEnfasis(texto) {
  return texto
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>");
}

function copyToClipboard(text) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).catch(console.error);
  } else {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
  }
}

// ===== LÓGICA PRINCIPAL =====
document.addEventListener("DOMContentLoaded", function () {
  const contenedor = document.getElementById("tutor-container");
  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send");
  const chatMessages = document.getElementById("chat-messages");
  const mensajeBienvenidaHTML = chatMessages.innerHTML;
  const toggleSidebar = document.getElementById("toggle-sidebar");
  const chatSidebar = document.getElementById("chat-sidebar");
  const chatHistory = document.getElementById("chat-history");
  const sidebarOverlay = document.getElementById("sidebar-overlay");
  const typingIndicator = document.getElementById("typing-indicator");

  // Cerrar chat (botón de la cabecera): siempre vuelve a Zona Opositor,
  // no a la home genérica -- es de donde se accede a Tu Tutor.
  document.getElementById("cerrar-chat-total")?.addEventListener("click", () => {
    window.location.href = "/zona-opositor/";
  });

  // SIDEBAR (historial)
  toggleSidebar.addEventListener("click", () => {
    chatSidebar.classList.toggle("visible");
    if (window.innerWidth <= 950) {
      sidebarOverlay.style.display = chatSidebar.classList.contains("visible") ? "block" : "none";
    }
  });

  function closeSidebar() {
    chatSidebar.classList.remove("visible");
    sidebarOverlay.style.display = "none";
  }

  document.addEventListener("click", (e) => {
    // toggleSidebar.contains(e.target) (no "!== toggleSidebar") porque el
    // icono es un <svg> con <path> hijos: al tocarlo, e.target es ese
    // <path>/<svg> interior, no el propio <button>, así que compararlo por
    // igualdad estricta hacía que este mismo clic que abría la barra la
    // volviera a cerrar en el acto.
    if (
      window.innerWidth <= 950 &&
      chatSidebar.classList.contains("visible") &&
      !chatSidebar.contains(e.target) &&
      !toggleSidebar.contains(e.target)
    ) {
      closeSidebar();
    }
  });

  sidebarOverlay?.addEventListener("click", closeSidebar);

  // PANEL DE PERSONALIZACIÓN (color de acento + modo oscuro)
  const settingsToggle = document.getElementById("settings-toggle");
  const settingsPanel = document.getElementById("settings-panel");
  const closeSettings = document.getElementById("close-settings");
  const colorOptions = document.querySelectorAll(".color-option");
  const darkModeToggle = document.getElementById("dark-mode-toggle");

  settingsToggle.addEventListener("click", () => settingsPanel.classList.toggle("active"));
  closeSettings.addEventListener("click", () => settingsPanel.classList.remove("active"));

  const acentoGuardado = localStorage.getItem("tutorAcento");
  if (acentoGuardado) {
    contenedor.dataset.acento = acentoGuardado;
    colorOptions.forEach(op => op.classList.toggle("active", op.dataset.acento === acentoGuardado));
  }
  colorOptions.forEach(op => {
    op.addEventListener("click", () => {
      const acento = op.dataset.acento;
      contenedor.dataset.acento = acento;
      localStorage.setItem("tutorAcento", acento);
      colorOptions.forEach(o => o.classList.toggle("active", o === op));
    });
  });

  // El modo oscuro es una preferencia global del sitio (misma variable que
  // usa el botón de la barra de navegación, data-theme + "age-theme" en
  // localStorage), no un ajuste propio de esta página -- así no quedan
  // desincronizados el interruptor de aquí y el de la barra de navegación.
  darkModeToggle.checked = document.documentElement.dataset.theme === "dark";
  darkModeToggle.addEventListener("change", () => {
    if (darkModeToggle.checked) {
      document.documentElement.dataset.theme = "dark";
      localStorage.setItem("age-theme", "dark");
    } else {
      delete document.documentElement.dataset.theme;
      localStorage.setItem("age-theme", "light");
    }
  });

  // PREGUNTAS RÁPIDAS
  document.querySelectorAll(".quick-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      input.value = btn.textContent;
      enviarMensaje();
    });
  });

  // GESTIÓN DE MENSAJES
  function agregarMensaje(tipo, texto) {
    const safeText = escapeHtml(texto);
    const div = document.createElement("div");
    if (tipo === "user") {
      div.className = "mensaje-user";
      div.innerHTML = `<div class="bubble-user">${safeText}</div>`;
    } else {
      div.className = "mensaje-bot";
      div.innerHTML = `
        <div class="avatar-bot-mini">
          <img src="https://randomuser.me/api/portraits/women/44.jpg" alt="Tu Tutor" />
        </div>
        <div class="bubble-bot">
          ${formatearMensajeBot(texto)}
          <div class="bubble-bot-actions"><button type="button" class="btn-copiar-mensaje" title="Copiar">📋</button></div>
        </div>
      `;
      // addEventListener con "texto" capturado por closure, en vez de un
      // onclick inline: no depende de 'unsafe-inline' en el CSP.
      div.querySelector(".btn-copiar-mensaje").addEventListener("click", () => copyToClipboard(texto));
    }
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function mostrarTyping(show) {
    typingIndicator.style.display = show ? "flex" : "none";
    if (show) {
      chatMessages.scrollTop = chatMessages.scrollHeight;
    }
  }

  // ENVÍO
  async function enviarMensaje() {
    const texto = input.value.trim();
    if (!texto) return;

    agregarMensaje("user", texto);
    input.value = "";
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 110) + "px";

    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;

    mostrarTyping(true);

    const { obtenerOposicionActual } = await import("/assets/oposicion.js");
    const oposicion = obtenerOposicionActual();

    fetch("https://oposicion-age.onrender.com/tu-tutor", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders },
      body: JSON.stringify({
        mensaje: texto,
        chat_id: chatIdActual,
        oposicion
      }),
      signal: AbortSignal.timeout(30000)
    })
      .then(async res => {
        mostrarTyping(false);
        if (res.status === 403) {
          agregarMensaje("bot", "🔒 Tu Tutor requiere el plan Premium. Ve a /planes/ para activarlo.");
          return null;
        }
        if (res.status === 429) {
          const datosError = await res.json();
          agregarMensaje("bot", `⏳ ${datosError.error || "Has alcanzado el límite de uso del chat por ahora."}`);
          return null;
        }
        return res.json();
      })
      .then(data => {
        if (!data) return;
        agregarMensaje("bot", data.respuesta || "Sin respuesta.");
        chatIdActual = data.chat_id;
        cargarHistorial();
      })
      .catch(() => {
        mostrarTyping(false);
        agregarMensaje("bot", "❌ Error al conectar con el servidor.");
      });
  }

  // HISTORIAL (persistido en Firestore, no en localStorage)
  let conversaciones = [];
  let chatIdActual = null;

  async function cargarHistorial() {
    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;
    fetch("https://oposicion-age.onrender.com/conversaciones", { headers: authHeaders })
      .then(res => res.json())
      .then(data => {
        conversaciones = data.conversaciones || [];
        mostrarHistorialEnSidebar();
      })
      .catch(err => console.error("❌ Error al cargar historial:", err));
  }

  function mostrarHistorialEnSidebar() {
    chatHistory.innerHTML = "";
    if (conversaciones.length === 0) {
      const vacio = document.createElement("li");
      vacio.className = "chat-history-vacio";
      vacio.textContent = "Aún no tienes conversaciones.";
      chatHistory.appendChild(vacio);
      return;
    }

    conversaciones.forEach((conv) => {
      const li = document.createElement("li");
      li.className = "chat-history-item";
      li.dataset.id = conv.id;
      li.setAttribute("role", "button");
      li.setAttribute("tabindex", "0");
      li.innerHTML = `
        <span class="chat-history-titulo">${escapeHtml(conv.titulo || "Conversación")}</span>
        <button type="button" class="btn-borrar-conversacion" aria-label="Borrar conversación" title="Borrar">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-1 14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2L4 6h16Z"/></svg>
        </button>
      `;
      li.addEventListener("click", () => cargarConversacion(conv.id));
      li.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") cargarConversacion(conv.id); });
      li.querySelector(".btn-borrar-conversacion").addEventListener("click", (e) => {
        e.stopPropagation();
        confirmarBorrarConversacion(conv.id);
      });
      chatHistory.appendChild(li);
    });
  }

  async function confirmarBorrarConversacion(id) {
    const resultado = await Swal.fire({
      title: "¿Borrar esta conversación?",
      text: "No podrás deshacer esta acción.",
      icon: "warning",
      showCancelButton: true,
      confirmButtonText: "Borrar",
      cancelButtonText: "Cancelar",
      confirmButtonColor: "var(--age-danger)"
    });
    if (!resultado.isConfirmed) return;

    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;
    try {
      const res = await fetch(`https://oposicion-age.onrender.com/conversacion/${id}`, {
        method: "DELETE",
        headers: authHeaders
      });
      if (!res.ok) throw new Error("No se pudo borrar");
      if (chatIdActual === id) iniciarNuevaConversacion();
      await cargarHistorial();
    } catch {
      Swal.fire("Error", "No se pudo borrar la conversación. Inténtalo de nuevo.", "error");
    }
  }

  async function cargarConversacion(id) {
    chatMessages.innerHTML = "";
    chatIdActual = id;
    mostrarTyping(true);
    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;
    fetch(`https://oposicion-age.onrender.com/conversacion/${id}`, { headers: authHeaders })
      .then(res => res.json())
      .then(data => {
        mostrarTyping(false);
        if (data.mensajes) {
          data.mensajes.forEach(m => {
            agregarMensaje(m.role === "user" ? "user" : "bot", m.content);
          });
        }
      })
      .catch(() => {
        mostrarTyping(false);
        agregarMensaje("bot", "❌ No se pudo cargar la conversación.");
      });

    document.querySelectorAll("#chat-history li").forEach(li => {
      li.classList.remove("active");
      if (li.dataset.id === id) li.classList.add("active");
    });
    if (window.innerWidth <= 950) closeSidebar();
  }

  function iniciarNuevaConversacion() {
    chatMessages.innerHTML = mensajeBienvenidaHTML;
    reengancharPreguntasRapidas();
    chatIdActual = null;
    document.querySelectorAll("#chat-history li").forEach(li => li.classList.remove("active"));
    if (window.innerWidth <= 950) closeSidebar();
  }

  function reengancharPreguntasRapidas() {
    chatMessages.querySelectorAll(".quick-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        input.value = btn.textContent;
        enviarMensaje();
      });
    });
  }

  // EVENTOS
  sendBtn.addEventListener("click", enviarMensaje);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      enviarMensaje();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 110) + "px";
  });

  // SALIR
  document.getElementById("salir-del-chat-sidebar")?.addEventListener("click", () => {
    window.location.href = "/zona-opositor/";
  });
  document.getElementById("nueva-conversacion-btn")?.addEventListener("click", iniciarNuevaConversacion);

  // INICIO
  cargarHistorial();
});
