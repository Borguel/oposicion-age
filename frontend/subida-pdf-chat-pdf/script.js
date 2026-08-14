import { obtenerAuthHeaders, marcarContenidoListo } from "/assets/auth.js";
import { protegerPagina } from "/assets/plan.js";
import { icono } from "/assets/icons.js";
import { leerStreamConTimeout } from "/assets/stream-utils.js";

protegerPagina("premium").then(() => marcarContenidoListo());

// Iconos estáticos del markup: se pintan aquí, una sola vez, a partir de
// los data-icon del HTML (en vez de emoji sueltos incrustados en el HTML).
document.querySelectorAll("[data-icon]").forEach((el) => {
  el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 24));
});

const BACKEND_URL = "https://oposicion-age.onrender.com";

// documento_id (12/08/2026): entrada directa desde "Mis documentos" -- si
// ya se subió el PDF antes para resumen/esquema/test/tarjetas, se puede
// chatear sobre él sin volver a subirlo ni ver el recuadro de "sube tu
// documento" (ver el botón "Chat PDF" en frontend/mis-documentos/script.js).
const documentoIdInicial = new URLSearchParams(location.search).get('documento_id');

let documentoIdActivo = null;
let historialChat = [];
let ultimoMensajeUsuario = "";

const uploadCard = document.getElementById('chatpdf-upload-card');
const uploadStatus = document.getElementById('chatpdf-upload-status');
const pdfUploadArea = document.getElementById('pdf-upload-area');
const pdfFileInput = document.getElementById('pdf-file');
const selectPdfBtn = document.getElementById('select-pdf-btn');
const chatCard = document.getElementById('chatpdf-card');
const pdfFilename = document.getElementById('pdf-filename');
const pageCount = document.getElementById('page-count');
const pdfChatBox = document.getElementById('pdf-chat-box');
const pdfUserInput = document.getElementById('pdf-user-input');
const pdfSendBtn = document.getElementById('pdf-send-btn');

selectPdfBtn.addEventListener('click', () => pdfFileInput.click());
pdfFileInput.addEventListener('change', () => handlePdfUpload());
pdfUploadArea.addEventListener('dragover', (e) => {
  e.preventDefault();
  pdfUploadArea.classList.add('active');
});
pdfUploadArea.addEventListener('dragleave', () => {
  pdfUploadArea.classList.remove('active');
});
pdfUploadArea.addEventListener('drop', (e) => {
  e.preventDefault();
  pdfUploadArea.classList.remove('active');
  if (e.dataTransfer.files.length) {
    pdfFileInput.files = e.dataTransfer.files;
    handlePdfUpload();
  }
});
pdfSendBtn.addEventListener('click', enviarMensajePdf);
pdfUserInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); enviarMensajePdf(); }
});

if (documentoIdInicial) {
  cargarDocumentoPorId(documentoIdInicial);
}

async function handlePdfUpload() {
  const file = pdfFileInput.files[0];
  if (!file) return;

  if (file.type !== 'application/pdf') {
    mostrarEstadoSubida('Por favor, selecciona un archivo PDF válido.', 'error');
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    mostrarEstadoSubida('El archivo supera los 10 MB. Por favor, sube un PDF más ligero.', 'error');
    pdfFileInput.value = '';
    return;
  }

  mostrarEstadoSubida('Analizando documento...', 'cargando');
  const formData = new FormData();
  formData.append('pdf', file);
  await subirPdfChat(formData);
}

async function cargarDocumentoPorId(documentoId) {
  uploadCard.classList.add('hidden');
  chatCard.classList.remove('hidden');
  actualizarDocbar('Cargando documento...', null);
  mostrarTyping(true);
  const formData = new FormData();
  formData.append('documento_id', documentoId);
  await subirPdfChat(formData);
}

function actualizarDocbar(nombre, paginas) {
  pdfFilename.textContent = nombre;
  pageCount.textContent = paginas ?? "-";
}

function mostrarEstadoSubida(texto, tipo) {
  uploadStatus.textContent = '';
  uploadStatus.className = 'chatpdf-upload-hint';
  if (tipo) uploadStatus.classList.add(`chatpdf-upload-hint-${tipo}`);
  if (typeof texto === 'string') {
    uploadStatus.textContent = texto;
  } else {
    // Array de "partes" (texto + enlace de confianza), ver enlacePlanes().
    for (const parte of texto) {
      uploadStatus.appendChild(parte instanceof Node ? parte : document.createTextNode(parte));
    }
  }
}

// Común a "subir un PDF nuevo" y "reutilizar un documento_id ya en Mis
// documentos" -- ambos llaman a /subir-pdf-chat (ver _resolver_texto_documento
// en blueprints/pdf_ia.py), que resuelve cualquiera de los dos casos.
async function subirPdfChat(formData) {
  const authHeaders = await obtenerAuthHeaders();
  if (!authHeaders) { mostrarTyping(false); return; }

  try {
    const response = await fetch(`${BACKEND_URL}/subir-pdf-chat`, {
      method: 'POST',
      headers: authHeaders,
      body: formData
    });
    mostrarTyping(false);
    if (response.status === 403) {
      mostrarFalloDeCarga(['Esta herramienta requiere el plan Básico o superior. Ve a ', enlacePlanes(), ' para activarlo.']);
      return;
    }
    if (response.status === 429) {
      const errorData = await response.json().catch(() => ({}));
      mostrarFalloDeCarga([
        `${errorData.error || "Has alcanzado el límite de uso de esta herramienta por ahora."} Ve a `,
        enlacePlanes(), ' para ampliar tu plan.',
      ]);
      return;
    }
    const datos = await response.json().catch(() => ({}));
    if (!response.ok) {
      mostrarFalloDeCarga(datos.error || "No se pudo procesar el documento.");
      return;
    }
    documentoIdActivo = datos.documento_id;
    historialChat = [];
    uploadCard.classList.add('hidden');
    chatCard.classList.remove('hidden');
    actualizarDocbar(datos.nombre_archivo, datos.paginas);
    pdfChatBox.innerHTML = '';
    agregarMensaje('bot', `Documento cargado. Pregúntame lo que quieras sobre "${datos.nombre_archivo}".`);
    pdfUserInput.disabled = false;
    pdfSendBtn.disabled = false;
    pdfUserInput.focus();
  } catch (error) {
    mostrarTyping(false);
    mostrarFalloDeCarga('No se pudo conectar con el servidor. Inténtalo de nuevo.');
    console.error('Error subiendo PDF:', error);
  }
}

// Un fallo de carga puede ocurrir ANTES de que exista el chat (subida
// inicial) o DESPUÉS (viniendo de un documento_id ya cargado) -- se
// muestra en el sitio que esté visible en cada caso.
function mostrarFalloDeCarga(mensaje) {
  if (chatCard.classList.contains('hidden')) {
    mostrarEstadoSubida(mensaje, 'error');
  } else {
    agregarMensaje('bot', mensaje);
  }
}

async function enviarMensajePdf() {
  const message = pdfUserInput.value.trim();
  if (!message || !documentoIdActivo) return;

  agregarMensaje('user', message);
  pdfUserInput.value = '';
  pdfSendBtn.disabled = true;
  ultimoMensajeUsuario = message;
  mostrarTyping(true);

  const authHeaders = await obtenerAuthHeaders();
  if (!authHeaders) { mostrarTyping(false); pdfSendBtn.disabled = false; return; }

  let respuesta;
  try {
    respuesta = await fetch(`${BACKEND_URL}/chat-pdf-mensaje/stream`, {
      method: 'POST',
      headers: { "Content-Type": "application/json", ...authHeaders },
      body: JSON.stringify({ mensaje: message, historial: historialChat, documento_id: documentoIdActivo }),
      signal: AbortSignal.timeout(90000)
    });
  } catch {
    mostrarTyping(false);
    agregarMensaje('bot', 'No se pudo conectar con el servidor. Inténtalo de nuevo.');
    pdfSendBtn.disabled = false;
    return;
  }

  mostrarTyping(false);

  if (respuesta.status === 403) {
    agregarMensaje('bot', ['Esta herramienta requiere el plan Básico o superior. Ve a ', enlacePlanes(), ' para activarlo.']);
    pdfSendBtn.disabled = false;
    return;
  }
  if (respuesta.status === 429) {
    const datosError = await respuesta.json().catch(() => ({}));
    agregarMensaje('bot', [
      `${datosError.error || "Has alcanzado el límite de uso de esta herramienta por ahora."} Ve a `,
      enlacePlanes(), ' para ampliar tu plan.',
    ]);
    pdfSendBtn.disabled = false;
    return;
  }
  if (!respuesta.ok || !respuesta.body) {
    agregarMensaje('bot', 'No se pudo obtener respuesta. Inténtalo de nuevo.');
    pdfSendBtn.disabled = false;
    return;
  }

  // Burbuja que empieza vacía y se va rellenando a medida que llegan
  // fragmentos del streaming -- efecto de "escritura" (como Tu Tutor), en
  // vez de aparecer de golpe cuando termina toda la respuesta.
  const burbuja = crearBurbujaBot();
  const lector = respuesta.body.getReader();
  const decodificador = new TextDecoder();
  let buffer = "";
  let textoAcumulado = "";
  let huboError = false;

  try {
    let terminado = false;
    while (!terminado) {
      const { done, value } = await leerStreamConTimeout(lector);
      if (done) break;
      buffer += decodificador.decode(value, { stream: true });
      const bloques = buffer.split("\n\n");
      buffer = bloques.pop();
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
          terminado = true;
        } else if (evento.tipo === "error") {
          huboError = true;
          terminado = true;
        }
      }
    }
    lector.cancel().catch(() => {});
  } catch {
    huboError = true;
  }

  pdfSendBtn.disabled = false;

  if (huboError && !textoAcumulado) {
    burbuja.div.remove();
    agregarMensaje('bot', 'No se pudo generar la respuesta. Inténtalo de nuevo en unos segundos.');
    return;
  }

  historialChat.push({ role: 'user', content: message });
  historialChat.push({ role: 'assistant', content: textoAcumulado });
}

function escapeHtml(texto) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return String(texto).replace(/[&<>"']/g, m => map[m]);
}

function aplicarEnfasis(texto) {
  return texto
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>");
}

// Markdown ligero para las respuestas de la IA (mismo criterio que
// /tu-tutor/script.js::formatearMensajeBot): escapa todo el HTML primero
// (nunca se inyecta HTML crudo del modelo) y luego traduce solo la
// sintaxis básica que el modelo suele usar.
function formatearMensajeBot(texto) {
  const lineas = escapeHtml(texto).split("\n");
  let html = "";
  let dentroDeLista = false;
  const cerrarLista = () => {
    if (dentroDeLista) { html += "</ul>"; dentroDeLista = false; }
  };
  for (const lineaOriginal of lineas) {
    const linea = lineaOriginal.trim();
    const encabezado = linea.match(/^#{1,6}\s+(.*)$/);
    const item = linea.match(/^[-*]\s+(.*)$/);
    if (encabezado) {
      cerrarLista();
      html += `<h3>${aplicarEnfasis(encabezado[1])}</h3>`;
    } else if (item) {
      if (!dentroDeLista) { html += "<ul>"; dentroDeLista = true; }
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

// Enlace de confianza a /planes/, para los mensajes de límite/plan -- se
// construye como elemento DOM real (nunca como texto con <a> dentro, que
// escapeHtml() rompía convirtiéndolo en texto literal en vez de un enlace
// pulsable).
function enlacePlanes() {
  const a = document.createElement('a');
  a.href = '/planes/';
  a.textContent = '/planes/';
  return a;
}

function crearBurbujaUser(texto) {
  const div = document.createElement('div');
  div.className = 'chatpdf-msg chatpdf-msg-user';
  div.innerHTML = `<div class="chatpdf-bubble chatpdf-bubble-user"></div>`;
  div.querySelector('.chatpdf-bubble-user').textContent = texto;
  pdfChatBox.appendChild(div);
  irAlFinal();
}

// texto puede ser: un string (se formatea con Markdown ligero) o un array
// de "partes" -- strings y/o nodos DOM ya de confianza (como el <a> de
// enlacePlanes()) -- para los mensajes fijos de este archivo que sí
// necesitan un enlace real, sin mezclar nunca eso con texto ajeno.
function crearBurbujaBot(texto) {
  const div = document.createElement('div');
  div.className = 'chatpdf-msg chatpdf-msg-bot';
  div.innerHTML = `
    <div class="chatpdf-avatar-bot">${icono('robot', 16)}</div>
    <div class="chatpdf-bubble chatpdf-bubble-bot"></div>
  `;
  const contenido = div.querySelector('.chatpdf-bubble-bot');
  if (Array.isArray(texto)) {
    const p = document.createElement('p');
    for (const parte of texto) {
      p.appendChild(parte instanceof Node ? parte : document.createTextNode(parte));
    }
    contenido.appendChild(p);
  } else if (typeof texto === 'string') {
    contenido.innerHTML = formatearMensajeBot(texto);
  }
  pdfChatBox.appendChild(div);
  irAlFinal();
  return { div, contenido };
}

function actualizarBurbujaBot(burbuja, texto) {
  burbuja.contenido.innerHTML = formatearMensajeBot(texto);
  irAlFinal();
}

function agregarMensaje(tipo, texto) {
  if (tipo === 'user') {
    crearBurbujaUser(texto);
  } else {
    crearBurbujaBot(texto);
  }
}

function irAlFinal() {
  pdfChatBox.scrollTop = pdfChatBox.scrollHeight;
}

function mostrarTyping(show) {
  let indicador = document.getElementById('chatpdf-typing');
  if (show) {
    if (indicador) return;
    indicador = document.createElement('div');
    indicador.id = 'chatpdf-typing';
    indicador.className = 'chatpdf-msg chatpdf-msg-bot';
    indicador.innerHTML = `
      <div class="chatpdf-avatar-bot">${icono('robot', 16)}</div>
      <div class="chatpdf-bubble chatpdf-bubble-bot chatpdf-typing">
        <span></span><span></span><span></span>
      </div>
    `;
    pdfChatBox.appendChild(indicador);
    irAlFinal();
  } else if (indicador) {
    indicador.remove();
  }
}
