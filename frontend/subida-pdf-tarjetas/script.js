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
    let tarjetas = [];
    let tarjetaActual = 0;
    let nombreArchivo = 'documento.pdf';
    let documentoIdActual = null;
    // === Referencias DOM ===
    const formularioPdf = document.getElementById('form-subir-pdf');
    // La tarjeta que envuelve el formulario: hay que ocultar esta, no solo
    // el <form>, o su cabecera se queda visible y vacía.
    const formularioCard = document.getElementById('formulario-pdf');
    const uploadArea = document.getElementById('upload-area');
    const selectFileBtn = document.getElementById('select-file-btn');
    const archivoPdfInput = document.getElementById('archivo-pdf');
    const fileNameDisplay = document.getElementById('file-name');
    const numTarjetasInput = document.getElementById('num-tarjetas');
    const contenedorCarga = document.getElementById('contenedor-carga');
    const alertaPreguntas = document.getElementById('alerta-preguntas');
    const mensajeError = document.getElementById('mensaje-error');
    const modoEstudio = document.getElementById('modo-estudio');
    const listaTarjetas = document.getElementById('lista-tarjetas');
    const tarjetaElement = document.getElementById('tarjeta-actual');
    const preguntaTarjeta = document.getElementById('pregunta-tarjeta');
    const respuestaTarjeta = document.getElementById('respuesta-tarjeta');
    const tarjetaActualNum = document.getElementById('tarjeta-actual-num');
    const totalTarjetas = document.getElementById('total-tarjetas');
    const btnAnterior = document.getElementById('btn-anterior');
    const btnSiguiente = document.getElementById('btn-siguiente');
    const btnListaTarjetas = document.getElementById('btn-lista-tarjetas');
    const btnVolverEstudio = document.getElementById('btn-volver-estudio');
    const btnCerrar = document.getElementById('btn-cerrar');
    const contenedorListaTarjetas = document.getElementById('contenedor-lista-tarjetas');
    const btnEscuchar = document.getElementById('btn-escuchar');
    const autoSaveIndicator = document.getElementById('auto-save-indicator');

    // === Guardado Automático en Firebase ===
    async function guardarTarjetasAutomaticamente() {
      try {
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) return;
        const res = await fetch("https://oposicion-age.onrender.com/guardar-tarjetas-pdf", {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders },
          body: JSON.stringify({
            tarjetas: tarjetas,
            nombre_archivo: nombreArchivo,
            documento_id: documentoIdActual
          })
        });
        const datos = await res.json();
        if (!res.ok) {
          console.error("❌ Error al guardar tarjetas en Firebase:", datos.error);
        } else {
          console.log("✅ Tarjetas guardadas automáticamente en Firebase");
        }
      } catch (e) {
        console.error("⚠️ Error al guardar tarjetas en Firebase:", e);
      }
    }

    // === Funciones de Auto-guardado ===
    function guardarEstado() {
      const estado = {
        tarjetas: tarjetas,
        tarjetaActual: tarjetaActual,
        timestamp: new Date().getTime()
      };
      localStorage.setItem('tarjetasMemoria', JSON.stringify(estado));
      // Mostrar indicador de guardado
      autoSaveIndicator.classList.add('show');
      setTimeout(() => {
        autoSaveIndicator.classList.remove('show');
      }, 2000);
    }
    function cargarEstado() {
      const estadoGuardado = localStorage.getItem('tarjetasMemoria');
      if (estadoGuardado) {
        try {
          const estado = JSON.parse(estadoGuardado);
          // Verificar si el estado no es demasiado viejo (menos de 7 días)
          const unaSemana = 7 * 24 * 60 * 60 * 1000;
          if (new Date().getTime() - estado.timestamp < unaSemana) {
            return estado;
          } else {
            // Limpiar estado viejo
            localStorage.removeItem('tarjetasMemoria');
          }
        } catch (e) {
          console.error('Error cargando estado guardado:', e);
          localStorage.removeItem('tarjetasMemoria');
        }
      }
      return null;
    }
    function limpiarEstado() {
      localStorage.removeItem('tarjetasMemoria');
    }
    function mostrarConfirmacionRestaurar() {
      const estado = cargarEstado();
      if (estado && estado.tarjetas && estado.tarjetas.length > 0) {
        Swal.fire({
          title: '¿Restaurar sesión anterior?',
          text: `Se encontraron ${estado.tarjetas.length} tarjetas de una sesión anterior. ¿Quieres restaurarlas?`,
          icon: 'question',
          showCancelButton: true,
          confirmButtonText: 'Sí, restaurar',
          cancelButtonText: 'No, empezar de nuevo',
          confirmButtonColor: '#3498db',
          cancelButtonColor: '#95a5a6'
        }).then((result) => {
          if (result.isConfirmed) {
            tarjetas = estado.tarjetas;
            tarjetaActual = estado.tarjetaActual || 0;
            formularioCard.classList.add('hidden');
            modoEstudio.classList.remove('hidden');
            mostrarTarjetaActual();
            Swal.fire({
              title: 'Sesión restaurada',
              text: `Se han cargado ${tarjetas.length} tarjetas.`,
              icon: 'success',
              confirmButtonText: 'Continuar estudiando'
            });
          } else {
            limpiarEstado();
          }
        });
      }
    }
    // === Funciones auxiliares ===
    function mostrarError(mensaje) {
      mensajeError.innerHTML = `⚠️ <strong>Error:</strong> ${mensaje}`;
      mensajeError.classList.remove('hidden');
      contenedorCarga.classList.add('hidden');
      modoEstudio.classList.add('hidden');
      listaTarjetas.classList.add('hidden');
      formularioCard.classList.remove('hidden');
    }
    function formatearFecha(fecha) {
      return new Intl.DateTimeFormat('es-ES', {
        year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit'
      }).format(fecha);
    }
    // === Descarga en PDF ===
    // Cada tarjeta (número + pregunta + respuesta) se mide como un único
    // bloque y se pagina entera de una vez -- igual que en
    // subida-pdf-resumen/esquemas -- para que una tarjeta nunca quede
    // partida a la mitad entre dos páginas.
    function descargarPDF() {
      const { jsPDF } = window.jspdf;
      const doc = new jsPDF({ unit: "mm", format: "a4" });
      const margin = 18;
      const pageWidth = doc.internal.pageSize.getWidth();
      const pageHeight = doc.internal.pageSize.getHeight();
      const anchoTexto = pageWidth - margin * 2 - 4;
      const limiteInferior = pageHeight - 22;
      let yPos = 0;
      let pagina = 0;

      function pintarPie() {
        doc.setFont("helvetica", "normal");
        doc.setFontSize(9);
        doc.setTextColor(150);
        doc.text(`Página ${pagina + 1}`, pageWidth - margin, pageHeight - 10, { align: "right" });
        doc.text("Oposición AGE", margin, pageHeight - 10);
        doc.setTextColor(0);
      }
      function nuevaPagina() {
        doc.addPage();
        pagina++;
        yPos = 24;
        pintarPie();
      }
      function asegurarEspacio(altura) {
        if (yPos + altura > limiteInferior) nuevaPagina();
      }

      // Portada
      yPos = 26;
      doc.setFont("helvetica", "bold");
      doc.setFontSize(20);
      doc.text(`Tarjetas de ${nombreArchivo}`, pageWidth / 2, yPos, { align: "center" });
      yPos += 10;
      doc.setFont("helvetica", "normal");
      doc.setFontSize(11);
      doc.setTextColor(110);
      doc.text(formatearFecha(new Date()), pageWidth / 2, yPos, { align: "center" });
      doc.setTextColor(0);
      yPos += 14;
      pintarPie();

      // Mismos colores de marca que la versión en pantalla (theme.css).
      const NARANJA_OSCURO = [232, 134, 15];
      const ALTO_LINEA_NUMERO = 12.5 * 0.42;
      const ALTO_LINEA_TEXTO = 11 * 0.42;

      function medirTarjeta(t, i) {
        doc.setFont("helvetica", "bold");
        doc.setFontSize(12.5);
        const lineasNumero = doc.splitTextToSize(`Tarjeta ${i + 1}`, anchoTexto);
        doc.setFont("helvetica", "bold");
        doc.setFontSize(11.5);
        const lineasPregunta = doc.splitTextToSize(t.pregunta || "Sin pregunta", anchoTexto);
        doc.setFont("helvetica", "normal");
        doc.setFontSize(11);
        const lineasRespuesta = doc.splitTextToSize(t.respuesta || "Sin respuesta", anchoTexto);
        const altura = 6
          + lineasNumero.length * ALTO_LINEA_NUMERO + 3
          + lineasPregunta.length * (11.5 * 0.42) + 4
          + lineasRespuesta.length * ALTO_LINEA_TEXTO + 8;
        return { lineasNumero, lineasPregunta, lineasRespuesta, altura };
      }

      tarjetas.map(medirTarjeta).forEach((m) => {
        asegurarEspacio(m.altura);
        yPos += 6;

        doc.setFont("helvetica", "bold");
        doc.setFontSize(12.5);
        doc.setTextColor(...NARANJA_OSCURO);
        m.lineasNumero.forEach((linea) => { doc.text(linea, margin, yPos); yPos += ALTO_LINEA_NUMERO; });
        doc.setTextColor(0);
        yPos += 3;

        doc.setFont("helvetica", "bold");
        doc.setFontSize(11.5);
        m.lineasPregunta.forEach((linea) => { doc.text(linea, margin, yPos); yPos += 11.5 * 0.42; });
        yPos += 4;

        doc.setFont("helvetica", "normal");
        doc.setFontSize(11);
        m.lineasRespuesta.forEach((linea) => { doc.text(linea, margin, yPos); yPos += ALTO_LINEA_TEXTO; });
        yPos += 6;

        doc.setDrawColor(225);
        doc.line(margin, yPos, pageWidth - margin, yPos);
        yPos += 8;
      });

      doc.save(`tarjetas_${nombreArchivo.replace('.pdf', '')}.pdf`);
    }
    function shuffleArray(array) {
      const arr = [...array];
      for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [arr[i], arr[j]] = [arr[j], arr[i]];
      }
      return arr;
    }
    function speak(text) {
      if ('speechSynthesis' in window) {
        speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'es-ES';
        utterance.rate = 0.9;
        speechSynthesis.speak(utterance);
      }
    }
    function mostrarTarjetaActual() {
      if (tarjetas.length === 0) return;
      const tarjeta = tarjetas[tarjetaActual];
      preguntaTarjeta.textContent = tarjeta.pregunta || 'Sin pregunta';
      respuestaTarjeta.textContent = tarjeta.respuesta || 'Sin respuesta';
      tarjetaActualNum.textContent = tarjetaActual + 1;
      totalTarjetas.textContent = tarjetas.length;
      tarjetaElement.classList.remove('volteada');
      btnAnterior.disabled = tarjetaActual === 0;
      btnSiguiente.disabled = tarjetaActual === tarjetas.length - 1;
      // Auto-guardar al cambiar de tarjeta
      guardarEstado();
    }
    // Las tarjetas las genera la IA a partir de un PDF subido por el
    // usuario: se escapan antes de pintarlas para que un documento con
    // "<script>" o similar como texto plano no se ejecute al mostrarlas.
    function escaparHtml(texto) {
      const div = document.createElement('div');
      div.textContent = texto ?? '';
      return div.innerHTML;
    }
    function mostrarListaTarjetas() {
      let html = '';
      tarjetas.forEach((tarjeta, index) => {
        html += `
          <div class="tarjeta-miniatura" data-index="${index}">
            <div class="pregunta">${escaparHtml(tarjeta.pregunta)}</div>
            <div class="respuesta">${escaparHtml(tarjeta.respuesta)}</div>
          </div>
        `;
      });
      contenedorListaTarjetas.innerHTML = html;
      // Delegado en vez de onclick inline en cada miniatura, para no
      // depender de 'unsafe-inline' en la política de seguridad de contenido.
      contenedorListaTarjetas.querySelectorAll('[data-index]').forEach((el) => {
        el.addEventListener('click', () => seleccionarTarjeta(Number(el.dataset.index)));
      });
    }
    function seleccionarTarjeta(index) {
      tarjetaActual = index;
      listaTarjetas.classList.add('hidden');
      modoEstudio.classList.remove('hidden');
      mostrarTarjetaActual();
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
            text: 'El archivo supera los 10 MB. Por favor, sube un PDF más ligero.',
            confirmButtonText: 'Entendido'
          });
          archivoPdfInput.value = '';
          return;
        }
        const fileName = file.name.length > 30 ? file.name.substring(0, 27) + '...' : file.name;
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
          Swal.fire({
            icon: 'error',
            title: 'Formato no válido',
            text: 'Solo se admiten archivos PDF.',
            confirmButtonText: 'Entendido'
          });
          return;
        }
        if (file.size > 10 * 1024 * 1024) {
          Swal.fire({
            icon: 'error',
            title: 'Archivo demasiado grande',
            text: 'El archivo supera los 10 MB.',
            confirmButtonText: 'Entendido'
          });
          return;
        }
        archivoPdfInput.files = e.dataTransfer.files;
        archivoPdfInput.dispatchEvent(new Event('change'));
      }
    });
    tarjetaElement.addEventListener('click', (e) => {
      if (!e.target.closest('#btn-escuchar')) {
        tarjetaElement.classList.toggle('volteada');
      }
    });
    btnEscuchar.addEventListener('click', () => {
      speak(respuestaTarjeta.textContent);
    });
    btnAnterior.addEventListener('click', () => {
      if (tarjetaActual > 0) {
        tarjetaActual--;
        mostrarTarjetaActual();
      }
    });
    btnSiguiente.addEventListener('click', () => {
      if (tarjetaActual < tarjetas.length - 1) {
        tarjetaActual++;
        mostrarTarjetaActual();
      }
    });
    btnListaTarjetas.addEventListener('click', () => {
      modoEstudio.classList.add('hidden');
      listaTarjetas.classList.remove('hidden');
      mostrarListaTarjetas();
    });
    btnVolverEstudio.addEventListener('click', () => {
      listaTarjetas.classList.add('hidden');
      modoEstudio.classList.remove('hidden');
    });
    document.getElementById('btn-descargar-pdf').addEventListener('click', descargarPDF);
    document.getElementById('btn-descargar-pdf-lista').addEventListener('click', descargarPDF);
    // "Cerrar" reúne lo que antes hacían por separado "Nuevo PDF" y
    // "Finalizar" (los dos volvían al formulario para adjuntar otro
    // documento): un único botón, sin diálogo de confirmación previo.
    btnCerrar.addEventListener('click', () => {
      tarjetas = [];
      tarjetaActual = 0;
      modoEstudio.classList.add('hidden');
      listaTarjetas.classList.add('hidden');
      alertaPreguntas.classList.add('hidden');
      mensajeError.classList.add('hidden');
      formularioCard.classList.remove('hidden');
      formularioPdf.reset();
      fileNameDisplay.classList.add('hidden');
      limpiarEstado();
    });
    // === Envío del formulario con carga mejorada ===
    formularioPdf.addEventListener('submit', async function(e) {
      e.preventDefault();
      const archivoInput = document.getElementById('archivo-pdf');
      const numTarjetas = parseInt(numTarjetasInput.value);
      if (!archivoInput.files.length) {
        Swal.fire({
          icon: 'warning',
          title: 'Selecciona un archivo',
          text: 'Debes seleccionar un archivo PDF para continuar.',
          confirmButtonText: 'Entendido'
        });
        return;
      }
      const archivo = archivoInput.files[0];
      if (archivo.type !== 'application/pdf') {
        mostrarError('El archivo seleccionado no es un PDF válido.');
        return;
      }
      nombreArchivo = archivo.name;
      const formData = new FormData();
      formData.append('pdf', archivo);
      formData.append('num_tarjetas', numTarjetasInput.value || 10);
      mensajeError.classList.add('hidden');
      alertaPreguntas.classList.add('hidden');
      formularioCard.classList.add('hidden');
      contenedorCarga.classList.remove('hidden');
      // Elementos de carga
      const textoEstado = document.getElementById('texto-estado');
      const aiIcon = document.getElementById('ai-icon');
      const etapas = [
        { mensaje: "Leyendo texto del PDF…", icono: "📄" },
        { mensaje: "Extrayendo conceptos clave…", icono: "🔍" },
        { mensaje: "Analizando estructura del temario…", icono: "📊" },
        { mensaje: "Generando preguntas inteligentes…", icono: "🧠" },
        { mensaje: "Preparando tarjetas de estudio…", icono: "✅" }
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
        const res = await fetch("https://oposicion-age.onrender.com/generar-tarjetas-desde-pdf", {
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
        if (!datos.tarjetas) throw new Error(datos.error || "No se generaron tarjetas.");
        datosIA = datos;
      } catch (err) {
        errorIA = err;
      }
      clearInterval(intervaloEtapas);
      if (errorIA) {
        mostrarError(errorIA.message);
        return;
      }
      // Procesar tarjetas
      let tarjetasFinales = datosIA.tarjetas || [];
      if (numTarjetas < tarjetasFinales.length) {
        tarjetasFinales = tarjetasFinales.slice(0, numTarjetas);
      }
      documentoIdActual = datosIA.documento_id || documentoIdActual;
      iniciarModoEstudio(tarjetasFinales, true, datosIA.advertencia, datosIA.sugerencia);
    });

    function iniciarModoEstudio(tarjetasEntrada, guardar, advertencia, sugerencia) {
      if (!tarjetasEntrada || tarjetasEntrada.length === 0) {
        mostrarError("No se generaron tarjetas válidas.");
        return;
      }
      // ✅ ALEATORIZAR
      tarjetas = shuffleArray(tarjetasEntrada);
      if (advertencia) {
        alertaPreguntas.innerHTML = `
          ⚠️
          <div>
            <strong>Aviso:</strong> ${advertencia}
            ${sugerencia ? `<br><em>${sugerencia}</em>` : ''}
          </div>
        `;
        alertaPreguntas.classList.remove('hidden');
      }
      tarjetaActual = 0;
      contenedorCarga.classList.add('hidden');
      modoEstudio.classList.remove('hidden');
      mostrarTarjetaActual();
      guardarEstado();
      // ✅ Guardar en Firebase (solo si es contenido recién generado, no al
      // solo repasar tarjetas ya guardadas)
      if (guardar) guardarTarjetasAutomaticamente();
    }

    // === Llegar desde "Mis documentos" ===
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

      if (ver === 'tarjetas') {
        const modo = params.get('modo') || 'todas';
        const cantidad = params.get('cantidad') || '10';
        textoEstado.textContent = 'Cargando tus tarjetas guardadas…';
        try {
          const qs = modo === 'aleatorias' ? `?modo=aleatorias&cantidad=${encodeURIComponent(cantidad)}` : '?modo=todas';
          const res = await fetch(`https://oposicion-age.onrender.com/documento/${documentoId}/tarjetas${qs}`, { headers: authHeaders });
          const datos = await res.json();
          if (!res.ok) throw new Error(datos.error || 'No se pudieron cargar las tarjetas.');
          iniciarModoEstudio(datos.tarjetas, false);
        } catch (err) {
          mostrarError(err.message);
        }
        return;
      }

      textoEstado.textContent = 'Generando tarjetas desde tu documento…';
      aiIcon.textContent = '🧠';
      try {
        const formData = new FormData();
        formData.append('documento_id', documentoId);
        formData.append('num_tarjetas', numTarjetasInput.value || 10);
        const res = await fetch("https://oposicion-age.onrender.com/generar-tarjetas-desde-pdf", {
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
        if (!datos.tarjetas) throw new Error(datos.error || "No se generaron tarjetas.");
        documentoIdActual = datos.documento_id || documentoIdActual;
        iniciarModoEstudio(datos.tarjetas, true, datos.advertencia, datos.sugerencia);
      } catch (err) {
        mostrarError(err.message);
      }
    })();

    // === Inicialización - Cargar estado guardado al inicio (solo si no se
    // llega desde "Mis documentos", para no pisar esa carga con un aviso de
    // restaurar una sesión de tarjetas antigua sin relación) ===
    document.addEventListener('DOMContentLoaded', function() {
      if (new URLSearchParams(window.location.search).get('documento_id')) return;
      // Esperar un poco para que la página cargue completamente
      setTimeout(() => {
        mostrarConfirmacionRestaurar();
      }, 1000);
    });
