import { icono } from "/assets/icons.js";
import { marcarContenidoListo } from "/assets/auth.js";

(async () => {
  const { protegerPagina } = await import("/assets/plan.js");
  await protegerPagina("premium");
  marcarContenidoListo();
})();

// Iconos estáticos del markup (los que no cambian dinámicamente por JS): se
// pintan aquí, una sola vez, a partir de los data-icon del HTML.
document.querySelectorAll("[data-icon]").forEach((el) => {
  el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 24));
});

async function obtenerAuthHeaders() {
      const { obtenerAuthHeaders: fn } = await import("/assets/auth.js");
      return fn();
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
          const { mostrarErrorGlobal } = await import("/assets/notificaciones.js");
          mostrarErrorGlobal("No se pudieron guardar las tarjetas en tu cuenta. Las tarjetas siguen visibles en pantalla, pero no han quedado guardadas.");
        } else {
          console.log("✅ Tarjetas guardadas automáticamente en Firebase");
        }
      } catch (e) {
        console.error("⚠️ Error al guardar tarjetas en Firebase:", e);
        const { mostrarErrorGlobal } = await import("/assets/notificaciones.js");
        mostrarErrorGlobal("No se pudieron guardar las tarjetas en tu cuenta. Las tarjetas siguen visibles en pantalla, pero no han quedado guardadas.");
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
      mensajeError.innerHTML = `${icono("alerta", 18)} <strong>Error:</strong> ${mensaje}`;
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
        doc.text("Domina tu Opo", margin, pageHeight - 10);
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
      // Título envuelto en varias líneas (10/08/2026, ver el comentario
      // largo en subida-pdf-resumen/script.js -- mismo bug, mismo arreglo).
      const lineasTitulo = doc.splitTextToSize(`Tarjetas de ${nombreArchivo.replace(/_/g, " ")}`, anchoTexto);
      lineasTitulo.forEach((linea) => {
        doc.text(linea, pageWidth / 2, yPos, { align: "center" });
        yPos += 8;
      });
      yPos += 2;
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
    // La tarjeta usa altura fija para el volteo 3D (las dos caras van
    // superpuestas con position:absolute, así que necesitan la misma
    // altura) -- con una pregunta o respuesta larga, el texto se salía por
    // debajo del borde redondeado en vez de quedarse dentro (05/08/2026,
    // bug real reportado con capturas). pregunta-tarjeta/respuesta-tarjeta
    // son hijos normales dentro de un flex en columna (no estirados por
    // align-items), así que su altura natural ya refleja lo que ocupa el
    // texto real aunque el padre tenga una altura fija -- se mide esa
    // altura y se agranda la tarjeta para que quepa siempre entera.
    function ajustarAlturaTarjeta() {
      const ALTURA_MINIMA = window.innerWidth <= 768 ? 250 : 300;
      const ALTURA_EXTRAS = 140; // relleno + separación + botón "Escuchar" (cara trasera) + hueco para el indicador de volteo
      const necesaria = Math.max(preguntaTarjeta.scrollHeight, respuestaTarjeta.scrollHeight) + ALTURA_EXTRAS;
      tarjetaElement.style.height = Math.max(ALTURA_MINIMA, necesaria) + 'px';
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
      ajustarAlturaTarjeta();
      // Auto-guardar al cambiar de tarjeta
      guardarEstado();
    }

    let temporizadorRedimension = null;
    window.addEventListener('resize', () => {
      clearTimeout(temporizadorRedimension);
      temporizadorRedimension = setTimeout(ajustarAlturaTarjeta, 150);
    });
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
    // Espera 'ms' como mínimo junto a 'promesa' -- ver el mismo helper en
    // subida-pdf-generar-test/script.js.
    function conEsperaMinima(promesa, ms) {
      return Promise.all([promesa, new Promise((resolve) => setTimeout(resolve, ms))]).then(([resultado]) => resultado);
    }

    // Sustituye el formulario por un aviso de que la generación ya ha
    // arrancado en el servidor y de que el resto del progreso se sigue
    // desde "Mis documentos" -- ver el comentario largo en
    // subida-pdf-generar-test/script.js, mismo motivo y mismo patrón.
    function mostrarRedireccionAMisDocumentos() {
      formularioCard.classList.add('hidden');
      contenedorCarga.classList.remove('hidden');
      document.getElementById('ai-icon').innerHTML = icono('cerebro', 32);
      document.getElementById('texto-estado').textContent = 'Nos ponemos a generar las tarjetas de tu documento…';
      const detalle = document.getElementById('texto-estado-detalle');
      detalle.textContent = 'Puede tardar unos minutos según lo largo que sea el documento. Te llevamos a "Mis documentos" para que veas cómo van apareciendo, sin tener que esperar aquí.';
      detalle.classList.remove('hidden');
      document.getElementById('progress-container-numerico').classList.add('hidden');
      document.getElementById('barra-indeterminada-redireccion').classList.remove('hidden');
      // El enlace "Ir a Mis documentos ahora" NO se muestra aquí todavía --
      // ver el comentario largo en subida-pdf-resumen/script.js (mismo bug:
      // es un <a href> normal, así que pulsarlo antes de que el POST llegue
      // al servidor cancela la petición en marcha en vez de solo saltarse
      // la espera). Se revela más abajo, en iniciarGeneracionBancoTarjetas,
      // una vez confirmado que el servidor ya ha arrancado.
      document.getElementById('sugerencia-mientras-tanto').classList.remove('hidden');
    }

    // Dispara la generación del banco completo de tarjetas y devuelve en
    // cuanto el servidor confirma que ha arrancado, sin esperar a que
    // termine -- ver el comentario largo en
    // subida-pdf-generar-test/script.js (iniciarGeneracionBancoPreguntas),
    // mismo motivo y mismo patrón.
    // Devuelve el documento_id en cuanto llega el evento "inicio" -- ver
    // el comentario largo en subida-pdf-generar-test/script.js
    // (iniciarGeneracionBancoPreguntas), mismo motivo y mismo patrón.
    async function iniciarGeneracionBancoTarjetas(formData, authHeaders) {
      const res = await fetch("https://oposicion-age.onrender.com/generar-banco-tarjetas-desde-pdf",
        { method: "POST", headers: authHeaders, body: formData });
      if (res.status === 403) {
        throw new Error('Necesitas iniciar sesión o mejorar de plan para usar esta herramienta. <a href="/planes/">Ver planes</a>');
      }
      if (res.status === 409) {
        throw new Error('Ya se está generando el banco de tarjetas de este documento. Consulta el progreso en "Mis documentos".');
      }
      if (res.status === 429) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(`${errorData.error || "Has alcanzado el límite de uso de esta herramienta por ahora."} <a href="/planes/">Ver planes</a>`);
      }
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.error || `Error del servidor: ${res.status}`);
      }
      // A partir de aquí el servidor ya ha aceptado la petición y ha
      // empezado a generar -- ahora sí es seguro ofrecer el enlace manual.
      document.getElementById('enlace-ir-a-mis-documentos').classList.remove('hidden');
      if (!res.body) return null;

      const lector = res.body.getReader();
      const decodificador = new TextDecoder();
      let buffer = "";
      let documentoId = null;
      try {
        for (let intentos = 0; intentos < 5 && !documentoId; intentos++) {
          const { done, value } = await lector.read();
          if (done) break;
          buffer += decodificador.decode(value, { stream: true });
          const bloques = buffer.split("\n\n");
          buffer = bloques.pop();
          for (const bloque of bloques) {
            const linea = bloque.trim();
            if (!linea.startsWith("data: ")) continue;
            try {
              const evento = JSON.parse(linea.slice(6));
              if (evento.tipo === "inicio") {
                documentoId = evento.documento_id;
                break;
              }
            } catch {
              // ignorar trozo no parseable
            }
          }
        }
      } finally {
        lector.cancel().catch(() => {});
      }
      return documentoId;
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
        fileNameDisplay.innerHTML = icono("documento", 16);
        fileNameDisplay.append(` ${fileName}`);
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
    // Si documentoIdActual ya está fijado (llegada desde "Mis documentos"
    // para generar tarjetas NUEVAS, ver inicializarDesdeDocumento más abajo)
    // no hace falta volver a subir el PDF -- se manda el documento_id ya
    // existente directamente.
    formularioPdf.addEventListener('submit', async function(e) {
      e.preventDefault();
      const formData = new FormData();

      if (documentoIdActual) {
        formData.append('documento_id', documentoIdActual);
      } else {
        const archivoInput = document.getElementById('archivo-pdf');
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
        formData.append('pdf', archivo);
      }
      mensajeError.classList.add('hidden');
      alertaPreguntas.classList.add('hidden');
      mostrarRedireccionAMisDocumentos();

      const authHeaders = await obtenerAuthHeaders();
      if (!authHeaders) return;

      try {
        const documentoId = await conEsperaMinima(iniciarGeneracionBancoTarjetas(formData, authHeaders), 9000);
        window.location.href = documentoId
          ? `/mis-documentos/?destacar=${encodeURIComponent(documentoId)}`
          : "/mis-documentos/";
      } catch (err) {
        mostrarError(err.message || "Error al generar las tarjetas.");
      }
    });

    function iniciarModoEstudio(tarjetasEntrada, guardar, advertencia, sugerencia) {
      if (!tarjetasEntrada || tarjetasEntrada.length === 0) {
        mostrarError("No se generaron tarjetas válidas.");
        return;
      }
      // ✅ ALEATORIZAR
      tarjetas = shuffleArray(tarjetasEntrada);
      // "Volver al documento" (05/08/2026): visible durante el repaso, para
      // poder generar más test o tarjetas del mismo documento sin tener
      // que salir del todo y buscarlo a mano en Mis Documentos.
      if (documentoIdActual) {
        const enlaceVolver = document.getElementById('enlace-volver-documento');
        if (enlaceVolver) {
          enlaceVolver.href = `/mis-documentos/?destacar=${encodeURIComponent(documentoIdActual)}`;
          enlaceVolver.classList.remove('hidden');
        }
      }
      if (advertencia) {
        alertaPreguntas.innerHTML = `
          <div class="alerta-aviso">
            <span class="alerta-aviso-icono">${icono("alerta", 20)}</span>
            <div>
              <strong>Aviso:</strong> ${advertencia}
              ${sugerencia ? `<br><em>${sugerencia}</em>` : ''}
            </div>
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

      import('/assets/otras-herramientas-pdf.js').then(({ pintarAccesosOtrasHerramientas }) => {
        pintarAccesosOtrasHerramientas({
          contenedor: document.getElementById('otras-herramientas-bloque'),
          documentoId: documentoIdActual,
          herramientaActual: 'subida-pdf-tarjetas',
        });
      });
    }

    // === Llegar desde "Mis documentos" ===
    (async function inicializarDesdeDocumento() {
      const params = new URLSearchParams(window.location.search);
      const documentoId = params.get('documento_id');
      const ver = params.get('ver');
      if (!documentoId) return;

      documentoIdActual = documentoId;

      if (ver === 'tarjetas') {
        formularioCard.classList.add('hidden');
        contenedorCarga.classList.remove('hidden');
        const textoEstado = document.getElementById('texto-estado');
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) return;
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

      // Repaso sacado del banco de tarjetas pre-generado (ver "Mis
      // documentos", filaBanco): a diferencia de "ver=tarjetas" (el último
      // set GUARDADO de este documento), esto tira de usuarios/{uid}/
      // banco_tarjetas_pdf/{documento_id} -- el pool generado en segundo
      // plano, del que se puede sacar un repaso de tamaño N (?cantidad=N) o
      // de todo lo generado (sin "cantidad") sin volver a gastar en IA.
      if (ver === 'banco-tarjetas') {
        formularioCard.classList.add('hidden');
        contenedorCarga.classList.remove('hidden');
        const textoEstado = document.getElementById('texto-estado');
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) return;
        textoEstado.textContent = 'Cargando tarjetas del banco…';
        try {
          const cantidad = params.get('cantidad');
          const qs = cantidad ? `?modo=aleatorias&cantidad=${encodeURIComponent(cantidad)}` : '?modo=todas';
          const res = await fetch(`https://oposicion-age.onrender.com/documento/${documentoId}/banco-tarjetas${qs}`, { headers: authHeaders });
          const datos = await res.json();
          if (!res.ok) throw new Error(datos.error || 'No se pudo cargar el banco de tarjetas.');
          if (!datos.tarjetas || datos.tarjetas.length === 0) {
            throw new Error('Este documento todavía no tiene tarjetas generadas en su banco.');
          }
          iniciarModoEstudio(datos.tarjetas, false);
        } catch (err) {
          mostrarError(err.message);
        }
        return;
      }

      // Generar tarjetas NUEVAS desde un documento ya subido: se deja el
      // formulario visible (sin pedir de nuevo el PDF) para que el usuario
      // elija cuántas tarjetas quiere, en vez de generar siempre con el
      // valor por defecto (10) sin preguntar -- antes se disparaba la
      // generación aquí mismo, de forma automática, ignorando lo que
      // hubiera en el campo "Número de tarjetas".
      const grupoArchivo = document.getElementById('grupo-archivo');
      if (grupoArchivo) grupoArchivo.style.display = 'none';
      const archivoInput = document.getElementById('archivo-pdf');
      if (archivoInput) archivoInput.required = false;
      const aviso = document.getElementById('aviso-documento-existente');
      if (aviso) aviso.classList.remove('hidden');
      // La cabecera de la tarjeta seguía diciendo "Subir Documento PDF" con
      // el icono de subida aunque ya no hiciera falta subir nada -- (05/08/2026,
      // a petición del usuario, confuso porque parecía que había que volver
      // a subir el PDF) se cambia por un mensaje acorde a lo que se va a
      // hacer de verdad: generar, no subir.
      const cardIcono = document.getElementById('card-icono-formulario');
      if (cardIcono) cardIcono.innerHTML = icono('tarjeta', 20);
      const cardTitulo = document.getElementById('card-titulo-formulario');
      if (cardTitulo) cardTitulo.textContent = 'Generar tarjetas desde tu documento';
      const subtitulo = document.getElementById('subtitulo-formulario');
      if (subtitulo) subtitulo.textContent = 'Ya tienes este documento en tu biblioteca. Genera tarjetas de estudio a partir de él con un clic.';
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
