let preguntas = [];
    let indicePreguntaActual = 0;
    let respuestasUsuario = [];
    let tiempoInicio;
    let intervaloTemporizador;
    let aciertos = 0;
    let fallos = 0;
    let sinResponder = 0;
    let porcentaje = 0;

    // === FUNCIONES AUXILIARES ===
    function formatearTiempo(segundos) {
      const m = String(Math.floor(segundos / 60)).padStart(2, '0');
      const s = String(segundos % 60).padStart(2, '0');
      return `${m}:${s}`;
    }

    function mostrarError(mensaje) {
      Swal.fire({
        icon: 'error',
        title: 'Error',
        text: mensaje,
        confirmButtonText: 'Entendido'
      });
      document.getElementById('form-subir-pdf').style.display = 'block';
      document.getElementById('contenedor-carga').style.display = 'none';
    }

    // === TEMPORIZADOR ===
    function iniciarTemporizador() {
      tiempoInicio = Date.now();
      intervaloTemporizador = setInterval(() => {
        const transcurrido = Math.floor((Date.now() - tiempoInicio) / 1000);
        document.getElementById("temporizador").innerHTML = `
          ⏱ Tiempo: <span class="pulse">${formatearTiempo(transcurrido)}</span>
        `;
        document.getElementById("temporizador").style.display = "block";
        document.getElementById("temporizador").style.textAlign = "center";
        document.getElementById("temporizador").style.fontSize = "1.5rem";
        document.getElementById("temporizador").style.fontWeight = "bold";
        document.getElementById("temporizador").style.padding = "15px";
        document.getElementById("temporizador").style.margin = "20px 0";
        document.getElementById("temporizador").style.background = "linear-gradient(135deg, #d0ebff, #a5d8ff)";
        document.getElementById("temporizador").style.color = "#1c7ed6";
        document.getElementById("temporizador").style.borderRadius = "12px";
        document.getElementById("temporizador").style.boxShadow = "0 4px 10px rgba(0,0,0,0.1)";
      }, 1000);
    }

    // === PROGRESO DE PREGUNTAS ===
    function actualizarBarraProgresoPreguntas() {
      const vistas = indicePreguntaActual + 1;
      const porcentaje = (vistas / preguntas.length) * 100;
      document.getElementById("progreso-preguntas").style.width = `${porcentaje}%`;
      document.getElementById("texto-progreso-preguntas").textContent = `${Math.round(porcentaje)}% (${vistas}/${preguntas.length})`;
      document.getElementById("barra-progreso-preguntas").style.display = "block";
    }

    // === GUARDADO EN FIRESTORE VIA BACKEND ===
    async function guardarTestEnBackend() {
      const usuario_id = window.usuarioEmail || "anonimo";
      const contenido = preguntas;
      const respuestas = respuestasUsuario;
      const nombreArchivo = document.getElementById('archivo-pdf').files[0]?.name || "documento.pdf";
      const tiempo = Math.floor((Date.now() - tiempoInicio) / 1000);
      
      const metadatos = {
        tipo: "test_pdf",
        tiempo: tiempo,
        nombreArchivo: nombreArchivo,
        origen: "Generar_test_pdf_html+js_1.3.UNIFICADO"
      };

      try {
        const res = await fetch("https://oposicion-age.onrender.com/guardar-test-pdf", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            usuario_id: usuario_id,
            test_data: { 
              preguntas: contenido,
              respuestas: respuestas,
              metadatos: metadatos
            },
            nombre_archivo: nombreArchivo
          })
        });
        
        const datos = await res.json();
        if (!res.ok) {
          console.warn("Test guardado: advertencia del backend", datos);
        } else {
          console.log("Test guardado exitosamente en Firebase");
        }
      } catch (e) {
        console.error("Error al guardar test en backend:", e);
      }
    }

    // === ARRANQUE DE SUBIDA PDF ===
    // Hacer que todo el área de upload sea clickeable
    document.getElementById('upload-area').addEventListener('click', () => {
      document.getElementById('archivo-pdf').click();
    });

    document.getElementById('archivo-pdf').addEventListener('change', () => {
      const file = document.getElementById('archivo-pdf').files[0];
      if (file) {
        if (file.size > 10 * 1024 * 1024) {
          Swal.fire({
            icon: 'error',
            title: 'Archivo demasiado grande',
            text: 'Máx. 10 MB.',
            confirmButtonText: 'Entendido'
          });
          document.getElementById('archivo-pdf').value = '';
          return;
        }
        const name = file.name.length > 30 ? file.name.substring(0, 27) + '...' : file.name;
        document.getElementById('file-name').textContent = name;
        document.getElementById('file-name').style.display = 'block';
      }
    });

    const uploadArea = document.getElementById('upload-area');
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
      uploadArea.addEventListener(eventName, e => { e.preventDefault(); e.stopPropagation(); });
    });
    ['dragenter', 'dragover'].forEach(eventName => {
      uploadArea.addEventListener(eventName, () => uploadArea.classList.add('dragover'));
    });
    ['dragleave', 'drop'].forEach(eventName => {
      uploadArea.addEventListener(eventName, () => uploadArea.classList.remove('dragover'));
    });
    uploadArea.addEventListener('drop', (e) => {
      const files = e.dataTransfer.files;
      document.getElementById('archivo-pdf').files = files;
      const event = new Event('change');
      document.getElementById('archivo-pdf').dispatchEvent(event);
    });

    // === ENVÍO DE FORMULARIO ===
    document.getElementById('form-subir-pdf').addEventListener('submit', async function(e) {
      e.preventDefault();
      const archivo = document.getElementById('archivo-pdf').files[0];
      const num_preguntas = parseInt(document.getElementById('num_preguntas').value);

      if (!archivo) return mostrarError('Selecciona un archivo PDF.');
      if (archivo.type !== 'application/pdf') return mostrarError('El archivo debe ser un PDF.');

      const formData = new FormData();
      formData.append('pdf', archivo);
      formData.append('num_preguntas', num_preguntas);

      document.getElementById('form-subir-pdf').style.display = 'none';
      document.getElementById('titulo-formulario').style.display = 'none';
      document.getElementById('contenedor-carga').style.display = 'block';

      const barraProgreso = document.getElementById('progreso-carga');
      const textoPorcentaje = document.getElementById('texto-carga');
      const textoEstado = document.getElementById('texto-estado');
      const aiIcon = document.getElementById('ai-icon');

      const etapas = [
        { mensaje: "Leyendo texto del PDF…", icono: "📄", porcentaje: 20 },
        { mensaje: "Extrayendo conceptos clave…", icono: "🔍", porcentaje: 40 },
        { mensaje: "Analizando estructura del temario…", icono: "📊", porcentaje: 60 },
        { mensaje: "Generando preguntas inteligentes…", icono: "🧠", porcentaje: 80 },
        { mensaje: "Preparando test…", icono: "✅", porcentaje: 95 }
      ];

      let datosIA = null;
      let errorIA = null;

      // Iniciar progreso inmediatamente
      barraProgreso.style.width = "5%";
      textoPorcentaje.textContent = "5%";
      aiIcon.textContent = "📄";
      textoEstado.textContent = "Iniciando procesamiento del PDF…";

      // Simular progreso inicial rápido
      let progresoActual = 5;
      const intervaloProgreso = setInterval(() => {
        if (progresoActual < 95) {
          progresoActual += 1;
          barraProgreso.style.width = `${progresoActual}%`;
          textoPorcentaje.textContent = `${progresoActual}%`;
          
          // Cambiar el color de la barra de progreso dinámicamente
          if (progresoActual < 30) {
            barraProgreso.style.background = `linear-gradient(90deg, #ff5252, #ff7675)`;
          } else if (progresoActual < 70) {
            barraProgreso.style.background = `linear-gradient(90deg, #ffa502, #ffb142)`;
          } else {
            barraProgreso.style.background = `linear-gradient(90deg, #2ed573, #7bed9f)`;
          }
          
          // Cambiar etapa basado en el progreso
          const etapa = etapas.find(e => progresoActual <= e.porcentaje) || etapas[etapas.length - 1];
          if (textoEstado.textContent !== etapa.mensaje) {
            aiIcon.textContent = etapa.icono;
            textoEstado.textContent = etapa.mensaje;
          }
        }
      }, 500); // Más rápido: 0.5 segundos por 1%

      const endpoints = [
        "https://oposicion-age.onrender.com/generar-test-pdf",
        "https://oposicion-age.onrender.com/generar_test_pdf", 
        "https://oposicion-age.onrender.com/generar-test-desde-pdf"
      ];

      // Ejecutar la petición en segundo plano
      let peticionExitosa = false;
      for (const url of endpoints) {
        try {
          const res = await fetch(url, { method: "POST", body: formData });
          if (res.ok) {
            const datos = await res.json();
            if (datos.test && datos.test.length > 0) {
              datosIA = datos;
              peticionExitosa = true;
              break;
            }
          }
        } catch (err) {
          console.warn(`Fallo en endpoint: ${url}`, err);
        }
      }

      if (!peticionExitosa) errorIA = new Error("Ningún endpoint devolvió preguntas válidas.");

      // Detener el intervalo de progreso
      clearInterval(intervaloProgreso);

      if (errorIA) {
        mostrarError(errorIA.message || "Error al generar el test.");
        return;
      }

      // Completar al 100%
      barraProgreso.style.width = "100%";
      textoPorcentaje.textContent = "100%";
      barraProgreso.style.background = `linear-gradient(90deg, #2ed573, #7bed9f)`;
      aiIcon.textContent = "✅";
      textoEstado.textContent = "¡Listo! Cargando test…";
      await new Promise(r => setTimeout(r, 800));

      preguntas = datosIA.test || [];
      if (preguntas.length === 0) {
        mostrarError("No se generaron preguntas válidas.");
        return;
      }

      respuestasUsuario = Array(preguntas.length).fill(null);
      indicePreguntaActual = 0;
      document.getElementById('contenedor-carga').style.display = 'none';
      iniciarTemporizador();
      actualizarBarraProgresoPreguntas();
      mostrarPregunta(indicePreguntaActual);
      document.getElementById('btn-finalizar').style.display = 'block';
    });

    // === RENDERIZADO DE PREGUNTAS ===
    function mostrarPregunta(i) {
      indicePreguntaActual = i;
      actualizarBarraProgresoPreguntas();

      const p = preguntas[i];
      let textoPregunta = p.pregunta.replace(/^\s*\d+\s*[\.\)]\s*/, "");
      let html = `<form id="form-pregunta"><fieldset style="padding: 20px;">
        <legend class="pregunta-en-negrita">${i + 1}. ${textoPregunta}</legend><br>`;

      for (const letra in p.opciones) {
        const opcion = p.opciones[letra];
        const checked = respuestasUsuario[i] === letra ? "checked" : "";
        html += `
          <div style="margin-bottom: 12px;">
            <label style="cursor: pointer; display: flex; align-items: flex-start;">
              <input type="radio" name="respuesta" value="${letra}" ${checked} style="margin-top: 4px; margin-right: 10px;">
              <div>${letra}) ${opcion}</div>
            </label>
          </div>`;
      }

      html += `
        <div class="botones-navegacion-test">
          ${i > 0 ? '<button type="button" id="btn-anterior" class="btn btn-accent btn-full">⬅️ Anterior</button>' : ''} 
          <button type="button" id="btn-desmarcar" class="btn btn-accent btn-full">❌ Desmarcar</button>
        </div>
        <button type="submit" class="btn btn-primary btn-full" style="margin-top: 15px;">
          ${i + 1 < preguntas.length ? 'Siguiente ➡️' : 'Finalizar test ✅'}
        </button>
      </fieldset></form>`;

      document.getElementById("contenedor-test").innerHTML = html;
      document.getElementById("contenedor-test").style.display = "block";

      document.getElementById("btn-desmarcar").addEventListener("click", () => {
        const marcadas = document.querySelectorAll('input[name="respuesta"]:checked');
        marcadas.forEach(m => m.checked = false);
        respuestasUsuario[i] = null;
      });

      if (i > 0 && document.getElementById("btn-anterior")) {
        document.getElementById("btn-anterior").addEventListener("click", () => {
          mostrarPregunta(i - 1);
        });
      }

      document.getElementById("form-pregunta").addEventListener("submit", function(e) {
        e.preventDefault();
        const seleccion = document.querySelector('input[name="respuesta"]:checked');
        respuestasUsuario[i] = seleccion ? seleccion.value : null;
        if (i + 1 < preguntas.length) {
          mostrarPregunta(i + 1);
        } else {
          const sinContestar = respuestasUsuario.filter(r => r === null).length;
          let mensaje = sinContestar > 0
            ? `Has dejado ${sinContestar} pregunta${sinContestar > 1 ? 's' : ''} sin contestar.`
            : '¿Quieres finalizar el test y ver los resultados?';
          Swal.fire({
            icon: 'question',
            title: '¿Deseas finalizar el test?',
            text: mensaje,
            showCancelButton: true,
            confirmButtonText: 'Sí, corregir',
            cancelButtonText: 'Seguir revisando',
          }).then((result) => {
            if (result.isConfirmed) {
              mostrarResultados();
            }
          });
        }
      });
    }

    // === RESULTADOS FINALES ===
    function mostrarResultados() {
      clearInterval(intervaloTemporizador);
      document.getElementById("barra-progreso-preguntas").style.display = "none";
      document.getElementById("contenedor-test").innerHTML = "";
      document.getElementById("contenedor-test").style.display = "none";
      document.getElementById("btn-finalizar").style.display = "none";

      aciertos = 0;
      preguntas.forEach((p, i) => {
        const correcta = p.respuesta_correcta || "No indicada";
        const seleccion = respuestasUsuario[i];
        if (seleccion === correcta) aciertos++;
      });
      fallos = preguntas.length - aciertos - respuestasUsuario.filter(r => r === null).length;
      sinResponder = respuestasUsuario.filter(r => r === null).length;
      porcentaje = ((aciertos / preguntas.length) * 100).toFixed(1);
      const nota = (aciertos * 1 - fallos * 0.33).toFixed(2);
      const notaEquivalente = ((nota / preguntas.length) * 70).toFixed(2);

      let html = `
        <div style='background:#f8f9fa;padding:25px;border-radius:12px;margin-bottom:25px;'>
          <h3>📊 Resumen del Test</h3>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 15px 0;">
            <div style="background: #e8f5e9; padding: 15px; border-radius: 10px;">
              <p style="color:green; font-weight:600;">✅ Aciertos: ${aciertos}</p>
            </div>
            <div style="background: #ffebee; padding: 15px; border-radius: 10px;">
              <p style="color:red; font-weight:600;">❌ Fallos: ${fallos}</p>
            </div>
            <div style="background: #e9ecef; padding: 15px; border-radius: 10px;">
              <p style="color:#495057; font-weight:600;">⏸ En blanco: ${sinResponder}</p>
            </div>
            <div style="background: #e7f5ff; padding: 15px; border-radius: 10px;">
              <p style="color:#1c7ed6; font-weight:600;">🎯 Porcentaje: ${porcentaje}%</p>
            </div>
          </div>
          <p><strong>📘 Nota simulada:</strong> ${nota} / ${preguntas.length}</p>
          <p><strong>📏 Nota equivalente AGE:</strong> ${notaEquivalente} / 70</p>
          <div style='background:#e9ecef;border-radius:10px;overflow:hidden;margin-top:15px;height:20px;'>
            <div style='width:${porcentaje}%;background:linear-gradient(to right,#4caf50,#81c784);height:100%;display:flex;align-items:center;justify-content:center;color:white;font-weight:600;'>
              ${porcentaje}%
            </div>
          </div>
        </div>
        <div class="filtros-container">
          <button class="btn btn-accent" onclick="aplicarFiltro('todos')">🟡 Todos</button>
          <button class="btn btn-primary" onclick="aplicarFiltro('acierto')">✅ Aciertos</button>
          <button class="btn btn-danger" onclick="aplicarFiltro('fallo')">❌ Fallos</button>
          <button class="btn" style="background: #adb5bd; color: white;" onclick="aplicarFiltro('blanco')">⏸ En blanco</button>
        </div>
        <h3 style="margin-top: 30px;">📝 Detalle de preguntas</h3>
        <ol style="padding-left: 18px;">`;

      preguntas.forEach((p, i) => {
        const correcta = p.respuesta_correcta || "No indicada";
        const seleccion = respuestasUsuario[i];
        let clase = "fallo";
        if (seleccion === correcta) {
          clase = "acierto";
        } else if (seleccion === null) {
          clase = "blanco";
        }

        let preguntaSinNumero = p.pregunta.replace(/^\s*\d+\s*[\.\)]\s*/, "");
        html += `<li class="${clase}" style="margin-bottom:25px;">
          <div class="pregunta-en-negrita">${i + 1}. ${preguntaSinNumero}</div>`;

        for (const letra in p.opciones) {
          let tipoRespuesta = "resp-neutra";
          let icono = "";
          if (letra === correcta) {
            tipoRespuesta = "resp-correcta";
            icono = '<span class="icono-correcto">✅</span>';
          }
          if (letra === seleccion && seleccion !== correcta) {
            tipoRespuesta = "resp-incorrecta";
            icono = '<span class="icono-incorrecto">❌ </span>';
          }
          html += `<div class="${tipoRespuesta}">${icono}${letra}) ${p.opciones[letra]}</div>`;
        }

        const idExp = "exp" + i;
        html += `<button class="btn" style="margin-top: 10px; background: #e9ecef; color: #495057;" 
                 onclick="document.getElementById('${idExp}').style.display = document.getElementById('${idExp}').style.display === 'none' ? 'block' : 'none';">
                 📘 Mostrar/Ocultar Explicación</button>`;
        html += `<div id="${idExp}" style="display:none; margin-top: 10px; padding: 15px; background: #f8f9fa; border-radius: 8px;">
                 <strong>Explicación:</strong> ${p.explicacion || "Sin explicación."}</div></li>`;
      });

      html += `</ol>`;
      document.getElementById("contenedor-resultados").innerHTML = html;
      document.getElementById("contenedor-resultados").style.display = "block";
      document.getElementById("btn-descargar-pdf").style.display = "block";

      guardarTestEnBackend();
    }

    // === FILTROS DE RESULTADOS ===
    function aplicarFiltro(tipo) {
      const items = document.querySelectorAll("#contenedor-resultados ol li");
      items.forEach(li => {
        if (tipo === 'todos') {
          li.style.display = 'block';
        } else {
          li.style.display = li.classList.contains(tipo) ? 'block' : 'none';
        }
      });
    }

    // === FINALIZAR TEST ===
    document.getElementById("btn-finalizar").addEventListener("click", () => {
      const sinContestar = respuestasUsuario.filter(r => r === null).length;
      let mensaje = sinContestar > 0
        ? `Has dejado ${sinContestar} pregunta${sinContestar > 1 ? 's' : ''} sin contestar.`
        : '¿Quieres finalizar el test y ver los resultados?';
      Swal.fire({
        icon: 'question',
        title: '¿Deseas finalizar el test?',
        text: mensaje,
        showCancelButton: true,
        confirmButtonText: 'Sí, corregir',
        cancelButtonText: 'Seguir revisando',
      }).then((result) => {
        if (result.isConfirmed) {
          mostrarResultados();
        }
      });
    });

    // === DESCARGAR PDF ===
    document.getElementById("btn-descargar-pdf").addEventListener("click", function() {
      const { jsPDF } = window.jspdf;
      const doc = new jsPDF();
      const margin = 15;
      const pageWidth = doc.internal.pageSize.getWidth();
      const pageHeight = doc.internal.pageSize.getHeight();
      let yPos = 20;

      function reemplazarEmojis(texto) {
        if (!texto) return "";
        return texto
          .replace(/✅/g, '[Correcta]')
          .replace(/❌/g, '[Incorrecta]')
          .replace(/⏸/g, '[En blanco]')
          .replace(/📘/g, 'Explicación:')
          .replace(/📝/g, '')
          .replace(/🤖/g, '')
          .replace(/⏱/g, 'Tiempo:')
          .replace(/📊/g, '')
          .replace(/📈/g, '')
          .replace(/🎯/g, '');
      }

      doc.setFontSize(18);
      doc.setFont("helvetica", "bold");
      doc.text("Resultados del Test", pageWidth / 2, yPos, null, null, 'center');
      yPos += 15;
      doc.setFontSize(12);
      doc.setFont("helvetica", "normal");
      const resumen = `Aciertos: ${aciertos} | Fallos: ${fallos} | En blanco: ${sinResponder} | Porcentaje: ${porcentaje}%`;
      doc.text(resumen, pageWidth / 2, yPos, null, null, 'center');
      yPos += 15;
      doc.setFontSize(11);

      preguntas.forEach((p, i) => {
        if (yPos > pageHeight - 50) {
          doc.addPage();
          yPos = 20;
        }
        doc.setFont("helvetica", "bold");
        let textoPregunta = p.pregunta.replace(/^\s*\d+\s*[\.\)]\s*/, "");
        textoPregunta = `${i + 1}. ${reemplazarEmojis(textoPregunta)}`;
        const preguntaLines = doc.splitTextToSize(textoPregunta, pageWidth - 2 * margin);
        preguntaLines.forEach(line => {
          if (yPos > pageHeight - 20) {
            doc.addPage();
            yPos = 20;
          }
          doc.text(line, margin, yPos);
          yPos += 7;
        });
        doc.setFont("helvetica", "normal");
        yPos += 5;
        for (const letra in p.opciones) {
          let opcionTexto = `${letra}) ${reemplazarEmojis(p.opciones[letra])}`;
          if (letra === p.respuesta_correcta) {
            opcionTexto += " [Correcta]";
          }
          const opcionLines = doc.splitTextToSize(opcionTexto, pageWidth - 2 * margin);
          opcionLines.forEach(line => {
            if (yPos > pageHeight - 20) {
              doc.addPage();
              yPos = 20;
            }
            doc.text(line, margin, yPos);
            yPos += 7;
          });
        }
        yPos += 5;
        const explicacion = p.explicacion || "Sin explicación disponible.";
        doc.setFont("helvetica", "bold");
        doc.text("Explicación:", margin, yPos);
        yPos += 7;
        doc.setFont("helvetica", "normal");
        const explicacionLines = doc.splitTextToSize(reemplazarEmojis(explicacion), pageWidth - 2 * margin);
        explicacionLines.forEach(line => {
          if (yPos > pageHeight - 20) {
            doc.addPage();
            yPos = 20;
          }
          doc.text(line, margin, yPos);
          yPos += 7;
        });
        yPos += 10;
        if (yPos < pageHeight - 10) {
          doc.setDrawColor(200);
          doc.line(margin, yPos, pageWidth - margin, yPos);
          yPos += 15;
        }
      });
      doc.save("resultados-test.pdf");
    });
