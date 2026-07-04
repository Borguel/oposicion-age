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
          const labelListaTemas = document.getElementById("label-lista-temas");
          const tituloFormulario = document.getElementById("titulo-formulario");
          listaTemas.style.display = "grid";
          if (tipo === "oficial") {
            labelListaTemas.textContent = "Filtra por tema (opcional, deja todo sin marcar para todos los temas):";
            tituloFormulario.textContent = "Genera tu Test Oficial";
          } else {
            labelListaTemas.textContent = "Selecciona uno o varios temas:";
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
      const { testIdEnCurso, limpiarSeguimiento } = await import("/assets/test-progreso.js");
      try {
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) return;
        const { obtenerOposicionActual } = await import("/assets/oposicion.js");
        const oposicion = obtenerOposicionActual();
        const res = await fetch("https://oposicion-age.onrender.com/guardar-test", {
          method: "POST",
          headers: {"Content-Type": "application/json", ...authHeaders},
          // Se manda el mismo test_id que se usó para autoguardar el
          // progreso mientras se hacía: así el documento "en_progreso" se
          // sobrescribe con el resultado final en vez de quedar duplicado.
          body: JSON.stringify({ contenido, respuestas, metadatos, oposicion, test_id: testIdEnCurso() })
        });
        const datos = await res.json();
        if (!res.ok) {
          Swal.fire("Error al guardar", datos.error || "No se pudo guardar el test.", "error");
        } else {
          limpiarSeguimiento();
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
        // Si se llega desde el enlace "repasar tema flojo" de estadísticas
        // (?temas=id1,id2), se marcan esos temas para que el usuario solo
        // tenga que pulsar "Generar test".
        const temasPreseleccionados = new Set(
          (new URLSearchParams(window.location.search).get("temas") || "")
            .split(",").map(t => t.trim()).filter(Boolean)
        );
        const { renderizarSelectorTemas } = await import("/assets/temas-selector.js");
        renderizarSelectorTemas(contenedor, listaTemasGlobal, temasPreseleccionados);
      } catch (err) {
        contenedor.innerHTML = `<p>Error al cargar temas: ${err.message}</p>`;
        console.error(err);
      }
    }

    // tiempoRestanteReanudado: si se pasa (al reanudar un test guardado), se
    // usa como tiempoLimite inicial en vez de recalcularlo desde el campo
    // "minutos_cronometro" del formulario (que al reanudar no tiene por qué
    // reflejar lo que se eligió la vez anterior) -- así el cronómetro
    // continúa en pausa desde donde se dejó, no se reinicia.
    function iniciarTemporizador(tiempoRestanteReanudado) {
      tiempoInicio = Date.now();
      document.getElementById("temporizador").style.display = "block";
      if (document.getElementById('modo_cronometrado').checked) {
        if (tiempoRestanteReanudado == null) {
          const minutos = parseInt(document.getElementById('minutos_cronometro').value) || 60;
          tiempoLimite = minutos * 60;
          tiempoTotalAsignado = tiempoLimite;
        } else {
          tiempoLimite = tiempoRestanteReanudado;
          // tiempoTotalAsignado ya lo fija quien llama (restaurado del guardado)
        }
        // En los tests oficiales se oculta la barra verde de tiempo (queda
        // solo la azul de progreso de preguntas); el cronómetro en sí y su
        // texto de cuenta atrás siguen funcionando igual.
        const tipoActual = document.getElementById('tipo_test').value;
        if (tipoActual !== "oficial") {
          document.getElementById("barra-progreso-tiempo").style.display = "block";
        }
        document.getElementById("temporizador").innerHTML = `⏱ Tiempo restante: <span class="pulse">${formatearTiempo(tiempoLimite)}</span>`;
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
          const porcentajeTiempo = ((tiempoTotalAsignado - tiempoLimite) / tiempoTotalAsignado) * 100;
          document.getElementById("progreso-tiempo").style.width = `${porcentajeTiempo}%`;
          document.getElementById("texto-progreso-tiempo").textContent = `${Math.round(porcentajeTiempo)}%`;
          // Autoguardado de progreso cada ~10s reales de cronómetro (no en
          // cada tick, para no saturar el backend).
          if (tiempoLimite % 10 === 0) {
            import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
              autoguardarProgreso({
                respuestas_usuario: respuestasUsuario,
                indice_actual: indicePreguntaActual,
                tiempo_restante_segundos: tiempoLimite
              });
            });
          }
        }, 1000);
      } else {
        document.getElementById("temporizador").textContent = `⏱ Tiempo: ${formatearTiempo(0)}`;
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
      // Para "oficial" el tema es un filtro opcional (sin marcar ninguno =
      // todos los temas); para los demás tipos sigue siendo obligatorio
      // elegir al menos uno.
      const temas = Array.from(document.querySelectorAll('input[name="tema"]:checked')).map(el => el.value);
      if (tipo !== "oficial" && temas.length === 0) {
        Swal.fire({
          icon: "warning",
          title: "Selecciona un tema",
          text: "Debes elegir al menos un tema para continuar.",
          confirmButtonText: "Entendido"
        });
        return;
      }
      const endpoint = tipo === "oficial" ? "/generar-test-oficial" :
                      tipo === "inteligente" ? "/generar-test-inteligente" :
                      "/generar-test-avanzado";
      document.getElementById('tarjeta-formulario').style.display = "none";
      document.getElementById('titulo-formulario').style.display = "none";
      document.getElementById("contenedor-test").style.display = "block";
      document.getElementById("contenedor-test").innerHTML = `
        <div class="carga-generando">
          <p id="mensaje-carga">Obteniendo preguntas...</p>
          <div class="barra-indeterminada"><div class="barra-indeterminada-fill"></div></div>
        </div>
      `;
      const mensajes = [
        "Obteniendo preguntas...",
        "Generando opciones...",
        "Validando contenido...",
        "Preparando tu test..."
      ];
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

        const modoCronometrado = document.getElementById('modo_cronometrado').checked;
        const minutosCronometro = parseInt(document.getElementById('minutos_cronometro').value) || 60;
        const { generarTestId, guardarContenidoInicial, activarGuardadoAlSalir } = await import("/assets/test-progreso.js");
        generarTestId();
        guardarContenidoInicial({
          oposicion, tipo, temas,
          contenido: preguntas,
          respuestas_usuario: respuestasUsuario,
          indice_actual: indicePreguntaActual,
          modo_cronometrado: modoCronometrado,
          tiempo_restante_segundos: modoCronometrado ? minutosCronometro * 60 : null,
          tiempo_total_asignado_segundos: modoCronometrado ? minutosCronometro * 60 : null,
          pagina_origen: "/test-generator/"
        });
        activarGuardadoAlSalir(() => ({
          respuestas_usuario: respuestasUsuario,
          indice_actual: indicePreguntaActual,
          modo_cronometrado: tiempoLimite !== null,
          tiempo_restante_segundos: tiempoLimite
        }));

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
      let html = `<form id="form-pregunta">
        <div class="pregunta-en-negrita">${i + 1}. ${textoPregunta}</div>`;
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
          <button type="button" id="btn-guardar-salir" class="age-btn age-btn-outline">💾 Guardar y salir</button>
        </div>
        <button type="submit" class="age-btn age-btn-primary age-btn-block" style="margin-top: 12px;">
          ${i + 1 < preguntas.length ? 'Siguiente →' : 'Finalizar test'}
        </button>
      </form>`;
      document.getElementById("contenedor-test").innerHTML = html;
      document.getElementById("btn-desmarcar").addEventListener("click", () => {
        const marcadas = document.querySelectorAll('input[name="respuesta"]:checked');
        marcadas.forEach(m => m.checked = false);
        respuestasUsuario[i] = null;
      });
      document.getElementById("btn-guardar-salir").addEventListener("click", async function() {
        const boton = this;
        boton.disabled = true;
        boton.textContent = "Guardando…";
        const { guardarProgresoInmediato } = await import("/assets/test-progreso.js");
        await guardarProgresoInmediato({
          respuestas_usuario: respuestasUsuario,
          indice_actual: indicePreguntaActual,
          tiempo_restante_segundos: tiempoLimite
        });
        window.location.href = "/mis-tests/";
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
        import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
          autoguardarProgreso({
            respuestas_usuario: respuestasUsuario,
            indice_actual: i + 1 < preguntas.length ? i + 1 : i,
            tiempo_restante_segundos: tiempoLimite
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

    let ultimasEstadisticas = null;

    async function mostrarResultados() {
      clearInterval(intervaloTemporizador);
      if (tiempoLimite !== null) clearInterval(intervaloCronometro);
      document.getElementById("temporizador").style.display = "none";
      document.getElementById("barra-progreso-tiempo").style.display = "none";
      document.getElementById("barra-progreso-preguntas").style.display = "none";
      document.getElementById("contenedor-test").innerHTML = "";
      document.getElementById("contenedor-test").style.display = "none";
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

    // Reanuda un test guardado "en_progreso" (llegado desde "Mis Tests" con
    // ?resume=<id>) exactamente donde se dejó: mismas preguntas, mismas
    // respuestas ya marcadas, misma pregunta actual y -- si era
    // cronometrado -- el cronómetro continúa desde los segundos restantes
    // guardados la última vez, no se reinicia por reloj real transcurrido.
    async function reanudarTest(resumeId) {
      const { usarTestId, cargarTestEnProgreso, activarGuardadoAlSalir } = await import("/assets/test-progreso.js");
      const guardado = await cargarTestEnProgreso(resumeId);
      if (!guardado || !guardado.contenido || !guardado.contenido.length) {
        Swal.fire({
          icon: 'error',
          title: 'No se pudo reanudar',
          text: 'No se ha encontrado ese test guardado.',
          confirmButtonText: 'Entendido'
        });
        return;
      }
      usarTestId(resumeId);
      preguntas = guardado.contenido;
      respuestasUsuario = Array.isArray(guardado.respuestas_usuario) && guardado.respuestas_usuario.length === preguntas.length
        ? guardado.respuestas_usuario
        : Array(preguntas.length).fill(null);
      indicePreguntaActual = guardado.indice_actual || 0;
      document.getElementById('tipo_test').value = guardado.tipo || "personalizado";

      document.getElementById('tarjeta-formulario').style.display = "none";
      document.getElementById('titulo-formulario').style.display = "none";
      document.getElementById("contenedor-test").style.display = "block";

      if (guardado.modo_cronometrado) {
        document.getElementById('modo_cronometrado').checked = true;
        tiempoTotalAsignado = guardado.tiempo_total_asignado_segundos || guardado.tiempo_restante_segundos || 0;
        iniciarTemporizador(guardado.tiempo_restante_segundos ?? tiempoTotalAsignado);
      } else {
        iniciarTemporizador();
      }
      document.getElementById("barra-progreso-preguntas").style.display = "block";
      actualizarBarraProgresoPreguntas();
      mostrarPregunta(indicePreguntaActual);
      activarGuardadoAlSalir(() => ({
        respuestas_usuario: respuestasUsuario,
        indice_actual: indicePreguntaActual,
        modo_cronometrado: tiempoLimite !== null,
        tiempo_restante_segundos: tiempoLimite
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
