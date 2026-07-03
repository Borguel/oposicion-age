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

    let ultimasEstadisticas = null;

    async function mostrarResultados() {
      clearInterval(intervaloTemporizador);
      if (tiempoLimite !== null) clearInterval(intervaloCronometro);
      document.getElementById("barra-progreso-tiempo").style.display = "none";
      document.getElementById("barra-progreso-preguntas").style.display = "none";
      document.getElementById("contenedor-test").innerHTML = "";
      document.getElementById("btn-finalizar").style.display = "none";
      const cont = document.getElementById("contenedor-resultados");
      cont.style.display = "block";

      const { renderizarResultadosTest } = await import("/assets/resultados-test.js");
      ultimasEstadisticas = renderizarResultadosTest({
        contenedor: cont,
        preguntas,
        respuestasUsuario,
        listaTemas: listaTemasGlobal
      });
      aciertos = ultimasEstadisticas.aciertos;
      fallos = ultimasEstadisticas.fallos;
      sinResponder = ultimasEstadisticas.sinResponder;
      porcentaje = ultimasEstadisticas.porcentaje;

      document.getElementById("btn-descargar-pdf").style.display = "block";
      guardarTestAutomaticamente();
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

    document.getElementById("btn-descargar-pdf").addEventListener("click", async function() {
      const { descargarResultadosPDF } = await import("/assets/resultados-test.js");
      descargarResultadosPDF({
        preguntas,
        respuestasUsuario,
        stats: ultimasEstadisticas,
        titulo: "Resultados del Test"
      });
    });

    window.addEventListener("load", () => {
      cargarTemas();
    });
