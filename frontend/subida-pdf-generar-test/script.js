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
    let nombreArchivo = 'documento.pdf';
    let documentoIdActual = null;
    // Segundos ya transcurridos al reanudar un test guardado, para que el
    // contador siga sumando en vez de reiniciarse a 00:00.
    let tiempoTranscurridoBase = 0;

    // === FUNCIONES AUXILIARES ===
    function formatearTiempo(segundos) {
      const m = String(Math.floor(segundos / 60)).padStart(2, '0');
      const s = String(segundos % 60).padStart(2, '0');
      return `${m}:${s}`;
    }

    function tiempoTranscurridoActual() {
      return tiempoTranscurridoBase + Math.floor((Date.now() - tiempoInicio) / 1000);
    }

    function mostrarError(mensaje) {
      Swal.fire({
        icon: 'error',
        title: 'Error',
        text: mensaje,
        confirmButtonText: 'Entendido'
      });
      document.getElementById('tarjeta-formulario').style.display = 'block';
      document.getElementById('contenedor-carga').style.display = 'none';
    }

    // === TEMPORIZADOR ===
    function iniciarTemporizador(tiempoTranscurridoReanudado) {
      tiempoTranscurridoBase = tiempoTranscurridoReanudado || 0;
      tiempoInicio = Date.now();
      const temporizadorEl = document.getElementById("temporizador");
      temporizadorEl.style.display = "block";
      temporizadorEl.style.textAlign = "center";
      temporizadorEl.style.fontSize = "1.5rem";
      temporizadorEl.style.fontWeight = "bold";
      temporizadorEl.style.padding = "15px";
      temporizadorEl.style.margin = "20px 0";
      temporizadorEl.style.background = "linear-gradient(135deg, #d0ebff, #a5d8ff)";
      temporizadorEl.style.color = "#1c7ed6";
      temporizadorEl.style.borderRadius = "12px";
      temporizadorEl.style.boxShadow = "0 4px 10px rgba(0,0,0,0.1)";
      temporizadorEl.textContent = `⏱ Tiempo: ${formatearTiempo(tiempoTranscurridoBase)}`;
      intervaloTemporizador = setInterval(() => {
        const transcurrido = tiempoTranscurridoActual();
        temporizadorEl.textContent = `⏱ Tiempo: ${formatearTiempo(transcurrido)}`;
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
      const contenido = preguntas;
      const respuestas = respuestasUsuario;
      const tiempo = tiempoTranscurridoActual();

      const metadatos = {
        tipo: "test_pdf",
        tiempo: tiempo,
        nombreArchivo: nombreArchivo,
        origen: "Generar_test_pdf_html+js_1.3.UNIFICADO"
      };

      const { testIdEnCurso, limpiarSeguimiento } = await import("/assets/test-progreso.js");
      try {
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) return;
        const res = await fetch("https://oposicion-age.onrender.com/guardar-test-pdf", {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders },
          body: JSON.stringify({
            test_data: {
              preguntas: contenido,
              respuestas: respuestas,
              metadatos: metadatos
            },
            nombre_archivo: nombreArchivo,
            documento_id: documentoIdActual,
            // Si este test se autoguardó "en_progreso" mientras se hacía, el
            // backend borra ese borrador en cuanto queda guardado de verdad
            // como test_pdf -- no debe quedar como "en progreso" en ningún sitio.
            test_id: testIdEnCurso()
          })
        });

        const datos = await res.json();
        if (!res.ok) {
          console.warn("Test guardado: advertencia del backend", datos);
        } else {
          console.log("Test guardado exitosamente en Firebase");
          limpiarSeguimiento();
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

      nombreArchivo = archivo.name;
      const formData = new FormData();
      formData.append('pdf', archivo);
      formData.append('num_preguntas', num_preguntas);

      document.getElementById('tarjeta-formulario').style.display = 'none';
      document.getElementById('contenedor-carga').style.display = 'block';

      const textoEstado = document.getElementById('texto-estado');
      const aiIcon = document.getElementById('ai-icon');

      const mensajes = [
        { mensaje: "Leyendo texto del PDF…", icono: "📄" },
        { mensaje: "Extrayendo conceptos clave…", icono: "🔍" },
        { mensaje: "Analizando estructura del temario…", icono: "📊" },
        { mensaje: "Generando preguntas inteligentes…", icono: "🧠" },
        { mensaje: "Preparando test…", icono: "✅" }
      ];

      let datosIA = null;
      let errorIA = null;

      let indiceMensaje = 0;
      textoEstado.textContent = mensajes[0].mensaje;
      aiIcon.textContent = mensajes[0].icono;
      const intervaloMensajes = setInterval(() => {
        indiceMensaje = (indiceMensaje + 1) % mensajes.length;
        textoEstado.textContent = mensajes[indiceMensaje].mensaje;
        aiIcon.textContent = mensajes[indiceMensaje].icono;
      }, 2200);

      const authHeaders = await obtenerAuthHeaders();
      if (!authHeaders) { clearInterval(intervaloMensajes); return; }

      // Ejecutar la petición en segundo plano
      try {
        const res = await fetch("https://oposicion-age.onrender.com/generar-test-desde-pdf", {
          method: "POST",
          headers: authHeaders,
          body: formData
        });
        if (res.status === 403) {
          throw new Error("Necesitas iniciar sesión o mejorar de plan para usar esta herramienta. Ve a /planes/ para más información.");
        }
        if (!res.ok) {
          const errorData = await res.json().catch(() => ({}));
          throw new Error(errorData.error || `Error del servidor: ${res.status}`);
        }
        const datos = await res.json();
        if (!datos.test || datos.test.length === 0) {
          throw new Error(datos.error || "No se pudieron generar preguntas válidas desde el PDF.");
        }
        datosIA = datos;
      } catch (err) {
        errorIA = err;
      }

      clearInterval(intervaloMensajes);

      if (errorIA) {
        mostrarError(errorIA.message || "Error al generar el test.");
        return;
      }

      documentoIdActual = datosIA.documento_id || documentoIdActual;
      iniciarTest(datosIA.test);
    });

    async function iniciarTest(preguntasEntrada) {
      preguntas = preguntasEntrada || [];
      if (preguntas.length === 0) {
        mostrarError("No se generaron preguntas válidas.");
        return;
      }

      respuestasUsuario = Array(preguntas.length).fill(null);
      indicePreguntaActual = 0;
      document.getElementById('contenedor-carga').style.display = 'none';

      const { obtenerOposicionActual } = await import("/assets/oposicion.js");
      const { generarTestId, guardarContenidoInicial, activarGuardadoAlSalir } = await import("/assets/test-progreso.js");
      generarTestId();
      guardarContenidoInicial({
        oposicion: obtenerOposicionActual(), tipo: "test_pdf", temas: [],
        contenido: preguntas,
        respuestas_usuario: respuestasUsuario,
        indice_actual: indicePreguntaActual,
        pagina_origen: "/subida-pdf-generar-test/",
        documento_id: documentoIdActual
      });
      activarGuardadoAlSalir(() => ({
        respuestas_usuario: respuestasUsuario,
        indice_actual: indicePreguntaActual,
        tiempo_transcurrido_segundos: tiempoTranscurridoActual()
      }));

      iniciarTemporizador();
      actualizarBarraProgresoPreguntas();
      mostrarPregunta(indicePreguntaActual);
      document.getElementById('btn-finalizar').style.display = 'block';
    }

    // === Reanudar un test guardado "en_progreso" (llegado desde "Mis
    // Tests" con ?resume=<id>) ===
    (async function intentarReanudarTest() {
      const { idDesdeUrlResume, usarTestId, cargarTestEnProgreso, activarGuardadoAlSalir } = await import("/assets/test-progreso.js");
      const resumeId = idDesdeUrlResume();
      if (!resumeId) return;

      document.getElementById('tarjeta-formulario').style.display = 'none';
      document.getElementById('contenedor-carga').style.display = 'block';
      const textoEstado = document.getElementById('texto-estado');
      if (textoEstado) textoEstado.textContent = 'Cargando tu test guardado…';

      const guardado = await cargarTestEnProgreso(resumeId);
      if (!guardado || !guardado.contenido || !guardado.contenido.length) {
        mostrarError("No se ha encontrado ese test guardado.");
        return;
      }
      usarTestId(resumeId);
      nombreArchivo = guardado.nombre_archivo || nombreArchivo;
      documentoIdActual = guardado.documento_id || documentoIdActual;
      preguntas = guardado.contenido;
      respuestasUsuario = Array.isArray(guardado.respuestas_usuario) && guardado.respuestas_usuario.length === preguntas.length
        ? guardado.respuestas_usuario
        : Array(preguntas.length).fill(null);
      indicePreguntaActual = guardado.indice_actual || 0;

      document.getElementById('contenedor-carga').style.display = 'none';
      iniciarTemporizador(guardado.tiempo_transcurrido_segundos || 0);
      actualizarBarraProgresoPreguntas();
      mostrarPregunta(indicePreguntaActual);
      document.getElementById('btn-finalizar').style.display = 'block';
      activarGuardadoAlSalir(() => ({
        respuestas_usuario: respuestasUsuario,
        indice_actual: indicePreguntaActual,
        tiempo_transcurrido_segundos: tiempoTranscurridoActual()
      }));
    })();

    // === Llegar desde "Mis documentos" ===
    (async function inicializarDesdeDocumento() {
      const params = new URLSearchParams(window.location.search);
      const documentoId = params.get('documento_id');
      const ver = params.get('ver');
      if (!documentoId) return;

      documentoIdActual = documentoId;
      document.getElementById('tarjeta-formulario').style.display = 'none';
      document.getElementById('contenedor-carga').style.display = 'block';
      const textoEstado = document.getElementById('texto-estado');
      const aiIcon = document.getElementById('ai-icon');

      const authHeaders = await obtenerAuthHeaders();
      if (!authHeaders) return;

      if (ver === 'test') {
        textoEstado.textContent = 'Cargando tu test guardado…';
        try {
          const res = await fetch(`https://oposicion-age.onrender.com/documento/${documentoId}/test`, { headers: authHeaders });
          const datos = await res.json();
          if (!res.ok) throw new Error(datos.error || 'No se pudo cargar el test.');
          nombreArchivo = datos.nombre_archivo || nombreArchivo;
          iniciarTest(datos.test);
        } catch (err) {
          mostrarError(err.message);
        }
        return;
      }

      textoEstado.textContent = 'Generando test desde tu documento…';
      aiIcon.textContent = '🧠';
      try {
        const numPreguntas = parseInt(params.get('num_preguntas')) || 10;
        const formData = new FormData();
        formData.append('documento_id', documentoId);
        formData.append('num_preguntas', numPreguntas);
        const res = await fetch("https://oposicion-age.onrender.com/generar-test-desde-pdf", {
          method: "POST",
          headers: authHeaders,
          body: formData
        });
        if (res.status === 403) throw new Error("Necesitas iniciar sesión o mejorar de plan para usar esta herramienta. Ve a /planes/ para más información.");
        if (!res.ok) {
          const errorData = await res.json().catch(() => ({}));
          throw new Error(errorData.error || `Error del servidor: ${res.status}`);
        }
        const datos = await res.json();
        if (!datos.test || datos.test.length === 0) {
          throw new Error(datos.error || "No se pudieron generar preguntas válidas desde el PDF.");
        }
        nombreArchivo = datos.nombre_archivo || nombreArchivo;
        documentoIdActual = datos.documento_id || documentoIdActual;
        iniciarTest(datos.test);
      } catch (err) {
        mostrarError(err.message);
      }
    })();

    // === RENDERIZADO DE PREGUNTAS ===
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
        <button type="submit" class="age-btn age-btn-primary age-btn-block" style="margin-top:12px;">
          ${i + 1 < preguntas.length ? 'Siguiente →' : 'Finalizar test'}
        </button>
      </form>`;

      document.getElementById("contenedor-test").innerHTML = html;
      document.getElementById("contenedor-test").style.display = "block";

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
          tiempo_transcurrido_segundos: tiempoTranscurridoActual()
        });
        window.location.href = "/mis-tests/";
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

    // === RESULTADOS FINALES (módulo compartido con el resto de tests) ===
    let ultimasEstadisticas = null;

    async function mostrarResultados() {
      clearInterval(intervaloTemporizador);
      document.getElementById("temporizador").style.display = "none";
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
        listaTemas: []
      });
      aciertos = ultimasEstadisticas.aciertos;
      fallos = ultimasEstadisticas.fallos;
      sinResponder = ultimasEstadisticas.sinResponder;
      porcentaje = ultimasEstadisticas.porcentaje;

      document.getElementById("btn-descargar-pdf").style.display = "block";

      guardarTestEnBackend();
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
    document.getElementById("btn-descargar-pdf").addEventListener("click", async function() {
      const { descargarResultadosPDF } = await import("/assets/resultados-test.js");
      descargarResultadosPDF({
        preguntas,
        respuestasUsuario,
        stats: ultimasEstadisticas,
        titulo: "Resultados: test desde PDF",
        nombreArchivo: "resultados-test-pdf.pdf"
      });
    });
