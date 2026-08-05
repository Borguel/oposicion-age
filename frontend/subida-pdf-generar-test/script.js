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

    let preguntas = [];
    let indicePreguntaActual = 0;
    let respuestasUsuario = [];
    // Preguntas marcadas con la banderita "revisar más tarde" y "duda", y
    // preguntas ya visitadas en esta sesión (para distinguir en el
    // navegador el gris de "no visitada" del rojo de "visitada pero sin
    // responder") -- mismo mecanismo que el resto de páginas de test.
    let marcadasRevision = [];
    let marcadasDuda = [];
    let visitadas = [];
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
    let oposicionActual = "";
    let textosFavoritas = new Set();
    let botonFavoritaHTML = () => "";
    let activarBotonFavorita = () => {};

    // === FUNCIONES AUXILIARES ===
    function formatearTiempo(segundos) {
      const m = String(Math.floor(segundos / 60)).padStart(2, '0');
      const s = String(segundos % 60).padStart(2, '0');
      return `${m}:${s}`;
    }

    function tiempoTranscurridoActual() {
      return tiempoTranscurridoBase + Math.floor((Date.now() - tiempoInicio) / 1000);
    }

    // Aviso NO bloqueante para cuando se generaron menos preguntas de las
    // pedidas (documento corto/repetitivo para tantas preguntas distintas,
    // ver blueprints/pdf_ia.py) -- el test sigue arrancando con las que sí
    // se generaron, pero el usuario debe saber que fueron menos de las
    // solicitadas en vez de asumir que pidió menos.
    function avisarSiPreguntasIncompletas(datosFinales) {
      if (!datosFinales.advertencia) return;
      Swal.fire({
        toast: true,
        position: 'top-end',
        icon: 'info',
        title: datosFinales.advertencia,
        showConfirmButton: false,
        timer: 6000,
        timerProgressBar: true,
      });
    }

    function mostrarError(mensaje) {
      Swal.fire({
        icon: 'error',
        title: 'Error',
        // html en vez de text: los mensajes de plan insuficiente/límite
        // agotado incluyen un enlace real a /planes/ (ver más abajo). El
        // resto de mensajes son texto plano nuestro (nunca contenido del
        // PDF subido), así que no hay riesgo de inyectar HTML ajeno aquí.
        html: mensaje,
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

    // === MAPA DE PREGUNTAS (mismo componente compartido que el resto de tests) ===
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
            oposicion: oposicionActual,
            marcadas_duda: marcadasDuda,
            // Este mismo test_id ya se autoguardó "en_progreso" mientras se
            // hacía el test -- el backend lo reutiliza para convertirlo en
            // el registro final (con respuestas, aciertos y nota), igual
            // que el resto de tipos de test, en vez de un borrador aparte.
            test_id: testIdEnCurso()
          })
        });

        const datos = await res.json();
        if (!res.ok) {
          console.warn("Test guardado: advertencia del backend", datos);
          const { mostrarErrorGlobal } = await import("/assets/notificaciones.js");
          mostrarErrorGlobal("No se pudo guardar el resultado de tu test en tu cuenta. Tus respuestas siguen visibles en pantalla, pero no han quedado guardadas.");
        } else {
          console.log("Test guardado exitosamente en Firebase");
          limpiarSeguimiento();
        }
      } catch (e) {
        console.error("Error al guardar test en backend:", e);
        const { mostrarErrorGlobal } = await import("/assets/notificaciones.js");
        mostrarErrorGlobal("No se pudo guardar el resultado de tu test en tu cuenta. Tus respuestas siguen visibles en pantalla, pero no han quedado guardadas.");
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

    // Espera 'ms' como mínimo junto a 'promesa' -- para que el mensaje de
    // "te llevamos a Mis documentos" (ver mostrarRedireccionAMisDocumentos)
    // no aparezca y desaparezca demasiado rápido en una respuesta de
    // servidor muy veloz, sin que el usuario llegue a leerlo.
    function conEsperaMinima(promesa, ms) {
      return Promise.all([promesa, new Promise((resolve) => setTimeout(resolve, ms))]).then(([resultado]) => resultado);
    }

    // Sustituye el formulario por un aviso de que la generación ya ha
    // arrancado en el servidor y de que el resto del progreso se sigue
    // desde "Mis documentos" -- 03/08/2026, decisión explícita del
    // usuario: el banco completo (hasta 100 preguntas) puede tardar varios
    // minutos, y nadie va a quedarse esperando en esta pantalla con una
    // barra de progreso. Barra INDETERMINADA (no numérica): esta página ya
    // no sigue el streaming de progreso, así que no hay un % real que
    // mostrar aquí.
    function mostrarRedireccionAMisDocumentos() {
      document.getElementById('tarjeta-formulario').style.display = 'none';
      document.getElementById('contenedor-carga').style.display = 'block';
      document.getElementById('ai-icon').innerHTML = icono('cerebro', 32);
      document.getElementById('texto-estado').textContent = 'Nos ponemos a generar las preguntas de tu documento…';
      const detalle = document.getElementById('texto-estado-detalle');
      detalle.textContent = 'Puede tardar unos minutos según lo largo que sea el documento. Te llevamos a "Mis documentos" para que veas cómo van apareciendo, sin tener que esperar aquí.';
      detalle.classList.remove('hidden');
      document.getElementById('progress-container-numerico').classList.add('hidden');
      document.getElementById('barra-indeterminada-redireccion').classList.remove('hidden');
      document.getElementById('enlace-ir-a-mis-documentos').classList.remove('hidden');
      document.getElementById('sugerencia-mientras-tanto').classList.remove('hidden');
    }

    // Dispara la generación del banco completo de preguntas y devuelve en
    // cuanto el servidor confirma que ha arrancado (cabeceras de la
    // respuesta), SIN esperar a que termine -- generar_banco_preguntas_
    // desde_pdf (blueprints/pdf_ia.py) ya deja el banco creado en
    // Firestore con estado "generando" ANTES de mandar ni un byte de
    // respuesta, así que en cuanto esta petición resuelve es seguro
    // redirigir a "Mis documentos": el hilo de fondo del servidor sigue
    // generando y persistiendo cada pregunta aceptada aunque esta pestaña
    // se cierre justo después (mismo principio que ya usan el resto de
    // rutas de generación desde PDF, ver el comentario largo en
    // blueprints/pdf_ia.py).
    // Devuelve el documento_id en cuanto llega el evento "inicio" (ver el
    // comentario largo en blueprints/pdf_ia.py) -- se lee solo lo justo
    // del stream para capturarlo, con un tope de lecturas por si acaso, y
    // se abandona el resto (el resto de la generación se sigue desde "Mis
    // documentos"). null si por lo que sea no llega a tiempo -- el
    // llamante debe poder redirigir igualmente sin él.
    async function iniciarGeneracionBancoPreguntas(formData, authHeaders) {
      const res = await fetch("https://oposicion-age.onrender.com/generar-banco-preguntas-desde-pdf", {
        method: "POST",
        headers: authHeaders,
        body: formData
      });
      if (res.status === 403) {
        throw new Error('Necesitas iniciar sesión o mejorar de plan para usar esta herramienta. <a href="/planes/">Ver planes</a>');
      }
      if (res.status === 409) {
        throw new Error('Ya se está generando el banco de preguntas de este documento. Consulta el progreso en "Mis documentos".');
      }
      if (res.status === 429) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(`${errorData.error || "Has alcanzado el límite de uso de esta herramienta por ahora."} <a href="/planes/">Ver planes</a>`);
      }
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.error || `Error del servidor: ${res.status}`);
      }
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
        // No se lee el resto del stream: el progreso a partir de aquí se
        // sigue desde "Mis documentos" (ver mis-documentos/script.js), que
        // sondea el estado del banco en vez de mantener esta conexión
        // abierta.
        lector.cancel().catch(() => {});
      }
      return documentoId;
    }

    // === ENVÍO DE FORMULARIO ===
    // Si documentoIdActual ya está fijado (llegada desde "Mis documentos"
    // para generar preguntas NUEVAS, ver inicializarDesdeDocumento más
    // abajo) no hace falta volver a subir el PDF -- se manda el
    // documento_id ya existente directamente.
    document.getElementById('form-subir-pdf').addEventListener('submit', async function(e) {
      e.preventDefault();
      const formData = new FormData();

      if (documentoIdActual) {
        formData.append('documento_id', documentoIdActual);
      } else {
        const archivo = document.getElementById('archivo-pdf').files[0];
        if (!archivo) return mostrarError('Selecciona un archivo PDF.');
        if (archivo.type !== 'application/pdf') return mostrarError('El archivo debe ser un PDF.');
        nombreArchivo = archivo.name;
        formData.append('pdf', archivo);
      }

      mostrarRedireccionAMisDocumentos();

      const authHeaders = await obtenerAuthHeaders();
      if (!authHeaders) return;

      try {
        const documentoId = await conEsperaMinima(iniciarGeneracionBancoPreguntas(formData, authHeaders), 9000);
        window.location.href = documentoId
          ? `/mis-documentos/?destacar=${encodeURIComponent(documentoId)}`
          : "/mis-documentos/";
      } catch (err) {
        mostrarError(err.message || "Error al generar las preguntas.");
      }
    });

    async function iniciarTest(preguntasEntrada) {
      preguntas = preguntasEntrada || [];
      if (preguntas.length === 0) {
        mostrarError("No se generaron preguntas válidas.");
        return;
      }

      respuestasUsuario = Array(preguntas.length).fill(null);
      marcadasRevision = Array(preguntas.length).fill(false);
      marcadasDuda = Array(preguntas.length).fill(false);
      visitadas = Array(preguntas.length).fill(false);
      indicePreguntaActual = 0;
      document.getElementById('contenedor-carga').style.display = 'none';

      const { obtenerOposicionActual } = await import("/assets/oposicion.js");
      oposicionActual = obtenerOposicionActual();
      const favoritasApi = await import("/assets/favoritas.js");
      botonFavoritaHTML = favoritasApi.botonFavoritaHTML;
      activarBotonFavorita = favoritasApi.activarBotonFavorita;
      textosFavoritas = await favoritasApi.cargarTextosFavoritas(oposicionActual);
      const { generarTestId, guardarContenidoInicial, activarGuardadoAlSalir } = await import("/assets/test-progreso.js");
      generarTestId();
      guardarContenidoInicial({
        oposicion: oposicionActual, tipo: "test_pdf", temas: [],
        contenido: preguntas,
        respuestas_usuario: respuestasUsuario,
        marcadas_revision: marcadasRevision,
        marcadas_duda: marcadasDuda,
        indice_actual: indicePreguntaActual,
        pagina_origen: "/subida-pdf-generar-test/",
        documento_id: documentoIdActual
      });
      activarGuardadoAlSalir(() => ({
        respuestas_usuario: respuestasUsuario,
        marcadas_revision: marcadasRevision,
        marcadas_duda: marcadasDuda,
        indice_actual: indicePreguntaActual,
        tiempo_transcurrido_segundos: tiempoTranscurridoActual()
      }));

      iniciarTemporizador();
      document.getElementById("navegador-preguntas").style.display = "flex";
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
      marcadasRevision = Array.isArray(guardado.marcadas_revision) && guardado.marcadas_revision.length === preguntas.length
        ? guardado.marcadas_revision
        : Array(preguntas.length).fill(false);
      marcadasDuda = Array.isArray(guardado.marcadas_duda) && guardado.marcadas_duda.length === preguntas.length
        ? guardado.marcadas_duda
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

      document.getElementById('contenedor-carga').style.display = 'none';
      iniciarTemporizador(guardado.tiempo_transcurrido_segundos || 0);
      document.getElementById("navegador-preguntas").style.display = "flex";
      mostrarPregunta(indicePreguntaActual);
      document.getElementById('btn-finalizar').style.display = 'block';
      activarGuardadoAlSalir(() => ({
        respuestas_usuario: respuestasUsuario,
        marcadas_revision: marcadasRevision,
        marcadas_duda: marcadasDuda,
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

      if (ver === 'test') {
        document.getElementById('tarjeta-formulario').style.display = 'none';
        document.getElementById('contenedor-carga').style.display = 'block';
        document.getElementById('texto-estado').textContent = 'Cargando tu test guardado…';
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) return;
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

      // Test sacado del banco de preguntas pre-generado (ver "Mis
      // documentos", filaBanco): a diferencia de "ver=test" (el último test
      // GUARDADO de este documento), esto tira de usuarios/{uid}/
      // banco_preguntas_pdf/{documento_id} -- el pool generado en segundo
      // plano, del que se puede sacar un test de tamaño N (?cantidad=N,
      // aleatorias) o de todo lo generado (sin "cantidad") sin volver a
      // gastar en IA.
      if (ver === 'banco') {
        document.getElementById('tarjeta-formulario').style.display = 'none';
        document.getElementById('contenedor-carga').style.display = 'block';
        document.getElementById('texto-estado').textContent = 'Cargando preguntas del banco…';
        const authHeaders = await obtenerAuthHeaders();
        if (!authHeaders) return;
        try {
          const cantidad = params.get('cantidad');
          const qs = cantidad ? `?modo=aleatorias&cantidad=${encodeURIComponent(cantidad)}` : '?modo=todas';
          const res = await fetch(`https://oposicion-age.onrender.com/documento/${documentoId}/banco-preguntas${qs}`, { headers: authHeaders });
          const datos = await res.json();
          if (!res.ok) throw new Error(datos.error || 'No se pudo cargar el banco de preguntas.');
          if (!datos.preguntas || datos.preguntas.length === 0) {
            throw new Error('Este documento todavía no tiene preguntas generadas en su banco.');
          }
          nombreArchivo = datos.nombre_archivo || nombreArchivo;
          iniciarTest(datos.preguntas);
        } catch (err) {
          mostrarError(err.message);
        }
        return;
      }

      // Generar un test NUEVO desde un documento ya subido: se deja el
      // formulario visible (sin pedir de nuevo el PDF) para que el
      // usuario elija cuántas preguntas quiere, en vez de generar
      // siempre con el valor por defecto (10) sin preguntar.
      const grupoArchivo = document.getElementById('grupo-archivo');
      if (grupoArchivo) grupoArchivo.style.display = 'none';
      const archivoInput = document.getElementById('archivo-pdf');
      if (archivoInput) archivoInput.required = false;
      const aviso = document.getElementById('aviso-documento-existente');
      if (aviso) aviso.classList.remove('hidden');
    })();

    // === RENDERIZADO DE PREGUNTAS ===
    async function mostrarPregunta(i) {
      // El texto de la pregunta/opciones viene generado por IA -- se escapa
      // antes de inyectarlo en innerHTML (mismo motivo y misma función que ya
      // usa la pantalla de resultados, ver assets/resultados-test.js).
      const { escaparHtml } = await import("/assets/resultados-test.js");
      indicePreguntaActual = i;
      visitadas[i] = true;
      actualizarNavegadorPreguntas();

      const p = preguntas[i];
      let textoPregunta = escaparHtml(p.pregunta.replace(/^\s*\d+\s*[\.\)]\s*/, ""));
      let html = `<form id="form-pregunta">
        <div class="pregunta-en-negrita">
          <span>${i + 1}. ${textoPregunta}</span>
          <div class="pregunta-acciones-header">
            ${botonFavoritaHTML(textosFavoritas.has(p.pregunta))}
            <button type="button" id="btn-marcar-revision" class="btn-marcar-revision${marcadasRevision[i] ? " activa" : ""} icono-inline" aria-label="Marcar para revisión" title="Marcar esta pregunta para revisarla antes de terminar el test (queda resaltada en el mapa de preguntas)">${icono("marcador", 16)}</button>
            <button type="button" id="btn-marcar-duda" class="btn-marcar-duda${marcadasDuda[i] ? " activa" : ""} icono-inline" aria-label="Marcar como duda" title="Marcar esta pregunta como duda: al terminar el test verás la nota contándola y sin contarla">${icono("pregunta", 16)}</button>
          </div>
        </div>`;

      for (const letra in p.opciones) {
        const opcion = escaparHtml(p.opciones[letra]);
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
      document.getElementById("contenedor-test").style.display = "block";
      const bloquePregunta = document.querySelector("#form-pregunta .pregunta-en-negrita");
      if (bloquePregunta) {
        bloquePregunta.dataset.respuestaCorrecta = p.respuesta_correcta || "";
        bloquePregunta.dataset.explicacion = p.explicacion || "";
      }
      activarBotonFavorita(document.getElementById("contenedor-test"), p, oposicionActual, textosFavoritas);
      document.getElementById("btn-marcar-revision").addEventListener("click", function() {
        marcadasRevision[i] = !marcadasRevision[i];
        this.classList.toggle("activa", marcadasRevision[i]);
        actualizarNavegadorPreguntas();
        import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
          autoguardarProgreso({
            respuestas_usuario: respuestasUsuario,
            marcadas_revision: marcadasRevision,
            marcadas_duda: marcadasDuda,
            indice_actual: i
          });
        });
      });
      document.getElementById("btn-marcar-duda").addEventListener("click", function() {
        if (!marcadasDuda[i] && (respuestasUsuario[i] === null || respuestasUsuario[i] === undefined)) {
          Swal.fire({ icon: "info", title: "Responde antes de marcarla", text: "Debes contestar esta pregunta antes de poder marcarla como duda." });
          return;
        }
        marcadasDuda[i] = !marcadasDuda[i];
        this.classList.toggle("activa", marcadasDuda[i]);
        import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
          autoguardarProgreso({
            respuestas_usuario: respuestasUsuario,
            marcadas_revision: marcadasRevision,
            marcadas_duda: marcadasDuda,
            indice_actual: i
          });
        });
      });
      document.querySelectorAll('input[name="respuesta"]').forEach((radio) => {
        radio.addEventListener("click", function() {
          // Un segundo clic sobre la misma opción la desmarca y deja la
          // pregunta en blanco, igual que en el resto de tests.
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
      botonGuardarSalir.innerHTML = `${icono("guardar", 16)} Guardar y salir`;
      botonGuardarSalir.onclick = async function() {
        const boton = this;
        boton.disabled = true;
        boton.textContent = "Guardando…";
        const { guardarProgresoInmediato } = await import("/assets/test-progreso.js");
        await guardarProgresoInmediato({
          respuestas_usuario: respuestasUsuario,
          marcadas_revision: marcadasRevision,
          marcadas_duda: marcadasDuda,
          indice_actual: indicePreguntaActual,
          tiempo_transcurrido_segundos: tiempoTranscurridoActual()
        });
        window.location.href = "/mis-tests/";
      };

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
            marcadas_revision: marcadasRevision,
            marcadas_duda: marcadasDuda,
            indice_actual: i + 1 < preguntas.length ? i + 1 : i,
            tiempo_transcurrido_segundos: tiempoTranscurridoActual()
          });
        });
        if (i + 1 < preguntas.length) {
          mostrarPregunta(i + 1);
        } else {
          const sinContestar = respuestasUsuario.filter(r => r === null).length;
          const numDudasSinResolver = marcadasDuda.filter(Boolean).length;
          const avisos = [];
          if (sinContestar > 0) avisos.push(`has dejado ${sinContestar} pregunta${sinContestar > 1 ? 's' : ''} sin contestar`);
          if (numDudasSinResolver > 0) avisos.push(`has marcado ${numDudasSinResolver} pregunta${numDudasSinResolver > 1 ? 's' : ''} como duda${numDudasSinResolver > 1 ? 's' : ''}`);
          let mensaje = avisos.length
            ? avisos.join(' y ').replace(/^./, (c) => c.toUpperCase()) + '.'
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
        listaTemas: [],
        marcadasDuda
      });
      aciertos = ultimasEstadisticas.aciertos;
      fallos = ultimasEstadisticas.fallos;
      sinResponder = ultimasEstadisticas.sinResponder;
      porcentaje = ultimasEstadisticas.porcentaje;

      document.getElementById("btn-descargar-pdf").style.display = "block";

      import('/assets/otras-herramientas-pdf.js').then(({ pintarAccesosOtrasHerramientas }) => {
        pintarAccesosOtrasHerramientas({
          contenedor: document.getElementById('otras-herramientas-bloque'),
          documentoId: documentoIdActual,
          herramientaActual: 'subida-pdf-generar-test',
        });
      });

      guardarTestEnBackend();
    }

    // === FINALIZAR TEST ===
    document.getElementById("btn-finalizar").addEventListener("click", () => {
      const sinContestar = respuestasUsuario.filter(r => r === null).length;
      const numDudasSinResolver = marcadasDuda.filter(Boolean).length;
      const avisos = [];
      if (sinContestar > 0) avisos.push(`has dejado ${sinContestar} pregunta${sinContestar > 1 ? 's' : ''} sin contestar`);
      if (numDudasSinResolver > 0) avisos.push(`has marcado ${numDudasSinResolver} pregunta${numDudasSinResolver > 1 ? 's' : ''} como duda${numDudasSinResolver > 1 ? 's' : ''}`);
      let mensaje = avisos.length
        ? avisos.join(' y ').replace(/^./, (c) => c.toUpperCase()) + '.'
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
