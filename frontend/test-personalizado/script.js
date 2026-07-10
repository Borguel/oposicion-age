// Test Personalizado: basado en el temario oficial, requiere elegir al
// menos un tema. Misma lógica de generación/toma de test/resultados que
// las demás páginas de test (ver /test-generator/, /test-oficial/,
// /test-inteligente/), separada en su propia página para no mezclar el
// selector de tipo de test con el propio formulario de generación.
const TIPO_TEST = "personalizado";
const ENDPOINT_GENERAR = "/generar-test-avanzado";
const REQUIERE_TEMA = true;

async function obtenerAuthHeaders() {
      const { obtenerAuthHeaders: fn } = await import("/assets/auth.js");
      return fn();
    }

    let preguntas = [];
    let indicePreguntaActual = 0;
    let respuestasUsuario = [];
    // Preguntas marcadas con la banderita "revisar más tarde" y preguntas ya
    // visitadas en esta sesión (para distinguir en el navegador el gris de
    // "no visitada" del rojo de "visitada pero sin responder").
    let marcadasRevision = [];
    let visitadas = [];
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
    // Base de segundos ya transcurridos al reanudar un test SIN cronómetro
    // (se suma al tiempo real transcurrido en esta sesión del navegador para
    // que el contador siga sumando en vez de reiniciarse a 00:00).
    let tiempoTranscurridoBase = 0;
    // Textos de las preguntas ya marcadas como favoritas por el usuario en
    // esta oposición, cargados una vez al empezar/reanudar el test para
    // poder pintar la estrella ya activada sin una petición por pregunta.
    let oposicionActual = "";
    let textosFavoritas = new Set();
    let botonFavoritaHTML = () => "";
    let activarBotonFavorita = () => {};

    function tiempoTranscurridoActual() {
      if (tiempoLimite !== null) return tiempoTotalAsignado - tiempoLimite;
      return tiempoTranscurridoBase + Math.floor((Date.now() - tiempoInicio) / 1000);
    }

    document.addEventListener("DOMContentLoaded", function() {
      document.getElementById('modo_cronometrado').addEventListener('change', function() {
        document.getElementById('tiempo_cronometro').style.display = this.checked ? 'flex' : 'none';
      });
    });

    async function guardarTestAutomaticamente() {
      const contenido = preguntas;
      const respuestas = respuestasUsuario;
      const temas = Array.from(document.querySelectorAll('input[name="tema"]:checked')).map(el => el.value);
      const tiempo = tiempoTranscurridoActual();
      const metadatos = { tipo: TIPO_TEST, tiempo, temas };
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
        await renderizarSelectorTemas(contenedor, listaTemasGlobal, temasPreseleccionados);
      } catch (err) {
        contenedor.innerHTML = `<p>Error al cargar temas: ${err.message}</p>`;
        console.error(err);
      }
    }

    // tiempoRestanteReanudado: si se pasa (al reanudar un test cronometrado
    // guardado), se usa como tiempoLimite inicial en vez de recalcularlo
    // desde el campo "minutos_cronometro" del formulario (que al reanudar no
    // tiene por qué reflejar lo que se eligió la vez anterior) -- así el
    // cronómetro continúa en pausa desde donde se dejó, no se reinicia.
    // tiempoTranscurridoReanudado: equivalente para un test SIN cronómetro,
    // para que el contador de tiempo transcurrido siga sumando en vez de
    // volver a 00:00 al reanudar.
    function iniciarTemporizador(tiempoRestanteReanudado, tiempoTranscurridoReanudado) {
      tiempoInicio = Date.now();
      const elTemporizador = document.getElementById("temporizador");
      const elTexto = document.getElementById("temporizador-texto");
      elTemporizador.style.display = "flex";
      const botonToggle = document.getElementById("btn-toggle-temporizador");
      botonToggle.onclick = () => elTemporizador.classList.toggle("temporizador-oculto");
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
        if (TIPO_TEST !== "oficial") {
          document.getElementById("barra-progreso-tiempo").style.display = "block";
        }
        elTexto.innerHTML = `⏱ Tiempo restante: <span class="pulse">${formatearTiempo(tiempoLimite)}</span>`;
        elTemporizador.classList.toggle("temporizador-urgente", tiempoLimite <= 300);
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
          elTexto.innerHTML = `⏱ Tiempo restante: <span class="pulse">${formatearTiempo(tiempoLimite)}</span>`;
          // Últimos 5 minutos: aviso rojo con parpadeo suave (antes no había
          // ningún estado de urgencia real, solo un tono azul que no cambiaba
          // nada visualmente hasta el último minuto).
          elTemporizador.classList.toggle("temporizador-urgente", tiempoLimite <= 300);
          const porcentajeTiempo = ((tiempoTotalAsignado - tiempoLimite) / tiempoTotalAsignado) * 100;
          document.getElementById("progreso-tiempo").style.width = `${porcentajeTiempo}%`;
          const elTextoProgresoTiempo = document.getElementById("texto-progreso-tiempo");
          if (elTextoProgresoTiempo) elTextoProgresoTiempo.textContent = `${Math.round(porcentajeTiempo)}%`;
          // Autoguardado de progreso cada ~10s reales de cronómetro (no en
          // cada tick, para no saturar el backend).
          if (tiempoLimite % 10 === 0) {
            import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
              autoguardarProgreso({
                respuestas_usuario: respuestasUsuario,
                marcadas_revision: marcadasRevision,
                indice_actual: indicePreguntaActual,
                tiempo_restante_segundos: tiempoLimite
              });
            });
          }
        }, 1000);
      } else {
        tiempoTranscurridoBase = tiempoTranscurridoReanudado || 0;
        elTexto.textContent = `⏱ Tiempo: ${formatearTiempo(tiempoTranscurridoBase)}`;
        intervaloTemporizador = setInterval(() => {
          const transcurrido = tiempoTranscurridoActual();
          elTexto.textContent = `⏱ Tiempo: ${formatearTiempo(transcurrido)}`;
          if (transcurrido % 10 === 0) {
            import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
              autoguardarProgreso({
                respuestas_usuario: respuestasUsuario,
                marcadas_revision: marcadasRevision,
                indice_actual: indicePreguntaActual,
                tiempo_transcurrido_segundos: transcurrido
              });
            });
          }
        }, 1000);
      }
    }

    function formatearTiempo(segundos) {
      const m = String(Math.floor(segundos / 60)).padStart(2, '0');
      const s = String(segundos % 60).padStart(2, '0');
      return `${m}:${s}`;
    }

    // Metadatos fijos del test en curso (fijados al entrar en modo test),
    // reusados para los autoguardados en segundo plano mientras llegan más
    // preguntas -- /autosave-test sobrescribe el documento entero cuando
    // manda "contenido", así que cada guardado posterior debe repetirlos.
    let metadatosFijosTest = null;
    // Si el usuario termina el test (mostrarResultados) mientras el resto
    // de preguntas todavía se está generando en segundo plano, hay que
    // dejar de tocar el estado ya cerrado -- el stream SSE sigue leyéndose
    // hasta el final igualmente, pero sin efecto sobre la UI/autoguardado.
    let testFinalizado = false;

    function asignarTemaFallback(pregunta, temas) {
      if (!pregunta.tema_id && temas.length > 0) {
        pregunta.tema_id = temas[Math.floor(Math.random() * temas.length)];
      }
    }

    function mostrarIndicadorGenerandoFondo(completadas, total) {
      if (testFinalizado) return;
      let el = document.getElementById("indicador-generando-fondo");
      if (!el) {
        el = document.createElement("div");
        el.id = "indicador-generando-fondo";
        el.className = "indicador-generando-fondo";
        document.getElementById("navegador-preguntas").insertAdjacentElement("afterend", el);
      }
      const restantes = Math.max(total - completadas, 0);
      el.textContent = restantes > 0
        ? `⏳ Generando ${restantes} pregunta${restantes !== 1 ? "s" : ""} más en segundo plano...`
        : "⏳ Terminando de verificar el resto de preguntas...";
    }

    function ocultarIndicadorGenerandoFondo() {
      document.getElementById("indicador-generando-fondo")?.remove();
    }

    // Aviso NO bloqueante para cuando algo falla generando el resto de
    // preguntas en segundo plano -- el usuario ya está respondiendo el
    // test, así que un Swal/alert a pantalla completa (como en el resto de
    // errores de esta página) le interrumpiría innecesariamente. Reutiliza
    // el mismo hueco del indicador de "generando en segundo plano" durante
    // unos segundos.
    function mostrarErrorGlobalNoBloqueante(mensaje) {
      let el = document.getElementById("indicador-generando-fondo");
      if (!el) {
        el = document.createElement("div");
        el.id = "indicador-generando-fondo";
        document.getElementById("navegador-preguntas").insertAdjacentElement("afterend", el);
      }
      el.className = "indicador-generando-fondo indicador-generando-fondo-aviso";
      el.textContent = `⚠️ ${mensaje}`;
      setTimeout(() => el.remove(), 8000);
    }

    function guardarContenidoEnSegundoPlano() {
      if (!metadatosFijosTest) return;
      import("/assets/test-progreso.js").then(({ actualizarContenidoEnCurso }) => {
        actualizarContenidoEnCurso({
          ...metadatosFijosTest,
          contenido: preguntas,
          respuestas_usuario: respuestasUsuario,
          marcadas_revision: marcadasRevision,
          indice_actual: indicePreguntaActual,
          tiempo_restante_segundos: tiempoLimite,
          tiempo_transcurrido_segundos: tiempoTranscurridoActual()
        });
      });
    }

    // Añade una pregunta que ha terminado de generarse/verificarse DESPUÉS
    // de que el usuario ya haya empezado a responder (test de N>10
    // preguntas, ver entrarEnModoTest) -- siempre al final, para no
    // desalinear las respuestas ya dadas a las preguntas anteriores.
    function agregarPreguntaEnCurso(pregunta, temas) {
      if (testFinalizado) return;
      asignarTemaFallback(pregunta, temas);
      preguntas.push(pregunta);
      respuestasUsuario.push(null);
      marcadasRevision.push(false);
      visitadas.push(false);
      actualizarNavegadorPreguntas();
      guardarContenidoEnSegundoPlano();
    }

    // Arranca la pantalla de test con las preguntas ya disponibles --
    // llamada tanto en el camino "normal" (todas las preguntas listas, al
    // llegar "fin") como en el camino de inicio temprano (N>10, en cuanto
    // hay min(10, N) preguntas, ver el bucle de lectura del stream SSE más
    // abajo). A partir de aquí el stream puede seguir corriendo en segundo
    // plano sin que esto se vuelva a llamar.
    async function entrarEnModoTest(preguntasIniciales, oposicion, temas) {
      preguntas = preguntasIniciales;
      preguntas.forEach(p => asignarTemaFallback(p, temas));
      respuestasUsuario = Array(preguntas.length).fill(null);
      marcadasRevision = Array(preguntas.length).fill(false);
      visitadas = Array(preguntas.length).fill(false);
      indicePreguntaActual = 0;
      oposicionActual = oposicion;
      const favoritasApi = await import("/assets/favoritas.js");
      botonFavoritaHTML = favoritasApi.botonFavoritaHTML;
      activarBotonFavorita = favoritasApi.activarBotonFavorita;
      textosFavoritas = await favoritasApi.cargarTextosFavoritas(oposicion);

      const modoCronometrado = document.getElementById('modo_cronometrado').checked;
      const minutosCronometro = parseInt(document.getElementById('minutos_cronometro').value) || 60;
      metadatosFijosTest = {
        oposicion, tipo: TIPO_TEST, temas,
        modo_cronometrado: modoCronometrado,
        tiempo_total_asignado_segundos: modoCronometrado ? minutosCronometro * 60 : null,
        pagina_origen: "/test-personalizado/"
      };
      const { generarTestId, guardarContenidoInicial, activarGuardadoAlSalir } = await import("/assets/test-progreso.js");
      generarTestId();
      guardarContenidoInicial({
        ...metadatosFijosTest,
        contenido: preguntas,
        respuestas_usuario: respuestasUsuario,
        marcadas_revision: marcadasRevision,
        indice_actual: indicePreguntaActual,
        tiempo_restante_segundos: modoCronometrado ? minutosCronometro * 60 : null
      });
      activarGuardadoAlSalir(() => ({
        respuestas_usuario: respuestasUsuario,
        marcadas_revision: marcadasRevision,
        indice_actual: indicePreguntaActual,
        modo_cronometrado: tiempoLimite !== null,
        tiempo_restante_segundos: tiempoLimite,
        tiempo_transcurrido_segundos: tiempoTranscurridoActual()
      }));

      iniciarTemporizador();
      document.getElementById("navegador-preguntas").style.display = "flex";
      mostrarPregunta(indicePreguntaActual);
    }

    document.getElementById("form-generar-test").addEventListener("submit", async function(e) {
      e.preventDefault();
      document.getElementById("barra-progreso-tiempo").style.display = "none";
      const num_preguntas = parseInt(document.getElementById("num_preguntas").value);
      const temas = Array.from(document.querySelectorAll('input[name="tema"]:checked')).map(el => el.value);
      if (REQUIERE_TEMA && temas.length === 0) {
        Swal.fire({
          icon: "warning",
          title: "Selecciona un tema",
          text: "Debes elegir al menos un tema para continuar.",
          confirmButtonText: "Entendido"
        });
        return;
      }
      document.getElementById('tarjeta-formulario').style.display = "none";
      document.querySelector('.test-type-container')?.classList.add('test-type-compacto');
      document.getElementById("contenedor-test").style.display = "block";
      document.getElementById("contenedor-test").innerHTML = `
        <div class="carga-generando">
          <p id="mensaje-carga">Preparando la generación...</p>
          <div class="progress-container">
            <div id="progreso-generacion" class="progress-bar" style="background: linear-gradient(90deg, var(--age-primary), var(--age-primary-dark, var(--age-primary)));"></div>
            <div id="texto-progreso-generacion" class="progress-text">0%</div>
          </div>
        </div>
      `;

      // Punto 1: antes de que llegue el primer evento SSE real, el
      // backend está montando el hilo y repartiendo cupos (no es
      // instantáneo) -- sin esto la barra se queda clavada en 0% un rato
      // y da sensación de que la página se ha colgado. Sube el % poco a
      // poco de forma artificial, con un techo bajo, y se para en cuanto
      // llega el primer evento de progreso real.
      let progresoCosmetico = 0;
      let intervaloCosmetico = setInterval(() => {
        progresoCosmetico = Math.min(progresoCosmetico + Math.random() * 3, 15);
        const elBarraCosmetica = document.getElementById("progreso-generacion");
        const elTextoBarraCosmetica = document.getElementById("texto-progreso-generacion");
        if (elBarraCosmetica) elBarraCosmetica.style.width = `${progresoCosmetico}%`;
        if (elTextoBarraCosmetica) elTextoBarraCosmetica.textContent = `${Math.round(progresoCosmetico)}%`;
      }, 400);
      const pararProgresoCosmetico = () => {
        if (intervaloCosmetico) {
          clearInterval(intervaloCosmetico);
          intervaloCosmetico = null;
        }
      };

      try {
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) { pararProgresoCosmetico(); return; }
        const { obtenerOposicionActual } = await import("/assets/oposicion.js");
        const oposicion = obtenerOposicionActual();
        // Cada pregunta se ancla a un artículo real del temario y se
        // verifica con una segunda llamada independiente antes de
        // aceptarla (nunca se corrige una que falla, se descarta y se
        // reintenta desde cero) -- tarda bastante más que antes, así que
        // el backend va retransmitiendo el progreso real por streaming
        // (Server-Sent Events) en vez de una única respuesta de golpe.
        const res = await fetch("https://oposicion-age.onrender.com" + ENDPOINT_GENERAR, {
          method: "POST",
          headers: {"Content-Type": "application/json", ...authHeaders},
          body: JSON.stringify({ temas, num_preguntas, oposicion })
        });
        if (res.status === 403) {
          pararProgresoCosmetico();
          const datosError = await res.json();
          document.getElementById('contenedor-test').innerHTML = `
            <p>${datosError.error === "Requiere plan superior" ? `Este tipo de test requiere el plan <strong>${datosError.plan_requerido}</strong>.` : "No tienes acceso a esta función."}</p>
            <a class="btn btn-primary" href="/planes/">Ver planes</a>
          `;
          return;
        }
        if (res.status === 429) {
          pararProgresoCosmetico();
          const datosError = await res.json();
          document.getElementById('contenedor-test').innerHTML = `<p>⏳ ${datosError.error || "Has alcanzado el límite de uso de esta herramienta por ahora."}</p>`;
          return;
        }
        if (!res.ok || !res.body) {
          pararProgresoCosmetico();
          document.getElementById('contenedor-test').innerHTML = `
            <p>Error al generar el test. Vuelve a intentarlo en unos segundos.</p>
            <button type="button" class="btn btn-primary" id="btn-volver-a-intentar">Volver a intentar</button>
          `;
          document.getElementById('btn-volver-a-intentar').addEventListener('click', () => location.reload());
          return;
        }

        const lector = res.body.getReader();
        const decodificador = new TextDecoder();
        let buffer = "";
        let datosFinales = null;

        // Punto 2: para peticiones de más de 10 preguntas, en cuanto
        // llegan las primeras min(10, num_preguntas) ya aceptadas se deja
        // al usuario empezar a responder mientras el resto se sigue
        // generando en segundo plano -- la lectura del stream NO se
        // interrumpe al transicionar, sigue drenándose hasta "fin".
        let transicionadoATest = false;
        let preguntasRecibidas = [];
        const umbralInicioTemprano = Math.min(10, num_preguntas);
        let ultimoCompletadas = 0;
        let ultimoTotal = num_preguntas;

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
              ultimoCompletadas = evento.completadas;
              ultimoTotal = evento.total;
              if (!transicionadoATest) {
                const elMensajeCarga = document.getElementById("mensaje-carga");
                const elBarra = document.getElementById("progreso-generacion");
                const elTextoBarra = document.getElementById("texto-progreso-generacion");
                const porcentaje = evento.total ? Math.round((evento.completadas / evento.total) * 100) : 0;
                if (elBarra) elBarra.style.width = `${porcentaje}%`;
                if (elTextoBarra) elTextoBarra.textContent = `${porcentaje}%`;
                if (elMensajeCarga) {
                  elMensajeCarga.textContent = `Generando y verificando pregunta ${evento.completadas} de ${evento.total}...`;
                }
              } else {
                mostrarIndicadorGenerandoFondo(evento.completadas, evento.total);
              }
            } else if (evento.tipo === "pregunta" && evento.pregunta) {
              if (!transicionadoATest) {
                preguntasRecibidas.push(evento.pregunta);
                if (num_preguntas > 10 && preguntasRecibidas.length >= umbralInicioTemprano) {
                  transicionadoATest = true;
                  entrarEnModoTest(preguntasRecibidas, oposicion, temas).then(() => {
                    mostrarIndicadorGenerandoFondo(ultimoCompletadas, ultimoTotal);
                  });
                }
              } else {
                agregarPreguntaEnCurso(evento.pregunta, temas);
              }
            } else if (evento.tipo === "fin") {
              datosFinales = evento;
            }
          }
        }

        if (transicionadoATest) {
          // El usuario ya está haciendo el test -- "fin" solo sirve para
          // reconciliar el conjunto definitivo (por si el streaming
          // entregó alguna pregunta que agregarPreguntaEnCurso no llegó a
          // procesar) y avisar de forma NO intrusiva si algo falló, sin
          // interrumpir la pregunta que se esté viendo. Si el usuario ya
          // terminó el test antes de que llegara "fin", no hay nada que
          // reconciliar en la UI (el resultado ya se calculó y se guardó).
          if (testFinalizado) return;
          ocultarIndicadorGenerandoFondo();
          if (datosFinales && Array.isArray(datosFinales.test)) {
            for (let i = preguntas.length; i < datosFinales.test.length; i++) {
              agregarPreguntaEnCurso(datosFinales.test[i], temas);
            }
            if (datosFinales.advertencia) {
              mostrarErrorGlobalNoBloqueante(datosFinales.advertencia);
            }
          } else if (!datosFinales || datosFinales.error) {
            mostrarErrorGlobalNoBloqueante((datosFinales && datosFinales.error) || "Ha ocurrido un error terminando de generar el resto de preguntas.");
          }
          guardarContenidoEnSegundoPlano();
          return;
        }

        if (!datosFinales) {
          document.getElementById('contenedor-test').innerHTML = "<p>Error al generar el test. Vuelve a intentarlo.</p>";
          return;
        }
        const datos = datosFinales;
        if (!datos.test || datos.test.length === 0) {
          document.getElementById('contenedor-test').innerHTML = `<p>${datos.advertencia || datos.error || "No se han recibido preguntas."}</p>`;
          return;
        }
        await entrarEnModoTest(datos.test, oposicion, temas);
      } catch (error) {
        pararProgresoCosmetico();
        const contenedorTest = document.getElementById('contenedor-test');
        contenedorTest.innerHTML = `
          <p>Error al generar el test: ${error.message}</p>
          <button type="button" class="btn btn-primary" id="btn-volver-a-intentar">Volver a intentar</button>
        `;
        document.getElementById('btn-volver-a-intentar').addEventListener('click', () => location.reload());
        console.error(error);
      }
    });

    function actualizarNavegadorPreguntas() {
      const contenedor = document.getElementById("navegador-preguntas");
      if (!contenedor) return;
      import("/assets/navegador-preguntas.js").then(({ renderizarNavegadorPreguntas }) => {
        renderizarNavegadorPreguntas(contenedor, {
          total: preguntas.length,
          respuestasUsuario,
          visitadas,
          marcadasRevision,
          indiceActual: indicePreguntaActual,
          onSaltar: (idx) => mostrarPregunta(idx)
        });
      });
    }

    function mostrarPregunta(i) {
      indicePreguntaActual = i;
      visitadas[i] = true;
      actualizarNavegadorPreguntas();
      const p = preguntas[i];
      let textoPregunta = p.pregunta.replace(/^\s*\d+\s*[\.\)]\s*/, "");
      let html = `<form id="form-pregunta">
        <div class="pregunta-en-negrita">
          <span>${i + 1}. ${textoPregunta}</span>
          <div class="pregunta-acciones-header">
            ${botonFavoritaHTML(textosFavoritas.has(p.pregunta))}
            <button type="button" id="btn-marcar-revision" class="btn-marcar-revision${marcadasRevision[i] ? " activa" : ""}" aria-label="Marcar para revisión" title="Marcar para revisar más tarde">🔖</button>
          </div>
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
          <button type="submit" class="age-btn age-btn-primary">
            ${i + 1 < preguntas.length ? 'Siguiente →' : 'Finalizar test'}
          </button>
        </div>
      </form>`;
      document.getElementById("contenedor-test").innerHTML = html;
      activarBotonFavorita(document.getElementById("contenedor-test"), p, oposicionActual, textosFavoritas);
      document.getElementById("btn-marcar-revision").addEventListener("click", function() {
        marcadasRevision[i] = !marcadasRevision[i];
        this.classList.toggle("activa", marcadasRevision[i]);
        actualizarNavegadorPreguntas();
        import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
          autoguardarProgreso({
            respuestas_usuario: respuestasUsuario,
            marcadas_revision: marcadasRevision,
            indice_actual: i
          });
        });
      });
      document.querySelectorAll('input[name="respuesta"]').forEach((radio) => {
        radio.addEventListener("click", function() {
          // Si la opción pulsada ya era la marcada, un segundo clic la
          // desmarca y deja la pregunta en blanco -- más intuitivo que un
          // botón "Desmarcar" aparte para quien se equivoca al elegir.
          if (respuestasUsuario[i] === this.value) {
            this.checked = false;
            respuestasUsuario[i] = null;
          } else {
            respuestasUsuario[i] = this.value;
          }
          actualizarNavegadorPreguntas();
        });
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
          marcadas_revision: marcadasRevision,
          indice_actual: indicePreguntaActual,
          tiempo_restante_segundos: tiempoLimite,
          tiempo_transcurrido_segundos: tiempoTranscurridoActual()
        });
        window.location.href = "/mis-tests/";
      };
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
            marcadas_revision: marcadasRevision,
            indice_actual: i + 1 < preguntas.length ? i + 1 : i,
            tiempo_restante_segundos: tiempoLimite,
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

    let ultimasEstadisticas = null;

    async function mostrarResultados() {
      testFinalizado = true;
      ocultarIndicadorGenerandoFondo();
      clearInterval(intervaloTemporizador);
      if (tiempoLimite !== null) clearInterval(intervaloCronometro);
      document.getElementById("temporizador").style.display = "none";
      document.getElementById("barra-progreso-tiempo").style.display = "none";
      document.getElementById("navegador-preguntas").style.display = "none";
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
      marcadasRevision = Array.isArray(guardado.marcadas_revision) && guardado.marcadas_revision.length === preguntas.length
        ? guardado.marcadas_revision
        : Array(preguntas.length).fill(false);
      indicePreguntaActual = guardado.indice_actual || 0;
      // No se guarda un historial de "visitadas" -- se asume que se llegó
      // hasta indice_actual avanzando en orden, así que se marcan como
      // visitadas todas las preguntas hasta ahí.
      visitadas = Array(preguntas.length).fill(false);
      for (let k = 0; k <= indicePreguntaActual && k < visitadas.length; k++) visitadas[k] = true;
      const { obtenerOposicionActual } = await import("/assets/oposicion.js");
      oposicionActual = guardado.oposicion || obtenerOposicionActual();
      const favoritasApi = await import("/assets/favoritas.js");
      botonFavoritaHTML = favoritasApi.botonFavoritaHTML;
      activarBotonFavorita = favoritasApi.activarBotonFavorita;
      textosFavoritas = await favoritasApi.cargarTextosFavoritas(oposicionActual);

      document.getElementById('tarjeta-formulario').style.display = "none";
      document.querySelector('.test-type-container')?.classList.add('test-type-compacto');
      document.getElementById("contenedor-test").style.display = "block";

      if (guardado.modo_cronometrado) {
        document.getElementById('modo_cronometrado').checked = true;
        tiempoTotalAsignado = guardado.tiempo_total_asignado_segundos || guardado.tiempo_restante_segundos || 0;
        iniciarTemporizador(guardado.tiempo_restante_segundos ?? tiempoTotalAsignado);
      } else {
        iniciarTemporizador(null, guardado.tiempo_transcurrido_segundos || 0);
      }
      document.getElementById("navegador-preguntas").style.display = "flex";
      mostrarPregunta(indicePreguntaActual);
      activarGuardadoAlSalir(() => ({
        respuestas_usuario: respuestasUsuario,
        marcadas_revision: marcadasRevision,
        indice_actual: indicePreguntaActual,
        modo_cronometrado: tiempoLimite !== null,
        tiempo_restante_segundos: tiempoLimite,
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
