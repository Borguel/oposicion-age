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
    let resumen = '';
    let nombreArchivo = 'documento.pdf';
    let documentoIdActual = null;
    // === Referencias DOM ===
    const formularioPdf = document.getElementById('form-subir-pdf');
    // La tarjeta que envuelve el formulario ("Subir Documento PDF"): hay que
    // ocultar esta, no solo el <form>, o su cabecera se queda visible y
    // vacía por encima del resultado o del estado de carga.
    const formularioCard = document.getElementById('formulario-pdf');
    const uploadArea = document.getElementById('upload-area');
    const selectFileBtn = document.getElementById('select-file-btn');
    const archivoPdfInput = document.getElementById('archivo-pdf');
    const fileNameDisplay = document.getElementById('file-name');
    const contenedorCarga = document.getElementById('contenedor-carga');
    const alertaPreguntas = document.getElementById('alerta-preguntas');
    const mensajeError = document.getElementById('mensaje-error');
    const resultadoResumen = document.getElementById('resultado-resumen');
    const contenidoResumen = document.getElementById('contenido-resumen');
    const resumenTitulo = document.getElementById('resumen-titulo');
    const resumenMeta = document.getElementById('resumen-meta');
    const fechaResumen = document.getElementById('fecha-resumen');
    const btnDescargarPdf = document.getElementById('btn-descargar-pdf');
    const btnCerrar = document.getElementById('btn-cerrar');
    const autoSaveIndicator = document.getElementById('auto-save-indicator');
    // === Guardado Automático en Firebase ===
    async function guardarResumenAutomaticamente() {
      const nombreArchivoActual = nombreArchivo;
      try {
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) return;
        const res = await fetch("https://oposicion-age.onrender.com/guardar-resumen-pdf", {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders },
          body: JSON.stringify({
            resumen: resumen,
            nombre_archivo: nombreArchivoActual,
            documento_id: documentoIdActual
          })
        });
        const datos = await res.json();
        if (!res.ok) {
          console.error("❌ Error al guardar resumen en Firebase:", datos.error);
        } else {
          console.log("✅ Resumen guardado automáticamente en Firebase");
          // Mostrar indicador
          autoSaveIndicator.classList.add('show');
          setTimeout(() => {
            autoSaveIndicator.classList.remove('show');
          }, 2000);
        }
      } catch (e) {
        console.error("⚠️ Error al guardar resumen en Firebase:", e);
      }
    }
    // === Funciones auxiliares ===
    function mostrarError(mensaje) {
      mensajeError.innerHTML = `⚠️ <strong>Error:</strong> ${mensaje}`;
      mensajeError.classList.remove('hidden');
      contenedorCarga.classList.add('hidden');
      resultadoResumen.classList.add('hidden');
      formularioCard.classList.remove('hidden');
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
      const element = document.getElementById('resumen-profesional');
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
      pdf.save(`resumen_${nombreArchivo.replace('.pdf', '')}.pdf`);
    }
    // === Eventos ===
    selectFileBtn.addEventListener('click', () => archivoPdfInput.click());
    archivoPdfInput.addEventListener('change', () => {
      const file = archivoPdfInput.files[0];
      if (file) {
        if (file.size > 10 * 1024 * 1024) {
          Swal.fire({
            icon: 'error',
            title: 'Archivo demasiado grande',
            text: 'El archivo supera los 10 MB.',
            confirmButtonText: 'Entendido'
          });
          archivoPdfInput.value = '';
          return;
        }
        nombreArchivo = file.name;
        const fileName = nombreArchivo.length > 30 ? nombreArchivo.substring(0, 27) + '...' : nombreArchivo;
        fileNameDisplay.textContent = `📄 ${fileName}`;
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
    // "Cerrar" hace lo que antes hacía "Nuevo PDF": vuelve al formulario
    // para adjuntar otro documento -- ya no hace falta un botón "Nuevo
    // documento" aparte ni un "Finalizar" con diálogo de confirmación previo.
    btnCerrar.addEventListener('click', () => {
      resumen = '';
      resultadoResumen.classList.add('hidden');
      alertaPreguntas.classList.add('hidden');
      mensajeError.classList.add('hidden');
      formularioCard.classList.remove('hidden');
      formularioPdf.reset();
      fileNameDisplay.classList.add('hidden');
    });
    btnDescargarPdf.addEventListener('click', () => {
      if (!resumen) return;
      descargarPDF();
      Swal.fire({ icon: 'success', title: 'PDF descargado', text: 'El resumen se ha guardado en formato PDF profesional.', confirmButtonText: 'Aceptar' });
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
      formularioCard.classList.add('hidden');
      contenedorCarga.classList.remove('hidden');
      // Cargar estado
      const textoEstado = document.getElementById('texto-estado');
      const aiIcon = document.getElementById('ai-icon');
      const etapas = [
        { mensaje: "Leyendo texto del PDF…", icono: "📄" },
        { mensaje: "Analizando estructura del documento…", icono: "🔍" },
        { mensaje: "Identificando conceptos clave…", icono: "📊" },
        { mensaje: "Sintetizando información relevante…", icono: "🧠" },
        { mensaje: "Preparando resumen final…", icono: "✅" }
      ];
      let indiceEtapa = 0;
      aiIcon.textContent = etapas[0].icono;
      textoEstado.textContent = etapas[0].mensaje;
      const intervaloEtapas = setInterval(() => {
        indiceEtapa = (indiceEtapa + 1) % etapas.length;
        aiIcon.textContent = etapas[indiceEtapa].icono;
        textoEstado.textContent = etapas[indiceEtapa].mensaje;
      }, 2200);

      let datosIA = null;
      let errorIA = null;
      const authHeaders = await obtenerAuthHeaders();
      if (!authHeaders) { clearInterval(intervaloEtapas); return; }
      try {
        const res = await fetch("https://oposicion-age.onrender.com/resumir-documento", {
          method: "POST",
          headers: authHeaders,
          body: formData
        });
        if (res.status === 403) {
          throw new Error("Necesitas iniciar sesión o mejorar de plan para usar esta herramienta. Ve a /planes/ para más información.");
        }
        if (!res.ok) {
          const errorData = await res.json().catch(() => ({}));
          throw new Error(errorData.error || `Error del servidor: ${res.status}`);
        }
        const datos = await res.json();
        if (!datos.resumen) throw new Error(datos.error || "No se pudo generar el resumen.");
        datosIA = datos;
      } catch (err) {
        errorIA = err;
      }
      clearInterval(intervaloEtapas);
      if (errorIA) {
        mostrarError(errorIA.message);
        return;
      }
      // Mostrar resumen
      documentoIdActual = datosIA.documento_id || documentoIdActual;
      mostrarResumenResultado(datosIA.resumen, true);
    });

    // El resumen lo genera la IA a partir de un PDF subido por el usuario:
    // se escapa antes de aplicar el formato Markdown para que un documento
    // con "<script>" o similar como texto plano no se ejecute al pintarlo.
    function escaparHtml(texto) {
      const div = document.createElement('div');
      div.textContent = texto ?? '';
      return div.innerHTML;
    }

    function mostrarResumenResultado(textoResumen, guardar) {
      resumen = textoResumen || "No se pudo generar el resumen.";
      const fecha = new Date();
      fechaResumen.textContent = formatearFecha(fecha);
      resumenTitulo.textContent = `Resumen de ${nombreArchivo}`;
      // Procesar y mostrar con formato
      let htmlResumen = escaparHtml(resumen)
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/^(#+)\s+(.*)$/gm, (match, hashes, title) => {
          const level = hashes.length;
          if (level === 1) return `<h2>${title}</h2>`;
          if (level === 2) return `<h3>${title}</h3>`;
          return `<p><strong>${title}</strong></p>`;
        })
        .replace(/^-\s+(.*)$/gm, '<li>$1</li>')
        .replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>');
      contenidoResumen.innerHTML = htmlResumen;
      contenedorCarga.classList.add('hidden');
      resultadoResumen.classList.remove('hidden');
      // ✅ Guardar en Firebase (solo si es contenido recién generado, no al
      // solo visualizar un resumen que ya estaba guardado)
      if (guardar) guardarResumenAutomaticamente();
    }

    // === Llegar desde "Mis documentos" (biblioteca de la página Herramientas
    // IA): con ?documento_id= se salta la subida y usa el texto ya
    // extraído; con &ver=resumen carga directamente el resumen ya guardado
    // en vez de generar uno nuevo. ===
    (async function inicializarDesdeDocumento() {
      const params = new URLSearchParams(window.location.search);
      const documentoId = params.get('documento_id');
      const ver = params.get('ver');
      if (!documentoId) return;

      documentoIdActual = documentoId;
      formularioCard.classList.add('hidden');
      contenedorCarga.classList.remove('hidden');
      const textoEstado = document.getElementById('texto-estado');
      const aiIcon = document.getElementById('ai-icon');

      const authHeaders = await obtenerAuthHeaders();
      if (!authHeaders) return;

      if (ver === 'resumen') {
        textoEstado.textContent = 'Cargando tu resumen guardado…';
        try {
          const res = await fetch(`https://oposicion-age.onrender.com/documento/${documentoId}/resumen`, { headers: authHeaders });
          const datos = await res.json();
          if (!res.ok) throw new Error(datos.error || 'No se pudo cargar el resumen.');
          nombreArchivo = datos.nombre_archivo || nombreArchivo;
          mostrarResumenResultado(datos.resumen, false);
        } catch (err) {
          mostrarError(err.message);
        }
        return;
      }

      textoEstado.textContent = 'Generando resumen desde tu documento…';
      aiIcon.textContent = '🧠';
      try {
        const formData = new FormData();
        formData.append('documento_id', documentoId);
        const res = await fetch("https://oposicion-age.onrender.com/resumir-documento", {
          method: "POST",
          headers: authHeaders,
          body: formData
        });
        if (res.status === 403) throw new Error("Necesitas iniciar sesión o mejorar de plan para usar esta herramienta. Ve a /planes/ para más información.");
        if (!res.ok) {
          const errorData = await res.json().catch(() => ({}));
          throw new Error(errorData.error || `Error del servidor: ${res.status}`);
        }
        const datos = await res.json();
        if (!datos.resumen) throw new Error(datos.error || "No se pudo generar el resumen.");
        nombreArchivo = datos.nombre_archivo || nombreArchivo;
        mostrarResumenResultado(datos.resumen, true);
      } catch (err) {
        mostrarError(err.message);
      }
    })();
