{
    "name": "Asistente AGE - Tarjetas",
    "short_name": "Tarjetas AGE",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#2c3e50",
    "theme_color": "#2c3e50",
    "icons": [{
      "src": "image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🧠</text></svg>",
      "sizes": "192x192",
      "type": "image/svg+xml"
    }]
  }

// === Modo Oscuro ===
    const themeToggle = document.getElementById('themeToggle');
    const isDark = localStorage.getItem('darkMode') === 'true' || 
                   (!('darkMode' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches);
    if (isDark) document.body.classList.add('dark-mode');
    themeToggle.addEventListener('click', () => {
      document.body.classList.toggle('dark-mode');
      localStorage.setItem('darkMode', document.body.classList.contains('dark-mode'));
    });
    // === Estado global ===
    let tarjetas = [];
    let tarjetaActual = 0;
    // === Referencias DOM ===
    const formularioPdf = document.getElementById('form-subir-pdf');
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
    const btnDescargarJson = document.getElementById('btn-descargar-json');
    const btnDescargarCsv = document.getElementById('btn-descargar-csv');
    const btnNuevoPdf = document.getElementById('btn-nuevo-pdf');
    const btnFinalizar = document.getElementById('btn-finalizar');
    const contenedorListaTarjetas = document.getElementById('contenedor-lista-tarjetas');
    const btnEscuchar = document.getElementById('btn-escuchar');
    const autoSaveIndicator = document.getElementById('auto-save-indicator');

    // === Guardado Automático en Firebase ===
    async function guardarTarjetasAutomaticamente() {
      const usuario_id = window.usuarioEmail || "usuario_prueba";
      const nombreArchivo = document.getElementById('archivo-pdf').files[0]?.name || "documento.pdf";
      
      try {
        const res = await fetch("https://oposicion-age.onrender.com/guardar-tarjetas-pdf", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            usuario_id,
            tarjetas: tarjetas,
            nombre_archivo: nombreArchivo
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
            formularioPdf.classList.add('hidden');
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
      mensajeError.innerHTML = `<i class="fas fa-exclamation-triangle"></i> <strong>Error:</strong> ${mensaje}`;
      mensajeError.classList.remove('hidden');
      contenedorCarga.classList.add('hidden');
      modoEstudio.classList.add('hidden');
      listaTarjetas.classList.add('hidden');
      formularioPdf.classList.remove('hidden');
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
    function mostrarListaTarjetas() {
      let html = '';
      tarjetas.forEach((tarjeta, index) => {
        html += `
          <div class="tarjeta-miniatura" onclick="seleccionarTarjeta(${index})">
            <div class="pregunta">${tarjeta.pregunta}</div>
            <div class="respuesta">${tarjeta.respuesta}</div>
          </div>
        `;
      });
      contenedorListaTarjetas.innerHTML = html;
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
    btnDescargarJson.addEventListener('click', () => {
      const dataStr = JSON.stringify(tarjetas, null, 2);
      const dataBlob = new Blob([dataStr], {type: 'application/json'});
      const url = URL.createObjectURL(dataBlob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'tarjetas_memoria.json';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      Swal.fire({
        icon: 'success',
        title: 'Tarjetas descargadas',
        text: 'Las tarjetas se han descargado correctamente',
        confirmButtonText: 'Aceptar'
      });
    });
    btnDescargarCsv.addEventListener('click', () => {
      const csvContent = "Pregunta,Respuesta\n" + 
        tarjetas.map(t => 
          `"${(t.pregunta || '').replace(/"/g, '""')}","${(t.respuesta || '').replace(/"/g, '""')}"`
        ).join('\n');
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'tarjetas_memoria.csv';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      Swal.fire({
        icon: 'success',
        title: 'CSV descargado',
        text: 'Archivo listo para importar en Anki o Quizlet.',
        confirmButtonText: 'Aceptar'
      });
    });
    btnNuevoPdf.addEventListener('click', () => {
      Swal.fire({
        title: '¿Comenzar con nuevo PDF?',
        text: 'Se perderán las tarjetas actuales no guardadas.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Sí, nuevo PDF',
        cancelButtonText: 'Cancelar'
      }).then((result) => {
        if (result.isConfirmed) {
          tarjetas = [];
          tarjetaActual = 0;
          modoEstudio.classList.add('hidden');
          listaTarjetas.classList.add('hidden');
          alertaPreguntas.classList.add('hidden');
          mensajeError.classList.add('hidden');
          formularioPdf.classList.remove('hidden');
          formularioPdf.reset();
          fileNameDisplay.classList.add('hidden');
          limpiarEstado();
        }
      });
    });
    btnFinalizar.addEventListener('click', () => {
      Swal.fire({
        icon: 'question',
        title: '¿Finalizar estudio?',
        text: '¿Estás seguro de que quieres finalizar el estudio de estas tarjetas?',
        showCancelButton: true,
        confirmButtonText: 'Sí, finalizar',
        cancelButtonText: 'Continuar estudiando',
      }).then((result) => {
        if (result.isConfirmed) {
          tarjetas = [];
          tarjetaActual = 0;
          modoEstudio.classList.add('hidden');
          listaTarjetas.classList.add('hidden');
          alertaPreguntas.classList.add('hidden');
          mensajeError.classList.add('hidden');
          formularioPdf.classList.remove('hidden');
          formularioPdf.reset();
          fileNameDisplay.classList.add('hidden');
          limpiarEstado();
          Swal.fire({
            icon: 'success',
            title: 'Estudio finalizado',
            text: 'Puedes subir un nuevo PDF para generar más tarjetas',
            confirmButtonText: 'Aceptar'
          });
        }
      });
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
      const formData = new FormData();
      formData.append('pdf', archivo);
      mensajeError.classList.add('hidden');
      alertaPreguntas.classList.add('hidden');
      formularioPdf.classList.add('hidden');
      contenedorCarga.classList.remove('hidden');
      // Elementos de carga
      const barraProgreso = document.getElementById('progreso-carga');
      const textoPorcentaje = document.getElementById('texto-carga');
      const textoEstado = document.getElementById('texto-estado');
      const aiIcon = document.getElementById('ai-icon');
      const etapas = [
        { mensaje: "Leyendo texto del PDF…", icono: "📄", duracion: 12000 },
        { mensaje: "Extrayendo conceptos clave…", icono: "🔍", duracion: 12000 },
        { mensaje: "Analizando estructura del temario…", icono: "📊", duracion: 12000 },
        { mensaje: "Generando preguntas inteligentes…", icono: "🧠", duracion: 12000 },
        { mensaje: "Preparando tarjetas de estudio…", icono: "✅", duracion: 12000 }
      ];
      let datosIA = null;
      let errorIA = null;
      let iaTerminada = false;
      // Llamada a la IA
      fetch("https://oposicion-age.onrender.com/generar-tarjetas-desde-pdf", {
        method: "POST",
        body: formData
      })
      .then(async res => {
        if (!res.ok) {
          const errorData = await res.json().catch(() => ({}));
          throw new Error(errorData.error || `Error del servidor: ${res.status}`);
        }
        const datos = await res.json();
        if (!datos.tarjetas) throw new Error(datos.error || "No se generaron tarjetas.");
        datosIA = datos;
      })
      .catch(err => {
        errorIA = err;
      })
      .finally(() => {
        iaTerminada = true;
      });
      // Función para efecto typewriter
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
      const duracionTotal = 60000; // 60 segundos
      // Mostrar etapas
      for (let i = 0; i < etapas.length; i++) {
        const etapa = etapas[i];
        aiIcon.textContent = etapa.icono;
        escribirTexto(textoEstado, etapa.mensaje);
        await new Promise(r => setTimeout(r, etapa.duracion));
        const progreso = Math.min(99, Math.round(((i + 1) / etapas.length) * 99));
        barraProgreso.style.width = `${progreso}%`;
        textoPorcentaje.textContent = `${progreso}%`;
      }
      // Esperar a que IA termine y hayan pasado 60s
      while (!(iaTerminada && (Date.now() - inicio >= duracionTotal))) {
        await new Promise(r => setTimeout(r, 200));
      }
      if (errorIA) {
        mostrarError(errorIA.message);
        return;
      }
      // Completar al 100%
      aiIcon.textContent = "✅";
      escribirTexto(textoEstado, "¡Listo! Cargando tarjetas…");
      barraProgreso.style.width = "100%";
      textoPorcentaje.textContent = "100%";
      await new Promise(r => setTimeout(r, 400));
      // Procesar tarjetas
      let tarjetasFinales = datosIA.tarjetas || [];
      if (numTarjetas < tarjetasFinales.length) {
        tarjetasFinales = tarjetasFinales.slice(0, numTarjetas);
      }
      if (tarjetasFinales.length === 0) {
        mostrarError("No se generaron tarjetas válidas.");
        return;
      }
      // ✅ ALEATORIZAR
      tarjetas = shuffleArray(tarjetasFinales);
      if (datosIA.advertencia) {
        alertaPreguntas.innerHTML = `
          <i class="fas fa-exclamation-triangle"></i>
          <div>
            <strong>Aviso:</strong> ${datosIA.advertencia}
            ${datosIA.sugerencia ? `<br><em>${datosIA.sugerencia}</em>` : ''}
          </div>
        `;
        alertaPreguntas.classList.remove('hidden');
      }
      tarjetaActual = 0;
      contenedorCarga.classList.add('hidden');
      modoEstudio.classList.remove('hidden');
      mostrarTarjetaActual();
      // Guardar estado después de generar tarjetas
      guardarEstado();
      // ✅ GUARDAR EN FIREBASE
      guardarTarjetasAutomaticamente();
    });
    // === PWA ===
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('application/javascript,');
    }
    // === Inicialización - Cargar estado guardado al inicio ===
    document.addEventListener('DOMContentLoaded', function() {
      // Esperar un poco para que la página cargue completamente
      setTimeout(() => {
        mostrarConfirmacionRestaurar();
      }, 1000);
    });
