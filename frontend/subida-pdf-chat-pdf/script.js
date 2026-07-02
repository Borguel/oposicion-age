// Variables globales
    let currentSessionId = null;
    let currentPdfFile = null;
    let pdfTextContent = "";

    // Elementos DOM
    const pdfUploadArea = document.getElementById('pdf-upload-area');
    const pdfFileInput = document.getElementById('pdf-file');
    const selectPdfBtn = document.getElementById('select-pdf-btn');
    const pdfInfo = document.getElementById('pdf-info');
    const pdfFilename = document.getElementById('pdf-filename');
    const pdfPreviewText = document.getElementById('pdf-preview-text');
    const pageCount = document.getElementById('page-count');
    const wordCount = document.getElementById('word-count');
    const generateSummaryBtn = document.getElementById('generate-summary-btn');
    const generateTestBtn = document.getElementById('generate-test-btn');
    const testOptions = document.getElementById('test-options');
    const numQuestionsInput = document.getElementById('num-questions');
    const questionTypeSelect = document.getElementById('question-type');
    const generateTestFinalBtn = document.getElementById('generate-test-final-btn');
    const pdfChatBox = document.getElementById('pdf-chat-box');
    const pdfUserInput = document.getElementById('pdf-user-input');
    const pdfSendBtn = document.getElementById('pdf-send-btn');
    const sessionInfo = document.getElementById('session-info');

    // Event listeners
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
    generateSummaryBtn.addEventListener('click', generateSummary);
    generateTestBtn.addEventListener('click', showTestOptions);
    generateTestFinalBtn.addEventListener('click', generateTest);
    pdfSendBtn.addEventListener('click', sendPdfMessage);
    pdfUserInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') sendPdfMessage();
    });

    // Manejar subida de PDF
    async function handlePdfUpload() {
      const file = pdfFileInput.files[0];
      if (!file) return;
      
      // Verificar que sea un PDF
      if (file.type !== 'application/pdf') {
        addMessageToPdfChat('Por favor, selecciona un archivo PDF válido.', 'bot');
        return;
      }
      
      currentPdfFile = file;
      pdfFilename.textContent = file.name;
      pdfInfo.classList.remove('hidden');
      
      // Simular análisis del PDF (en un caso real, esto se haría en el servidor)
      pdfPreviewText.textContent = "Analizando documento...";
      showTypingIndicator();
      
      // Simular delay de análisis
      setTimeout(() => {
        hideTypingIndicator();
        
        // Simular contenido extraído del PDF
        pdfTextContent = `Documento: ${file.name}\n\nEste es un documento de ejemplo con contenido educativo. Contiene información sobre diversos temas que pueden ser útiles para el estudio. En un caso real, aquí estaría el texto extraído del PDF.`;
        
        pdfPreviewText.textContent = pdfTextContent.substring(0, 200) + "...";
        pageCount.textContent = "12";
        wordCount.textContent = "5,240";
        
        addMessageToPdfChat(`PDF "${file.name}" cargado correctamente. He analizado el documento y estoy listo para ayudarte.`, 'bot');
        
        // Mostrar preguntas sugeridas
        showSuggestedQuestions();
        
        // En un caso real, aquí enviaríamos el PDF al servidor
        uploadPdfToServer(file);
      }, 2000);
    }

    // Subir PDF al servidor (simulado)
    async function uploadPdfToServer(file) {
      const formData = new FormData();
      formData.append('pdf', file);
      formData.append('usuario_id', 'ID_DEL_USUARIO'); // Reemplazar con ID real
      
      try {
        const response = await fetch('/upload-pdf-chat', {
          method: 'POST',
          body: formData
        });
        
        const data = await response.json();
        if (data.session_id) {
          currentSessionId = data.session_id;
          sessionInfo.textContent = `Documento: ${file.name}`;
        }
      } catch (error) {
        console.error('Error subiendo PDF:', error);
      }
    }

    // Generar resumen
    async function generateSummary() {
      if (!currentPdfFile) return;
      
      addMessageToPdfChat('Por favor, genera un resumen detallado de este documento.', 'user');
      showTypingIndicator();
      
      // Simular generación de resumen
      setTimeout(() => {
        hideTypingIndicator();
        
        const summary = `
          <h3>Resumen del Documento</h3>
          <p>Este documento aborda temas fundamentales sobre [Tema del documento]. A continuación, se presentan los puntos clave:</p>
          <ul>
            <li><strong>Concepto Principal 1:</strong> Explicación breve del primer concepto importante.</li>
            <li><strong>Concepto Principal 2:</strong> Explicación breve del segundo concepto importante.</li>
            <li><strong>Concepto Principal 3:</strong> Explicación breve del tercer concepto importante.</li>
            <li><strong>Aplicaciones prácticas:</strong> Cómo aplicar estos conceptos en situaciones reales.</li>
            <li><strong>Conclusiones:</strong> Puntos clave a recordar del documento.</li>
          </ul>
          <p>Este resumen te ayudará a comprender los aspectos más importantes del documento y a prepararte para evaluaciones.</p>
        `;
        
        addMessageToPdfChat(summary, 'bot');
      }, 3000);
    }

    // Mostrar opciones de test
    function showTestOptions() {
      testOptions.classList.remove('hidden');
      addMessageToPdfChat('He configurado las opciones para generar un test. Selecciona el número y tipo de preguntas.', 'bot');
    }

    // Generar test
    async function generateTest() {
      if (!currentPdfFile) return;
      
      const numQuestions = numQuestionsInput.value || 5;
      const questionType = questionTypeSelect.value;
      testOptions.classList.add('hidden');
      
      addMessageToPdfChat(`Generando test de ${numQuestions} preguntas (${questionType})...`, 'user');
      showTypingIndicator();
      
      // Simular generación de test
      setTimeout(() => {
        hideTypingIndicator();
        
        addMessageToPdfChat(`He creado un test de ${numQuestions} preguntas basado en el documento. ¡Buena suerte!`, 'bot');
        
        // Generar preguntas de ejemplo
        for (let i = 1; i <= numQuestions; i++) {
          const preguntaHtml = `
            <div class="test-question">
              <p><strong>Pregunta ${i}:</strong> ¿Cuál es el concepto principal explicado en la sección ${i} del documento?</p>
              <ul>
                <li>A) Opción A de respuesta</li>
                <li>B) Opción B de respuesta</li>
                <li>C) Opción C de respuesta</li>
                <li>D) Opción D de respuesta</li>
              </ul>
              <p class="answer"><strong>Respuesta correcta:</strong> C</p>
              <p class="explanation">Esta es la explicación de por qué la respuesta C es correcta, basada en el contenido del documento.</p>
            </div>
          `;
          addMessageToPdfChat(preguntaHtml, 'bot');
        }
        
        // En un caso real, aquí enviaríamos la solicitud al servidor
        // generateTestFromServer(numQuestions, questionType);
      }, 4000);
    }

    // Enviar mensaje al chat del PDF
    async function sendPdfMessage() {
      const message = pdfUserInput.value.trim();
      if (!message) return;
      
      addMessageToPdfChat(message, 'user');
      pdfUserInput.value = '';
      showTypingIndicator();
      
      // Simular respuesta de la IA
      setTimeout(() => {
        hideTypingIndicator();
        
        let response = "";
        if (message.toLowerCase().includes('explica') || message.toLowerCase().includes('qué es')) {
          response = `Basándome en el documento, puedo explicarte ese concepto. [Aquí iría una explicación detallada del concepto solicitado, extraída del contenido del PDF]. ¿Te ha quedado claro o necesitas más información?`;
        } else if (message.toLowerCase().includes('importante') || message.toLowerCase().includes('clave')) {
          response = `Según el análisis del documento, los puntos clave son: 1) [Primer punto importante], 2) [Segundo punto importante], 3) [Tercer punto importante]. Estos conceptos son fundamentales para comprender el tema.`;
        } else {
          response = `En relación con tu pregunta sobre "${message}", el documento menciona que [aquí iría la respuesta específica basada en el contenido del PDF]. ¿Te gustaría que profundice en algún aspecto en particular?`;
        }
        
        addMessageToPdfChat(response, 'bot');
      }, 2000);
    }

    // Mostrar preguntas sugeridas
    function showSuggestedQuestions() {
      const suggestedQuestions = [
        "¿Cuáles son los puntos principales del documento?",
        "Explícame el concepto más importante",
        "¿Qué aplicaciones prácticas tiene este contenido?",
        "Genera un esquema de estudio"
      ];
      
      let questionsHtml = `<div class="suggested-questions">`;
      suggestedQuestions.forEach(question => {
        questionsHtml += `<div class="suggested-question" onclick="askSuggestedQuestion('${question}')">${question}</div>`;
      });
      questionsHtml += `</div>`;
      
      addMessageToPdfChat("Puedes hacerme alguna de estas preguntas para comenzar:", 'bot');
      addMessageToPdfChat(questionsHtml, 'bot');
    }

    // Pregunta sugerida
    function askSuggestedQuestion(question) {
      pdfUserInput.value = question;
      sendPdfMessage();
    }

    // Funciones auxiliares para la interfaz
    function addMessageToPdfChat(message, sender) {
      const messageElement = document.createElement('div');
      messageElement.classList.add('message', `${sender}-message`);
      
      if (sender === 'user') {
        messageElement.innerHTML = `<p>${message}</p>`;
      } else {
        // Para mensajes del bot, permitimos HTML para formato más rico
        messageElement.innerHTML = message;
      }
      
      pdfChatBox.appendChild(messageElement);
      pdfChatBox.scrollTop = pdfChatBox.scrollHeight;
    }

    function showTypingIndicator() {
      const typingElement = document.createElement('div');
      typingElement.classList.add('message', 'bot-message');
      typingElement.id = 'typing-indicator';
      typingElement.innerHTML = '<div class="spinner"></div> <span>Analizando...</span>';
      pdfChatBox.appendChild(typingElement);
      pdfChatBox.scrollTop = pdfChatBox.scrollHeight;
    }

    function hideTypingIndicator() {
      const typingElement = document.getElementById('typing-indicator');
      if (typingElement) typingElement.remove();
    }

    // En un caso real, estas funciones se conectarían con el backend
    async function generateTestFromServer(numQuestions, questionType) {
      try {
        const response = await fetch('/generate-test-from-pdf', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            session_id: currentSessionId,
            num_preguntas: numQuestions,
            tipo_preguntas: questionType,
            usuario_id: 'ID_DEL_USUARIO'
          })
        });
        
        const data = await response.json();
        return data;
      } catch (error) {
        console.error('Error generando test:', error);
        return null;
      }
    }
