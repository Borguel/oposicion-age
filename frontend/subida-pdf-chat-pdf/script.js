import { idToken } from "/assets/auth.js";

const BACKEND_URL = "https://oposicion-age.onrender.com";

let pdfCargado = false;
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

async function obtenerAuthHeaders() {
  const token = await idToken();
  if (!token) {
    window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
    return null;
  }
  return { "Authorization": "Bearer " + token };
}

selectPdfBtn.addEventListener('click', () => pdfFileInput.click());
pdfFileInput.addEventListener('change', handlePdfUpload);
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

async function handlePdfUpload() {
  const file = pdfFileInput.files[0];
  if (!file) return;

  if (file.type !== 'application/pdf') {
    addMessageToPdfChat('Por favor, selecciona un archivo PDF válido.', 'bot');
    return;
  }

  pdfFilename.textContent = file.name;
  pdfInfo.classList.remove('hidden');
  pdfPreviewText.textContent = "Analizando documento...";
  pageCount.textContent = "-";
  showTypingIndicator();

  const authHeaders = await obtenerAuthHeaders();
  if (!authHeaders) { hideTypingIndicator(); return; }

  const formData = new FormData();
  formData.append('pdf', file);

  try {
    const response = await fetch(`${BACKEND_URL}/subir-pdf-chat`, {
      method: 'POST',
      headers: authHeaders,
      body: formData
    });
    hideTypingIndicator();
    if (response.status === 403) {
      pdfPreviewText.textContent = "Esta herramienta requiere el plan Premium.";
      addMessageToPdfChat('Esta herramienta requiere el plan Premium. Ve a <a href="/planes/">/planes/</a> para activarlo.', 'bot');
      return;
    }
    const datos = await response.json().catch(() => ({}));
    if (!response.ok) {
      pdfPreviewText.textContent = "No se pudo procesar el documento.";
      addMessageToPdfChat(datos.error || "No se pudo procesar el documento.", 'bot');
      return;
    }
    pdfCargado = true;
    historialChat = [];
    pdfPreviewText.textContent = `Documento "${datos.nombre_archivo}" listo. Ya puedes preguntar sobre su contenido.`;
    pageCount.textContent = datos.paginas ?? "-";
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
  if (!message || !pdfCargado) return;

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
      body: JSON.stringify({ mensaje: message, historial: historialChat })
    });
    hideTypingIndicator();
    const datos = await response.json().catch(() => ({}));
    if (response.status === 403) {
      addMessageToPdfChat('Esta herramienta requiere el plan Premium. Ve a <a href="/planes/">/planes/</a> para activarlo.', 'bot');
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

function addMessageToPdfChat(message, sender) {
  const messageElement = document.createElement('div');
  messageElement.classList.add('message', `${sender}-message`);
  if (sender === 'user') {
    messageElement.textContent = message;
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
