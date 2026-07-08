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
    const resultadoEsquema = document.getElementById('resultado-esquema');
    const contenidoEsquema = document.getElementById('contenido-esquema');
    const esquemaTitulo = document.getElementById('esquema-titulo');
    const esquemaMeta = document.getElementById('esquema-meta');
    const fechaEsquema = document.getElementById('fecha-esquema');
    const btnDescargarPdf = document.getElementById('btn-descargar-pdf');
    const btnCerrar = document.getElementById('btn-cerrar');
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
            nombre_archivo: nombreArchivoActual,
            documento_id: documentoIdActual
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
      mensajeError.innerHTML = `⚠️ <strong>Error:</strong> ${mensaje}`;
      mensajeError.classList.remove('hidden');
      contenedorCarga.classList.add('hidden');
      resultadoEsquema.classList.add('hidden');
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
    // === Parser del esquema Markdown-lite a bloques ===
    // Única fuente de verdad para el formato del esquema: tanto el render en
    // pantalla (bloquesAHtml) como la descarga en PDF (descargarPDF) recorren
    // esta misma lista de bloques, en vez de tener dos parsers de markdown
    // distintos que puedan divergir.
    function parsearEsquemaABloques(texto) {
      const lineas = (texto || "").split("\n");
      const bloques = [];
      for (const lineaOriginal of lineas) {
        const linea = lineaOriginal.trim();
        if (!linea) continue;
        // Acepta cualquier nivel de encabezado ("#", "##", "###"...): la IA
        // no siempre se ciñe a los dos niveles pedidos en el prompt, y antes
        // un "###" (u otro nivel no contemplado) no se reconocía como
        // encabezado y se colaba tal cual, almohadillas incluidas, como texto
        // plano. A partir de nivel 2 se trata igual que "##" (mismo estilo).
        const matchEncabezado = linea.match(/^(#{1,6})\s+(.*)$/);
        if (matchEncabezado) {
          bloques.push({ tipo: matchEncabezado[1].length === 1 ? "h2" : "h3", texto: matchEncabezado[2].trim() });
          continue;
        }
        if (linea.startsWith("> ")) {
          bloques.push({ tipo: "definicion", texto: linea.slice(2).trim() });
          continue;
        }
        const matchNumerado = linea.match(/^(\d+)\.\s+(.*)$/);
        if (matchNumerado) {
          bloques.push({ tipo: "numero", numero: matchNumerado[1], texto: matchNumerado[2].trim() });
          continue;
        }
        if (linea.startsWith("- ") || linea.startsWith("* ")) {
          bloques.push({ tipo: "bullet", texto: linea.slice(2).trim() });
          continue;
        }
        // Cualquier línea que no encaje en un marcador conocido se trata
        // como párrafo normal -- así nunca se pierde texto aunque la IA no
        // siga el formato al pie de la letra.
        bloques.push({ tipo: "parrafo", texto: linea });
      }
      return bloques;
    }
    // El esquema lo genera la IA a partir de un PDF subido por el usuario:
    // se escapa antes de aplicar el marcado de negrita para que un documento
    // con "<script>" o similar como texto plano no se ejecute al pintarlo.
    function escaparHtml(texto) {
      const div = document.createElement('div');
      div.textContent = texto ?? '';
      return div.innerHTML;
    }
    function negritaInlineHtml(texto) {
      return escaparHtml(texto).replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    }
    function quitarMarcadoresNegrita(texto) {
      return texto.replace(/\*\*(.*?)\*\*/g, '$1');
    }
    function bloquesAHtml(bloques) {
      const html = [];
      let listaAbierta = null;
      function cerrarLista() {
        if (listaAbierta) { html.push(`</${listaAbierta}>`); listaAbierta = null; }
      }
      bloques.forEach((b) => {
        if (b.tipo === "h2") { cerrarLista(); html.push(`<h2>${negritaInlineHtml(b.texto)}</h2>`); return; }
        if (b.tipo === "h3") { cerrarLista(); html.push(`<h3>${negritaInlineHtml(b.texto)}</h3>`); return; }
        if (b.tipo === "definicion") { cerrarLista(); html.push(`<div class="esquema-definicion">${negritaInlineHtml(b.texto)}</div>`); return; }
        if (b.tipo === "numero") {
          if (listaAbierta !== "ol") { cerrarLista(); html.push("<ol>"); listaAbierta = "ol"; }
          html.push(`<li>${negritaInlineHtml(b.texto)}</li>`);
          return;
        }
        if (b.tipo === "bullet") {
          if (listaAbierta !== "ul") { cerrarLista(); html.push("<ul>"); listaAbierta = "ul"; }
          html.push(`<li>${negritaInlineHtml(b.texto)}</li>`);
          return;
        }
        cerrarLista();
        html.push(`<p>${negritaInlineHtml(b.texto)}</p>`);
      });
      cerrarLista();
      return html.join("\n");
    }

    // === Descarga en PDF ===
    // Antes se rasterizaba todo el esquema con html2canvas y se recortaba la
    // imagen resultante cada 295mm sin mirar dónde caían las líneas de
    // texto -- de ahí que el PDF cortase frases a la mitad entre páginas.
    // Ahora se recorre la misma lista de bloques del parser con el patrón ya
    // usado en assets/resultados-test.js: se mide el alto de cada bloque
    // antes de dibujarlo y se salta de página si no cabe entero.
    function descargarPDF() {
      const { jsPDF } = window.jspdf;
      const doc = new jsPDF({ unit: "mm", format: "a4" });
      const margin = 18;
      const pageWidth = doc.internal.pageSize.getWidth();
      const pageHeight = doc.internal.pageSize.getHeight();
      const anchoTexto = pageWidth - margin * 2;
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
      doc.text(`Esquema de ${nombreArchivo}`, pageWidth / 2, yPos, { align: "center" });
      yPos += 10;
      doc.setFont("helvetica", "normal");
      doc.setFontSize(11);
      doc.setTextColor(110);
      doc.text(formatearFecha(new Date()), pageWidth / 2, yPos, { align: "center" });
      doc.setTextColor(0);
      yPos += 14;
      pintarPie();

      // Mismos colores de marca que la versión en pantalla (theme.css):
      // --age-primary #ffa633 para el acento de los "h2" y --age-primary-dark
      // #e8860f para el texto de los "h3" -- antes el PDF se generaba
      // siempre en negro, perdiendo el naranja que hace la web más visual.
      const NARANJA_PRIMARIO = [255, 166, 51];
      const NARANJA_OSCURO = [232, 134, 15];

      const bloques = parsearEsquemaABloques(esquema);
      bloques.forEach((b) => {
        let fontSize = 11;
        let fontStyle = "normal";
        let prefijo = "";
        let indent = 0;
        let extraArriba = 0;
        let color = [0, 0, 0];
        const esDefinicion = b.tipo === "definicion";
        const esH2 = b.tipo === "h2";

        if (esH2) { fontSize = 15; fontStyle = "bold"; extraArriba = 6; indent = 4; }
        else if (b.tipo === "h3") { fontSize = 12.5; fontStyle = "bold"; extraArriba = 4; color = NARANJA_OSCURO; }
        else if (b.tipo === "bullet") { prefijo = "• "; indent = 5; }
        else if (b.tipo === "numero") { prefijo = `${b.numero}. `; indent = 5; }
        else if (esDefinicion) { fontStyle = "italic"; indent = 4; }

        const texto = quitarMarcadoresNegrita(b.texto);
        doc.setFont("helvetica", fontStyle);
        doc.setFontSize(fontSize);
        const lineas = doc.splitTextToSize(prefijo + texto, anchoTexto - indent - (esDefinicion ? 4 : 0));
        const altoLinea = fontSize * 0.42;
        const alturaBloque = extraArriba + lineas.length * altoLinea + (esDefinicion ? 4 : 2);

        asegurarEspacio(alturaBloque);
        yPos += extraArriba;

        if (esDefinicion) {
          doc.setFillColor(255, 241, 222);
          doc.setDrawColor(...NARANJA_PRIMARIO);
          doc.roundedRect(margin, yPos - altoLinea * 0.75, anchoTexto, lineas.length * altoLinea + 4, 2, 2, "FD");
          yPos += 3;
        } else if (esH2) {
          // Barra de acento naranja a la izquierda, igual que el
          // "border-left: 4px solid var(--age-primary)" del h2 en pantalla.
          doc.setFillColor(...NARANJA_PRIMARIO);
          doc.rect(margin, yPos - altoLinea * 0.78, 1.3, lineas.length * altoLinea, "F");
        }

        doc.setTextColor(...color);
        lineas.forEach((linea) => {
          doc.text(linea, margin + indent + (esDefinicion ? 2 : 0), yPos);
          yPos += altoLinea;
        });
        doc.setTextColor(0);
        yPos += esDefinicion ? 4 : 2;
      });

      doc.save(`esquema_${nombreArchivo.replace('.pdf', '')}.pdf`);
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
    // "Cerrar" hace exactamente lo que antes hacía "Nuevo PDF": vuelve al
    // formulario para adjuntar otro documento -- por eso ya no hace falta un
    // botón "Nuevo documento" aparte, ni un "Finalizar" con diálogo de
    // confirmación previo.
    btnCerrar.addEventListener('click', () => {
      esquema = '';
      resultadoEsquema.classList.add('hidden');
      alertaPreguntas.classList.add('hidden');
      mensajeError.classList.add('hidden');
      formularioCard.classList.remove('hidden');
      formularioPdf.reset();
      fileNameDisplay.classList.add('hidden');
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
      formularioCard.classList.add('hidden');
      contenedorCarga.classList.remove('hidden');
      // Cargar estado
      const textoEstado = document.getElementById('texto-estado');
      const aiIcon = document.getElementById('ai-icon');
      const etapas = [
        { mensaje: "Leyendo texto del PDF…", icono: "📄" },
        { mensaje: "Analizando estructura del documento…", icono: "🔍" },
        { mensaje: "Identificando temas y subtemas…", icono: "📊" },
        { mensaje: "Organizando jerarquía conceptual…", icono: "🧠" },
        { mensaje: "Preparando esquema final…", icono: "✅" }
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
        const res = await fetch("https://oposicion-age.onrender.com/generar-esquema-desde-pdf", {
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
        if (!datos.esquema) throw new Error(datos.error || "No se pudo generar el esquema.");
        datosIA = datos;
      } catch (err) {
        errorIA = err;
      }
      clearInterval(intervaloEtapas);
      if (errorIA) {
        mostrarError(errorIA.message);
        return;
      }
      // Mostrar esquema
      documentoIdActual = datosIA.documento_id || documentoIdActual;
      mostrarEsquemaResultado(datosIA.esquema, true);
    });

    function mostrarEsquemaResultado(textoEsquema, guardar) {
      esquema = textoEsquema || "No se pudo generar el esquema.";
      const fecha = new Date();
      fechaEsquema.textContent = formatearFecha(fecha);
      esquemaTitulo.textContent = `Esquema de ${nombreArchivo}`;
      // Procesar y mostrar con formato (mismo parser que usa la descarga en PDF)
      contenidoEsquema.innerHTML = bloquesAHtml(parsearEsquemaABloques(esquema));
      contenedorCarga.classList.add('hidden');
      resultadoEsquema.classList.remove('hidden');
      // ✅ Guardar en Firebase (solo si es contenido recién generado)
      if (guardar) guardarEsquemaAutomaticamente();
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

      if (ver === 'esquema') {
        textoEstado.textContent = 'Cargando tu esquema guardado…';
        try {
          const res = await fetch(`https://oposicion-age.onrender.com/documento/${documentoId}/esquema`, { headers: authHeaders });
          const datos = await res.json();
          if (!res.ok) throw new Error(datos.error || 'No se pudo cargar el esquema.');
          nombreArchivo = datos.nombre_archivo || nombreArchivo;
          mostrarEsquemaResultado(datos.esquema, false);
        } catch (err) {
          mostrarError(err.message);
        }
        return;
      }

      textoEstado.textContent = 'Generando esquema desde tu documento…';
      aiIcon.textContent = '🧠';
      try {
        const formData = new FormData();
        formData.append('documento_id', documentoId);
        const res = await fetch("https://oposicion-age.onrender.com/generar-esquema-desde-pdf", {
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
        if (!datos.esquema) throw new Error(datos.error || "No se pudo generar el esquema.");
        nombreArchivo = datos.nombre_archivo || nombreArchivo;
        mostrarEsquemaResultado(datos.esquema, true);
      } catch (err) {
        mostrarError(err.message);
      }
    })();
