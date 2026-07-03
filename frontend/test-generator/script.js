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
    let tiempoLimite = null;
    let intervaloCronometro = null;
    let listaTemasGlobal = [];
    let aciertos = 0;
    let fallos = 0;
    let sinResponder = 0;
    let porcentaje = 0;
    let tiempoTotalAsignado = 0;

    document.addEventListener("DOMContentLoaded", function() {
      const cards = document.querySelectorAll('.test-type-card');
      cards.forEach(card => {
        card.addEventListener('click', function() {
          cards.forEach(c => c.classList.remove('selected'));
          this.classList.add('selected');
          const tipo = this.dataset.tipo;
          document.getElementById('tipo_test').value = tipo;
          const listaTemas = document.getElementById("lista-temas");
          const tituloFormulario = document.getElementById("titulo-formulario");
          if (tipo === "oficial") {
            listaTemas.style.display = "none";
            tituloFormulario.textContent = "Genera tu Test Oficial";
          } else {
            listaTemas.style.display = "grid";
            tituloFormulario.textContent = tipo === "personalizado" 
              ? "Genera tu Test Personalizado" 
              : "Genera tu Test Inteligente IA";
          }
        });
      });
      document.querySelector('.test-type-card[data-tipo="personalizado"]').click();
      document.getElementById('modo_cronometrado').addEventListener('change', function() {
        document.getElementById('tiempo_cronometro').style.display = this.checked ? 'flex' : 'none';
      });
    });

    async function guardarTestAutomaticamente() {
      const contenido = preguntas;
      const respuestas = respuestasUsuario;
      const tipo = document.getElementById('tipo_test').value;
      const temas = Array.from(document.querySelectorAll('input[name="tema"]:checked')).map(el => el.value);
      let tiempo;
      if (tiempoLimite !== null) {
        tiempo = tiempoTotalAsignado - tiempoLimite;
      } else {
        tiempo = Math.floor((Date.now() - tiempoInicio) / 1000);
      }
      const metadatos = { tipo, tiempo, temas };
      try {
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) return;
        const { obtenerOposicionActual } = await import("/assets/oposicion.js");
        const oposicion = obtenerOposicionActual();
        const res = await fetch("https://oposicion-age.onrender.com/guardar-test", {
          method: "POST",
          headers: {"Content-Type": "application/json", ...authHeaders},
          body: JSON.stringify({ contenido, respuestas, metadatos, oposicion })
        });
        const datos = await res.json();
        if (!res.ok) {
          Swal.fire("Error al guardar", datos.error || "No se pudo guardar el test.", "error");
        }
      } catch (e) {
        console.error("Error al guardar test:", e);
      }
    }

    async function cargarTemas() {
      const contenedor = document.getElementById("lista-temas");
      contenedor.innerHTML = "<p>Cargando temas...</p>";
      try {
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) return;
        const { obtenerOposicionActual } = await import("/assets/oposicion.js");
        const oposicion = obtenerOposicionActual();
        const res = await fetch(`https://oposicion-age.onrender.com/temas-disponibles?oposicion=${encodeURIComponent(oposicion)}`, { headers: authHeaders });
        const datos = await res.json();
        listaTemasGlobal = datos.temas || [];
        if (listaTemasGlobal.length === 0) {
          contenedor.innerHTML = "<p>No hay temas disponibles.</p>";
          return;
        }
        contenedor.innerHTML = "";
        listaTemasGlobal.forEach(t => {
          const label = document.createElement("label");
          label.innerHTML = `
            <input type="checkbox" name="tema" value="${t.id}">
            ${t.titulo}
          `;
          contenedor.appendChild(label);
        });
      } catch (err) {
        contenedor.innerHTML = `<p>Error al cargar temas: ${err.message}</p>`;
        console.error(err);
      }
    }

    function iniciarTemporizador() {
      tiempoInicio = Date.now();
      if (document.getElementById('modo_cronometrado').checked) {
        const minutos = parseInt(document.getElementById('minutos_cronometro').value) || 60;
        tiempoLimite = minutos * 60;
        tiempoTotalAsignado = tiempoLimite;
        document.getElementById("barra-progreso-tiempo").style.display = "block";
        intervaloTemporizador = setInterval(() => {
          tiempoLimite--;
          if (tiempoLimite <= 0) {
            clearInterval(intervaloTemporizador);
            Swal.fire({
              title: '¡Tiempo terminado!',
              text: 'Se ha finalizado el test automáticamente.',
              icon: 'warning',
              confirmButtonText: 'Ver resultados'
            }).then(() => {
              mostrarResultados();
            });
            return;
          }
          document.getElementById("temporizador").innerHTML = `
            ⏱ Tiempo restante: <span class="pulse">${formatearTiempo(tiempoLimite)}</span>
          `;
          if (tiempoLimite <= 60) {
            document.getElementById("temporizador").style.background = 'linear-gradient(135deg, #fff3bf, #ffd8a8)';
            document.getElementById("temporizador").style.color = '#e67700';
          } else if (tiempoLimite <= 300) {
            document.getElementById("temporizador").style.background = 'linear-gradient(135deg, #d0ebff, #a5d8ff)';
            document.getElementById("temporizador").style.color = '#1c7ed6';
          }
          const porcentajeTiempo = ((minutos * 60 - tiempoLimite) / (minutos * 60)) * 100;
          document.getElementById("progreso-tiempo").style.width = `${porcentajeTiempo}%`;
          document.getElementById("texto-progreso-tiempo").textContent = `${Math.round(porcentajeTiempo)}%`;
        }, 1000);
      } else {
        intervaloTemporizador = setInterval(() => {
          const transcurrido = Math.floor((Date.now() - tiempoInicio) / 1000);
          document.getElementById("temporizador").textContent = `⏱ Tiempo: ${formatearTiempo(transcurrido)}`;
        }, 1000);
      }
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

    document.getElementById("form-generar-test").addEventListener("submit", async function(e) {
      e.preventDefault();
      document.getElementById("barra-progreso-tiempo").style.display = "none";
      document.getElementById("barra-progreso-preguntas").style.display = "none";
      const tipo = document.getElementById('tipo_test').value;
      const num_preguntas = parseInt(document.getElementById("num_preguntas").value);
      let temas = [];
      if (tipo !== "oficial") {
        temas = Array.from(document.querySelectorAll('input[name="tema"]:checked')).map(el => el.value);
        if (temas.length === 0) {
          Swal.fire({
            icon: "warning",
            title: "Selecciona un tema",
            text: "Debes elegir al menos un tema para continuar.",
            confirmButtonText: "Entendido"
          });
          return;
        }
      }
      const endpoint = tipo === "oficial" ? "/generar-test-oficial" : 
                      tipo === "inteligente" ? "/generar-test-inteligente" : 
                      "/generar-test-avanzado";
      document.getElementById('form-generar-test').style.display = "none";
      document.getElementById('titulo-formulario').style.display = "none";
      document.getElementById("contenedor-test").innerHTML = `
        <div style="text-align: center; padding: 20px;">
          <p id="mensaje-carga">⏳ Iniciando generación de test...</p>
          <div class="progress-container">
            <div id="barra-carga" class="barra-carga" style="width: 0%"></div>
            <div id="texto-carga" class="progress-text">0%</div>
          </div>
        </div>
      `;
      let progreso = 0;
      const mensajes = [
        "Obteniendo preguntas...",
        "Generando opciones...",
        "Validando contenido...",
        "Preparando test...",
        "Finalizando..."
      ];
      const intervalCarga = setInterval(() => {
        if (progreso < 100) {
          progreso += 1;
          const indiceMensaje = Math.min(Math.floor(progreso / 20), mensajes.length - 1);
          document.getElementById("mensaje-carga").textContent = `⏳ ${mensajes[indiceMensaje]}`;
          document.getElementById("barra-carga").style.width = `${progreso}%`;
          document.getElementById("texto-carga").textContent = `${progreso}%`;
        }
      }, 190);
      try {
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) { clearInterval(intervalCarga); return; }
        const { obtenerOposicionActual } = await import("/assets/oposicion.js");
        const oposicion = obtenerOposicionActual();
        const res = await fetch("https://oposicion-age.onrender.com" + endpoint, {
          method: "POST",
          headers: {"Content-Type": "application/json", ...authHeaders},
          body: JSON.stringify({ temas, num_preguntas, oposicion })
        });
        clearInterval(intervalCarga);
        if (res.status === 403) {
          const datosError = await res.json();
          document.getElementById('contenedor-test').innerHTML = `
            <p>${datosError.error === "Requiere plan superior" ? `Este tipo de test requiere el plan <strong>${datosError.plan_requerido}</strong>.` : "No tienes acceso a esta función."}</p>
            <a class="btn btn-primary" href="/planes/">Ver planes</a>
          `;
          return;
        }
        const datos = await res.json();
        preguntas = datos.test || [];
        if (preguntas.length === 0) {
          document.getElementById('contenedor-test').innerHTML = "<p>No se han recibido preguntas.</p>";
          return;
        }
        preguntas.forEach(p => {
          if (!p.tema_id && temas.length > 0) {
            p.tema_id = temas[Math.floor(Math.random() * temas.length)];
          }
        });
        respuestasUsuario = Array(preguntas.length).fill(null);
        indicePreguntaActual = 0;
        iniciarTemporizador();
        document.getElementById("barra-progreso-preguntas").style.display = "block";
        actualizarBarraProgresoPreguntas();
        mostrarPregunta(indicePreguntaActual);
      } catch (error) {
        clearInterval(intervalCarga);
        document.getElementById('contenedor-test').innerHTML = `
          <p>Error al generar el test: ${error.message}</p>
          <button class="btn btn-primary" onclick="location.reload()">Volver a intentar</button>
        `;
        console.error(error);
      }
    });

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
        <div style="margin-top: 30px; display: flex; justify-content: space-between;">
          ${i > 0 ? '<button type="button" id="btn-anterior" class="btn btn-accent" style="width: 48%;">⬅️ Anterior</button>' : ''} 
          <button type="button" id="btn-desmarcar" class="btn btn-accent" style="width: ${i > 0 ? '48%' : '100%'};">❌ Desmarcar</button>
        </div>
        <button type="submit" class="btn btn-primary btn-siguiente" style="margin-top: 15px;">
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
        document.getElementById("btn-anterior").addEventListener("click", () => {
          mostrarPregunta(i - 1);
        });
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

    async function mostrarResultados() {
      clearInterval(intervaloTemporizador);
      if (tiempoLimite !== null) clearInterval(intervaloCronometro);
      document.getElementById("barra-progreso-tiempo").style.display = "none";
      document.getElementById("barra-progreso-preguntas").style.display = "none";
      document.getElementById("contenedor-test").innerHTML = "";
      document.getElementById("btn-finalizar").style.display = "none";
      const cont = document.getElementById("contenedor-resultados");
      cont.style.display = "block";
      aciertos = 0;
      const tipo = document.getElementById('tipo_test').value;
      let html = `
        <div class="filtros-container">
          <button class="btn btn-accent" onclick="aplicarFiltro('todos')">🟡 Todos</button>
          <button class="btn btn-primary" onclick="aplicarFiltro('acierto')">✅ Aciertos</button>
          <button class="btn btn-danger" onclick="aplicarFiltro('fallo')">❌ Fallos</button>
          <button class="btn" style="background: #adb5bd; color: white;" onclick="aplicarFiltro('blanco')">⏸ En blanco</button>
        </div>
        <ol style="padding-left: 18px;">`;
      const statsPorTema = {};
      preguntas.forEach((p, i) => {
        const tema = listaTemasGlobal.find(t => t.id === p.tema_id);
        const temaId = tema ? tema.id : "desconocido";
        const tituloTema = tema ? tema.titulo : "Tema desconocido";
        if (!statsPorTema[temaId]) {
          statsPorTema[temaId] = {
            titulo: tituloTema,
            total: 0,
            aciertos: 0,
            fallos: 0,
            blancos: 0
          };
        }
        statsPorTema[temaId].total++;
        const correcta = p.respuesta_correcta || "No indicada";
        const explicacion = p.explicacion || "Sin explicación.";
        const seleccion = respuestasUsuario[i];
        let clase = "fallo";
        if (seleccion === correcta) {
          aciertos++;
          clase = "acierto";
          statsPorTema[temaId].aciertos++;
        } else if (seleccion === null) {
          clase = "blanco";
          statsPorTema[temaId].blancos++;
        } else {
          statsPorTema[temaId].fallos++;
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
                 <strong>Explicación:</strong> ${explicacion}</div></li>`;
      });
      fallos = preguntas.length - aciertos - respuestasUsuario.filter(r => r === null).length;
      sinResponder = respuestasUsuario.filter(r => r === null).length;
      porcentaje = ((aciertos / preguntas.length) * 100).toFixed(1);
      const nota = (aciertos * 1 - fallos * 0.33).toFixed(2);
      const notaEquivalente = ((nota / preguntas.length) * 70).toFixed(2);
      let chartHTML = '';
      if (tipo !== "oficial") {
        chartHTML = '<div class="stats-container">';
        chartHTML += '<div class="chart-container"><canvas id="chart-temas"></canvas></div>';
        chartHTML += '<div class="chart-container"><canvas id="chart-rendimiento"></canvas></div></div>';
      }
      html = `
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
        ${chartHTML ? '<h3>📈 Estadísticas por Temas</h3>' + chartHTML : ''}
        <h3 style="margin-top: 30px;">📝 Detalle de preguntas</h3>
      ` + html;
      html += `</ol>`;
      cont.innerHTML = html;
      document.getElementById("btn-descargar-pdf").style.display = "block";
      if (tipo !== "oficial") {
        crearGraficoTemas(statsPorTema);
        crearGraficoRendimiento(statsPorTema);
      }
      guardarTestAutomaticamente();
    }

    function crearGraficoTemas(stats) {
      const ctx = document.getElementById('chart-temas').getContext('2d');
      const temas = Object.values(stats);
      new Chart(ctx, {
        type: 'bar',
        data: {
          labels: temas.map(t => t.titulo.length > 20 ? t.titulo.substring(0, 17) + '...' : t.titulo),
          datasets: [{
            label: 'Aciertos',
            data: temas.map(t => t.aciertos),
            backgroundColor: '#4caf50',
            borderColor: '#388e3c',
            borderWidth: 1
          }, {
            label: 'Fallos',
            data: temas.map(t => t.fallos),
            backgroundColor: '#ef5350',
            borderColor: '#d32f2f',
            borderWidth: 1
          }, {
            label: 'Blancos',
            data: temas.map(t => t.blancos),
            backgroundColor: '#bdbdbd',
            borderColor: '#757575',
            borderWidth: 1
          }]
        },
        options: {
          responsive: true,
          plugins: {
            title: {
              display: true,
              text: 'Rendimiento por tema',
              font: { size: 16 }
            },
            legend: { position: 'top' }
          },
          scales: {
            y: {
              beginAtZero: true,
              title: { display: true, text: 'Cantidad' }
            }
          }
        }
      });
    }

    function crearGraficoRendimiento(stats) {
      const ctx = document.getElementById('chart-rendimiento').getContext('2d');
      const temas = Object.values(stats);
      new Chart(ctx, {
        type: 'doughnut',
        data: {
          labels: ['Aciertos', 'Fallos', 'Blancos'],
          datasets: [{
            data: [
              temas.reduce((sum, t) => sum + t.aciertos, 0),
              temas.reduce((sum, t) => sum + t.fallos, 0),
              temas.reduce((sum, t) => sum + t.blancos, 0)
            ],
            backgroundColor: ['#4caf50', '#ef5350', '#bdbdbd'],
            borderColor: ['#388e3c', '#d32f2f', '#757575'],
            borderWidth: 1
          }]
        },
        options: {
          responsive: true,
          plugins: {
            title: {
              display: true,
              text: 'Distribución general',
              font: { size: 16 }
            },
            legend: { position: 'top' }
          }
        }
      });
    }

    document.addEventListener("DOMContentLoaded", function() {
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
          .replace(/🏛️/g, '')
          .replace(/🤖/g, '')
          .replace(/⏱/g, 'Tiempo:')
          .replace(/📊/g, '')
          .replace(/📈/g, '')
          .replace(/📝/g, '')
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

    window.addEventListener("load", () => {
      cargarTemas();
    });
