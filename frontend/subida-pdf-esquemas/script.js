// === Modo Oscuro ===
    const themeToggle = document.getElementById('themeToggle');
    const isDark = localStorage.getItem('darkMode') === 'true' || 
                   (!('darkMode' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches);
    if (isDark) document.body.classList.add('dark-mode');
    themeToggle.addEventListener('click', () => {
      document.body.classList.toggle('dark-mode');
      localStorage.setItem('darkMode', document.body.classList.contains('dark-mode'));
    });
    async function obtenerAuthHeaders() {
      const { idToken } = await import("/assets/auth.js");
      const token = await idToken();
      if (!token) {
        window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
        return null;
      }
      return { "Authorization": "Bearer " + token };
    }

    // === Estado global ===
    let esquema = '';
    let nombreArchivo = 'documento.pdf';
    // === Referencias DOM ===
    const formularioPdf = document.getElementById('form-subir-pdf');
    const uploadArea = document.getElementById('upload-area');
    const selectFileBtn = document.getElementById('select-file-btn');
    const archivoPdfInput = document.getElementById('archivo-pdf');
    const fileNameDisplay = document.getElementById('file-name');
    const contenedorCarga = document.getElementById('contenedor-carga');
    const alertaPreguntas = document.getElementById('alerta-preguntas');
    const mensajeError = document.getElementById('mensaje-error');
    const resultadoEsquema = document.getElementById('resultado-esquema');
    const contenidoEsquema = document.getElementById('contenido-esquema');
    const esquemaTitulo = document.getElementById('esquema-titulo');
    const esquemaMeta = document.getElementById('esquema-meta');
    const fechaEsquema = document.getElementById('fecha-esquema');
    const btnDescargarPdf = document.getElementById('btn-descargar-pdf');
    const btnDescargarTxt = document.getElementById('btn-descargar-txt');
    const btnNuevoPdf = document.getElementById('btn-nuevo-pdf');
    const btnFinalizar = document.getElementById('btn-finalizar');
    const autoSaveIndicator = document.getElementById('auto-save-indicator');
    // === Guardado Automático en Firebase ===
    async function guardarEsquemaAutomaticamente() {
      const nombreArchivoActual = nombreArchivo;
      try {
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) return;
        const res = await fetch("https://oposicion-age.onrender.com/guardar-esquema-pdf", {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders },
          body: JSON.stringify({
            esquema: esquema,
            nombre_archivo: nombreArchivoActual
          })
        });
        const datos = await res.json();
        if (!res.ok) {
          console.error("❌ Error al guardar esquema en Firebase:", datos.error);
        } else {
          console.log("✅ Esquema guardado automáticamente en Firebase");
          // Mostrar indicador
          autoSaveIndicator.classList.add('show');
          setTimeout(() => {
            autoSaveIndicator.classList.remove('show');
          }, 2000);
        }
      } catch (e) {
        console.error("⚠️ Error al guardar esquema en Firebase:", e);
      }
    }
    // === Funciones auxiliares ===
    function mostrarError(mensaje) {
      mensajeError.innerHTML = `<i class="fas fa-exclamation-triangle"></i> <strong>Error:</strong> ${mensaje}`;
      mensajeError.classList.remove('hidden');
      contenedorCarga.classList.add('hidden');
      resultadoEsquema.classList.add('hidden');
      formularioPdf.classList.remove('hidden');
    }
    function descargarArchivo(contenido, nombre, tipo) {
      const blob = new Blob([contenido], { type });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = nombre;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }
    function formatearFecha(fecha) {
      return new Intl.DateTimeFormat('es-ES', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      }).format(fecha);
    }
    async function descargarPDF() {
      const { jsPDF } = window.jspdf;
      const element = document.getElementById('esquema-profesional');
      const canvas = await html2canvas(element, {
        scale: 2,
        useCORS: true,
        backgroundColor: null
      });
      const imgData = canvas.toDataURL('image/png');
      const pdf = new jsPDF('p', 'mm', 'a4');
      const imgWidth = 190;
      const pageHeight = 295;
      const imgHeight = (canvas.height * imgWidth) / canvas.width;
      let heightLeft = imgHeight;
      let position = 10;
      pdf.addImage(imgData, 'PNG', 10, position, imgWidth, imgHeight);
      heightLeft -= pageHeight - position - 10;
      while (heightLeft >= 0) {
        position = heightLeft - imgHeight + 10;
        pdf.addPage();
        pdf.addImage(imgData, 'PNG', 10, position, imgWidth, imgHeight);
        heightLeft -= pageHeight;
      }
      pdf.save(`esquema_${nombreArchivo.replace('.pdf', '')}.pdf`);
    }
    // === Eventos ===
    selectFileBtn.addEventListener('click', () => archivoPdfInput.click());
    archivoPdfInput.addEventListener('change', () => {
      const file = archivoPdfInput.files[0];
      if (file) {
        if (file.size > 10 * 1024 * 1024) {
          Swal.fire({ icon: 'error', title: 'Archivo demasiado grande', text: 'El archivo supera los 10 MB.', confirmButtonText: 'Entendido' });
          archivoPdfInput.value = '';
          return;
        }
        nombreArchivo = file.name;
        const fileName = nombreArchivo.length > 30 ? nombreArchivo.substring(0, 27) + '...' : nombreArchivo;
        fileNameDisplay.innerHTML = `<i class="fas fa-file-pdf"></i> ${fileName}`;
        fileNameDisplay.classList.remove('hidden');
      } else {
        fileNameDisplay.classList.add('hidden');
      }
    });
    ['dragover', 'dragenter'].forEach(evt => {
      uploadArea.addEventListener(evt, e => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
      });
    });
    ['dragleave', 'dragend'].forEach(evt => {
      uploadArea.addEventListener(evt, () => {
        uploadArea.classList.remove('dragover');
      });
    });
    uploadArea.addEventListener('drop', e => {
      e.preventDefault();
      uploadArea.classList.remove('dragover');
      if (e.dataTransfer.files.length) {
        const file = e.dataTransfer.files[0];
        if (file.type !== 'application/pdf') {
          Swal.fire({ icon: 'error', title: 'Formato no válido', text: 'Solo se admiten archivos PDF.', confirmButtonText: 'Entendido' });
          return;
        }
        if (file.size > 10 * 1024 * 1024) {
          Swal.fire({ icon: 'error', title: 'Archivo demasiado grande', text: 'El archivo supera los 10 MB.', confirmButtonText: 'Entendido' });
          return;
        }
        archivoPdfInput.files = e.dataTransfer.files;
        archivoPdfInput.dispatchEvent(new Event('change'));
      }
    });
    btnNuevoPdf.addEventListener('click', () => {
      esquema = '';
      resultadoEsquema.classList.add('hidden');
      alertaPreguntas.classList.add('hidden');
      mensajeError.classList.add('hidden');
      formularioPdf.classList.remove('hidden');
      formularioPdf.reset();
      fileNameDisplay.classList.add('hidden');
    });
    btnFinalizar.addEventListener('click', () => {
      Swal.fire({
        icon: 'question',
        title: '¿Finalizar esquema?',
        text: '¿Estás seguro de que quieres finalizar?',
        showCancelButton: true,
        confirmButtonText: 'Sí, finalizar',
        cancelButtonText: 'Continuar',
      }).then((result) => {
        if (result.isConfirmed) {
          esquema = '';
          resultadoEsquema.classList.add('hidden');
          alertaPreguntas.classList.add('hidden');
          mensajeError.classList.add('hidden');
          formularioPdf.classList.remove('hidden');
          formularioPdf.reset();
          fileNameDisplay.classList.add('hidden');
          Swal.fire({ icon: 'success', title: 'Esquema finalizado', text: 'Puedes subir un nuevo documento.', confirmButtonText: 'Aceptar' });
        }
      });
    });
    btnDescargarTxt.addEventListener('click', () => {
      if (!esquema) return;
      descargarArchivo(esquema, `esquema_${nombreArchivo.replace('.pdf', '')}.txt`, 'text/plain');
      Swal.fire({ icon: 'success', title: 'Esquema descargado', text: 'El esquema se ha guardado como archivo de texto.', confirmButtonText: 'Aceptar' });
    });
    btnDescargarPdf.addEventListener('click', () => {
      if (!esquema) return;
      descargarPDF();
      Swal.fire({ icon: 'success', title: 'PDF descargado', text: 'El esquema se ha guardado en formato PDF profesional.', confirmButtonText: 'Aceptar' });
    });
    // === Envío del formulario ===
    formularioPdf.addEventListener('submit', async function(e) {
      e.preventDefault();
      const archivoInput = document.getElementById('archivo-pdf');
      if (!archivoInput.files.length) {
        Swal.fire({ icon: 'warning', title: 'Selecciona un archivo', text: 'Debes seleccionar un archivo PDF.', confirmButtonText: 'Entendido' });
        return;
      }
      const archivo = archivoInput.files[0];
      if (archivo.type !== 'application/pdf') {
        mostrarError('El archivo seleccionado no es un PDF válido.');
        return;
      }
      const formData = new FormData();
      formData.append('pdf', archivo);
      mensajeError.classList.add('hidden');
      alertaPreguntas.classList.add('hidden');
      formularioPdf.classList.add('hidden');
      contenedorCarga.classList.remove('hidden');
      // Cargar estado
      const barraProgreso = document.getElementById('progreso-carga');
      const textoPorcentaje = document.getElementById('texto-carga');
      const textoEstado = document.getElementById('texto-estado');
      const aiIcon = document.getElementById('ai-icon');
      const etapas = [
        { mensaje: "Leyendo texto del PDF…", icono: "📄", duracion: 12000 },
        { mensaje: "Analizando estructura del documento…", icono: "🔍", duracion: 12000 },
        { mensaje: "Identificando temas y subtemas…", icono: "📊", duracion: 12000 },
        { mensaje: "Organizando jerarquía conceptual…", icono: "🧠", duracion: 12000 },
        { mensaje: "Preparando esquema final…", icono: "✅", duracion: 12000 }
      ];
      let datosIA = null;
      let errorIA = null;
      let iaTerminada = false;
      const authHeaders = await obtenerAuthHeaders();
      if (!authHeaders) return;
      fetch("https://oposicion-age.onrender.com/generar-esquema-desde-pdf", {
        method: "POST",
        headers: authHeaders,
        body: formData
      })
      .then(async res => {
        if (res.status === 403) {
          throw new Error("Esta herramienta requiere el plan Premium. Ve a /planes/ para activarlo.");
        }
        if (!res.ok) {
          const errorData = await res.json().catch(() => ({}));
          throw new Error(errorData.error || `Error del servidor: ${res.status}`);
        }
        const datos = await res.json();
        if (!datos.esquema) throw new Error(datos.error || "No se pudo generar el esquema.");
        datosIA = datos;
      })
      .catch(err => { errorIA = err; })
      .finally(() => { iaTerminada = true; });
      function escribirTexto(elemento, texto) {
        elemento.textContent = '';
        setTimeout(() => {
          elemento.textContent = texto;
          elemento.style.animation = 'none';
          setTimeout(() => {
            elemento.style.animation = 'typing 3.5s steps(40, end), blink-caret 0.75s step-end infinite';
          }, 10);
        }, 10);
      }
      const inicio = Date.now();
      const duracionTotal = 60000;
      for (let i = 0; i < etapas.length; i++) {
        const etapa = etapas[i];
        aiIcon.textContent = etapa.icono;
        escribirTexto(textoEstado, etapa.mensaje);
        await new Promise(r => setTimeout(r, etapa.duracion));
        const progreso = Math.min(99, Math.round(((i + 1) / etapas.length) * 99));
        barraProgreso.style.width = `${progreso}%`;
        textoPorcentaje.textContent = `${progreso}%`;
      }
      while (!(iaTerminada && (Date.now() - inicio >= duracionTotal))) {
        await new Promise(r => setTimeout(r, 200));
      }
      if (errorIA) {
        mostrarError(errorIA.message);
        return;
      }
      aiIcon.textContent = "✅";
      escribirTexto(textoEstado, "¡Listo! Generando esquema…");
      barraProgreso.style.width = "100%";
      textoPorcentaje.textContent = "100%";
      await new Promise(r => setTimeout(r, 400));
      // Mostrar esquema
      esquema = datosIA.esquema || "No se pudo generar el esquema.";
      const fecha = new Date();
      fechaEsquema.textContent = formatearFecha(fecha);
      esquemaTitulo.textContent = `Esquema de ${nombreArchivo}`;
      // Procesar y mostrar con formato
      let htmlEsquema = esquema
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/^(#+)\s+(.*)$/gm, (match, hashes, title) => {
          const level = hashes.length;
          if (level === 1) return `<h2>${title}</h2>`;
          if (level === 2) return `<h3>${title}</h3>`;
          return `<p><strong>${title}</strong></p>`;
        })
        .replace(/^-\s+(.*)$/gm, '<li>$1</li>')
        .replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>');
      contenidoEsquema.innerHTML = htmlEsquema;
      contenedorCarga.classList.add('hidden');
      resultadoEsquema.classList.remove('hidden');
      // ✅ Guardar en Firebase
      guardarEsquemaAutomaticamente();
    });
    // === PWA ===
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('application/javascript,');
    }
