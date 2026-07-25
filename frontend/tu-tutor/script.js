import { icono } from "/assets/icons.js";
import { leerStreamConTimeout } from "/assets/stream-utils.js";

// Se resuelve aquí, en el nivel superior del módulo (que se ejecuta
// "deferred" pero SIEMPRE antes de DOMContentLoaded), y no dentro del
// listener de más abajo: así "mensajeBienvenidaHTML" captura el SVG ya
// insertado, no el marcador data-icon sin resolver.
document.querySelectorAll("[data-icon]").forEach((el) => {
  el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 24));
});

// ===== AUTENTICACIÓN =====
async function obtenerAuthHeaders() {
  const { obtenerAuthHeaders: fn } = await import("/assets/auth.js");
  return fn();
}

// El chat en sí (historial, ajustes, mensajes) se podía ver y usar entero
// sin haber iniciado sesión -- solo se pedía login al primer intento de
// enviar un mensaje. Ahora se exige nada más cargar la página.
obtenerAuthHeaders();

// ===== FUNCIONES AUXILIARES =====
// Los títulos del temario pueden ser epígrafes muy largos ("La Administración
// General del Estado: principios de organización y funcionamiento. Órganos
// centrales..."). Para las etiquetas de los botones se corta por el primer
// ":" o "." (que suele dejar el nombre principal del tema) y, si aún es largo,
// se recorta con puntos suspensivos -- así el botón no se convierte en un
// bloque gigante de varias líneas.
function acortarTitulo(titulo) {
  const base = (String(titulo || "").split(/[:.]/)[0] || String(titulo || "")).trim();
  return base.length > 55 ? base.slice(0, 55).trim() + "…" : base;
}

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

// Devuelve una promesa que se resuelve con true/false según si la copia
// tuvo éxito, para que quien llame pueda dar alguna señal visual -- antes
// un fallo de navigator.clipboard.writeText (p. ej. permiso denegado) no
// se notaba de ninguna forma, el botón "copiar" simplemente no hacía nada.
async function copyToClipboard(text) {
  if (navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      console.error("No se pudo copiar al portapapeles:", e);
      return false;
    }
  }
  try {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    document.body.appendChild(textarea);
    textarea.select();
    const exito = document.execCommand('copy');
    document.body.removeChild(textarea);
    return exito;
  } catch (e) {
    console.error("No se pudo copiar al portapapeles:", e);
    return false;
  }
}

// ===== LÓGICA PRINCIPAL =====
document.addEventListener("DOMContentLoaded", async function () {
  const { protegerPagina } = await import("/assets/plan.js");
  if (!(await protegerPagina("premium"))) return;

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

  // AUTOSCROLL "PEGAJOSO": mientras el tutor va escribiendo (streaming), solo
  // seguimos bajando la vista si el usuario ya estaba abajo del todo -- si ha
  // subido a releer un mensaje anterior, se queda donde está en vez de que
  // cada fragmento nuevo le arrastre hacia el final. irAlFinal() se usa para
  // los saltos "forzados" (el usuario acaba de enviar algo, o de pulsar un
  // botón que genera una respuesta nueva); irAlFinalSiProcede() es la versión
  // que respeta la posición de scroll durante el streaming.
  const UMBRAL_SCROLL_FINAL = 80;
  const scrollAbajoBtn = document.getElementById("scroll-to-bottom");

  function cercaDelFinal() {
    return chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight <= UMBRAL_SCROLL_FINAL;
  }
  function actualizarBotonScroll() {
    if (scrollAbajoBtn) scrollAbajoBtn.style.display = cercaDelFinal() ? "none" : "flex";
  }
  function irAlFinal() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
    actualizarBotonScroll();
  }
  function irAlFinalSiProcede() {
    if (cercaDelFinal()) irAlFinal();
    else actualizarBotonScroll();
  }
  chatMessages.addEventListener("scroll", actualizarBotonScroll);
  scrollAbajoBtn?.addEventListener("click", irAlFinal);

  // PREGUNTAS RÁPIDAS
  document.querySelectorAll(".quick-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      input.value = btn.textContent;
      enviarMensaje();
    });
  });

  // GESTIÓN DE MENSAJES
  // iconoPrefijo (opcional): nombre de icono de /assets/icons.js que se
  // antepone al primer bloque del mensaje. Se inserta como SVG de confianza
  // (viene siempre de nuestro propio código, nunca del texto en sí) DESPUÉS
  // de que formatearMensajeBot() ya haya escapado el texto -- así un icono
  // no puede colarse como HTML crudo si algún día "texto" viene de fuera.
  function agregarMensaje(tipo, texto, iconoPrefijo) {
    const safeText = escapeHtml(texto);
    const div = document.createElement("div");
    if (tipo === "user") {
      div.className = "mensaje-user";
      div.innerHTML = `<div class="bubble-user">${safeText}</div>`;
      chatMessages.appendChild(div);
      irAlFinal();
      return null;
    }
    const burbuja = crearBurbujaBot();
    actualizarBurbujaBot(burbuja, texto);
    if (iconoPrefijo) {
      const primerBloque = burbuja.contenido.querySelector("p, h3, li");
      if (primerBloque) primerBloque.insertAdjacentHTML("afterbegin", `${icono(iconoPrefijo, 16)} `);
    }
    return burbuja;
  }

  // Enlace real a /planes/ para los avisos de plan insuficiente/límite
  // agotado -- agregarMensaje() escapa el texto del bot (necesario, viene
  // de la IA), así que un <a> no puede ir dentro de ese texto: se añade
  // como elemento aparte, mismo patrón y clase que assets/tutor-widget.js.
  function agregarCtaPlanes() {
    const enlace = document.createElement("a");
    enlace.className = "tw-cta-planes";
    enlace.href = "/planes/";
    enlace.textContent = "Ver planes";
    chatMessages.appendChild(enlace);
    irAlFinal();
  }

  // Burbuja de respuesta del tutor que empieza vacía y se va rellenando a
  // medida que llegan fragmentos del streaming (efecto de "escritura"), en
  // vez de aparecer de golpe cuando termina toda la respuesta.
  function crearBurbujaBot() {
    const div = document.createElement("div");
    div.className = "mensaje-bot";
    div.innerHTML = `
      <div class="avatar-bot-mini">
        <img src="/assets/tutor-avatar.svg" alt="Tu Tutor" />
      </div>
      <div class="bubble-bot">
        <div class="bubble-bot-contenido"></div>
        <div class="bubble-bot-actions"><button type="button" class="btn-copiar-mensaje" aria-label="Copiar mensaje" title="Copiar">${icono("documento", 16)}</button></div>
      </div>
    `;
    chatMessages.appendChild(div);
    irAlFinal();
    const estado = { texto: "" };
    // addEventListener con "estado" capturado por closure, en vez de un
    // onclick inline: no depende de 'unsafe-inline' en el CSP. Lee
    // estado.texto en el momento del click (no el texto en el momento de
    // crear la burbuja), para copiar siempre la versión final.
    const botonCopiar = div.querySelector(".btn-copiar-mensaje");
    botonCopiar.addEventListener("click", async () => {
      const exito = await copyToClipboard(estado.texto);
      const iconoOriginal = botonCopiar.innerHTML;
      botonCopiar.innerHTML = exito ? icono("check", 16) : icono("alerta", 16);
      botonCopiar.title = exito ? "Copiado" : "No se pudo copiar";
      setTimeout(() => {
        botonCopiar.innerHTML = iconoOriginal;
        botonCopiar.title = "Copiar";
      }, 1500);
    });
    return { div, contenido: div.querySelector(".bubble-bot-contenido"), estado };
  }

  function actualizarBurbujaBot(burbuja, texto) {
    burbuja.estado.texto = texto;
    burbuja.contenido.innerHTML = formatearMensajeBot(texto);
    irAlFinalSiProcede();
  }

  function mostrarTyping(show) {
    typingIndicator.style.display = show ? "flex" : "none";
    if (show) {
      irAlFinal();
    }
  }

  const ERROR_TECNICO_TUTOR = "El tutor ha tenido un problema técnico al generar la respuesta. Vuelve a intentarlo en unos segundos.";

  // ENVÍO. Usa /tu-tutor/stream (Server-Sent Events) para mostrar la
  // respuesta con efecto de escritura en vez de esperar a que DeepSeek
  // termine de generarla entera -- se percibe mucho más rápido aunque el
  // backend tarde lo mismo.
  async function enviarMensaje() {
    const texto = input.value.trim();
    if (!texto) return;

    agregarMensaje("user", texto);
    input.value = "";
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 110) + "px";

    await pedirRespuestaTutor(texto);
  }

  // Extraído de enviarMensaje() para poder reutilizarlo al regenerar una
  // respuesta que se cortó a medias (ver botón "Regenerar" más abajo) sin
  // volver a añadir el mensaje del usuario, que ya está en el historial.
  async function pedirRespuestaTutor(texto) {
    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;

    ultimoMensajeUsuario = texto;
    mostrarTyping(true);

    const { obtenerOposicionActual } = await import("/assets/oposicion.js");
    const oposicion = obtenerOposicionActual();

    let respuesta;
    try {
      respuesta = await fetch("https://oposicion-age.onrender.com/tu-tutor/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ mensaje: texto, chat_id: chatIdActual, oposicion }),
        signal: AbortSignal.timeout(60000)
      });
    } catch {
      mostrarTyping(false);
      agregarMensaje("bot", "Error al conectar con el servidor.", "cruz");
      return;
    }

    mostrarTyping(false);

    if (respuesta.status === 403) {
      agregarMensaje("bot", "Tu Tutor requiere el plan Premium.", "candado");
      agregarCtaPlanes();
      return;
    }
    if (respuesta.status === 429) {
      const datosError = await respuesta.json().catch(() => ({}));
      agregarMensaje("bot", datosError.error || "Has alcanzado el límite de uso del chat por ahora.", "arena");
      agregarCtaPlanes();
      return;
    }
    if (!respuesta.ok || !respuesta.body) {
      agregarMensaje("bot", ERROR_TECNICO_TUTOR, "alerta");
      return;
    }

    const burbuja = crearBurbujaBot();
    const lector = respuesta.body.getReader();
    const decodificador = new TextDecoder();
    let buffer = "";
    let textoAcumulado = "";
    let temasRelacionados = [];
    let huboError = false;

    try {
      while (true) {
        const { done, value } = await leerStreamConTimeout(lector);
        if (done) break;
        buffer += decodificador.decode(value, { stream: true });
        const bloques = buffer.split("\n\n");
        buffer = bloques.pop(); // el último trozo puede venir incompleto
        for (const bloque of bloques) {
          const linea = bloque.trim();
          if (!linea.startsWith("data: ")) continue;
          let evento;
          try {
            evento = JSON.parse(linea.slice(6));
          } catch {
            continue;
          }
          if (evento.tipo === "delta") {
            textoAcumulado += evento.texto;
            actualizarBurbujaBot(burbuja, textoAcumulado);
          } else if (evento.tipo === "fin") {
            chatIdActual = evento.chat_id;
            temasRelacionados = evento.temas_relacionados || [];
          } else if (evento.tipo === "error") {
            huboError = true;
          }
        }
      }
    } catch {
      huboError = true;
    }

    if (huboError && !textoAcumulado) {
      burbuja.div.remove();
      agregarMensaje("bot", ERROR_TECNICO_TUTOR, "alerta");
      return;
    }

    // El streaming se cortó a medias (error de red/servidor tras haber
    // empezado a escribir) -- a diferencia del caso anterior, aquí SÍ hay
    // texto que enseñar, así que se deja tal cual en vez de descartarlo,
    // pero se avisa de que está incompleto y se ofrece regenerarla en vez
    // de dejar una respuesta cortada sin ningún indicio.
    if (huboError && textoAcumulado) {
      mostrarBurbujaCortada(burbuja, texto);
      return;
    }

    finalizarBurbujaBot(burbuja, temasRelacionados);
    cargarHistorial();
  }

  // Añade a una respuesta ya completa sus acciones: "Más fácil" y "Otra
  // respuesta" (secundarias), y -- si la respuesta iba sobre un tema concreto
  // del temario-- un botón que lleva a generar un test de ese tema (deep-link
  // al Test Personalizado con el tema ya marcado). Todo con textContent, sin
  // HTML crudo del backend.
  function finalizarBurbujaBot(burbuja, temasRelacionados) {
    const bubble = burbuja.div.querySelector(".bubble-bot");
    if (!bubble) return;

    const pie = document.createElement("div");
    pie.className = "bubble-bot-pie";

    const secundarias = document.createElement("div");
    secundarias.className = "bubble-bot-secundarias";

    const btnFacil = document.createElement("button");
    btnFacil.type = "button";
    btnFacil.className = "btn-mensaje-sec";
    btnFacil.innerHTML = `${icono("bombilla", 16)} Más fácil`;
    btnFacil.title = "Explícamelo de forma más sencilla";
    btnFacil.addEventListener("click", () => {
      input.value = "Explícamelo de forma más sencilla, con un ejemplo cotidiano.";
      enviarMensaje();
    });

    const btnOtra = document.createElement("button");
    btnOtra.type = "button";
    btnOtra.className = "btn-mensaje-sec";
    btnOtra.innerHTML = `${icono("actualizar", 16)} Otra respuesta`;
    btnOtra.title = "Regenerar esta respuesta";
    btnOtra.addEventListener("click", () => {
      if (!ultimoMensajeUsuario) return;
      burbuja.div.remove();
      pedirRespuestaTutor(ultimoMensajeUsuario);
    });

    secundarias.append(btnFacil, btnOtra);
    pie.appendChild(secundarias);

    if (Array.isArray(temasRelacionados) && temasRelacionados.length) {
      const temasRow = document.createElement("div");
      temasRow.className = "bubble-bot-temas";
      temasRelacionados.forEach(tema => {
        if (!tema || !tema.tema_id) return;
        const enlace = document.createElement("a");
        enlace.className = "btn-tema-mensaje";
        enlace.href = "/test-personalizado/?temas=" + encodeURIComponent(tema.tema_id);
        enlace.innerHTML = `${icono("lapiz", 16)} Generar test de ${escapeHtml(acortarTitulo(tema.titulo))}`;
        temasRow.appendChild(enlace);
      });
      if (temasRow.children.length) pie.appendChild(temasRow);
    }

    bubble.appendChild(pie);
    irAlFinalSiProcede();
  }

  // A diferencia de .bubble-bot-actions (el icono de copiar, oculto salvo
  // hover -- pensado como una acción secundaria), este aviso va siempre
  // visible: es precisamente el momento en que el usuario necesita verlo
  // sin tener que pasar el ratón por encima.
  function mostrarBurbujaCortada(burbuja, textoOriginal) {
    const bloque = document.createElement("div");
    bloque.className = "bubble-bot-cortada";
    const aviso = document.createElement("span");
    aviso.className = "bubble-bot-cortada-aviso";
    aviso.innerHTML = `${icono("alerta", 16)} Respuesta incompleta`;
    const botonRegenerar = document.createElement("button");
    botonRegenerar.type = "button";
    botonRegenerar.className = "btn-regenerar-mensaje";
    botonRegenerar.innerHTML = `${icono("actualizar", 16)} Regenerar`;
    botonRegenerar.addEventListener("click", async () => {
      botonRegenerar.disabled = true;
      botonRegenerar.textContent = "Regenerando…";
      burbuja.div.remove();
      await pedirRespuestaTutor(textoOriginal);
    });
    bloque.append(aviso, botonRegenerar);
    burbuja.div.querySelector(".bubble-bot").appendChild(bloque);
  }

  // HISTORIAL (persistido en Firestore, no en localStorage)
  let conversaciones = [];
  let chatIdActual = null;
  // Recomendación proactiva del saludo (nº de tests, tema flojo, tema
  // pendiente...). Se pide una vez y se reutiliza al iniciar cada nueva
  // conversación, sin volver a llamar al backend.
  let sugerenciaInicial = null;
  // Último mensaje que envió el usuario: lo usan los botones "Otra respuesta"
  // (regenerar) de cada burbuja del bot para volver a preguntar lo mismo.
  let ultimoMensajeUsuario = "";

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
        agregarMensaje("bot", "No se pudo cargar la conversación.", "cruz");
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
    aplicarSugerenciaBienvenida();
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

  // SALUDO PROACTIVO: rellena el mensaje de bienvenida con la recomendación
  // personalizada (tema flojo / tema pendiente / etc.), un botón que lleva a
  // generar un test de ese tema, y unas preguntas rápidas contextualizadas.
  // Todo el texto llega en plano y se inserta con textContent (nunca innerHTML
  // con datos del usuario), así el nombre o el título del tema no pueden
  // inyectar HTML.
  function aplicarSugerenciaBienvenida() {
    if (!sugerenciaInicial) return;
    const welcome = chatMessages.querySelector(".welcome-message");
    if (!welcome) return; // hay una conversación cargada, no el saludo

    const saludoEl = welcome.querySelector(".welcome-saludo-texto") || welcome.querySelector(".welcome-saludo");
    const mensajeEl = welcome.querySelector(".welcome-mensaje");
    const accionEl = welcome.querySelector(".welcome-accion");
    const quickWrap = welcome.querySelector(".quick-questions");

    if (saludoEl && sugerenciaInicial.saludo) {
      saludoEl.textContent = `${sugerenciaInicial.saludo} Soy Tu Tutor`;
    }
    if (mensajeEl && sugerenciaInicial.mensaje) {
      mensajeEl.textContent = sugerenciaInicial.mensaje;
    }

    if (accionEl) {
      accionEl.innerHTML = "";
      const accion = sugerenciaInicial.accion;
      if (accion && accion.tema_id) {
        const enlace = document.createElement("a");
        enlace.className = "btn-accion-tutor";
        enlace.href = "/test-personalizado/?temas=" + encodeURIComponent(accion.tema_id);
        const etiquetaAccion = accion.titulo ? ("Practicar " + acortarTitulo(accion.titulo)) : (accion.label || "Practicar este tema");
        enlace.innerHTML = `${icono("lapiz", 16)} ${escapeHtml(etiquetaAccion)}`;
        accionEl.appendChild(enlace);
      }
    }

    if (quickWrap && Array.isArray(sugerenciaInicial.sugerencias) && sugerenciaInicial.sugerencias.length) {
      quickWrap.innerHTML = "";
      sugerenciaInicial.sugerencias.forEach(textoSugerencia => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "quick-btn";
        btn.textContent = textoSugerencia;
        quickWrap.appendChild(btn);
      });
      reengancharPreguntasRapidas();
    }
  }

  async function cargarSugerenciaInicial() {
    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;
    try {
      const { obtenerOposicionActual } = await import("/assets/oposicion.js");
      const oposicion = obtenerOposicionActual();
      const res = await fetch(
        `https://oposicion-age.onrender.com/tu-tutor/sugerencia-inicial?oposicion=${encodeURIComponent(oposicion)}`,
        { headers: authHeaders }
      );
      if (!res.ok) return; // si falla, se queda el saludo estático por defecto
      sugerenciaInicial = await res.json();
      aplicarSugerenciaBienvenida();
    } catch {
      // Silencioso a propósito: el saludo estático del HTML ya es válido.
    }
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
  cargarSugerenciaInicial();
});
