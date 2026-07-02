// ===== FUNCIONES AUXILIARES =====
function escapeHtml(text) {
  const map = { '&': '&amp;', '<': '<', '>': '>', '"': '&quot;', "'": '&#039;' };
  return text.replace(/[&<>"']/g, m => map[m]);
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
  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send");
  const chatMessages = document.getElementById("chat-messages");
  const toggleSidebar = document.getElementById("toggle-sidebar");
  const chatSidebar = document.getElementById("chat-sidebar");
  const chatHistory = document.getElementById("chat-history");
  const sidebarOverlay = document.getElementById("sidebar-overlay");
  const typingIndicator = document.getElementById("typing-indicator");

  // Botón X móvil
  const cerrarChat = document.getElementById("cerrar-chat-total");
  if (cerrarChat) {
    cerrarChat.addEventListener("click", () => {
      window.location.href = "https://lightslategray-caribou-622401.hostingersite.com/panel-de-usuario/";
    });
  }

  // SIDEBAR
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
    if (
      window.innerWidth <= 950 &&
      chatSidebar.classList.contains("visible") &&
      !chatSidebar.contains(e.target) &&
      e.target !== toggleSidebar
    ) {
      closeSidebar();
    }
  });

  sidebarOverlay?.addEventListener("click", closeSidebar);

  // GESTIÓN DE MENSAJES
  function agregarMensaje(tipo, texto) {
    const safeText = escapeHtml(texto);
    const div = document.createElement("div");
    if (tipo === "user") {
      div.className = "mensaje-user";
      div.innerHTML = `<div class="bubble-user">${safeText}</div>`;
    } else {
      const copyBtn = `<button onclick="copyToClipboard(${JSON.stringify(texto)})" title="Copiar">📋</button>`;
      div.className = "mensaje-bot";
      div.innerHTML = `
        <div class="avatar-bot-mini">
          <img src="https://randomuser.me/api/portraits/women/44.jpg" alt="Asistente IA" />
        </div>
        <div class="bubble-bot">
          ${safeText}
          <div class="bubble-bot-actions">${copyBtn}</div>
        </div>
      `;
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
  function enviarMensaje() {
    const texto = input.value.trim();
    if (!texto) return;

    agregarMensaje("user", texto);
    input.value = "";
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 110) + "px";

    mostrarTyping(true);

    fetch("https://oposicion-age.onrender.com/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mensaje: texto,
        temas: [],
        usuario_id: typeof usuarioEmail !== "undefined" ? usuarioEmail : "anonimo",
        chat_id: chatIdActual
      }),
      signal: AbortSignal.timeout(10000)
    })
      .then(res => {
        mostrarTyping(false);
        return res.json();
      })
      .then(data => {
        agregarMensaje("bot", data.respuesta || "Sin respuesta.");
        chatIdActual = data.chat_id;
        cargarHistorial();
      })
      .catch(() => {
        mostrarTyping(false);
        agregarMensaje("bot", "❌ Error al conectar con el servidor.");
      });
  }

  // HISTORIAL
  let conversaciones = [];
  let chatIdActual = null;

  function cargarHistorial() {
    const id = typeof usuarioEmail !== "undefined" ? usuarioEmail : "anonimo";
    fetch(`https://oposicion-age.onrender.com/conversaciones?usuario_id=${encodeURIComponent(id)}`)
      .then(res => res.json())
      .then(data => {
        conversaciones = data.conversaciones || [];
        mostrarHistorialEnSidebar();
      })
      .catch(err => console.error("❌ Error al cargar historial:", err));
  }

  function mostrarHistorialEnSidebar() {
    chatHistory.innerHTML = "";
    const nueva = document.createElement("li");
    nueva.textContent = "➕ Nueva conversación";
    nueva.setAttribute("role", "button");
    nueva.setAttribute("tabindex", "0");
    nueva.onclick = iniciarNuevaConversacion;
    nueva.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") iniciarNuevaConversacion(); };
    chatHistory.appendChild(nueva);

    conversaciones.forEach((conv) => {
      const li = document.createElement("li");
      li.textContent = conv.titulo || "Conversación";
      li.dataset.id = conv.id;
      li.setAttribute("role", "button");
      li.setAttribute("tabindex", "0");
      li.onclick = () => cargarConversacion(conv.id);
      li.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") cargarConversacion(conv.id); };
      chatHistory.appendChild(li);
    });
  }

  function cargarConversacion(id) {
    chatMessages.innerHTML = "";
    chatIdActual = id;
    mostrarTyping(true);
    const idUser = typeof usuarioEmail !== "undefined" ? usuarioEmail : "anonimo";
    fetch(`https://oposicion-age.onrender.com/conversacion/${id}?usuario_id=${encodeURIComponent(idUser)}`)
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
    chatMessages.innerHTML = "";
    chatIdActual = null;
    document.querySelectorAll("#chat-history li").forEach(li => li.classList.remove("active"));
    if (window.innerWidth <= 950) closeSidebar();
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
    window.location.href = "https://lightslategray-caribou-622401.hostingersite.com/panel-de-usuario/";
  });

  // INICIO
  cargarHistorial();
});
