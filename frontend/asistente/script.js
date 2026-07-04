async function obtenerAuthHeaders() {
    const { idToken } = await import("/assets/auth.js");
    const token = await idToken();
    if (!token) {
        window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
        return null;
    }
    return { "Authorization": "Bearer " + token };
}

document.addEventListener("DOMContentLoaded", function() {
            // Elementos DOM
            const input = document.getElementById("chat-input");
            const sendBtn = document.getElementById("chat-send");
            const chatMessages = document.getElementById("chat-messages");
            const historyPanel = document.getElementById("history-panel");
            const settingsPanel = document.getElementById("settings-panel");
            const historyToggle = document.getElementById("history-toggle");
            const settingsToggle = document.getElementById("settings-toggle");
            const closeHistory = document.getElementById("close-history");
            const closeSettings = document.getElementById("close-settings");
            const clearChatBtn = document.getElementById("clear-chat");
            const darkModeToggle = document.getElementById("dark-mode-toggle");
            const animationsToggle = document.getElementById("animations-toggle");
            const progressBar = document.querySelector(".progress-bar");
            const typingProgress = document.getElementById("typing-progress");
            const quickBtns = document.querySelectorAll(".quick-btn");
            const colorOptions = document.querySelectorAll(".color-option");
            const voiceBtn = document.getElementById("voice-btn");
            
            // Variables de estado
            let isDarkMode = false;
            let animationsEnabled = true;
            let currentTheme = "blue";
            let conversationHistory = [];
            
            // Inicialización
            loadPreferences();
            loadHistory();
            setupEventListeners();
            input.focus();
            
            // Cargar preferencias del localStorage
            function loadPreferences() {
                const savedTheme = localStorage.getItem("chatTheme");
                const savedDarkMode = localStorage.getItem("darkMode") === "true";
                const savedAnimations = localStorage.getItem("animations") !== "false";
                
                if (savedTheme) {
                    setTheme(savedTheme);
                    // Actualizar indicador visual de tema activo
                    colorOptions.forEach(option => {
                        option.classList.remove("active");
                        if (option.getAttribute("data-theme") === savedTheme) {
                            option.classList.add("active");
                        }
                    });
                }
                if (savedDarkMode) {
                    toggleDarkMode();
                }
                if (savedAnimations !== undefined) {
                    animationsEnabled = savedAnimations;
                    animationsToggle.checked = savedAnimations;
                }
            }
            
            // Configurar event listeners
            function setupEventListeners() {
                // Envío de mensajes
                sendBtn.addEventListener("click", enviarMensaje);
                input.addEventListener("keydown", function(e) {
                    if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        enviarMensaje();
                    }
                });
                
                // Autoajuste del textarea
                input.addEventListener("input", function() {
                    this.style.height = "auto";
                    this.style.height = (this.scrollHeight) + "px";
                });
                
                // Paneles de historial y configuración
                historyToggle.addEventListener("click", () => togglePanel(historyPanel));
                settingsToggle.addEventListener("click", () => togglePanel(settingsPanel));
                closeHistory.addEventListener("click", () => historyPanel.classList.remove("active"));
                closeSettings.addEventListener("click", () => settingsPanel.classList.remove("active"));
                
                // Limpiar chat
                clearChatBtn.addEventListener("click", clearChat);
                
                // Toggles de configuración
                darkModeToggle.addEventListener("change", toggleDarkMode);
                animationsToggle.addEventListener("change", function() {
                    animationsEnabled = this.checked;
                    localStorage.setItem("animations", animationsEnabled);
                });
                
                // Preguntas rápidas
                quickBtns.forEach(btn => {
                    btn.addEventListener("click", function() {
                        const question = this.textContent;
                        input.value = question;
                        enviarMensaje();
                    });
                });
                
                // Selectores de color
                colorOptions.forEach(option => {
                    option.addEventListener("click", function() {
                        const theme = this.getAttribute("data-theme");
                        setTheme(theme);
                        
                        // Actualizar indicador visual
                        colorOptions.forEach(opt => opt.classList.remove("active"));
                        this.classList.add("active");
                    });
                });
                
                // Botón de voz
                voiceBtn.addEventListener("click", function() {
                    showNotification("Reconocimiento de voz activado. Esta funcionalidad se implementaría completamente en una versión de producción.");
                });
            }
            
            // Función para alternar paneles
            function togglePanel(panel) {
                // Cerrar cualquier otro panel abierto
                if (historyPanel !== panel) historyPanel.classList.remove("active");
                if (settingsPanel !== panel) settingsPanel.classList.remove("active");
                
                // Alternar el panel solicitado
                panel.classList.toggle("active");
            }
            
            // Función para enviar mensaje
            function enviarMensaje() {
                const texto = input.value.trim();
                if (!texto) return;
                
                agregarMensaje("user", texto);
                input.value = "";
                input.style.height = "auto";
                
                // Mostrar indicador de escritura
                mostrarTypingIndicator();
                
                // Simular respuesta mientras se conecta con la API
                setTimeout(async () => {
                    const authHeaders = await obtenerAuthHeaders();
                    if (!authHeaders) { ocultarTypingIndicator(); return; }
                    const { obtenerOposicionActual } = await import("/assets/oposicion.js");
                    const oposicion = obtenerOposicionActual();
                    // Enviar a la API usando tu endpoint
                    fetch("https://oposicion-age.onrender.com/consultar-asistente-examen", {
                        method: "POST",
                        headers: { "Content-Type": "application/json", ...authHeaders },
                        body: JSON.stringify({ mensaje: texto, oposicion })
                    })
                    .then(res => {
                        if (res.status === 403) {
                            ocultarTypingIndicator();
                            agregarMensaje("bot", "🔒 El asistente premium requiere el plan Premium. Ve a /planes/ para activarlo.");
                            return null;
                        }
                        return res.json();
                    })
                    .then(data => {
                        if (!data) return;
                        ocultarTypingIndicator();
                        if (data.respuesta) {
                            agregarMensaje("bot", data.respuesta);
                            guardarEnHistorial(texto, data.respuesta);
                        } else {
                            agregarMensaje("bot", "❌ Hubo un error: " + (data.error || "Respuesta vacía"));
                        }
                    })
                    .catch(err => {
                        ocultarTypingIndicator();
                        agregarMensaje("bot", "❌ Error al conectar con el servidor");
                        console.error("Error:", err);
                    });
                }, 1000);
            }
            
            // El chat pinta tanto lo que escribe el usuario como la
            // respuesta de la IA: se escapa antes de convertir saltos de
            // línea en <br> para que ningún mensaje pueda ejecutar HTML.
            function escaparHtml(texto) {
                const div = document.createElement("div");
                div.textContent = texto ?? "";
                return div.innerHTML;
            }

            // Función para agregar mensajes al chat
            function agregarMensaje(tipo, texto) {
                const div = document.createElement("div");
                div.className = tipo === "user" ? "mensaje-user" : "mensaje-bot";

                if (animationsEnabled) {
                    div.style.animation = "fadeIn 0.5s ease-out";
                }

                const textoSeguro = escaparHtml(texto).replace(/\n/g, "<br>");
                if (tipo === "user") {
                    div.innerHTML = `
                        <div class="bubble-user">
                            <div class="message-content">${textoSeguro}</div>
                            <div class="message-time">${getCurrentTime()}</div>
                        </div>
                        <div class="user-avatar">
                            <i class="fas fa-user"></i>
                        </div>
                    `;
                } else {
                    div.innerHTML = `
                        <div class="avatar-bot-mini">
                            <img src="https://randomuser.me/api/portraits/women/44.jpg" alt="Asistente">
                        </div>
                        <div class="bubble-bot">
                            <div class="message-content">${textoSeguro}</div>
                            <div class="message-actions">
                                <button class="action-btn copy-btn" title="Copiar">
                                    <i class="far fa-copy"></i>
                                </button>
                                <div class="message-time">${getCurrentTime()}</div>
                            </div>
                        </div>
                    `;
                }
                
                chatMessages.appendChild(div);
                scrollToBottom();
                
                // Agregar evento de copia para los nuevos mensajes del bot
                if (tipo === "bot") {
                    const copyBtn = div.querySelector(".copy-btn");
                    copyBtn.addEventListener("click", function() {
                        navigator.clipboard.writeText(texto);
                        showNotification("¡Texto copiado al portapapeles!");
                    });
                }
            }
            
            // Función para mostrar indicador de escritura
            function mostrarTypingIndicator() {
                typingProgress.style.display = "block";
                progressBar.style.animation = "progress-animation 2s infinite";
            }
            
            // Función para ocultar indicador de escritura
            function ocultarTypingIndicator() {
                typingProgress.style.display = "none";
                progressBar.style.animation = "none";
            }
            
            // Función para obtener hora actual
            function getCurrentTime() {
                const now = new Date();
                return `${now.getHours()}:${now.getMinutes().toString().padStart(2, "0")}`;
            }
            
            // Scroll al final
            function scrollToBottom() {
                chatMessages.scrollTop = chatMessages.scrollHeight;
                setTimeout(() => {
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                }, 50);
            }
            
            // Guardar en historial
            function guardarEnHistorial(pregunta, respuesta) {
                const conversation = {
                    id: Date.now(),
                    date: new Date().toLocaleDateString(),
                    question: pregunta,
                    answer: respuesta
                };
                
                conversationHistory.push(conversation);
                localStorage.setItem("chatHistory", JSON.stringify(conversationHistory));
                updateHistoryPanel();
            }
            
            // Cargar historial
            function loadHistory() {
                const savedHistory = localStorage.getItem("chatHistory");
                if (savedHistory) {
                    conversationHistory = JSON.parse(savedHistory);
                    updateHistoryPanel();
                }
            }
            
            // Actualizar panel de historial
            function updateHistoryPanel() {
                const historyList = document.querySelector(".history-list");
                historyList.innerHTML = "";
                
                if (conversationHistory.length === 0) {
                    historyList.innerHTML = `<div class="empty-history">No hay conversaciones guardadas</div>`;
                    return;
                }
                
                conversationHistory.forEach(conv => {
                    const historyItem = document.createElement("div");
                    historyItem.className = "history-item";
                    const preguntaCorta = conv.question.substring(0, 50) + (conv.question.length > 50 ? "..." : "");
                    historyItem.innerHTML = `
                        <div class="history-date">${escaparHtml(conv.date)}</div>
                        <div class="history-question">${escaparHtml(preguntaCorta)}</div>
                        <button class="history-load-btn" data-id="${conv.id}">
                            <i class="fas fa-history"></i> Cargar
                        </button>
                    `;
                    historyList.appendChild(historyItem);
                    
                    // Evento para cargar conversación
                    const loadBtn = historyItem.querySelector(".history-load-btn");
                    loadBtn.addEventListener("click", function() {
                        const id = parseInt(this.getAttribute("data-id"));
                        loadConversation(id);
                        historyPanel.classList.remove("active");
                    });
                });
            }
            
            // Cargar conversación específica
            function loadConversation(id) {
                const conversation = conversationHistory.find(c => c.id === id);
                if (!conversation) return;
                
                // Limpiar chat actual
                chatMessages.innerHTML = "";
                
                // Agregar mensajes de la conversación
                agregarMensaje("user", conversation.question);
                agregarMensaje("bot", conversation.answer);
            }
            
            // Limpiar chat
            function clearChat() {
                chatMessages.innerHTML = `
                    <div class="welcome-message">
                        <div class="avatar-bot-mini">
                            <img src="https://randomuser.me/api/portraits/women/44.jpg" alt="Asistente">
                        </div>
                        <div class="bubble-bot">
                            <h3>¡Hola de nuevo! 👋</h3>
                            <p>¿En qué puedo ayudarte hoy sobre los exámenes AGE?</p>
                            <div class="quick-questions">
                                <button class="quick-btn">Estructura del examen</button>
                                <button class="quick-btn">Temario actualizado</button>
                                <button class="quick-btn">Consejos de estudio</button>
                            </div>
                        </div>
                    </div>
                `;
                
                // Reasignar eventos a los botones rápidos
                document.querySelectorAll(".quick-btn").forEach(btn => {
                    btn.addEventListener("click", function() {
                        const question = this.textContent;
                        input.value = question;
                        enviarMensaje();
                    });
                });
            }
            
            // Cambiar tema de color
            function setTheme(theme) {
                currentTheme = theme;
                document.documentElement.setAttribute("data-theme", theme);
                localStorage.setItem("chatTheme", theme);
            }
            
            // Alternar modo oscuro
            function toggleDarkMode() {
                isDarkMode = !isDarkMode;
                document.body.classList.toggle("dark-mode", isDarkMode);
                localStorage.setItem("darkMode", isDarkMode);
                darkModeToggle.checked = isDarkMode;
            }
            
            // Mostrar notificación
            function showNotification(message) {
                const notification = document.createElement("div");
                notification.className = "notification";
                notification.textContent = message;
                document.body.appendChild(notification);
                
                setTimeout(() => {
                    notification.classList.add("show");
                }, 10);
                
                setTimeout(() => {
                    notification.classList.remove("show");
                    setTimeout(() => {
                        document.body.removeChild(notification);
                    }, 300);
                }, 2000);
            }
        });
