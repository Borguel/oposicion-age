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
    // Segundos ya transcurridos al reanudar un test guardado, para que el
    // contador siga sumando en vez de reiniciarse a 00:00.
    let tiempoTranscurridoBase = 0;
    let oposicionActual = "";
    let textosFavoritas = new Set();
    let botonFavoritaHTML = () => "";
    let activarBotonFavorita = () => {};

    function tiempoTranscurridoActual() {
      return tiempoTranscurridoBase + Math.floor((Date.now() - tiempoInicio) / 1000);
    }

    let listaTemasGlobal = [];

    function mostrarAviso(texto) {
      const aviso = document.getElementById('aviso-falladas');
      aviso.innerText = texto;
      aviso.style.display = 'block';
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
        const { renderizarSelectorTemas } = await import("/assets/temas-selector.js");
        await renderizarSelectorTemas(contenedor, listaTemasGlobal);
      } catch (err) {
        contenedor.innerHTML = `<p>Error al cargar temas: ${err.message}</p>`;
        console.error(err);
      }
    }

    function iniciarTemporizador(tiempoTranscurridoReanudado) {
      tiempoTranscurridoBase = tiempoTranscurridoReanudado || 0;
      tiempoInicio = Date.now();
      document.getElementById("temporizador").style.display = "block";
      document.getElementById("temporizador").textContent = `⏱ Tiempo: ${formatearTiempo(tiempoTranscurridoBase)}`;
      intervaloTemporizador = setInterval(() => {
        const transcurrido = tiempoTranscurridoActual();
        document.getElementById("temporizador").textContent = `⏱ Tiempo: ${formatearTiempo(transcurrido)}`;
        if (transcurrido % 10 === 0) {
          import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
            autoguardarProgreso({
              respuestas_usuario: respuestasUsuario,
              indice_actual: indicePreguntaActual,
              tiempo_transcurrido_segundos: transcurrido
            });
          });
        }
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
      const temas = Array.from(document.querySelectorAll('input[name="tema"]:checked')).map(el => el.value);
      document.getElementById('tarjeta-formulario').style.display = "none";
      document.getElementById('titulo-formulario').style.display = "none";
      document.getElementById('aviso-falladas').style.display = "none";

      document.getElementById("contenedor-test").style.display = "block";
      document.getElementById("contenedor-test").innerHTML = `
        <div class="carga-generando">
          <p id="mensaje-carga">Buscando tus preguntas falladas...</p>
          <div class="barra-indeterminada"><div class="barra-indeterminada-fill"></div></div>
        </div>
      `;

      const mensajes = ["Buscando tus preguntas falladas...", "Cargando contenido...", "Preparando el test..."];
      let indiceMensaje = 0;
      const intervalCarga = setInterval(() => {
        indiceMensaje = (indiceMensaje + 1) % mensajes.length;
        const elMensaje = document.getElementById("mensaje-carga");
        if (elMensaje) elMensaje.textContent = mensajes[indiceMensaje];
      }, 2200);

      try {
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) { clearInterval(intervalCarga); return; }
        const { obtenerOposicionActual } = await import("/assets/oposicion.js");
        const res = await fetch("https://oposicion-age.onrender.com/generar-test-fallos", {
          method: "POST",
          headers: {"Content-Type": "application/json", ...authHeaders},
          body: JSON.stringify({ num_preguntas, temas, oposicion: obtenerOposicionActual() })
        });

        clearInterval(intervalCarga);
        const datos = await res.json();
        preguntas = datos.test || [];

        if (preguntas.length === 0) {
          mostrarAviso(datos.mensaje || "No tienes preguntas falladas pendientes en tu cuenta. Haz algún test y vuelve aquí para repasarlas.");
          document.getElementById("contenedor-test").innerHTML = "";
          document.getElementById("contenedor-test").style.display = "none";
          document.getElementById('tarjeta-formulario').style.display = "";
          document.getElementById('titulo-formulario').style.display = "";
          return;
        }

        if (datos.mensaje) {
          await Swal.fire({
            icon: "info",
            title: "Menos preguntas de las pedidas",
            text: datos.mensaje,
            confirmButtonText: "Empezar de todas formas"
          });
        }

        respuestasUsuario = Array(preguntas.length).fill(null);
        indicePreguntaActual = 0;
        oposicionActual = obtenerOposicionActual();
        const favoritasApi = await import("/assets/favoritas.js");
        botonFavoritaHTML = favoritasApi.botonFavoritaHTML;
        activarBotonFavorita = favoritasApi.activarBotonFavorita;
        textosFavoritas = await favoritasApi.cargarTextosFavoritas(oposicionActual);

        const { generarTestId, guardarContenidoInicial, activarGuardadoAlSalir } = await import("/assets/test-progreso.js");
        generarTestId();
        guardarContenidoInicial({
          oposicion: obtenerOposicionActual(), tipo: "falladas", temas,
          contenido: preguntas,
          respuestas_usuario: respuestasUsuario,
          indice_actual: indicePreguntaActual,
          pagina_origen: "/preguntas-falladas/"
        });
        activarGuardadoAlSalir(() => ({
          respuestas_usuario: respuestasUsuario,
          indice_actual: indicePreguntaActual,
          tiempo_transcurrido_segundos: tiempoTranscurridoActual()
        }));

        iniciarTemporizador();

        document.getElementById("barra-progreso-preguntas").style.display = "block";
        actualizarBarraProgresoPreguntas();

        mostrarPregunta(indicePreguntaActual);
      } catch (error) {
        clearInterval(intervalCarga);
        mostrarAviso("❌ Error buscando preguntas falladas. Intenta más tarde.");
        document.getElementById("contenedor-test").innerHTML = "";
        document.getElementById("contenedor-test").style.display = "none";
        document.getElementById('tarjeta-formulario').style.display = "";
        document.getElementById('titulo-formulario').style.display = "";
        console.error(error);
      }
    });

    function mostrarPregunta(i) {
      indicePreguntaActual = i;
      actualizarBarraProgresoPreguntas();

      const p = preguntas[i];
      let html = `<form id="form-pregunta">
        <div class="pregunta-en-negrita">
          <span>${i + 1}. ${p.pregunta}</span>
          ${botonFavoritaHTML(textosFavoritas.has(p.pregunta))}
        </div>`;

      for (const letra in p.opciones) {
        const opcion = p.opciones[letra];
        const checked = respuestasUsuario[i] === letra ? "checked" : "";
        html += `
          <label class="opcion-respuesta">
            <input type="radio" name="respuesta" value="${letra}" ${checked}>
            <span class="opcion-letra">${letra}</span>
            <span class="opcion-texto">${opcion}</span>
          </label>`;
      }

      html += `
        <div class="botones-navegacion-test">
          ${i > 0 ? '<button type="button" id="btn-anterior" class="age-btn age-btn-outline">← Anterior</button>' : ''}
          <button type="button" id="btn-desmarcar" class="age-btn age-btn-outline">Desmarcar</button>
        </div>
        <button type="submit" class="age-btn age-btn-primary age-btn-block" style="margin-top:12px;">
          ${i + 1 < preguntas.length ? 'Siguiente →' : 'Finalizar test'}
        </button>
      </form>`;

      document.getElementById("contenedor-test").innerHTML = html;
      activarBotonFavorita(document.getElementById("contenedor-test"), p, oposicionActual, textosFavoritas);
      document.getElementById("btn-desmarcar").addEventListener("click", () => {
        const marcadas = document.querySelectorAll('input[name="respuesta"]:checked');
        marcadas.forEach(m => m.checked = false);
        respuestasUsuario[i] = null;
      });
      const botonGuardarSalir = document.getElementById("btn-guardar-salir");
      botonGuardarSalir.style.display = "block";
      botonGuardarSalir.disabled = false;
      botonGuardarSalir.textContent = "💾 Guardar y salir";
      botonGuardarSalir.onclick = async function() {
        const boton = this;
        boton.disabled = true;
        boton.textContent = "Guardando…";
        const { guardarProgresoInmediato } = await import("/assets/test-progreso.js");
        await guardarProgresoInmediato({
          respuestas_usuario: respuestasUsuario,
          indice_actual: indicePreguntaActual,
          tiempo_transcurrido_segundos: tiempoTranscurridoActual()
        });
        window.location.href = "/mis-tests/";
      };

      document.getElementById("btn-finalizar").style.display = "block";
      
      if (i > 0 && document.getElementById("btn-anterior")) {
        document.getElementById("btn-anterior").addEventListener("click", () => mostrarPregunta(i - 1));
      }
      
      document.getElementById("form-pregunta").addEventListener("submit", function(e) {
        e.preventDefault();
        const seleccion = document.querySelector('input[name="respuesta"]:checked');
        const respuestaSeleccionada = seleccion ? seleccion.value : null;
        respuestasUsuario[i] = respuestaSeleccionada;
        import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
          autoguardarProgreso({
            respuestas_usuario: respuestasUsuario,
            indice_actual: i + 1 < preguntas.length ? i + 1 : i,
            tiempo_transcurrido_segundos: tiempoTranscurridoActual()
          });
        });

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
      const tiempo = tiempoTranscurridoActual();
      const metadatos = { tipo, tiempo };
      const { testIdEnCurso, limpiarSeguimiento } = await import("/assets/test-progreso.js");

      try {
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) return;
        const { obtenerOposicionActual } = await import("/assets/oposicion.js");
        const res = await fetch("https://oposicion-age.onrender.com/guardar-test", {
          method: "POST",
          headers: {"Content-Type": "application/json", ...authHeaders},
          body: JSON.stringify({ contenido, respuestas, metadatos, oposicion: obtenerOposicionActual(), test_id: testIdEnCurso() })
        });

        const datos = await res.json();
        if (!res.ok) {
          console.error("Error al guardar test:", datos.error || "No se pudo guardar el test.");
        } else {
          limpiarSeguimiento();
        }
      } catch (e) {
        console.error("Error al guardar test falladas:", e);
      }
    }

    let ultimasEstadisticas = null;

    async function mostrarResultados() {
      clearInterval(intervaloTemporizador);
      document.getElementById("temporizador").style.display = "none";
      document.getElementById("barra-progreso-preguntas").style.display = "none";
      document.getElementById("contenedor-test").innerHTML = "";
      document.getElementById("contenedor-test").style.display = "none";
      document.getElementById("btn-finalizar").style.display = "none";
      document.getElementById("btn-guardar-salir").style.display = "none";
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

    async function reanudarTest(resumeId) {
      const { usarTestId, cargarTestEnProgreso, activarGuardadoAlSalir } = await import("/assets/test-progreso.js");
      const guardado = await cargarTestEnProgreso(resumeId);
      if (!guardado || !guardado.contenido || !guardado.contenido.length) {
        mostrarAviso("No se ha encontrado ese test guardado.");
        return;
      }
      usarTestId(resumeId);
      preguntas = guardado.contenido;
      respuestasUsuario = Array.isArray(guardado.respuestas_usuario) && guardado.respuestas_usuario.length === preguntas.length
        ? guardado.respuestas_usuario
        : Array(preguntas.length).fill(null);
      indicePreguntaActual = guardado.indice_actual || 0;
      const { obtenerOposicionActual } = await import("/assets/oposicion.js");
      oposicionActual = guardado.oposicion || obtenerOposicionActual();
      const favoritasApi = await import("/assets/favoritas.js");
      botonFavoritaHTML = favoritasApi.botonFavoritaHTML;
      activarBotonFavorita = favoritasApi.activarBotonFavorita;
      textosFavoritas = await favoritasApi.cargarTextosFavoritas(oposicionActual);

      document.getElementById('tarjeta-formulario').style.display = "none";
      document.getElementById('titulo-formulario').style.display = "none";
      document.getElementById("contenedor-test").style.display = "block";

      iniciarTemporizador(guardado.tiempo_transcurrido_segundos || 0);
      document.getElementById("barra-progreso-preguntas").style.display = "block";
      actualizarBarraProgresoPreguntas();
      mostrarPregunta(indicePreguntaActual);
      activarGuardadoAlSalir(() => ({
        respuestas_usuario: respuestasUsuario,
        indice_actual: indicePreguntaActual,
        tiempo_transcurrido_segundos: tiempoTranscurridoActual()
      }));
    }

    window.addEventListener("load", async () => {
      await cargarTemas();
      const { idDesdeUrlResume } = await import("/assets/test-progreso.js");
      const resumeId = idDesdeUrlResume();
      if (resumeId) {
        reanudarTest(resumeId);
      }
    });
