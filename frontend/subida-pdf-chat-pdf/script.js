import { obtenerAuthHeaders, marcarContenidoListo } from "/assets/auth.js";
import { protegerPagina } from "/assets/plan.js";
import { icono } from "/assets/icons.js";

protegerPagina("premium").then(() => marcarContenidoListo());

// Iconos estáticos del markup: se pintan aquí, una sola vez, a partir de
// los data-icon del HTML (en vez de emoji sueltos incrustados en el HTML).
document.querySelectorAll("[data-icon]").forEach((el) => {
  el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 24));
});

const BACKEND_URL = "https://oposicion-age.onrender.com";

// documento_id (12/08/2026): entrada directa desde "Mis documentos" -- si
// ya se subió el PDF antes para resumen/esquema/test/tarjetas, se puede
// chatear sobre él sin volver a subirlo (ver /subida-pdf-chat-pdf/?documento_id=...
// en frontend/mis-documentos/script.js).
const documentoIdInicial = new URLSearchParams(location.search).get('documento_id');

let documentoIdActivo = null;
let historialChat = [];

const pdfUploadArea = document.getElementById('pdf-upload-area');
const pdfFileInput = document.getElementById('pdf-file');
const selectPdfBtn = document.getElementById('select-pdf-btn');
const pdfInfo = document.getElementById('pdf-info');
const pdfFilename = document.getElementById('pdf-filename');
const pdfPreviewText = document.getElementById('pdf-preview-text');
const pageCount = document.getElementById('page-count');
const pdfChatBox = document.getElementById('pdf-chat-box');
const pdfUserInput = document.getElementById('pdf-user-input');
const pdfSendBtn = document.getElementById('pdf-send-btn');
const sessionInfo = document.getElementById('session-info');

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
pdfUserInput.addEventListener('keypress', (e) => {
  if (e.key === 'Enter') enviarMensajePdf();
});

if (documentoIdInicial) {
  cargarDocumentoPorId(documentoIdInicial);
}

async function handlePdfUpload() {
  const file = pdfFileInput.files[0];
  if (!file) return;

  if (file.type !== 'application/pdf') {
    addMessageToPdfChat('Por favor, selecciona un archivo PDF válido.', 'bot');
    return;
  }

  if (file.size > 10 * 1024 * 1024) {
    addMessageToPdfChat('El archivo supera los 10 MB. Por favor, sube un PDF más ligero.', 'bot');
    pdfFileInput.value = '';
    return;
  }

  pdfFilename.textContent = file.name;
  pdfInfo.classList.remove('hidden');
  pdfPreviewText.textContent = "Analizando documento...";
  pageCount.textContent = "-";

  const formData = new FormData();
  formData.append('pdf', file);
  await subirPdfChat(formData);
}

async function cargarDocumentoPorId(documentoId) {
  pdfFilename.textContent = "";
  pdfInfo.classList.remove('hidden');
  pdfPreviewText.textContent = "Cargando documento...";
  pageCount.textContent = "-";

  const formData = new FormData();
  formData.append('documento_id', documentoId);
  await subirPdfChat(formData);
}

// Común a "subir un PDF nuevo" y "reutilizar un documento_id ya en Mis
// documentos" -- ambos llaman a /subir-pdf-chat (ver _resolver_texto_documento
// en blueprints/pdf_ia.py), que resuelve cualquiera de los dos casos.
async function subirPdfChat(formData) {
  showTypingIndicator();
  const authHeaders = await obtenerAuthHeaders();
  if (!authHeaders) { hideTypingIndicator(); return; }

  try {
    const response = await fetch(`${BACKEND_URL}/subir-pdf-chat`, {
      method: 'POST',
      headers: authHeaders,
      body: formData
    });
    hideTypingIndicator();
    if (response.status === 403) {
      pdfPreviewText.textContent = "Esta herramienta requiere el plan Básico o superior.";
      addMessageToPdfChat(['Esta herramienta requiere el plan Básico o superior. Ve a ', enlacePlanes(), ' para activarlo.'], 'bot');
      return;
    }
    if (response.status === 429) {
      const errorData = await response.json().catch(() => ({}));
      pdfPreviewText.textContent = "Límite de uso alcanzado.";
      addMessageToPdfChat([
        `${errorData.error || "Has alcanzado el límite de uso de esta herramienta por ahora."} Ve a `,
        enlacePlanes(), ' para ampliar tu plan.',
      ], 'bot');
      return;
    }
    const datos = await response.json().catch(() => ({}));
    if (!response.ok) {
      pdfPreviewText.textContent = "No se pudo procesar el documento.";
      addMessageToPdfChat(datos.error || "No se pudo procesar el documento.", 'bot');
      return;
    }
    documentoIdActivo = datos.documento_id;
    historialChat = [];
    pdfPreviewText.textContent = `Documento "${datos.nombre_archivo}" listo. Ya puedes preguntar sobre su contenido.`;
    pageCount.textContent = datos.paginas ?? "-";
    pdfFilename.textContent = datos.nombre_archivo;
    sessionInfo.textContent = `Documento: ${datos.nombre_archivo}`;
    pdfUserInput.disabled = false;
    pdfSendBtn.disabled = false;
    addMessageToPdfChat(`PDF "${datos.nombre_archivo}" cargado correctamente. Pregúntame lo que quieras sobre su contenido.`, 'bot');
  } catch (error) {
    hideTypingIndicator();
    pdfPreviewText.textContent = "No se pudo conectar con el servidor.";
    addMessageToPdfChat('No se pudo conectar con el servidor. Inténtalo de nuevo.', 'bot');
    console.error('Error subiendo PDF:', error);
  }
}

async function enviarMensajePdf() {
  const message = pdfUserInput.value.trim();
  if (!message || !documentoIdActivo) return;

  addMessageToPdfChat(message, 'user');
  pdfUserInput.value = '';
  pdfSendBtn.disabled = true;
  showTypingIndicator();

  const authHeaders = await obtenerAuthHeaders();
  if (!authHeaders) { hideTypingIndicator(); return; }

  try {
    const response = await fetch(`${BACKEND_URL}/chat-pdf-mensaje`, {
      method: 'POST',
      headers: { "Content-Type": "application/json", ...authHeaders },
      body: JSON.stringify({ mensaje: message, historial: historialChat, documento_id: documentoIdActivo })
    });
    hideTypingIndicator();
    const datos = await response.json().catch(() => ({}));
    if (response.status === 403) {
      addMessageToPdfChat(['Esta herramienta requiere el plan Básico o superior. Ve a ', enlacePlanes(), ' para activarlo.'], 'bot');
      return;
    }
    if (response.status === 429) {
      addMessageToPdfChat([
        `${datos.error || "Has alcanzado el límite de uso de esta herramienta por ahora."} Ve a `,
        enlacePlanes(), ' para ampliar tu plan.',
      ], 'bot');
      return;
    }
    if (!response.ok) {
      addMessageToPdfChat(datos.error || "No se pudo obtener respuesta. Inténtalo de nuevo.", 'bot');
      return;
    }
    historialChat.push({ role: 'user', content: message });
    historialChat.push({ role: 'assistant', content: datos.respuesta });
    addMessageToPdfChat(datos.respuesta, 'bot');
  } catch (error) {
    hideTypingIndicator();
    addMessageToPdfChat('No se pudo conectar con el servidor. Inténtalo de nuevo.', 'bot');
    console.error('Error en el chat con PDF:', error);
  } finally {
    pdfSendBtn.disabled = false;
  }
}

function escaparHtml(texto) {
  const div = document.createElement('div');
  div.textContent = texto;
  return div.innerHTML;
}

// Enlace de confianza a /planes/, para los mensajes de límite/plan de abajo
// -- construido como elemento DOM real (nunca como texto con <a> dentro,
// que escaparHtml() rompía convirtiéndolo en texto literal en vez de un
// enlace pulsable).
function enlacePlanes() {
  const a = document.createElement('a');
  a.href = '/planes/';
  a.textContent = '/planes/';
  return a;
}

// message puede ser: un string (texto plano de la IA/usuario, se escapa
// siempre) o un array de "partes" -- strings y/o nodos DOM ya de confianza
// (como el <a> de enlacePlanes()) -- para los mensajes fijos de este
// archivo que sí necesitan markup, sin mezclar nunca eso con texto ajeno.
function addMessageToPdfChat(message, sender) {
  const messageElement = document.createElement('div');
  messageElement.classList.add('message', `${sender}-message`);
  if (sender === 'user') {
    messageElement.textContent = message;
  } else if (Array.isArray(message)) {
    const p = document.createElement('p');
    for (const parte of message) {
      p.appendChild(parte instanceof Node ? parte : document.createTextNode(parte));
    }
    messageElement.appendChild(p);
  } else {
    // La respuesta viene de la IA como texto plano: se escapa por seguridad
    // y se convierten los saltos de línea en <br> para que se lea bien.
    messageElement.innerHTML = `<p>${escaparHtml(message).replace(/\n/g, '<br>')}</p>`;
  }
  pdfChatBox.appendChild(messageElement);
  pdfChatBox.scrollTop = pdfChatBox.scrollHeight;
}

function showTypingIndicator() {
  const typingElement = document.createElement('div');
  typingElement.classList.add('message', 'bot-message');
  typingElement.id = 'typing-indicator';
  typingElement.innerHTML = '<div class="spinner"></div> <span>Pensando...</span>';
  pdfChatBox.appendChild(typingElement);
  pdfChatBox.scrollTop = pdfChatBox.scrollHeight;
}

function hideTypingIndicator() {
  const typingElement = document.getElementById('typing-indicator');
  if (typingElement) typingElement.remove();
}
