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
    // El guardado en Firestore ya no depende de esta pestaña (05/08/2026):
    // ahora ocurre desde el propio hilo de fondo del backend nada más
    // terminar de generar (ver el comentario largo en blueprints/pdf_ia.py)
    // -- esta página solo GENERA (redirige a Mis documentos antes de que
    // termine, ver mostrarRedireccionAMisDocumentos) o MUESTRA un esquema
    // ya guardado (ver=esquema), nunca ambas cosas a la vez, así que ya no
    // hace falta un guardado explícito desde aquí.
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
          const textoEncabezado = matchEncabezado[2].trim();
          // yaEtiquetado (05/08/2026, bug real reportado por un usuario):
          // h3/h4 llevan un prefijo numérico auto-generado ("I.1", "3.a"...
          // ver el ::before de style.css y el "prefijo" de descargarPDF) --
          // pero si el documento original YA numeraba sus propias
          // subsecciones con letras/números (p. ej. "A. Defensa de la
          // competencia...", tal cual las preserva el modelo), el prefijo
          // auto-generado se pega delante SIN que el modelo lo sepa,
          // produciendo dobles numeraciones sin sentido ("3.a A. Defensa
          // de la competencia..."). Si el propio texto ya empieza con su
          // propia etiqueta, se marca para que el renderer (pantalla y PDF)
          // NO añada la suya encima -- se confía en la del documento.
          const yaEtiquetado = /^(?:[A-ZÁÉÍÓÚÑ]|\d+|[IVXLCDM]+)[.)]\s+/.test(textoEncabezado);
          bloques.push({ tipo, texto: textoEncabezado, yaEtiquetado });
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
        // Admite CUALQUIER número de marcadores "- "/"* " repetidos al
        // principio de la línea (defensivo, 05/08/2026, bug real: el
        // modelo a veces duplica el guión de la propia viñeta, "- -
        // Se aplica desde...", dejando un "-" suelto como texto si solo se
        // quita uno).
        const matchBullet = linea.match(/^(?:[-*]\s+)+(.*)$/);
        if (matchBullet) {
          bloques.push({ tipo: "bullet", texto: matchBullet[1].trim(), nivel });
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
    // Negrita "**texto**" -> <strong>, cursiva "*texto*" -> <em> (05/08/2026,
    // bug real: el modelo usa a veces cursiva -- p. ej. "*ex ante*", un
    // latinismo jurídico habitual -- aunque el prompt no la pida
    // explícitamente; antes se colaban los asteriscos literales sin
    // convertir). El orden importa: se resuelve primero "**" para que no
    // quede ningún "*" suelto que la segunda pasada pudiera interpretar
    // mal, y al final se limpia cualquier asterisco que no haya llegado a
    // formar un par completo (fallo puntual de formato del modelo) en vez
    // de dejarlo como texto literal.
    function negritaInlineHtml(texto) {
      return escaparHtml(texto)
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/\*/g, '');
    }
    function quitarMarcadoresNegrita(texto) {
      return texto.replace(/\*\*(.*?)\*\*/g, '$1').replace(/\*(.*?)\*/g, '$1').replace(/\*/g, '');
    }
    // Detecta una viñeta con forma "Término: explicación" para resaltar el
    // término en negrita automáticamente (05/08/2026, a petición del
    // usuario: "alguna parte importante más resaltada") -- muy habitual en
    // los esquemas generados (p. ej. "Reglamento (CE) n.º 139/2004: marco
    // de la Unión para el examen de las concentraciones..."), y el modelo
    // no siempre lo marca en negrita por su cuenta. Si el texto YA empieza
    // con "**" es que el modelo decidió qué resaltar -- se respeta tal
    // cual y no se toca.
    function detectarEtiquetaBullet(texto) {
      if (texto.startsWith("**")) return null;
      const m = texto.match(/^([^:*]{3,70}):\s+(.+)$/s);
      if (!m) return null;
      return { etiqueta: `${m[1]}:`, resto: m[2] };
    }
    // Igual que negritaInlineHtml pero aplicando además el auto-resaltado
    // de detectarEtiquetaBullet -- solo para el texto de una viñeta/ítem
    // numerado, no para encabezados ni definiciones (ahí el modelo ya
    // controla el énfasis con su propio "**").
    function lineaListaHtml(texto) {
      const et = detectarEtiquetaBullet(texto);
      if (!et) return negritaInlineHtml(texto);
      return `<strong>${negritaInlineHtml(et.etiqueta)}</strong> ${negritaInlineHtml(et.resto)}`;
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
          return `<li>${lineaListaHtml(n.texto)}${hijosHtml}</li>`;
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
        // sin-prefijo (ver yaEtiquetado en parsearEsquemaABloques): la
        // numeración auto-generada de h3/h4 vive en el ::before de
        // style.css -- esta clase le dice a esa regla que no la pinte
        // cuando el propio encabezado ya trae su etiqueta.
        const claseEtiqueta = b.yaEtiquetado ? ' class="sin-prefijo"' : "";
        if (b.tipo === "h2") { html.push(`<h2>${negritaInlineHtml(b.texto)}</h2>`); i++; continue; }
        if (b.tipo === "h3") { html.push(`<h3${claseEtiqueta}>${negritaInlineHtml(b.texto)}</h3>`); i++; continue; }
        if (b.tipo === "h4") { html.push(`<h4${claseEtiqueta}>${negritaInlineHtml(b.texto)}</h4>`); i++; continue; }
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
      // Título envuelto en varias líneas (10/08/2026, ver el comentario
      // largo en subida-pdf-resumen/script.js -- mismo bug, mismo arreglo).
      const lineasTitulo = doc.splitTextToSize(`Esquema de ${nombreArchivo.replace(/_/g, " ")}`, anchoTexto);
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
          // yaEtiquetado (ver parsearEsquemaABloques): sin prefijo propio
          // cuando el encabezado ya trae su propia etiqueta -- mismo
          // criterio que el CSS "sin-prefijo" en pantalla.
          if (!b.yaEtiquetado) prefijo = `${aRomano(contadorH2)}.${contadorH3} `;
        } else if (b.tipo === "h4") {
          contadorH4++;
          // Color oscuro casi negro (antes gris [90,90,90], 05/08/2026, a
          // petición del usuario): con gris y el mismo tamaño que el texto
          // normal de las viñetas, un h4 apenas se distinguía como
          // encabezado real -- se confundía con el cuerpo del esquema.
          fontSize = 11.5; fontStyle = "bold"; extraArriba = 4; indent = 8; color = [35, 35, 35];
          if (!b.yaEtiquetado) prefijo = `${contadorH3}.${aLetra(contadorH4)} `;
        } else if (b.tipo === "etiqueta-vineta") {
          // Término resaltado en negrita en su propia línea, justo encima
          // de la explicación (ver expandirEtiquetas/detectarEtiquetaBullet)
          // -- la misma idea que <strong> en pantalla, pero como línea
          // propia en vez de negrita dentro del párrafo: jsPDF dibuja cada
          // bloque con UN solo estilo de letra, así que mezclar negrita y
          // texto normal en la misma línea habría exigido medir y dibujar
          // varios "runs" por línea -- esto consigue el mismo resaltado
          // visual sin esa complejidad.
          fontSize = 11; fontStyle = "bold"; extraArriba = 2; indent = 5 + nivel * 5;
          prefijo = `${GLIFOS_VIÑETA[Math.min(nivel, GLIFOS_VIÑETA.length - 1)]} `;
        } else if (b.tipo === "bullet") {
          indent = 5 + nivel * 5;
          // continuacion (ver expandirEtiquetas): esta viñeta ya mostró su
          // glifo en la línea "etiqueta-vineta" justo encima -- aquí no se
          // repite, se sangra igual para que quede como continuación.
          prefijo = b.continuacion ? "" : `${GLIFOS_VIÑETA[Math.min(nivel, GLIFOS_VIÑETA.length - 1)]} `;
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

      // Expande una viñeta/ítem numerado con forma "Término: explicación"
      // (ver detectarEtiquetaBullet) en DOS bloques -- el término, como
      // línea propia en negrita, y la explicación justo debajo como
      // continuación de la misma viñeta -- para poder resaltarlo en el PDF
      // sin tener que mezclar estilos de letra dentro de una misma línea
      // dibujada (ver el comentario largo de "etiqueta-vineta" en
      // medirBloque). Solo para el PDF: en pantalla esto ya lo resuelve
      // lineaListaHtml con un <strong> normal dentro del mismo <li>.
      function expandirEtiquetas(bloques) {
        const resultado = [];
        for (const b of bloques) {
          if (b.tipo === "bullet" || b.tipo === "numero") {
            const et = detectarEtiquetaBullet(b.texto);
            if (et) {
              resultado.push({ tipo: "etiqueta-vineta", texto: et.etiqueta, nivel: b.nivel });
              resultado.push({ ...b, texto: et.resto, continuacion: true });
              continue;
            }
          }
          resultado.push(b);
        }
        return resultado;
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

      const medidos = expandirEtiquetas(parsearEsquemaABloques(esquema)).map(medirBloque);
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
        // Una "etiqueta-vineta" nunca va sola: su explicación (el bullet
        // "continuacion" que expandirEtiquetas puso justo detrás) tiene
        // que caer en la misma página que el término al que pertenece.
        const esEtiquetaConContinuacion = m.tipo === "etiqueta-vineta" && siguiente && siguiente.continuacion;
        let alturaNecesaria = m.alturaBloque;
        if ((m.esEncabezado || esPadreDeSubViñeta || esEtiquetaConContinuacion) && siguiente) alturaNecesaria += siguiente.alturaBloque;
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
        } else if (m.tipo === "etiqueta-vineta" || m.tipo === "bullet" || m.tipo === "numero") {
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
    // Espera 'ms' como mínimo junto a 'promesa' -- para que el aviso de
    // redirección (ver mostrarRedireccionAMisDocumentos) no aparezca y
    // desaparezca en un parpadeo con un documento corto. Mismo patrón que
    // subida-pdf-tarjetas/subida-pdf-generar-test.
    function conEsperaMinima(promesa, ms) {
      return Promise.all([promesa, new Promise((resolve) => setTimeout(resolve, ms))]).then(([resultado]) => resultado);
    }

    // Sustituye el formulario por un aviso de que la generación ya ha
    // arrancado en el servidor y de que el esquema aparecerá en "Mis
    // documentos" en cuanto esté listo (05/08/2026, a petición del usuario:
    // antes había que quedarse en esta pantalla viendo la barra de progreso
    // hasta el final). El guardado ya no depende de que esta pestaña siga
    // abierta -- ver el comentario largo en blueprints/pdf_ia.py.
    function mostrarRedireccionAMisDocumentos() {
      formularioCard.classList.add('hidden');
      contenedorCarga.classList.remove('hidden');
      document.getElementById('ai-icon').innerHTML = icono('cerebro', 32);
      document.getElementById('texto-estado').textContent = 'Nos ponemos a generar el esquema de tu documento…';
      const detalle = document.getElementById('texto-estado-detalle');
      detalle.textContent = 'Puede tardar un poco según lo largo que sea el documento. Te llevamos a "Mis documentos" para que lo veas en cuanto esté listo, sin tener que esperar aquí.';
      detalle.classList.remove('hidden');
      document.getElementById('progress-container-numerico').classList.add('hidden');
      document.getElementById('barra-indeterminada-redireccion').classList.remove('hidden');
      // El enlace "Ir a Mis documentos ahora" NO se muestra aquí todavía
      // (10/08/2026, bug real: es un <a href> normal, sin JS de por medio --
      // pulsarlo dispara una navegación completa que el navegador usa para
      // CANCELAR cualquier fetch todavía en marcha de esta página. Si el
      // usuario lo pulsaba antes de que el POST a /generar-esquema-desde-pdf
      // llegara siquiera al servidor, la generación no llegaba ni a
      // arrancar -- "le doy rápido y no genera nada"). Se revela más abajo,
      // en iniciarGeneracionEsquemaConRedireccion, solo una vez que la
      // respuesta del servidor confirma que la generación YA empezó.
      document.getElementById('sugerencia-mientras-tanto').classList.remove('hidden');
    }

    // Consume SOLO el evento "inicio" del stream SSE de
    // /generar-esquema-desde-pdf (documento_id, ver blueprints/pdf_ia.py) y
    // cancela la conexión -- el resto de la generación sigue en el
    // servidor y se guarda sola, así que no hace falta seguir escuchando
    // para que termine. Mismo patrón que iniciarGeneracionBancoTarjetas en
    // subida-pdf-tarjetas/script.js.
    async function iniciarGeneracionEsquemaConRedireccion(url, formData, authHeaders) {
      const res = await fetch(url, { method: "POST", headers: authHeaders, body: formData });
      if (res.status === 403) {
        throw new Error('Necesitas iniciar sesión o mejorar de plan para usar esta herramienta. <a href="/planes/">Ver planes</a>');
      }
      if (res.status === 429) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(`${errorData.error || "Has alcanzado el límite de uso de esta herramienta por ahora."} <a href="/planes/">Ver planes</a>`);
      }
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.error || `Error del servidor: ${res.status}`);
      }
      // A partir de aquí la respuesta ya ha llegado -- el servidor ha
      // aceptado la petición y ha empezado a generar (ver el comentario
      // largo en mostrarRedireccionAMisDocumentos) -- ahora sí es seguro
      // ofrecer el enlace manual, navegar ya no puede impedir que arranque.
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
      // Override manual de tipo_contenido (05/08/2026, ver es_texto_legal
      // en blueprints/pdf_ia.py): solo se envía si el usuario lo marcó a
      // mano -- sin marcar, el backend decide en automático con lo ya
      // guardado del documento o detectar_texto_legal.
      if (document.getElementById('checkbox-texto-legal')?.checked) {
        formData.append('es_texto_legal', 'true');
      }
      mensajeError.classList.add('hidden');
      alertaPreguntas.classList.add('hidden');
      mostrarRedireccionAMisDocumentos();

      const authHeaders = await obtenerAuthHeaders();
      if (!authHeaders) return;

      try {
        const documentoId = await conEsperaMinima(
          iniciarGeneracionEsquemaConRedireccion("https://oposicion-age.onrender.com/generar-esquema-desde-pdf", formData, authHeaders),
          9000,
        );
        window.location.href = documentoId
          ? `/mis-documentos/?destacar=${encodeURIComponent(documentoId)}&generando=esquema`
          : "/mis-documentos/";
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

    function mostrarEsquemaResultado(textoEsquema, tipoContenidoDetectado) {
      esquema = textoEsquema || "No se pudo generar el esquema.";
      const fecha = new Date();
      fechaEsquema.textContent = formatearFecha(fecha);
      esquemaTitulo.textContent = `Esquema de ${nombreArchivo}`;
      // Aviso "detectado como texto legal" (05/08/2026): solo se pinta con
      // una generación nueva -- al solo VER un esquema ya guardado no
      // viaja este campo, así que se queda oculto.
      document.getElementById('aviso-tipo-legal')?.classList.toggle('hidden', tipoContenidoDetectado !== 'legal');
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

      const authHeaders = await obtenerAuthHeaders();
      if (!authHeaders) return;

      if (ver === 'esquema') {
        formularioCard.classList.add('hidden');
        contenedorCarga.classList.remove('hidden');
        document.getElementById('texto-estado').textContent = 'Cargando tu esquema guardado…';
        try {
          const res = await fetch(`https://oposicion-age.onrender.com/documento/${documentoId}/esquema`, { headers: authHeaders });
          const datos = await res.json();
          if (!res.ok) throw new Error(datos.error || 'No se pudo cargar el esquema.');
          nombreArchivo = datos.nombre_archivo || nombreArchivo;
          mostrarEsquemaResultado(datos.esquema);
        } catch (err) {
          mostrarError(err.message);
        }
        return;
      }

      // Sin "ver": generar un esquema NUEVO desde un documento ya en la
      // biblioteca (botón "Regenerar"/"Generar esquema" de la ficha en Mis
      // documentos) -- mismo aviso de redirección que la subida de un PDF
      // nuevo, sin checkbox de texto legal disponible aquí (se mantiene en
      // automático, como ya era el caso).
      mostrarRedireccionAMisDocumentos();
      try {
        const formData = new FormData();
        formData.append('documento_id', documentoId);
        const idConfirmado = await conEsperaMinima(
          iniciarGeneracionEsquemaConRedireccion("https://oposicion-age.onrender.com/generar-esquema-desde-pdf", formData, authHeaders),
          9000,
        );
        window.location.href = `/mis-documentos/?destacar=${encodeURIComponent(idConfirmado || documentoId)}&generando=esquema`;
      } catch (err) {
        mostrarError(err.message);
      }
    })();
