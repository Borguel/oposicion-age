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
        const { obtenerOposicionActual } = await import("/assets/oposicion.js");
        const res = await fetch("https://oposicion-age.onrender.com/generar-test-fallos", {
          method: "POST",
          headers: {"Content-Type": "application/json", ...authHeaders},
          body: JSON.stringify({ num_preguntas, oposicion: obtenerOposicionActual() })
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
        const { obtenerOposicionActual } = await import("/assets/oposicion.js");
        const res = await fetch("https://oposicion-age.onrender.com/guardar-test", {
          method: "POST",
          headers: {"Content-Type": "application/json", ...authHeaders},
          body: JSON.stringify({ contenido, respuestas, metadatos, oposicion: obtenerOposicionActual() })
        });

        const datos = await res.json();
        if (!res.ok) {
          console.error("Error al guardar test:", datos.error || "No se pudo guardar el test.");
        }
      } catch (e) {
        console.error("Error al guardar test falladas:", e);
      }
    }

    let ultimasEstadisticas = null;

    async function mostrarResultados() {
      clearInterval(intervaloTemporizador);
      document.getElementById("contenedor-test").innerHTML = "";
      document.getElementById("btn-finalizar").style.display = "none";
      const cont = document.getElementById("contenedor-resultados");
      cont.style.display = "block";

      const { renderizarResultadosTest } = await import("/assets/resultados-test.js");
      ultimasEstadisticas = renderizarResultadosTest({
        contenedor: cont,
        preguntas,
        respuestasUsuario,
        listaTemas: []
      });
      aciertos = ultimasEstadisticas.aciertos;
      fallos = ultimasEstadisticas.fallos;
      sinResponder = ultimasEstadisticas.sinResponder;
      porcentaje = ultimasEstadisticas.porcentaje;

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

    document.getElementById("btn-descargar-pdf").addEventListener("click", async () => {
      const { descargarResultadosPDF } = await import("/assets/resultados-test.js");
      descargarResultadosPDF({
        preguntas,
        respuestasUsuario,
        stats: ultimasEstadisticas,
        titulo: "Resultados: preguntas falladas",
        nombreArchivo: "test_falladas.pdf"
      });
    });
