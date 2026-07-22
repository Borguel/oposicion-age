import { icono } from "/assets/icons.js";

import("/assets/plan.js").then(({ protegerPagina }) => protegerPagina("premium"));

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
          const { mostrarErrorGlobal } = await import("/assets/notificaciones.js");
          mostrarErrorGlobal("No se pudo guardar el resumen en tu cuenta. El texto sigue visible en pantalla, pero no ha quedado guardado.");
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
        const { mostrarErrorGlobal } = await import("/assets/notificaciones.js");
        mostrarErrorGlobal("No se pudo guardar el resumen en tu cuenta. El texto sigue visible en pantalla, pero no ha quedado guardado.");
      }
    }
    // === Funciones auxiliares ===
    function mostrarError(mensaje) {
      mensajeError.innerHTML = `${icono("alerta", 18)} <strong>Error:</strong> ${mensaje}`;
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
    // === Parser del resumen Markdown-lite a bloques ===
    // Única fuente de verdad para el formato del resumen: tanto el render en
    // pantalla (bloquesAHtml) como la descarga en PDF (descargarPDF) recorren
    // esta misma lista de bloques, en vez de tener dos parsers de markdown
    // distintos que puedan divergir (y, sobre todo, en vez de rasterizar el
    // HTML con html2canvas: eso recortaba la imagen cada 295mm sin mirar
    // dónde caían las líneas de texto, así que el PDF cortaba frases a la
    // mitad entre páginas).
    function parsearResumenABloques(texto) {
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
        if (b.tipo === "definicion") { cerrarLista(); html.push(`<div class="resumen-definicion">${negritaInlineHtml(b.texto)}</div>`); return; }
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
      doc.text(`Resumen de ${nombreArchivo}`, pageWidth / 2, yPos, { align: "center" });
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

      // Mide un bloque (tipo de letra, líneas ya envueltas al ancho de
      // página, alto total) SIN dibujar nada -- se usa en una primera pasada
      // para poder mirar "hacia adelante" al bloque siguiente antes de
      // decidir si hay que saltar de página.
      function medirBloque(b) {
        let fontSize = 11, fontStyle = "normal", prefijo = "", indent = 0, extraArriba = 0, color = [0, 0, 0];
        const esDefinicion = b.tipo === "definicion";
        const esH2 = b.tipo === "h2";
        const esEncabezado = esH2 || b.tipo === "h3";

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
        return { esDefinicion, esH2, esEncabezado, fontSize, fontStyle, indent, extraArriba, color, lineas, altoLinea, alturaBloque };
      }

      const medidos = parsearResumenABloques(resumen).map(medirBloque);
      medidos.forEach((m, i) => {
        // Evita que un encabezado se quede "huérfano" solo al final de una
        // página con su contenido empujado a la siguiente (lo que se veía
        // como un corte a medias): si es un encabezado, se exige que quepa
        // TAMBIÉN el bloque siguiente antes de dibujarlo -- si no cabe
        // ninguno de los dos, ambos pasan juntos a la página nueva.
        let alturaNecesaria = m.alturaBloque;
        if (m.esEncabezado && i + 1 < medidos.length) alturaNecesaria += medidos[i + 1].alturaBloque;
        asegurarEspacio(alturaNecesaria);
        yPos += m.extraArriba;

        // Reaplicar tipo de letra: la medición de bloques posteriores ya
        // dejó el estado de "doc" cambiado.
        doc.setFont("helvetica", m.fontStyle);
        doc.setFontSize(m.fontSize);

        if (m.esDefinicion) {
          doc.setFillColor(255, 241, 222);
          doc.setDrawColor(...NARANJA_PRIMARIO);
          doc.roundedRect(margin, yPos - m.altoLinea * 0.75, anchoTexto, m.lineas.length * m.altoLinea + 4, 2, 2, "FD");
          yPos += 3;
        } else if (m.esH2) {
          // Barra de acento naranja a la izquierda, igual que el
          // "border-left: 4px solid var(--age-primary)" del h2 en pantalla.
          doc.setFillColor(...NARANJA_PRIMARIO);
          doc.rect(margin, yPos - m.altoLinea * 0.78, 1.3, m.lineas.length * m.altoLinea, "F");
        }

        doc.setTextColor(...m.color);
        m.lineas.forEach((linea) => {
          doc.text(linea, margin + m.indent + (m.esDefinicion ? 2 : 0), yPos);
          yPos += m.altoLinea;
        });
        doc.setTextColor(0);
        yPos += m.esDefinicion ? 4 : 2;
      });

      doc.save(`resumen_${nombreArchivo.replace('.pdf', '')}.pdf`);
    }
    // Consume el stream SSE de /resumir-documento (progreso real por
    // fragmento del map-reduce, ver deepseek_utils.generar_documento_largo_por_partes)
    // y devuelve el evento "fin" -- usado tanto al subir un PDF nuevo como al
    // generar desde un documento ya guardado en "Mis documentos". Antes de
    // que llegue el primer evento real sube el % de forma cosmética (igual
    // que en test-personalizado) para que no parezca que la página se ha
    // colgado mientras el backend extrae y trocea el texto.
    async function generarResumenConProgreso(url, formData, authHeaders) {
      const textoEstado = document.getElementById('texto-estado');
      const aiIcon = document.getElementById('ai-icon');
      const elBarra = document.getElementById('progreso-generacion-pdf');
      const elTextoBarra = document.getElementById('texto-progreso-generacion-pdf');

      let progresoCosmetico = 0;
      let intervaloCosmetico = setInterval(() => {
        progresoCosmetico = Math.min(progresoCosmetico + Math.random() * 3, 15);
        if (elBarra) elBarra.style.width = `${progresoCosmetico}%`;
        if (elTextoBarra) elTextoBarra.textContent = `${Math.round(progresoCosmetico)}%`;
      }, 400);
      const pararProgresoCosmetico = () => {
        if (intervaloCosmetico) {
          clearInterval(intervaloCosmetico);
          intervaloCosmetico = null;
        }
      };

      try {
        const res = await fetch(url, { method: "POST", headers: authHeaders, body: formData });
        if (res.status === 403) {
          throw new Error('Necesitas iniciar sesión o mejorar de plan para usar esta herramienta. <a href="/planes/">Ver planes</a>');
        }
        if (res.status === 429) {
          const errorData = await res.json().catch(() => ({}));
          throw new Error(`${errorData.error || "Has alcanzado el límite de uso de esta herramienta por ahora."} <a href="/planes/">Ver planes</a>`);
        }
        if (!res.ok || !res.body) {
          const errorData = await res.json().catch(() => ({}));
          throw new Error(errorData.error || `Error del servidor: ${res.status}`);
        }

        const lector = res.body.getReader();
        const decodificador = new TextDecoder();
        let buffer = "";
        let datosFinales = null;

        while (true) {
          const { done, value } = await lector.read();
          if (done) break;
          buffer += decodificador.decode(value, { stream: true });
          const bloques = buffer.split("\n\n");
          buffer = bloques.pop(); // el último trozo puede venir incompleto
          for (const bloque of bloques) {
            const linea = bloque.trim();
            if (!linea.startsWith("data: ")) continue;
            let evento;
            try {
              evento = JSON.parse(linea.slice(6));
            } catch {
              continue;
            }
            pararProgresoCosmetico();
            if (evento.tipo === "progreso") {
              const porcentaje = evento.total ? Math.round((evento.completadas / evento.total) * 100) : 0;
              if (elBarra) elBarra.style.width = `${porcentaje}%`;
              if (elTextoBarra) elTextoBarra.textContent = `${porcentaje}%`;
              if (textoEstado) {
                textoEstado.textContent = evento.fase === "fusionando"
                  ? "Uniendo las partes en un resumen final…"
                  : `Analizando el documento (parte ${evento.completadas} de ${evento.total})…`;
              }
              if (aiIcon) aiIcon.innerHTML = icono("cerebro", 32);
            } else if (evento.tipo === "fin") {
              datosFinales = evento;
            }
          }
        }

        if (!datosFinales) {
          throw new Error("Error al generar el resumen. Vuelve a intentarlo.");
        }
        if (!datosFinales.resumen) {
          throw new Error(datosFinales.error || "No se pudo generar el resumen.");
        }
        return datosFinales;
      } finally {
        pararProgresoCosmetico();
      }
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
      document.getElementById('texto-estado').textContent = "Leyendo texto del PDF…";
      document.getElementById('ai-icon').innerHTML = icono("documento", 32);

      const authHeaders = await obtenerAuthHeaders();
      if (!authHeaders) return;

      try {
        const datosIA = await generarResumenConProgreso("https://oposicion-age.onrender.com/resumir-documento", formData, authHeaders);
        documentoIdActual = datosIA.documento_id || documentoIdActual;
        mostrarResumenResultado(datosIA.resumen, true);
      } catch (err) {
        mostrarError(err.message || "Error al generar el resumen.");
      }
    });

    // El resumen lo genera la IA a partir de un PDF subido por el usuario:
    // se escapa antes de aplicar el formato Markdown para que un documento
    // con "<script>" o similar como texto plano no se ejecute al pintarlo.
    function escaparHtml(texto) {
      const div = document.createElement('div');
      div.textContent = texto ?? '';
      return div.innerHTML;
    }

    // Con un documento largo, el resumen completo en pantalla se hace
    // kilométrico. Se muestra solo un primer tramo y, si hay más, un botón
    // "Ver resumen completo" para desplegar el resto sin perder nada --
    // quien prefiera no desplazarse por una pantalla larguísima puede
    // simplemente descargar el PDF (los botones ya están justo debajo) y
    // estudiarlo desde ahí. Umbral en bloques (encabezados/párrafos/viñetas
    // ya parseados), no en caracteres, para no cortar nunca a mitad de uno.
    const BLOQUES_PREVIEW_RESUMEN = 14;

    function mostrarResumenResultado(textoResumen, guardar) {
      resumen = textoResumen || "No se pudo generar el resumen.";
      const fecha = new Date();
      fechaResumen.textContent = formatearFecha(fecha);
      resumenTitulo.textContent = `Resumen de ${nombreArchivo}`;
      // Por si se muestra un resumen tras otro sin recargar la página (p.
      // ej. al cerrar y generar uno nuevo), se quita cualquier botón "ver
      // más" que quedara de la vez anterior antes de crear el nuevo.
      const verMasAnterior = document.getElementById('resumen-ver-mas-bloque');
      if (verMasAnterior) verMasAnterior.remove();

      const bloques = parsearResumenABloques(resumen);
      if (bloques.length > BLOQUES_PREVIEW_RESUMEN + 4) {
        contenidoResumen.innerHTML = bloquesAHtml(bloques.slice(0, BLOQUES_PREVIEW_RESUMEN));
        contenidoResumen.insertAdjacentHTML(
          'beforeend',
          `<div id="resumen-resto" class="hidden">${bloquesAHtml(bloques.slice(BLOQUES_PREVIEW_RESUMEN))}</div>`
        );
        contenidoResumen.insertAdjacentHTML('afterend', `
          <div class="resumen-ver-mas-bloque" id="resumen-ver-mas-bloque">
            <button type="button" class="btn btn-outline" id="btn-ver-mas-resumen">Ver resumen completo ↓</button>
            <p class="resumen-ver-mas-nota">O descárgalo en PDF para estudiarlo con más comodidad.</p>
          </div>
        `);
        document.getElementById('btn-ver-mas-resumen').addEventListener('click', () => {
          document.getElementById('resumen-resto').classList.remove('hidden');
          document.getElementById('resumen-ver-mas-bloque').remove();
        });
      } else {
        contenidoResumen.innerHTML = bloquesAHtml(bloques);
      }

      contenedorCarga.classList.add('hidden');
      resultadoResumen.classList.remove('hidden');
      // ✅ Guardar en Firebase (solo si es contenido recién generado, no al
      // solo visualizar un resumen que ya estaba guardado)
      if (guardar) guardarResumenAutomaticamente();

      import('/assets/otras-herramientas-pdf.js').then(({ pintarAccesosOtrasHerramientas }) => {
        pintarAccesosOtrasHerramientas({
          contenedor: document.getElementById('otras-herramientas-bloque'),
          documentoId: documentoIdActual,
          herramientaActual: 'subida-pdf-resumen',
        });
      });
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
      aiIcon.innerHTML = icono('cerebro', 32);
      try {
        const formData = new FormData();
        formData.append('documento_id', documentoId);
        const datos = await generarResumenConProgreso("https://oposicion-age.onrender.com/resumir-documento", formData, authHeaders);
        nombreArchivo = datos.nombre_archivo || nombreArchivo;
        mostrarResumenResultado(datos.resumen, true);
      } catch (err) {
        mostrarError(err.message);
      }
    })();
