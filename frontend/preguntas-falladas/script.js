async function obtenerAuthHeaders() {
      const { idToken } = await import("/assets/auth.js");
      const token = await idToken();
      if (!token) {
        window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
        return null;
      }
      return { "Authorization": "Bearer " + token };
    }

    let preguntas = [];
    let indicePreguntaActual = 0;
    let respuestasUsuario = [];
    let tiempoInicio;
    let intervaloTemporizador;
    let aciertos = 0;
    let fallos = 0;
    let sinResponder = 0;
    let porcentaje = 0;

    function mostrarAviso(texto) {
      const aviso = document.getElementById('aviso-falladas');
      aviso.innerText = texto;
      aviso.style.display = 'block';
    }

    function iniciarTemporizador() {
      tiempoInicio = Date.now();
      intervaloTemporizador = setInterval(() => {
        const transcurrido = Math.floor((Date.now() - tiempoInicio) / 1000);
        document.getElementById("temporizador").textContent = `⏱ Tiempo: ${formatearTiempo(transcurrido)}`;
      }, 1000);
    }

    function formatearTiempo(segundos) {
      const m = String(Math.floor(segundos / 60)).padStart(2, '0');
      const s = String(segundos % 60).padStart(2, '0');
      return `${m}:${s}`;
    }

    function actualizarBarraProgresoPreguntas() {
      const vistas = indicePreguntaActual + 1;
      const porcentaje = (vistas / preguntas.length) * 100;
      document.getElementById("progreso-preguntas").style.width = `${porcentaje}%`;
      document.getElementById("texto-progreso-preguntas").textContent = `${Math.round(porcentaje)}% (${vistas}/${preguntas.length})`;
    }

    document.getElementById("form-falladas").addEventListener("submit", async function(e) {
      e.preventDefault();
      document.getElementById('contenedor-resultados').style.display = "none";
      const num_preguntas = parseInt(document.getElementById("num_preguntas").value);
      document.getElementById('form-falladas').style.display = "none";
      document.getElementById('titulo-formulario').style.display = "none";
      document.getElementById('aviso-falladas').style.display = "none";
      
      document.getElementById("contenedor-test").innerHTML = `
        <div class="loading-container">
          <p>⏳ Buscando preguntas falladas...</p>
          <progress id="barra-carga" value="0" max="100" style="width: 100%; height: 20px;"></progress>
          <p id="texto-carga">0%</p>
        </div>
      `;
      
      let progreso = 0;
      const mensajes = [
        "Obteniendo preguntas...",
        "Cargando contenido...",
        "Preparando test...",
        "Finalizando..."
      ];
      
      const intervalCarga = setInterval(() => {
        if (progreso < 100) {
          progreso += 2;
          const indiceMensaje = Math.min(Math.floor(progreso / 25), mensajes.length - 1);
          document.getElementById("texto-carga").textContent = `${mensajes[indiceMensaje]} ${progreso}%`;
          document.getElementById("barra-carga").value = progreso;
        }
      }, 60);

      try {
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) { clearInterval(intervalCarga); return; }
        const res = await fetch("https://oposicion-age.onrender.com/generar-test-fallos", {
          method: "POST",
          headers: {"Content-Type": "application/json", ...authHeaders},
          body: JSON.stringify({ num_preguntas })
        });
        
        clearInterval(intervalCarga);
        const datos = await res.json();
        preguntas = datos.test || [];
        
        if (preguntas.length === 0) {
          mostrarAviso("No tienes preguntas falladas pendientes en tu cuenta. Haz algún test y vuelve aquí para repasarlas.");
          document.getElementById("contenedor-test").innerHTML = "";
          document.getElementById("form-falladas").style.display = "";
          document.getElementById('titulo-formulario').style.display = "";
          return;
        }
        
        respuestasUsuario = Array(preguntas.length).fill(null);
        indicePreguntaActual = 0;
        iniciarTemporizador();
        
        document.getElementById("barra-progreso-preguntas").style.display = "block";
        actualizarBarraProgresoPreguntas();
        
        mostrarPregunta(indicePreguntaActual);
      } catch (error) {
        clearInterval(intervalCarga);
        mostrarAviso("❌ Error buscando preguntas falladas. Intenta más tarde.");
        document.getElementById("contenedor-test").innerHTML = "";
        document.getElementById("form-falladas").style.display = "";
        document.getElementById('titulo-formulario').style.display = "";
        console.error(error);
      }
    });

    function mostrarPregunta(i) {
      indicePreguntaActual = i;
      actualizarBarraProgresoPreguntas();
      
      const p = preguntas[i];
      let html = `<form id="form-pregunta"><fieldset style="padding: 20px;">
        <legend class="pregunta-en-negrita">${i + 1}. ${p.pregunta}</legend><br>`;
      
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
          ${i > 0 ? '<button type="button" id="btn-anterior" class="btn-naranja">⬅️ Anterior</button>' : ''} 
          <button type="button" id="btn-desmarcar" class="btn-naranja">❌ Desmarcar</button>
        </div>
        <button type="submit" class="btn btn-primary" style="margin-top: 15px; width: 100%;">
          ${i + 1 < preguntas.length ? 'Siguiente ➡️' : 'Finalizar test ✅'}
        </button>
      </fieldset></form>`;
      
      document.getElementById("contenedor-test").innerHTML = html;
      document.getElementById("btn-desmarcar").addEventListener("click", () => {
        const marcadas = document.querySelectorAll('input[name="respuesta"]:checked');
        marcadas.forEach(m => m.checked = false);
        respuestasUsuario[i] = null;
      });
      
      document.getElementById("btn-finalizar").style.display = "block";
      
      if (i > 0 && document.getElementById("btn-anterior")) {
        document.getElementById("btn-anterior").addEventListener("click", () => mostrarPregunta(i - 1));
      }
      
      document.getElementById("form-pregunta").addEventListener("submit", function(e) {
        e.preventDefault();
        const seleccion = document.querySelector('input[name="respuesta"]:checked');
        const respuestaSeleccionada = seleccion ? seleccion.value : null;
        respuestasUsuario[i] = respuestaSeleccionada;
        
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

    async function guardarTestFalladasAutomaticamente() {
      const contenido = preguntas;
      const respuestas = respuestasUsuario;
      const tipo = "falladas";
      const tiempo = Math.floor((Date.now() - tiempoInicio) / 1000);
      const metadatos = { tipo, tiempo };

      try {
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) return;
        const res = await fetch("https://oposicion-age.onrender.com/guardar-test", {
          method: "POST",
          headers: {"Content-Type": "application/json", ...authHeaders},
          body: JSON.stringify({ contenido, respuestas, metadatos })
        });
        
        const datos = await res.json();
        if (!res.ok) {
          console.error("Error al guardar test:", datos.error || "No se pudo guardar el test.");
        }
      } catch (e) {
        console.error("Error al guardar test falladas:", e);
      }
    }

    async function mostrarResultados() {
      clearInterval(intervaloTemporizador);
      document.getElementById("contenedor-test").innerHTML = "";
      document.getElementById("btn-finalizar").style.display = "none";
      const cont = document.getElementById("contenedor-resultados");
      cont.style.display = "block";
      
      aciertos = 0;
      let html = `
        <div class="filtros-container">
          <button class="btn btn-accent" onclick="aplicarFiltro('todos')">🟡 Todos</button>
          <button class="btn btn-primary" onclick="aplicarFiltro('acierto')">✅ Aciertos</button>
          <button class="btn btn-danger" onclick="aplicarFiltro('fallo')">❌ Fallos</button>
          <button class="btn" style="background: #adb5bd; color: white;" onclick="aplicarFiltro('blanco')">⏸ En blanco</button>
        </div>
        <ol style="padding-left: 18px;">`;
      
      preguntas.forEach((p, i) => {
        const correcta = p.respuesta_correcta || "No indicada";
        const explicacion = p.explicacion || "Sin explicación.";
        const seleccion = respuestasUsuario[i];
        
        let clase = seleccion === correcta ? "acierto" : (seleccion === null ? "blanco" : "fallo");
        let preguntaSinNumero = p.pregunta.replace(/^\s*\d+\s*[\.\\)]\s*/, "");
        
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
                 onclick="document.getElementById('${idExp}').style.display = document.getElementById('${idExp}').style.display === 'none' ? 'block' : 'none';">📘 Mostrar/Ocultar Explicación</button>`;
        html += `<div id="${idExp}" style="display:none; margin-top: 10px; padding: 15px; background: #f8f9fa; border-radius: 8px;">
                 <strong>Explicación:</strong> ${explicacion}</div></li>`;
        
        if (seleccion === correcta) aciertos++;
      });
      
      fallos = preguntas.length - aciertos - respuestasUsuario.filter(r => r === null).length;
      sinResponder = respuestasUsuario.filter(r => r === null).length;
      porcentaje = ((aciertos / preguntas.length) * 100).toFixed(1);
      const nota = (aciertos * 1 - fallos * 0.33).toFixed(2);
      const notaEquivalente = ((nota / preguntas.length) * 70).toFixed(2);
      
      html = `
        <div style='background:#f8f9fa;padding:25px;border-radius:12px;margin-bottom:25px;'>
          <h3>📊 Resumen del Test</h3>
          <div class="summary-grid">
            <div class="summary-item aciertos">
              <p style="font-weight:600;">✅ Aciertos: ${aciertos}</p>
            </div>
            <div class="summary-item fallos">
              <p style="font-weight:600;">❌ Fallos: ${fallos}</p>
            </div>
            <div class="summary-item blancos">
              <p style="font-weight:600;">⏸ En blanco: ${sinResponder}</p>
            </div>
            <div class="summary-item porcentaje">
              <p style="font-weight:600;">🎯 Porcentaje: ${porcentaje}%</p>
            </div>
          </div>
          <p><strong>📘 Nota simulada:</strong> ${nota} / ${preguntas.length}</p>
          <p><strong>📏 Nota equivalente AGE:</strong> ${notaEquivalente} / 70</p>
          <div class="progress-summary">
            <div class="progress-summary-fill" style='width:${porcentaje}%;background:linear-gradient(to right,#4caf50,#81c784);'>
              ${porcentaje}%
            </div>
          </div>
        </div>
        <h3 style="margin-top: 30px;">📝 Detalle de preguntas</h3>
      ` + html;
      
      html += `</ol>`;
      cont.innerHTML = html;
      document.getElementById("btn-descargar-pdf").style.display = "block";
      
      guardarTestFalladasAutomaticamente();
    }

    document.addEventListener("DOMContentLoaded", function () {
      const btnFinalizar = document.getElementById("btn-finalizar");
      if (!btnFinalizar) return;
      
      btnFinalizar.addEventListener("click", () => {
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
    });

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

    document.getElementById("btn-descargar-pdf").addEventListener("click", () => {
      const { jsPDF } = window.jspdf;
      const doc = new jsPDF();
      let y = 20;
      const pageHeight = doc.internal.pageSize.height;
      const lineHeight = 7;
      const margen = 10;
      doc.setFontSize(12);

      doc.setFont(undefined, "bold");
      doc.text("Resultados del Test de Preguntas Falladas", margen, y);
      y += 10;
      
      doc.setFont(undefined, "normal");
      doc.text(`Aciertos: ${aciertos} | Fallos: ${fallos} | En blanco: ${sinResponder} | Porcentaje: ${porcentaje}%`, margen, y);
      y += 10;

      preguntas.forEach((p, i) => {
        let preguntaSinNumero = p.pregunta.replace(/^\s*\d+\s*[\.\\)]\s*/, "");
        const preguntaTexto = `Pregunta ${i + 1}: ${preguntaSinNumero}`;
        doc.setFont(undefined, "bold");
        y = añadirTexto(doc, preguntaTexto, margen, y, lineHeight, pageHeight);
        doc.setFont(undefined, "normal");
        
        for (const clave in p.opciones) {
          let texto = `${clave}) ${p.opciones[clave]}`;
          if (clave === p.respuesta_correcta) {
            doc.setTextColor(67, 160, 71);
            doc.setFont(undefined, "bold");
          } else {
            doc.setTextColor(0,0,0);
            doc.setFont(undefined, "normal");
          }
          
          doc.text(texto, margen + 5, y + 4);
          y += lineHeight + 3;
          if (y > pageHeight - margen) {
            doc.addPage();
            y = margen;
          }
        }
        
        doc.setTextColor(0,0,0);
        doc.setFont(undefined, "normal");
        y = añadirTexto(doc, `Explicación: ${p.explicacion}`, margen, y, lineHeight, pageHeight);
        y += 4;
        
        if (y > pageHeight - margen) {
          doc.addPage();
          y = margen;
        }
      });

      doc.save("test_falladas.pdf");
      
      function añadirTexto(doc, texto, x, y, lh, ph) {
        const lineas = doc.splitTextToSize(texto, 180);
        lineas.forEach(linea => {
          if (y + lh > ph - 10) {
            doc.addPage();
            y = 10;
          }
          doc.text(linea, x, y);
          y += lh;
        });
        return y;
      }
    });
