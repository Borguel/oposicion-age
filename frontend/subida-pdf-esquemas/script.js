import { icono } from "/assets/icons.js";
import { leerStreamConTimeout } from "/assets/stream-utils.js";
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
          const { mostrarErrorGlobal } = await import("/assets/notificaciones.js");
          mostrarErrorGlobal("No se pudo guardar el esquema en tu cuenta. El contenido sigue visible en pantalla, pero no ha quedado guardado.");
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
        const { mostrarErrorGlobal } = await import("/assets/notificaciones.js");
        mostrarErrorGlobal("No se pudo guardar el esquema en tu cuenta. El contenido sigue visible en pantalla, pero no ha quedado guardado.");
      }
    }
    // === Funciones auxiliares ===
    function mostrarError(mensaje) {
      mensajeError.innerHTML = `${icono("alerta", 18)} <strong>Error:</strong> ${mensaje}`;
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
        if (!lineaOriginal.trim()) continue;
        // A diferencia del resumen, aquí SÍ importa la sangría original:
        // es lo único que permite reconstruir un árbol de viñetas anidadas
        // en vez de una lista plana. Se cuenta antes de recortarla.
        const sinSaltoFinal = lineaOriginal.replace(/\s+$/, "");
        const espaciosIniciales = (sinSaltoFinal.match(/^ */) || [""])[0].length;
        const nivel = Math.min(4, Math.floor(espaciosIniciales / 2));
        const linea = sinSaltoFinal.trim();
        // Acepta cualquier nivel de encabezado ("#" a "######"): la IA no
        // siempre se ciñe exactamente a los niveles pedidos en el prompt.
        // "#" -> h2 (sección principal), "##" -> h3 (subsección), 3 o más
        // almohadillas -> h4 (el nivel más profundo del árbol, p. ej. un
        // artículo concreto dentro de un capítulo).
        const matchEncabezado = linea.match(/^(#{1,6})\s+(.*)$/);
        if (matchEncabezado) {
          const profundidad = matchEncabezado[1].length;
          const tipo = profundidad === 1 ? "h2" : profundidad === 2 ? "h3" : "h4";
          bloques.push({ tipo, texto: matchEncabezado[2].trim() });
          continue;
        }
        if (linea.startsWith("> ")) {
          bloques.push({ tipo: "definicion", texto: linea.slice(2).trim() });
          continue;
        }
        const matchNumerado = linea.match(/^(\d+)\.\s+(.*)$/);
        if (matchNumerado) {
          bloques.push({ tipo: "numero", numero: matchNumerado[1], texto: matchNumerado[2].trim(), nivel });
          continue;
        }
        if (linea.startsWith("- ") || linea.startsWith("* ")) {
          bloques.push({ tipo: "bullet", texto: linea.slice(2).trim(), nivel });
          continue;
        }
        // Cualquier línea que no encaje en un marcador conocido se trata
        // como párrafo normal -- así nunca se pierde texto aunque la IA no
        // siga el formato al pie de la letra.
        bloques.push({ tipo: "parrafo", texto: linea });
      }
      return bloques;
    }
    // Reconstruye el árbol de viñetas a partir de una racha plana de bloques
    // "bullet"/"numero" consecutivos con su nivel de sangría, usando una pila
    // (algoritmo estándar para convertir una lista plana con profundidad en
    // un árbol): cada nuevo ítem cuelga del último ítem de nivel inferior
    // todavía abierto en la pila.
    function construirArbolLista(items) {
      const raiz = { hijos: [] };
      const pila = [{ nodo: raiz, nivel: -1 }];
      items.forEach((item) => {
        const nodo = { ...item, hijos: [] };
        while (pila.length > 1 && pila[pila.length - 1].nivel >= item.nivel) {
          pila.pop();
        }
        pila[pila.length - 1].nodo.hijos.push(nodo);
        pila.push({ nodo, nivel: item.nivel });
      });
      return raiz.hijos;
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
    // Renderiza un árbol de viñetas (ver construirArbolLista) a HTML anidado
    // de verdad: cada <ul>/<ol> hijo va DENTRO del <li> de su padre, no como
    // hermano suelto -- así el CSS puede dibujar líneas de conexión y
    // viñetas distintas por profundidad real, no solo por color.
    function renderizarListaHtml(nodos) {
      const partes = [];
      let i = 0;
      while (i < nodos.length) {
        const tipoActual = nodos[i].tipo;
        const grupo = [];
        while (i < nodos.length && nodos[i].tipo === tipoActual) {
          grupo.push(nodos[i]);
          i++;
        }
        const etiqueta = tipoActual === "numero" ? "ol" : "ul";
        const items = grupo.map((n) => {
          const hijosHtml = n.hijos.length ? renderizarListaHtml(n.hijos) : "";
          return `<li>${negritaInlineHtml(n.texto)}${hijosHtml}</li>`;
        }).join("");
        partes.push(`<${etiqueta}>${items}</${etiqueta}>`);
      }
      return partes.join("");
    }
    function bloquesAHtml(bloques) {
      const html = [];
      let i = 0;
      while (i < bloques.length) {
        const b = bloques[i];
        if (b.tipo === "bullet" || b.tipo === "numero") {
          const grupo = [];
          while (i < bloques.length && (bloques[i].tipo === "bullet" || bloques[i].tipo === "numero")) {
            grupo.push(bloques[i]);
            i++;
          }
          html.push(renderizarListaHtml(construirArbolLista(grupo)));
          continue;
        }
        if (b.tipo === "h2") { html.push(`<h2>${negritaInlineHtml(b.texto)}</h2>`); i++; continue; }
        if (b.tipo === "h3") { html.push(`<h3>${negritaInlineHtml(b.texto)}</h3>`); i++; continue; }
        if (b.tipo === "h4") { html.push(`<h4>${negritaInlineHtml(b.texto)}</h4>`); i++; continue; }
        if (b.tipo === "definicion") { html.push(`<div class="esquema-definicion">${negritaInlineHtml(b.texto)}</div>`); i++; continue; }
        html.push(`<p>${negritaInlineHtml(b.texto)}</p>`);
        i++;
      }
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
      // Gris de las líneas de estructura (mismo tono que --age-border en
      // pantalla, algo más marcado para que se distinga bien impreso).
      const GRIS_LINEA = [200, 203, 210];

      // Numeración jerárquica tipo "esquema clásico" (I. / I.1 / I.1.a), igual
      // que la que se ve en pantalla vía contadores CSS -- así el PDF y la
      // pantalla transmiten la misma sensación de árbol, no de lista plana.
      function aRomano(numero) {
        const valores = [[1000, "M"], [900, "CM"], [500, "D"], [400, "CD"], [100, "C"], [90, "XC"], [50, "L"], [40, "XL"], [10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"]];
        let resto = numero, resultado = "";
        for (const [valor, letra] of valores) {
          while (resto >= valor) { resultado += letra; resto -= valor; }
        }
        return resultado;
      }
      function aLetra(numero) {
        return String.fromCharCode(96 + numero); // 1 -> 'a', 2 -> 'b'...
      }
      let contadorH2 = 0, contadorH3 = 0, contadorH4 = 0;

      // Glifo de viñeta distinto por nivel de anidación, igual que el
      // list-style-type por profundidad en pantalla -- así una sub-viñeta se
      // distingue a simple vista de una viñeta de primer nivel. Limitado a
      // caracteres de WinAnsiEncoding (la fuente helvetica estándar de
      // jsPDF no sabe dibujar fuera de ese juego, p. ej. "‣" salía
      // completamente descuadrado, con las letras separadas).
      const GLIFOS_VIÑETA = ["•", "–", "»", "·", "•"];

      // Mide un bloque (tipo de letra, líneas ya envueltas al ancho de
      // página, alto total) SIN dibujar nada -- se usa en una primera pasada
      // para poder mirar "hacia adelante" al bloque siguiente antes de
      // decidir si hay que saltar de página.
      function medirBloque(b) {
        let fontSize = 11, fontStyle = "normal", prefijo = "", indent = 0, extraArriba = 0, color = [0, 0, 0];
        const esDefinicion = b.tipo === "definicion";
        const esH2 = b.tipo === "h2";
        const esEncabezado = esH2 || b.tipo === "h3" || b.tipo === "h4";
        const nivel = b.nivel || 0;

        if (esH2) {
          contadorH2++; contadorH3 = 0; contadorH4 = 0;
          fontSize = 15; fontStyle = "bold"; extraArriba = 6; indent = 4;
          prefijo = `${aRomano(contadorH2)}. `;
        } else if (b.tipo === "h3") {
          contadorH3++; contadorH4 = 0;
          fontSize = 12.5; fontStyle = "bold"; extraArriba = 4; indent = 4; color = NARANJA_OSCURO;
          prefijo = `${aRomano(contadorH2)}.${contadorH3} `;
        } else if (b.tipo === "h4") {
          contadorH4++;
          fontSize = 11; fontStyle = "bold"; extraArriba = 3; indent = 8; color = [90, 90, 90];
          prefijo = `${contadorH3}.${aLetra(contadorH4)} `;
        } else if (b.tipo === "bullet") {
          prefijo = `${GLIFOS_VIÑETA[Math.min(nivel, GLIFOS_VIÑETA.length - 1)]} `;
          indent = 5 + nivel * 5;
        } else if (b.tipo === "numero") {
          prefijo = `${b.numero}. `;
          indent = 5 + nivel * 5;
        } else if (esDefinicion) { fontStyle = "italic"; indent = 4; }

        const texto = quitarMarcadoresNegrita(b.texto);
        doc.setFont("helvetica", fontStyle);
        doc.setFontSize(fontSize);
        const lineas = doc.splitTextToSize(prefijo + texto, anchoTexto - indent - (esDefinicion ? 4 : 0));
        const altoLinea = fontSize * 0.42;
        const alturaBloque = extraArriba + lineas.length * altoLinea + (esDefinicion ? 4 : 2);
        return { tipo: b.tipo, nivel, esDefinicion, esH2, esEncabezado, fontSize, fontStyle, indent, extraArriba, color, lineas, altoLinea, alturaBloque };
      }

      // Dibuja una línea vertical de estructura (el equivalente en PDF del
      // "border-left" de h2/h3/h4 y de las listas anidadas en pantalla):
      // sin esto, el PDF perdía por completo las guías que dejan ver de un
      // vistazo qué cuelga de qué.
      function dibujarLineaEstructura(m, x, color, punteada) {
        doc.setDrawColor(...color);
        doc.setLineWidth(punteada ? 0.25 : 0.35);
        if (punteada) doc.setLineDashPattern([0.8, 0.8], 0);
        const yInicio = yPos - m.altoLinea * 0.78;
        doc.line(x, yInicio, x, yInicio + m.lineas.length * m.altoLinea);
        if (punteada) doc.setLineDashPattern([], 0);
        doc.setDrawColor(0);
        doc.setLineWidth(0.2);
      }

      const medidos = parsearEsquemaABloques(esquema).map(medirBloque);
      medidos.forEach((m, i) => {
        // Evita que un bloque se quede "huérfano" solo al final de una
        // página con lo que cuelga de él empujado a la siguiente (lo que se
        // veía como un corte a medias): si es un encabezado, o una viñeta
        // que va a tener sub-viñetas justo debajo, se exige que quepa
        // TAMBIÉN el bloque siguiente antes de dibujarlo -- si no cabe
        // ninguno de los dos, ambos pasan juntos a la página nueva.
        const siguiente = medidos[i + 1];
        const esPadreDeSubViñeta = (m.tipo === "bullet" || m.tipo === "numero") && siguiente &&
          (siguiente.tipo === "bullet" || siguiente.tipo === "numero") && siguiente.nivel > m.nivel;
        let alturaNecesaria = m.alturaBloque;
        if ((m.esEncabezado || esPadreDeSubViñeta) && siguiente) alturaNecesaria += siguiente.alturaBloque;
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
        } else if (m.tipo === "h3") {
          dibujarLineaEstructura(m, margin + 1.5, NARANJA_PRIMARIO, false);
        } else if (m.tipo === "h4") {
          dibujarLineaEstructura(m, margin + 3, GRIS_LINEA, true);
        } else if (m.tipo === "bullet" || m.tipo === "numero") {
          // Misma línea gris que el "border-left" del <ul>/<ol> en pantalla:
          // sólida en el primer nivel, punteada a partir del segundo, para
          // que las sub-viñetas se distingan de un vistazo del tronco
          // principal de la lista.
          dibujarLineaEstructura(m, margin + 2 + m.nivel * 5, GRIS_LINEA, m.nivel > 0);
        }

        doc.setTextColor(...m.color);
        m.lineas.forEach((linea) => {
          doc.text(linea, margin + m.indent + (m.esDefinicion ? 2 : 0), yPos);
          yPos += m.altoLinea;
        });
        doc.setTextColor(0);
        yPos += m.esDefinicion ? 4 : 2;
      });

      doc.save(`esquema_${nombreArchivo.replace('.pdf', '')}.pdf`);
    }
    // Consume el stream SSE de /generar-esquema-desde-pdf (progreso real por
    // fragmento del map-reduce, ver deepseek_utils.generar_documento_largo_por_partes)
    // y devuelve el evento "fin" -- usado tanto al subir un PDF nuevo como al
    // generar desde un documento ya guardado en "Mis documentos". Con un
    // documento corto (un único fragmento) solo llega UN evento de progreso
    // real, justo al final -- ver /assets/progreso-conversador.js para cómo
    // se evita que la barra se quede "pillada" ese rato.
    async function generarEsquemaConProgreso(url, formData, authHeaders) {
      const { crearProgresoConversador } = await import("/assets/progreso-conversador.js");
      const progreso = crearProgresoConversador({
        elBarra: document.getElementById('progreso-generacion-pdf'),
        elTextoBarra: document.getElementById('texto-progreso-generacion-pdf'),
        elTexto: document.getElementById('texto-estado'),
        elIcono: document.getElementById('ai-icon'),
        etapasLeyendo: [
          { mensaje: "Leyendo el texto del PDF…", icono: "documento" },
          { mensaje: "Detectando la estructura del documento…", icono: "buscar" },
        ],
        etapasGenerando: [
          { mensaje: "Identificando temas y subtemas…", icono: "buscar" },
          { mensaje: "Organizando la jerarquía de conceptos…", icono: "cerebro" },
          { mensaje: "Construyendo el árbol del esquema…", icono: "cerebro" },
          { mensaje: "Revisando que no se repita ningún epígrafe…", icono: "check" },
        ],
        etapasFusionando: [
          { mensaje: "Uniendo las partes en un esquema final…", icono: "cerebro" },
          { mensaje: "Comprobando que la jerarquía quede equilibrada…", icono: "check" },
        ],
      });

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

        // "fin" es SIEMPRE el último evento del stream (el backend termina
        // justo después de emitirlo): en cuanto llega (queda en datosFinales)
        // se sale sin esperar al cierre de la conexión (done) -- en
        // iPhone/WebKit esa señal a veces no llega nunca aunque todo esté ya
        // recibido, y quedarse esperándola dejaba la pantalla congelada.
        while (!datosFinales) {
          const { done, value } = await leerStreamConTimeout(lector);
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
            if (evento.tipo === "progreso") {
              const mensajeExacto = evento.fase === "fusionando"
                ? null
                : `Analizando el documento (parte ${evento.completadas} de ${evento.total})…`;
              progreso.avanzar(evento, mensajeExacto);
            } else if (evento.tipo === "fin") {
              datosFinales = evento;
            }
          }
        }

        lector.cancel().catch(() => {});

        if (!datosFinales) {
          throw new Error("Error al generar el esquema. Vuelve a intentarlo.");
        }
        if (!datosFinales.esquema) {
          throw new Error(datosFinales.error || "No se pudo generar el esquema.");
        }
        progreso.completar();
        return datosFinales;
      } finally {
        progreso.detener();
      }
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
      document.getElementById('texto-estado').textContent = "Leyendo texto del PDF…";
      document.getElementById('ai-icon').innerHTML = icono("documento", 32);

      const authHeaders = await obtenerAuthHeaders();
      if (!authHeaders) return;

      try {
        const datosIA = await generarEsquemaConProgreso("https://oposicion-age.onrender.com/generar-esquema-desde-pdf", formData, authHeaders);
        documentoIdActual = datosIA.documento_id || documentoIdActual;
        mostrarEsquemaResultado(datosIA.esquema, true);
      } catch (err) {
        mostrarError(err.message || "Error al generar el esquema.");
      }
    });

    // Con un documento largo, el esquema completo en pantalla se hace
    // kilométrico. Se muestra solo un primer tramo y, si hay más, un botón
    // "Ver esquema completo" para desplegar el resto sin perder nada --
    // quien prefiera no desplazarse por una pantalla larguísima puede
    // simplemente descargar el PDF (los botones ya están justo debajo) y
    // estudiarlo desde ahí. Igual que en el resumen, pero aquí el corte
    // debe caer en un punto "seguro": justo antes de un encabezado o de una
    // viñeta de primer nivel, nunca en mitad de un grupo de sub-viñetas --
    // cortar ahí partiría en dos un mismo árbol de viñetas anidadas.
    const BLOQUES_PREVIEW_ESQUEMA = 18;
    function calcularCorteSeguro(bloques, objetivo) {
      for (let i = objetivo; i < bloques.length; i++) {
        const b = bloques[i];
        if (b.tipo === "h2" || b.tipo === "h3" || b.tipo === "h4") return i;
        if ((b.tipo === "bullet" || b.tipo === "numero") && (b.nivel || 0) === 0) return i;
      }
      return bloques.length;
    }

    function mostrarEsquemaResultado(textoEsquema, guardar) {
      esquema = textoEsquema || "No se pudo generar el esquema.";
      const fecha = new Date();
      fechaEsquema.textContent = formatearFecha(fecha);
      esquemaTitulo.textContent = `Esquema de ${nombreArchivo}`;
      // Por si se muestra un esquema tras otro sin recargar la página, se
      // quita cualquier botón "ver más" que quedara de la vez anterior.
      const verMasAnterior = document.getElementById('esquema-ver-mas-bloque');
      if (verMasAnterior) verMasAnterior.remove();

      // Procesar y mostrar con formato (mismo parser que usa la descarga en PDF)
      const bloques = parsearEsquemaABloques(esquema);
      const corte = bloques.length > BLOQUES_PREVIEW_ESQUEMA + 4
        ? calcularCorteSeguro(bloques, BLOQUES_PREVIEW_ESQUEMA)
        : bloques.length;
      if (corte < bloques.length) {
        contenidoEsquema.innerHTML = bloquesAHtml(bloques.slice(0, corte));
        contenidoEsquema.insertAdjacentHTML(
          'beforeend',
          `<div id="esquema-resto" class="hidden">${bloquesAHtml(bloques.slice(corte))}</div>`
        );
        contenidoEsquema.insertAdjacentHTML('afterend', `
          <div class="esquema-ver-mas-bloque" id="esquema-ver-mas-bloque">
            <button type="button" class="btn btn-outline" id="btn-ver-mas-esquema">Ver esquema completo ↓</button>
            <p class="esquema-ver-mas-nota">O descárgalo en PDF para estudiarlo con más comodidad.</p>
          </div>
        `);
        document.getElementById('btn-ver-mas-esquema').addEventListener('click', () => {
          document.getElementById('esquema-resto').classList.remove('hidden');
          document.getElementById('esquema-ver-mas-bloque').remove();
        });
      } else {
        contenidoEsquema.innerHTML = bloquesAHtml(bloques);
      }
      contenedorCarga.classList.add('hidden');
      resultadoEsquema.classList.remove('hidden');
      // ✅ Guardar en Firebase (solo si es contenido recién generado)
      if (guardar) guardarEsquemaAutomaticamente();

      import('/assets/otras-herramientas-pdf.js').then(({ pintarAccesosOtrasHerramientas }) => {
        pintarAccesosOtrasHerramientas({
          contenedor: document.getElementById('otras-herramientas-bloque'),
          documentoId: documentoIdActual,
          herramientaActual: 'subida-pdf-esquemas',
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
      aiIcon.innerHTML = icono('cerebro', 32);
      try {
        const formData = new FormData();
        formData.append('documento_id', documentoId);
        const datos = await generarEsquemaConProgreso("https://oposicion-age.onrender.com/generar-esquema-desde-pdf", formData, authHeaders);
        nombreArchivo = datos.nombre_archivo || nombreArchivo;
        mostrarEsquemaResultado(datos.esquema, true);
      } catch (err) {
        mostrarError(err.message);
      }
    })();
