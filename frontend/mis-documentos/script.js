import { idToken, marcarContenidoListo } from "/assets/auth.js";
import { mostrarErrorGlobal } from "/assets/notificaciones.js";
import { icono } from "/assets/icons.js";

const BACKEND_URL = "https://oposicion-age.onrender.com";
const NUEVA_CARPETA = "__nueva__";
// Carpeta especial que agrupa los documentos sin asignar -- no existe como
// tal en el catálogo de carpetas del backend, se calcula aquí a partir de
// qué documentos tienen "carpeta" vacío.
const SIN_CARPETA = "__sin_carpeta__";

document.querySelectorAll("[data-icon]").forEach((el) => {
  el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 24));
});

let documentos = [];
let carpetas = [];
let carpetaActual = null; // null = viendo el listado de carpetas

function escaparHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto == null ? "" : String(texto);
  return div.innerHTML;
}

function normalizarTexto(texto) {
  return (texto || "").toString().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
}

// Cuota mensual de documentos con banco generado (05/08/2026): aviso
// discreto para que no te enteres del límite solo cuando lo agotas y sale
// el 429 -- sin ninguna cifra de coste, solo el conteo de documentos.
function pintarCuotaDocumentosMes(cuota) {
  const el = document.getElementById("cuota-documentos-mes");
  if (!el) return;
  const usados = cuota?.usados ?? 0;
  const limite = cuota?.limite ?? 0;
  if (!limite || limite <= 0) {
    el.classList.add("hidden");
    return;
  }
  el.textContent = `${usados} de ${limite} documentos generados este mes`;
  el.classList.toggle("cuota-documentos-mes-alerta", usados / limite >= 0.8);
  el.classList.remove("hidden");
}

function formatearFecha(iso) {
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat('es-ES', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(iso));
  } catch (e) {
    return "";
  }
}

// === Modales genéricos de confirmación/texto (05/08/2026) ===
// Sustituyen a confirm()/prompt() nativos del navegador -- desentonaban con
// el resto de la página, que ya tiene sus propios modales
// (.documentos-modal-*). Ambos devuelven una Promise, como su equivalente
// nativo, para poder seguir escribiendo `if (!(await mostrarConfirmacion(...)))
// return;` en el sitio de la llamada.

function mostrarConfirmacion({ titulo = "Confirmar", mensaje, textoAceptar = "Confirmar", peligro = false }) {
  return new Promise((resolve) => {
    const overlay = document.getElementById("modal-confirmar");
    const btnAceptar = document.getElementById("confirmar-aceptar");
    const btnCancelar = document.getElementById("confirmar-cancelar");
    const btnCerrar = document.getElementById("confirmar-cerrar");

    document.getElementById("confirmar-titulo").textContent = titulo;
    document.getElementById("confirmar-mensaje").textContent = mensaje;
    btnAceptar.textContent = textoAceptar;
    btnAceptar.classList.toggle("age-btn-danger", peligro);
    btnAceptar.classList.toggle("age-btn-primary", !peligro);

    const terminar = (resultado) => {
      overlay.classList.add("hidden");
      btnAceptar.removeEventListener("click", onAceptar);
      btnCancelar.removeEventListener("click", onCancelar);
      btnCerrar.removeEventListener("click", onCancelar);
      overlay.removeEventListener("click", onOverlay);
      resolve(resultado);
    };
    const onAceptar = () => terminar(true);
    const onCancelar = () => terminar(false);
    const onOverlay = (evento) => { if (evento.target === overlay) terminar(false); };

    btnAceptar.addEventListener("click", onAceptar);
    btnCancelar.addEventListener("click", onCancelar);
    btnCerrar.addEventListener("click", onCancelar);
    overlay.addEventListener("click", onOverlay);
    overlay.classList.remove("hidden");
  });
}

function mostrarPrompt({ titulo, label, valorInicial = "", placeholder = "", textoAceptar = "Guardar" }) {
  return new Promise((resolve) => {
    const overlay = document.getElementById("modal-prompt");
    const formulario = document.getElementById("prompt-formulario");
    const input = document.getElementById("prompt-input");
    const btnCancelar = document.getElementById("prompt-cancelar");
    const btnCerrar = document.getElementById("prompt-cerrar");

    document.getElementById("prompt-titulo").textContent = titulo;
    document.getElementById("prompt-label").textContent = label;
    document.getElementById("prompt-aceptar").textContent = textoAceptar;
    input.value = valorInicial;
    input.placeholder = placeholder;

    const terminar = (resultado) => {
      overlay.classList.add("hidden");
      formulario.removeEventListener("submit", onSubmit);
      btnCancelar.removeEventListener("click", onCancelar);
      btnCerrar.removeEventListener("click", onCancelar);
      overlay.removeEventListener("click", onOverlay);
      resolve(resultado);
    };
    const onSubmit = (evento) => { evento.preventDefault(); terminar(input.value); };
    const onCancelar = () => terminar(null);
    const onOverlay = (evento) => { if (evento.target === overlay) terminar(null); };

    formulario.addEventListener("submit", onSubmit);
    btnCancelar.addEventListener("click", onCancelar);
    btnCerrar.addEventListener("click", onCancelar);
    overlay.addEventListener("click", onOverlay);
    overlay.classList.remove("hidden");
    input.focus();
    input.select();
  });
}

// Toast "Deshacer" (05/08/2026): sustituye al confirm() bloqueante de
// eliminar documento -- el borrado se hace optimista (se quita YA de la
// vista) y solo se llama de verdad al backend si el aviso desaparece sin
// que se pulse "Deshacer". Los botones de renombrar/eliminar están muy
// juntos en la tarjeta, así que este margen evita perder un documento por
// un clic torpe.
function mostrarToastDeshacer({ mensaje, alDeshacer, alConfirmar, duracionMs = 6000 }) {
  const contenedor = document.getElementById("toast-contenedor");
  const toast = document.createElement("div");
  toast.className = "documentos-toast";
  toast.innerHTML = `<span></span><button type="button" class="documentos-toast-deshacer">Deshacer</button>`;
  toast.querySelector("span").textContent = mensaje;
  contenedor.appendChild(toast);

  let resuelto = false;
  const temporizador = setTimeout(() => {
    if (resuelto) return;
    resuelto = true;
    toast.remove();
    alConfirmar();
  }, duracionMs);

  toast.querySelector(".documentos-toast-deshacer").addEventListener("click", () => {
    if (resuelto) return;
    resuelto = true;
    clearTimeout(temporizador);
    toast.remove();
    alDeshacer();
  });
}

function filaContenido({ label, iconoHtml, existe, cantidad, urlVer, urlGenerar, urlAleatorias, textoGenerar, urlContinuar }) {
  const acciones = [];
  // "Continuar" (test autoguardado sin terminar, ver
  // obtener_tests_en_progreso_por_documento en documentos_pdf.py) se
  // ofrece SIEMPRE que exista, incluso si todavía no hay ningún test
  // finalizado de este documento -- antes, un test empezado y no acabado
  // no aparecía por ningún sitio en la biblioteca, solo "Ver"/"Generar
  // más" (que dependen de haber finalizado al menos uno) o "Generar test"
  // desde cero.
  if (urlContinuar) {
    acciones.push(`<a class="documento-card-btn principal" href="${urlContinuar}">Continuar</a>`);
  }
  if (existe) {
    acciones.push(`<a class="documento-card-btn${urlContinuar ? "" : " principal"}" href="${urlVer}">Ver</a>`);
    if (urlAleatorias) {
      acciones.push(`<a class="documento-card-btn" href="${urlAleatorias}">10 aleatorias</a>`);
    }
    acciones.push(`<a class="documento-card-btn" href="${urlGenerar}">Generar más</a>`);
  } else {
    acciones.push(`<a class="documento-card-btn${urlContinuar ? "" : " principal"}" href="${urlGenerar}">${textoGenerar}</a>`);
  }
  const etiquetaCantidad = existe && cantidad ? ` (${cantidad})` : "";
  // Estado (05/08/2026, rediseño visual): antes la única señal de si un
  // tipo de contenido ya existía era el propio texto del botón ("Ver" vs.
  // "Generar resumen") -- fácil de pasar por alto en un vistazo rápido.
  // Ahora cada tipo lleva un estado explícito (Generado/En progreso/Aún no
  // generado) junto al icono, igual que ya hacía el banco adaptativo con
  // sus propios estados más abajo.
  const estadoHtml = urlContinuar
    ? `<span class="documento-card-tipo-estado documento-card-tipo-estado-progreso">${icono("reloj", 12)} Test en progreso</span>`
    : existe
      ? `<span class="documento-card-tipo-estado documento-card-tipo-estado-generado">${icono("check", 12)} Generado</span>`
      : `<span class="documento-card-tipo-estado">Aún no generado</span>`;
  return `
    <div class="documento-card-tipo">
      <div class="documento-card-tipo-cabecera">
        <span class="documento-card-tipo-icono">${iconoHtml}</span>
        <div class="documento-card-tipo-info">
          <span class="documento-card-tipo-label">${label}${etiquetaCantidad}</span>
          ${estadoHtml}
        </div>
      </div>
      <div class="documento-card-fila-acciones">${acciones.join("")}</div>
    </div>
  `;
}

// modoCarpeta: "quitar" (dentro de una carpeta real: botón para sacarlo),
// "mover" (dentro de "Sin carpeta": select para meterlo en una), "etiqueta"
// (resultados de búsqueda: solo texto informativo, sin acción).
function seccionCarpeta(doc, modoCarpeta) {
  if (modoCarpeta === "quitar") {
    return `
      <div class="documento-card-carpeta">
        <button type="button" class="documento-card-quitar" data-id="${doc.id}">Quitar de esta carpeta</button>
      </div>
    `;
  }
  if (modoCarpeta === "mover") {
    const opciones = [
      `<option value="">Mover a una carpeta…</option>`,
      ...carpetas.map((c) => `<option value="${escaparHtml(c)}">${escaparHtml(c)}</option>`),
      `<option value="${NUEVA_CARPETA}">+ Nueva carpeta…</option>`
    ].join("");
    return `
      <div class="documento-card-carpeta">
        <select class="select-carpeta" data-id="${doc.id}">${opciones}</select>
      </div>
    `;
  }
  if (modoCarpeta === "etiqueta") {
    return `<div class="documento-card-carpeta documento-card-carpeta-etiqueta">${icono("carpeta", 16)} ${doc.carpeta ? escaparHtml(doc.carpeta) : "Sin carpeta"}</div>`;
  }
  return "";
}

// Banco de preguntas/tarjetas pre-generado (03/08/2026): a diferencia de
// las filas "Tarjetas"/"Test" de arriba (una sesión concreta ya generada
// y guardada), esto es un POOL generado en segundo plano hasta agotar el
// contenido distinto del documento (ver generar_banco_preguntas_
// adaptativo/generar_banco_tarjetas_adaptativo en el backend), del que el
// usuario puede sacar tantas veces como quiera un test/repaso de tamaño
// N o de todo lo generado, sin volver a gastar en IA cada vez.
function filaBanco(doc, tipo) {
  const estado = doc[`banco_${tipo}_estado`];
  const total = doc[`banco_${tipo}_total`] || 0;
  const esPreguntas = tipo === "preguntas";
  const label = esPreguntas ? "Banco de preguntas" : "Banco de tarjetas";
  const nombreItem = esPreguntas ? "pregunta" : "tarjeta";
  const iconoHtml = icono(esPreguntas ? "matraz" : "tarjeta", 16);
  const rutaPractica = esPreguntas ? "/subida-pdf-generar-test/" : "/subida-pdf-tarjetas/";
  const paramVer = esPreguntas ? "banco" : "banco-tarjetas";
  const etiquetaAccion = esPreguntas ? "Test" : "Repasar";

  // Estado (05/08/2026, rediseño visual): antes este texto vivía mezclado
  // dentro de "acciones" (la fila de botones), así que el aviso de
  // "generando"/"completo"/"error" acababa al lado de un botón con el
  // mismo peso visual que él -- ahora vive junto al icono y la etiqueta,
  // igual que el estado Generado/Aún no generado de filaContenido.
  let estadoHtml = `<span class="documento-card-tipo-estado">Sin generar todavía</span>`;
  const acciones = [];
  if (!estado || estado === "sin_generar") {
    acciones.push(`<button type="button" class="documento-card-btn principal" data-banco-generar="${tipo}" data-id="${doc.id}">Generar banco de ${tipo}</button>`);
  } else {
    if (estado === "generando") {
      // Sin el tope interno (antes "1/100"): el usuario no tiene por qué
      // saber cuál es el techo de seguridad del banco, solo cuántas lleva
      // generadas hasta ahora -- este número se actualiza en vivo según
      // van llegando eventos de progreso (ver iniciarBanco).
      estadoHtml = `<span class="documento-card-tipo-estado documento-card-tipo-estado-progreso">${icono("reloj", 12)} Generando… ${total} ${nombreItem}${total === 1 ? "" : "s"} hasta ahora</span>`;
    } else if (estado === "completo") {
      // Aviso explícito de que la generación YA terminó (03/08/2026, a
      // petición del usuario: antes, al pasar de "generando" a completo,
      // no había ninguna señal clara de que el sistema hubiera acabado de
      // trabajar -- solo aparecían los botones de practicar, fáciles de
      // confundir con "sigue generando").
      estadoHtml = `<span class="documento-card-tipo-estado documento-card-tipo-estado-generado">${icono("check", 12)} ${total} ${nombreItem}${total === 1 ? "" : "s"} generada${total === 1 ? "" : "s"}</span>`;
    } else if (estado === "error") {
      estadoHtml = `<span class="documento-card-tipo-estado documento-card-tipo-estado-error">No se pudo generar</span>`;
      acciones.push(`<button type="button" class="documento-card-btn" data-banco-generar="${tipo}" data-id="${doc.id}">Reintentar</button>`);
    } else if (estado === "atascado") {
      // "atascado" (03/08/2026, bug real): el backend deja de reportar un
      // banco como "generando" pasados varios minutos sin ninguna
      // actualización (ver documentos_pdf._banco_atascado) -- típicamente
      // porque el hilo de fondo murió a mitad de generación (un
      // despliegue del servidor, por ejemplo) sin llegar a terminar. Antes
      // esto dejaba el documento mostrando "Generando..." para siempre,
      // sin ninguna forma de reintentar.
      estadoHtml = `<span class="documento-card-tipo-estado documento-card-tipo-estado-error">La generación se interrumpió${total > 0 ? ` (se quedaron ${total} guardadas)` : ""}</span>`;
      acciones.push(`<button type="button" class="documento-card-btn" data-banco-generar="${tipo}" data-id="${doc.id}">Reintentar</button>`);
    }
    if (total > 0) {
      if (total > 1) {
        // Cantidad libre (03/08/2026, a petición del usuario: antes era un
        // botón fijo "de 10") -- el usuario elige cuántas de las "total"
        // disponibles quiere en esta sesión, entre 1 y el total del banco.
        acciones.push(`
          <span class="documento-card-banco-cantidad">
            <input type="number" class="documento-card-banco-input" min="1" max="${total}"
                   value="${Math.min(10, total)}" data-banco-cantidad="${tipo}"
                   aria-label="Cantidad de ${label.toLowerCase()}">
            <button type="button" class="documento-card-btn" data-banco-empezar="${tipo}" data-id="${doc.id}">${etiquetaAccion}</button>
          </span>
        `);
      }
      acciones.push(`<a class="documento-card-btn${estado === "completo" ? " principal" : ""}" href="${rutaPractica}?documento_id=${doc.id}&ver=${paramVer}">${etiquetaAccion} de todas (${total})</a>`);
    }
  }

  return `
    <div class="documento-card-tipo">
      <div class="documento-card-tipo-cabecera">
        <span class="documento-card-tipo-icono">${iconoHtml}</span>
        <div class="documento-card-tipo-info">
          <span class="documento-card-tipo-label">${label}</span>
          ${estadoHtml}
        </div>
      </div>
      <div class="documento-card-fila-acciones">${acciones.join("")}</div>
    </div>
  `;
}

// Lee la cantidad elegida en el input de al lado del botón pulsado (dentro
// de la misma fila de acciones) y navega a la herramienta correspondiente
// pidiendo un test/repaso de ese tamaño sobre el banco ya generado.
function irABanco(evento, documentoId, tipo) {
  const fila = evento.currentTarget.closest(".documento-card-fila-acciones");
  const input = fila?.querySelector("input[data-banco-cantidad]");
  const doc = documentos.find((d) => d.id === documentoId);
  const total = doc ? (doc[`banco_${tipo}_total`] || 0) : 0;
  let cantidad = parseInt(input?.value, 10);
  if (!Number.isFinite(cantidad) || cantidad < 1) cantidad = 1;
  if (total && cantidad > total) cantidad = total;
  const rutaPractica = tipo === "preguntas" ? "/subida-pdf-generar-test/" : "/subida-pdf-tarjetas/";
  const paramVer = tipo === "preguntas" ? "banco" : "banco-tarjetas";
  window.location.href = `${rutaPractica}?documento_id=${documentoId}&ver=${paramVer}&cantidad=${cantidad}`;
}

// archivoOriginal (opcional): el File recién subido, para la generación
// que se dispara justo después de "Subir documento" (ver
// inicializarSubidaDocumento). El documento en Firestore guarda el texto
// recortado a 150.000 caracteres (~50 páginas, ver MAX_CARACTERES_DOCUMENTO
// en documentos_pdf.py -- Firestore no admite más de 1 MB por documento),
// así que tirar de documento_id para la PRIMERA generación de un PDF largo
// se quedaría corto sin que el usuario lo note. Reenviar el archivo (en vez
// de documento_id) hace que el backend use el texto recién extraído
// COMPLETO para esa generación -- _resolver_texto_documento ya sabe
// reutilizar el mismo documento (por hash del texto) en vez de duplicarlo.
// El resto de llamadas a iniciarBanco (botón "Generar banco" de un
// documento ya existente en la biblioteca) no tienen el archivo a mano y
// siguen usando documento_id, con la misma limitación de siempre.
async function iniciarBanco(documentoId, tipo, archivoOriginal) {
  const doc = documentos.find((d) => d.id === documentoId);
  if (doc) doc[`banco_${tipo}_estado`] = "generando";
  const refrescar = () => {
    if (carpetaActual !== null) renderizarDocumentosDeCarpeta();
    const query = document.getElementById("filtro-busqueda")?.value;
    if (query) renderizarBusqueda(query);
  };
  refrescar();
  // Red de seguridad (05/08/2026, bug real): la lectura del SSE de abajo
  // depende de que la respuesta llegue sin bufferizar por el camino --
  // algunos proxies/CDN delante del backend no lo respetan (o el propio
  // hosting), y el contador se quedaba clavado en 0 hasta recargar la
  // página a mano (que sí funcionaba, porque cargarDocumentos() arranca
  // este mismo sondeo). Arrancarlo aquí también asegura que el contador
  // avance cada 4s aunque la lectura directa del stream no llegue a
  // tiempo real, sin esperar a un reload manual.
  iniciarSondeoBancosSiHaceFalta();

  try {
    const token = await idToken();
    const ruta = tipo === "preguntas" ? "generar-banco-preguntas-desde-pdf" : "generar-banco-tarjetas-desde-pdf";
    const formData = new FormData();
    if (archivoOriginal) {
      formData.append("pdf", archivoOriginal);
    } else {
      formData.append("documento_id", documentoId);
    }
    const res = await fetch(`${BACKEND_URL}/${ruta}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData
    });
    if (!res.ok || !res.body) {
      const datos = await res.json().catch(() => ({}));
      throw new Error(datos.error || "No se pudo iniciar la generación del banco.");
    }

    const lector = res.body.getReader();
    const decodificador = new TextDecoder();
    let buffer = "";
    let terminado = false;
    while (!terminado) {
      const { done, value } = await lector.read();
      if (done) break;
      buffer += decodificador.decode(value, { stream: true });
      const bloques = buffer.split("\n\n");
      buffer = bloques.pop();
      for (const bloque of bloques) {
        const linea = bloque.trim();
        if (!linea.startsWith("data: ")) continue;
        let evento;
        try { evento = JSON.parse(linea.slice(6)); } catch { continue; }
        if (evento.tipo === "progreso") {
          if (doc) {
            doc[`banco_${tipo}_total`] = evento.completadas;
            doc[`banco_${tipo}_objetivo`] = evento.objetivo;
          }
          refrescar();
        } else if (evento.tipo === "fin") {
          terminado = true;
          if (doc) {
            doc[`banco_${tipo}_total`] = evento.total ?? doc[`banco_${tipo}_total`];
            doc[`banco_${tipo}_estado`] = evento.total ? "completo" : "error";
          }
        }
      }
    }
  } catch (e) {
    if (doc) doc[`banco_${tipo}_estado`] = "error";
    mostrarErrorGlobal(e.message || "No se pudo generar el banco.");
  } finally {
    refrescar();
  }
}

function tarjetaDocumento(doc, modoCarpeta) {
  const nombreCorto = (doc.titulo || doc.nombre_archivo || "Documento").slice(0, 90);
  const meta = [
    doc.nombre_archivo,
    doc.num_paginas ? `${doc.num_paginas} páginas` : null,
    doc.fecha_subida ? `subido el ${formatearFecha(doc.fecha_subida)}` : null
  ].filter(Boolean).join(" · ");

  // Iconos distintos por tipo (05/08/2026, rediseño visual): "Resumen"
  // usaba el mismo icono genérico de "documento" que ahora identifica a
  // los documentos sueltos en la vista de carpetas -- para no repetir ese
  // significado aquí, usa "lista" (afín a un resumen en puntos clave).
  // Esquema/Tarjetas/Test mantienen los iconos que ya usa el resto del
  // sitio para cada herramienta (esquema, tarjeta, matraz).
  const filasContenido = [
    filaContenido({
      label: "Resumen", iconoHtml: icono("lista", 18), existe: doc.tiene_resumen,
      urlVer: `/subida-pdf-resumen/?documento_id=${doc.id}&ver=resumen`,
      urlGenerar: `/subida-pdf-resumen/?documento_id=${doc.id}`,
      textoGenerar: "Generar resumen"
    }),
    filaContenido({
      label: "Esquema", iconoHtml: icono("esquema", 18), existe: doc.tiene_esquema,
      urlVer: `/subida-pdf-esquemas/?documento_id=${doc.id}&ver=esquema`,
      urlGenerar: `/subida-pdf-esquemas/?documento_id=${doc.id}`,
      textoGenerar: "Generar esquema"
    }),
    filaContenido({
      label: "Tarjetas", iconoHtml: icono("tarjeta", 18), existe: doc.num_tarjetas > 0, cantidad: doc.num_tarjetas,
      urlVer: `/subida-pdf-tarjetas/?documento_id=${doc.id}&ver=tarjetas&modo=todas`,
      urlAleatorias: `/subida-pdf-tarjetas/?documento_id=${doc.id}&ver=tarjetas&modo=aleatorias&cantidad=10`,
      urlGenerar: `/subida-pdf-tarjetas/?documento_id=${doc.id}`,
      textoGenerar: "Generar tarjetas"
    }),
    filaContenido({
      label: "Test", iconoHtml: icono("matraz", 18), existe: doc.num_tests > 0,
      cantidad: doc.num_tests ? `${doc.num_tests} intento${doc.num_tests > 1 ? "s" : ""}` : null,
      urlVer: `/subida-pdf-generar-test/?documento_id=${doc.id}&ver=test`,
      urlGenerar: `/subida-pdf-generar-test/?documento_id=${doc.id}`,
      urlContinuar: doc.test_en_progreso ? `/subida-pdf-generar-test/?resume=${doc.test_en_progreso}` : null,
      textoGenerar: "Generar test"
    })
  ].join("");
  const filasBanco = [filaBanco(doc, "preguntas"), filaBanco(doc, "tarjetas")].join("");

  return `
    <div class="documento-card" data-id="${doc.id}">
      <div class="documento-card-header">
        <div class="documento-card-icon">${icono("libro", 26)}</div>
        <div>
          <p class="documento-card-titulo">
            ${escaparHtml(nombreCorto)}
            <button type="button" class="documento-card-renombrar" data-id="${doc.id}" aria-label="Renombrar documento" title="Renombrar documento">${icono("lapiz", 14)}</button>
            <button type="button" class="documento-card-eliminar" data-id="${doc.id}" aria-label="Eliminar documento" title="Eliminar documento">${icono("papelera", 14)}</button>
          </p>
          <p class="documento-card-meta">${escaparHtml(meta)}</p>
        </div>
      </div>
      ${seccionCarpeta(doc, modoCarpeta)}
      <p class="documento-card-seccion-titulo">Contenido generado</p>
      <div class="documento-card-tipos">${filasContenido}</div>
      <p class="documento-card-seccion-titulo">Banco de práctica</p>
      <div class="documento-card-tipos">${filasBanco}</div>
    </div>
  `;
}

function tarjetaCarpeta(idCarpeta, nombreMostrado, cantidad, esEspecial) {
  return `
    <button type="button" class="carpeta-tile${esEspecial ? " carpeta-tile-especial" : ""}" data-carpeta="${escaparHtml(idCarpeta)}">
      <span class="carpeta-tile-icono">${esEspecial ? icono("documento", 26) : icono("carpeta", 26)}</span>
      <span class="carpeta-tile-nombre">${escaparHtml(nombreMostrado)}</span>
      <span class="carpeta-tile-contador">${cantidad} documento${cantidad === 1 ? "" : "s"}</span>
    </button>
  `;
}

// Un documento sin carpeta se muestra directamente con su propio nombre
// (no agrupado detrás de una única tarjeta genérica "Sin carpeta"), con
// "Sin carpeta" como subtítulo -- así se ve de un vistazo de qué documento
// se trata sin tener que entrar. Sigue llevando a la misma vista de "Sin
// carpeta" al pulsarlo (donde puede moverse a una carpeta real).
function tarjetaDocumentoSuelto(doc) {
  const nombre = (doc.titulo || doc.nombre_archivo || "Documento").slice(0, 60);
  return `
    <button type="button" class="carpeta-tile carpeta-tile-especial" data-carpeta="${SIN_CARPETA}">
      <span class="carpeta-tile-icono">${icono("documento", 26)}</span>
      <span class="carpeta-tile-nombre">${escaparHtml(nombre)}</span>
      <span class="carpeta-tile-contador">Sin carpeta</span>
    </button>
  `;
}

function renderizarCarpetas() {
  const grid = document.getElementById("carpetas-grid");
  const sinCarpetaDocs = documentos.filter((d) => !d.carpeta);

  const tiles = carpetas.map((nombre) => {
    const cantidad = documentos.filter((d) => d.carpeta === nombre).length;
    return tarjetaCarpeta(nombre, nombre, cantidad, false);
  });

  sinCarpetaDocs.forEach((doc) => tiles.push(tarjetaDocumentoSuelto(doc)));

  grid.innerHTML = tiles.join("");
  grid.querySelectorAll("[data-carpeta]").forEach((boton) => {
    boton.addEventListener("click", () => abrirCarpeta(boton.dataset.carpeta));
  });
}

// Filtro de texto dentro de una carpeta (05/08/2026): el buscador de arriba
// solo funciona en la vista de carpetas -- este es su equivalente DENTRO de
// una, para no depender de scroll cuando hay muchos documentos ahí. Se
// reinicia cada vez que se entra en una carpeta (ver abrirCarpeta).
let filtroCarpetaActual = "";

function renderizarDocumentosDeCarpeta() {
  const contenedor = document.getElementById("carpeta-detalle-lista");
  const esSinCarpeta = carpetaActual === SIN_CARPETA;
  const q = normalizarTexto(filtroCarpetaActual);
  const docsFiltrados = documentos.filter((d) => (esSinCarpeta ? !d.carpeta : d.carpeta === carpetaActual))
    .filter((d) => !q || normalizarTexto(d.titulo || d.nombre_archivo).includes(q));

  if (docsFiltrados.length === 0) {
    contenedor.innerHTML = q
      ? `<p class="documentos-carpeta-vacia">Sin resultados para "${escaparHtml(filtroCarpetaActual)}".</p>`
      : `<p class="documentos-carpeta-vacia">No hay documentos aquí todavía.</p>`;
    return;
  }

  contenedor.innerHTML = docsFiltrados.map((d) => tarjetaDocumento(d, esSinCarpeta ? "mover" : "quitar")).join("");

  if (esSinCarpeta) {
    contenedor.querySelectorAll(".select-carpeta").forEach((select) => {
      select.addEventListener("change", onMoverDesdeSinCarpeta);
    });
  } else {
    contenedor.querySelectorAll(".documento-card-quitar").forEach((boton) => {
      boton.addEventListener("click", () => quitarDeCarpeta(boton.dataset.id));
    });
  }
  contenedor.querySelectorAll(".documento-card-renombrar").forEach((boton) => {
    boton.addEventListener("click", () => renombrarDocumento(boton.dataset.id));
  });
  contenedor.querySelectorAll(".documento-card-eliminar").forEach((boton) => {
    boton.addEventListener("click", () => eliminarDocumento(boton.dataset.id));
  });
  contenedor.querySelectorAll("[data-banco-generar]").forEach((boton) => {
    boton.addEventListener("click", () => iniciarBanco(boton.dataset.id, boton.dataset.bancoGenerar));
  });
  contenedor.querySelectorAll("[data-banco-empezar]").forEach((boton) => {
    boton.addEventListener("click", (evento) => irABanco(evento, boton.dataset.id, boton.dataset.bancoEmpezar));
  });
  contenedor.querySelectorAll("input[data-banco-cantidad]").forEach((input) => {
    input.addEventListener("keydown", (evento) => {
      if (evento.key !== "Enter") return;
      evento.target.closest(".documento-card-fila-acciones")?.querySelector("[data-banco-empezar]")?.click();
    });
  });
}

async function renombrarDocumento(documentoId) {
  const doc = documentos.find((d) => d.id === documentoId);
  if (!doc) return;
  const nuevoNombre = await mostrarPrompt({
    titulo: "Renombrar documento", label: "Nuevo nombre",
    valorInicial: doc.titulo || doc.nombre_archivo || "",
  });
  if (nuevoNombre === null) return;
  const limpio = nuevoNombre.trim();
  if (!limpio) return;
  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/documento/${documentoId}/titulo`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ titulo: limpio })
    });
    const datos = await res.json();
    if (!res.ok) throw new Error(datos.error || "No se pudo renombrar el documento.");
    doc.titulo = datos.titulo || limpio;
    if (carpetaActual !== null) renderizarDocumentosDeCarpeta();
    const query = document.getElementById("filtro-busqueda")?.value;
    if (query) renderizarBusqueda(query);
  } catch (e) {
    mostrarErrorGlobal(e.message || "No se pudo renombrar el documento.");
  }
}

function refrescarVistasDocumentos() {
  if (carpetaActual !== null) renderizarDocumentosDeCarpeta();
  const query = document.getElementById("filtro-busqueda")?.value;
  if (query) renderizarBusqueda(query);
}

// Borrado optimista con "Deshacer" (05/08/2026, ver mostrarToastDeshacer):
// el documento desaparece de la vista al instante, pero el DELETE real al
// backend no se dispara hasta que el toast expira sin deshacerse. No borra
// en cascada lo ya generado a partir de él (ver documentos_pdf.
// eliminar_documento) -- solo deja de aparecer agrupado aquí.
async function eliminarDocumento(documentoId) {
  const doc = documentos.find((d) => d.id === documentoId);
  if (!doc) return;
  const nombre = doc.titulo || doc.nombre_archivo || "Documento";

  // Confirmación previa (05/08/2026, a petición del usuario) + el toast
  // "Deshacer" de después como última red de seguridad: los iconos de
  // renombrar/eliminar están muy juntos en la tarjeta, así que conviene
  // las dos capas, no solo una.
  const confirmado = await mostrarConfirmacion({
    titulo: "Eliminar documento",
    mensaje: `¿Seguro que quieres eliminar "${nombre}"? Los resúmenes, esquemas, tarjetas o tests que ya hubieras generado a partir de él no se borran, pero dejarán de aparecer agrupados aquí.`,
    textoAceptar: "Eliminar",
    peligro: true,
  });
  if (!confirmado) return;

  documentos = documentos.filter((d) => d.id !== documentoId);
  refrescarVistasDocumentos();

  mostrarToastDeshacer({
    mensaje: `"${nombre}" eliminado de tu biblioteca.`,
    alDeshacer: () => {
      documentos.push(doc);
      refrescarVistasDocumentos();
    },
    alConfirmar: async () => {
      try {
        const token = await idToken();
        const res = await fetch(`${BACKEND_URL}/documento/${documentoId}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${token}` }
        });
        if (!res.ok) {
          const datos = await res.json().catch(() => ({}));
          throw new Error(datos.error || "No se pudo eliminar el documento.");
        }
      } catch (e) {
        // El borrado real falló DESPUÉS de haberlo quitado ya de la vista
        // -- se restaura para no dejar el frontend desincronizado del
        // servidor (donde el documento sigue existiendo).
        documentos.push(doc);
        refrescarVistasDocumentos();
        mostrarErrorGlobal(e.message || "No se pudo eliminar el documento.");
      }
    },
  });
}

function abrirCarpeta(idCarpeta) {
  carpetaActual = idCarpeta;
  const esSinCarpeta = idCarpeta === SIN_CARPETA;

  document.getElementById("vista-carpetas").classList.add("hidden");
  document.getElementById("vista-carpeta-detalle").classList.remove("hidden");
  document.getElementById("carpeta-detalle-titulo").textContent = esSinCarpeta ? "Sin carpeta" : idCarpeta;
  document.getElementById("btn-eliminar-carpeta").classList.toggle("hidden", esSinCarpeta);
  document.getElementById("btn-anadir-documentos").classList.toggle("hidden", esSinCarpeta);
  filtroCarpetaActual = "";
  const inputFiltroCarpeta = document.getElementById("filtro-busqueda-carpeta");
  if (inputFiltroCarpeta) inputFiltroCarpeta.value = "";

  renderizarDocumentosDeCarpeta();
}

function volverACarpetas() {
  carpetaActual = null;
  document.getElementById("vista-carpeta-detalle").classList.add("hidden");
  document.getElementById("vista-carpetas").classList.remove("hidden");
  renderizarCarpetas();
}

function renderizarBusqueda(query) {
  const grid = document.getElementById("carpetas-grid");
  const resultados = document.getElementById("busqueda-resultados");
  const q = normalizarTexto(query);

  if (!q) {
    grid.classList.remove("hidden");
    resultados.classList.add("hidden");
    return;
  }

  grid.classList.add("hidden");
  resultados.classList.remove("hidden");

  const encontrados = documentos.filter((d) => normalizarTexto(d.titulo || d.nombre_archivo).includes(q));
  if (encontrados.length === 0) {
    resultados.innerHTML = `<p class="documentos-carpeta-vacia">Sin resultados para "${escaparHtml(query)}".</p>`;
    return;
  }
  resultados.innerHTML = encontrados.map((d) => tarjetaDocumento(d, "etiqueta")).join("");
  resultados.querySelectorAll(".documento-card-renombrar").forEach((boton) => {
    boton.addEventListener("click", () => renombrarDocumento(boton.dataset.id));
  });
  resultados.querySelectorAll(".documento-card-eliminar").forEach((boton) => {
    boton.addEventListener("click", () => eliminarDocumento(boton.dataset.id));
  });
  resultados.querySelectorAll("[data-banco-generar]").forEach((boton) => {
    boton.addEventListener("click", () => iniciarBanco(boton.dataset.id, boton.dataset.bancoGenerar));
  });
  resultados.querySelectorAll("[data-banco-empezar]").forEach((boton) => {
    boton.addEventListener("click", (evento) => irABanco(evento, boton.dataset.id, boton.dataset.bancoEmpezar));
  });
  resultados.querySelectorAll("input[data-banco-cantidad]").forEach((input) => {
    input.addEventListener("keydown", (evento) => {
      if (evento.key !== "Enter") return;
      evento.target.closest(".documento-card-fila-acciones")?.querySelector("[data-banco-empezar]")?.click();
    });
  });
}

async function asignarCarpeta(documentoId, carpeta) {
  const token = await idToken();
  await fetch(`${BACKEND_URL}/documento/${documentoId}/carpeta`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ carpeta })
  });
  const doc = documentos.find((d) => d.id === documentoId);
  if (doc) doc.carpeta = carpeta;
}

async function crearCarpetaEnBackend(nombre) {
  const token = await idToken();
  const res = await fetch(`${BACKEND_URL}/carpetas-documentos`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ nombre })
  });
  const datos = await res.json();
  if (!res.ok) throw new Error(datos.error || "No se pudo crear la carpeta.");
  if (!carpetas.includes(datos.nombre)) carpetas.push(datos.nombre);
  return datos.nombre;
}

async function onMoverDesdeSinCarpeta(evento) {
  const select = evento.target;
  const documentoId = select.dataset.id;
  let nuevaCarpeta = select.value;
  if (!nuevaCarpeta) return;

  if (nuevaCarpeta === NUEVA_CARPETA) {
    const nombre = await mostrarPrompt({
      titulo: "Nueva carpeta", label: "Nombre de la carpeta", placeholder: 'Por ejemplo, "Tema 1"',
    });
    if (!nombre || !nombre.trim()) {
      renderizarDocumentosDeCarpeta();
      return;
    }
    try {
      nuevaCarpeta = await crearCarpetaEnBackend(nombre.trim());
    } catch (e) {
      mostrarErrorGlobal(e.message || "No se pudo crear la carpeta.");
      renderizarDocumentosDeCarpeta();
      return;
    }
  }

  await asignarCarpeta(documentoId, nuevaCarpeta);
  renderizarDocumentosDeCarpeta();
}

async function quitarDeCarpeta(documentoId) {
  await asignarCarpeta(documentoId, "");
  renderizarDocumentosDeCarpeta();
}

// candidatosModalAnadir/seleccionModalAnadir (05/08/2026): la selección se
// guarda aparte de los checkboxes del DOM porque el buscador del modal
// vuelve a pintar la lista al filtrar -- si se leyera con
// querySelectorAll(":checked") al confirmar, cualquier documento marcado y
// luego oculto por el filtro se perdería.
let candidatosModalAnadir = [];
let seleccionModalAnadir = new Set();

function renderizarListaModalAnadir(query) {
  const lista = document.getElementById("modal-anadir-lista");
  if (candidatosModalAnadir.length === 0) {
    lista.innerHTML = `<p class="documentos-modal-vacio">Todos tus documentos ya están en esta carpeta.</p>`;
    return;
  }
  const q = normalizarTexto(query);
  const filtrados = q
    ? candidatosModalAnadir.filter((d) => normalizarTexto(d.titulo || d.nombre_archivo).includes(q))
    : candidatosModalAnadir;
  if (filtrados.length === 0) {
    lista.innerHTML = `<p class="documentos-modal-vacio">Sin resultados para "${escaparHtml(query)}".</p>`;
    return;
  }
  lista.innerHTML = filtrados.map((d) => `
    <label class="documentos-modal-item">
      <input type="checkbox" value="${d.id}" ${seleccionModalAnadir.has(d.id) ? "checked" : ""} />
      <span class="documentos-modal-item-titulo">${escaparHtml(d.titulo || d.nombre_archivo || "Documento")}</span>
      <span class="documentos-modal-item-carpeta">${d.carpeta ? escaparHtml(d.carpeta) : "Sin carpeta"}</span>
    </label>
  `).join("");
  lista.querySelectorAll("input[type=checkbox]").forEach((casilla) => {
    casilla.addEventListener("change", () => {
      if (casilla.checked) seleccionModalAnadir.add(casilla.value);
      else seleccionModalAnadir.delete(casilla.value);
    });
  });
}

function abrirModalAnadir() {
  document.getElementById("modal-anadir-carpeta-nombre").textContent = carpetaActual;
  candidatosModalAnadir = documentos.filter((d) => d.carpeta !== carpetaActual);
  seleccionModalAnadir = new Set();
  const busqueda = document.getElementById("modal-anadir-busqueda");
  busqueda.value = "";
  // Solo se muestra el buscador si hay candidatos de sobra para que merezca
  // la pena filtrar -- con pocos, una lista corta ya se ve de un vistazo.
  busqueda.classList.toggle("hidden", candidatosModalAnadir.length <= 6);
  renderizarListaModalAnadir("");
  document.getElementById("modal-anadir-documentos").classList.remove("hidden");
}

function cerrarModalAnadir() {
  document.getElementById("modal-anadir-documentos").classList.add("hidden");
}

// === Subir documento directamente desde "Mis documentos" (05/08/2026) ===
// Antes solo se podía subir un PDF nuevo desde cada herramienta por
// separado (Resumen/Esquema/Tarjetas/Test), eligiendo qué generar ANTES de
// subir el archivo. Este flujo invierte el orden: se sube y se guarda en la
// biblioteca primero (sin gastar nada en IA, ver /subir-documento), y solo
// DESPUÉS se pregunta qué banco generar -- reutilizando iniciarBanco(), que
// ya sabe pintar el progreso en vivo sobre la tarjeta del documento.
let subirDocCarpetaDestino = null;
let subirDocIdActual = null;
// El File recién subido, para que la primera generación (justo después de
// subir) use el texto completo en vez del recortado guardado en Firestore
// -- ver el comentario largo junto a iniciarBanco.
let subirDocArchivoActual = null;

function abrirModalSubirDocumento(carpetaDestino) {
  subirDocCarpetaDestino = carpetaDestino || null;
  subirDocIdActual = null;
  subirDocArchivoActual = null;
  document.getElementById("subir-doc-input").value = "";
  document.getElementById("subir-doc-paso-elegir").classList.add("hidden");
  document.getElementById("subir-doc-paso-cargando").classList.add("hidden");
  document.getElementById("subir-doc-paso-archivo").classList.remove("hidden");
  document.getElementById("modal-subir-documento").classList.remove("hidden");
}

function cerrarModalSubirDocumento() {
  document.getElementById("modal-subir-documento").classList.add("hidden");
}

// Vuelve a pedir la lista completa (mismo endpoint que cargarDocumentos) --
// más simple y fiable que reconstruir a mano el documento recién creado con
// todos sus campos (banco_*_estado, num_paginas...), y cubre también el
// caso de "primer documento" (pasar de la biblioteca vacía a tener contenido).
async function recargarDocumentos() {
  const token = await idToken();
  const res = await fetch(`${BACKEND_URL}/mis-documentos`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error("No se pudo actualizar tu biblioteca.");
  const datos = await res.json();
  documentos = datos.documentos || [];
  carpetas = datos.carpetas || [];
  pintarCuotaDocumentosMes(datos.cuota_documentos_mes);
  if (documentos.length > 0) {
    document.getElementById("documentos-vacio").classList.add("hidden");
    document.getElementById("documentos-contenido").classList.remove("hidden");
  }
}

async function subirArchivo(archivo) {
  if (archivo.type !== "application/pdf") {
    mostrarErrorGlobal("El archivo debe ser un PDF.");
    return;
  }
  if (archivo.size > 10 * 1024 * 1024) {
    mostrarErrorGlobal("El PDF no puede superar los 10 MB.");
    return;
  }
  document.getElementById("subir-doc-paso-archivo").classList.add("hidden");
  document.getElementById("subir-doc-paso-cargando").classList.remove("hidden");

  try {
    const token = await idToken();
    const formData = new FormData();
    formData.append("pdf", archivo);
    const res = await fetch(`${BACKEND_URL}/subir-documento`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData
    });
    const datos = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(datos.error || "No se pudo subir el documento.");

    subirDocIdActual = datos.documento_id;
    subirDocArchivoActual = archivo;
    if (subirDocCarpetaDestino) {
      await asignarCarpeta(subirDocIdActual, subirDocCarpetaDestino);
    }
    await recargarDocumentos();

    document.getElementById("subir-doc-paso-cargando").classList.add("hidden");
    document.getElementById("subir-doc-nombre").textContent = datos.nombre_archivo || "Tu documento";
    document.getElementById("subir-doc-paso-elegir").classList.remove("hidden");

    const doc = documentos.find((d) => d.id === subirDocIdActual);
    abrirCarpeta(doc ? (doc.carpeta || SIN_CARPETA) : SIN_CARPETA);
    requestAnimationFrame(() => {
      const tarjeta = document.querySelector(`.documento-card[data-id="${CSS.escape(subirDocIdActual)}"]`);
      tarjeta?.classList.add("documento-card-destacada");
    });
  } catch (e) {
    cerrarModalSubirDocumento();
    mostrarErrorGlobal(e.message || "No se pudo subir el documento.");
  }
}

function inicializarSubidaDocumento() {
  const dropzone = document.getElementById("subir-doc-dropzone");
  const inputArchivo = document.getElementById("subir-doc-input");

  dropzone.addEventListener("click", () => inputArchivo.click());
  inputArchivo.addEventListener("change", () => {
    const archivo = inputArchivo.files[0];
    if (archivo) subirArchivo(archivo);
  });
  ["dragenter", "dragover", "dragleave", "drop"].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => { e.preventDefault(); e.stopPropagation(); });
  });
  ["dragenter", "dragover"].forEach((evt) => dropzone.addEventListener(evt, () => dropzone.classList.add("dragover")));
  ["dragleave", "drop"].forEach((evt) => dropzone.addEventListener(evt, () => dropzone.classList.remove("dragover")));
  dropzone.addEventListener("drop", (e) => {
    const archivo = e.dataTransfer.files[0];
    if (archivo) subirArchivo(archivo);
  });

  document.getElementById("btn-subir-documento").addEventListener("click", () => abrirModalSubirDocumento(null));
  document.getElementById("btn-subir-documento-vacio")?.addEventListener("click", () => abrirModalSubirDocumento(null));
  document.getElementById("btn-subir-documento-carpeta").addEventListener("click", () => {
    abrirModalSubirDocumento(carpetaActual && carpetaActual !== SIN_CARPETA ? carpetaActual : null);
  });
  document.getElementById("modal-subir-cerrar").addEventListener("click", cerrarModalSubirDocumento);
  document.getElementById("modal-subir-documento").addEventListener("click", (evento) => {
    if (evento.target.id === "modal-subir-documento") cerrarModalSubirDocumento();
  });
  document.getElementById("subir-doc-ahora-no").addEventListener("click", cerrarModalSubirDocumento);
  document.getElementById("subir-doc-generar-preguntas").addEventListener("click", () => {
    const id = subirDocIdActual;
    const archivo = subirDocArchivoActual;
    cerrarModalSubirDocumento();
    if (id) iniciarBanco(id, "preguntas", archivo);
  });
  document.getElementById("subir-doc-generar-tarjetas").addEventListener("click", () => {
    const id = subirDocIdActual;
    const archivo = subirDocArchivoActual;
    cerrarModalSubirDocumento();
    if (id) iniciarBanco(id, "tarjetas", archivo);
  });
}

async function confirmarAnadirDocumentos() {
  const seleccionados = [...seleccionModalAnadir];
  cerrarModalAnadir();
  if (seleccionados.length === 0) return;
  await Promise.all(seleccionados.map((id) => asignarCarpeta(id, carpetaActual)));
  renderizarDocumentosDeCarpeta();
}

function inicializarEventos() {
  document.getElementById("btn-crear-carpeta").addEventListener("click", async () => {
    const nombre = await mostrarPrompt({
      titulo: "Nueva carpeta", label: "Nombre de la carpeta", placeholder: 'Por ejemplo, "Tema 1"',
    });
    if (!nombre || !nombre.trim()) return;
    try {
      await crearCarpetaEnBackend(nombre.trim());
      renderizarCarpetas();
    } catch (e) {
      mostrarErrorGlobal(e.message || "No se pudo crear la carpeta.");
    }
  });

  document.getElementById("btn-volver-carpetas").addEventListener("click", volverACarpetas);

  document.getElementById("btn-eliminar-carpeta").addEventListener("click", async () => {
    if (carpetaActual === SIN_CARPETA) return;
    const cantidad = documentos.filter((d) => d.carpeta === carpetaActual).length;
    const mensaje = cantidad > 0
      ? `Los ${cantidad} documento${cantidad === 1 ? "" : "s"} que tiene dentro pasarán a "Sin carpeta" (no se borran).`
      : `¿Eliminar la carpeta "${carpetaActual}"?`;
    const confirmado = await mostrarConfirmacion({
      titulo: `Eliminar carpeta "${carpetaActual}"`, mensaje, textoAceptar: "Eliminar", peligro: true,
    });
    if (!confirmado) return;

    const token = await idToken();
    await fetch(`${BACKEND_URL}/carpetas-documentos`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ nombre: carpetaActual })
    });
    documentos.forEach((d) => { if (d.carpeta === carpetaActual) d.carpeta = ""; });
    carpetas = carpetas.filter((c) => c !== carpetaActual);
    volverACarpetas();
  });

  document.getElementById("btn-anadir-documentos").addEventListener("click", abrirModalAnadir);
  document.getElementById("modal-anadir-cerrar").addEventListener("click", cerrarModalAnadir);
  document.getElementById("modal-anadir-confirmar").addEventListener("click", confirmarAnadirDocumentos);
  document.getElementById("modal-anadir-documentos").addEventListener("click", (evento) => {
    if (evento.target.id === "modal-anadir-documentos") cerrarModalAnadir();
  });
  document.getElementById("modal-anadir-busqueda").addEventListener("input", (evento) => {
    renderizarListaModalAnadir(evento.target.value);
  });

  document.getElementById("filtro-busqueda").addEventListener("input", (evento) => renderizarBusqueda(evento.target.value));
  document.getElementById("filtro-busqueda-carpeta").addEventListener("input", (evento) => {
    filtroCarpetaActual = evento.target.value;
    renderizarDocumentosDeCarpeta();
  });

  inicializarSubidaDocumento();
}

// Sondeo del progreso de bancos en generación (03/08/2026): cuando se
// llega aquí redirigido desde "Subir PDF" (ver subida-pdf-generar-test/
// subida-pdf-tarjetas), la conexión SSE que iba retransmitiendo el
// progreso se queda en la página anterior -- se pierde al navegar. Para
// que el contador siga actualizándose SOLO, sin que el usuario tenga que
// refrescar a mano, se vuelve a pedir /mis-documentos cada pocos segundos
// mientras algún banco siga "generando", y se para en cuanto no quede
// ninguno.
let temporizadorSondeoBancos = null;

function hayBancosGenerando() {
  return documentos.some((d) => d.banco_preguntas_estado === "generando" || d.banco_tarjetas_estado === "generando");
}

function detenerSondeoBancos() {
  if (temporizadorSondeoBancos) {
    clearTimeout(temporizadorSondeoBancos);
    temporizadorSondeoBancos = null;
  }
}

async function sondearBancosEnGeneracion() {
  temporizadorSondeoBancos = null;
  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/mis-documentos`, { headers: { Authorization: `Bearer ${token}` } });
    if (res.ok) {
      const datos = await res.json();
      pintarCuotaDocumentosMes(datos.cuota_documentos_mes);
      const porId = new Map((datos.documentos || []).map((d) => [d.id, d]));
      documentos.forEach((doc) => {
        const actualizado = porId.get(doc.id);
        if (!actualizado) return;
        doc.banco_preguntas_estado = actualizado.banco_preguntas_estado;
        doc.banco_preguntas_total = actualizado.banco_preguntas_total;
        doc.banco_preguntas_objetivo = actualizado.banco_preguntas_objetivo;
        doc.banco_tarjetas_estado = actualizado.banco_tarjetas_estado;
        doc.banco_tarjetas_total = actualizado.banco_tarjetas_total;
        doc.banco_tarjetas_objetivo = actualizado.banco_tarjetas_objetivo;
      });
      if (carpetaActual !== null) renderizarDocumentosDeCarpeta();
      const query = document.getElementById("filtro-busqueda")?.value;
      if (query) renderizarBusqueda(query);
    }
  } catch (e) {
    // Sondeo silencioso: un fallo puntual (red, token) no debe interrumpir
    // nada -- se reintenta en el siguiente ciclo mientras siga haciendo falta.
  }
  iniciarSondeoBancosSiHaceFalta();
}

function iniciarSondeoBancosSiHaceFalta() {
  if (temporizadorSondeoBancos || !hayBancosGenerando()) return;
  temporizadorSondeoBancos = setTimeout(sondearBancosEnGeneracion, 4000);
}

// Llegada desde "Subir PDF" con ?destacar=<documento_id> (03/08/2026): en
// vez de dejar al usuario buscando en qué carpeta cayó el documento recién
// subido, se abre directamente la vista donde está (o "Sin carpeta") y se
// resalta su tarjeta un momento, para que sea evidente de un vistazo dónde
// seguir el progreso de su banco.
function destacarDocumentoDesdeUrl() {
  const id = new URLSearchParams(window.location.search).get("destacar");
  if (!id) return;
  const doc = documentos.find((d) => d.id === id);
  if (!doc) return;
  abrirCarpeta(doc.carpeta || SIN_CARPETA);
  requestAnimationFrame(() => {
    const tarjeta = document.querySelector(`.documento-card[data-id="${CSS.escape(id)}"]`);
    if (!tarjeta) return;
    tarjeta.scrollIntoView({ behavior: "smooth", block: "center" });
    tarjeta.classList.add("documento-card-destacada");
    setTimeout(() => tarjeta.classList.remove("documento-card-destacada"), 3000);
  });
}

async function cargarDocumentos() {
  const token = await idToken();
  if (!token) {
    window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
    return;
  }
  const { protegerPagina } = await import("/assets/plan.js");
  if (!(await protegerPagina("premium"))) {
    marcarContenidoListo();
    return;
  }

  try {
    const res = await fetch(`${BACKEND_URL}/mis-documentos`, { headers: { Authorization: `Bearer ${token}` } });
    document.getElementById("documentos-cargando").classList.add("hidden");
    if (!res.ok) throw new Error("No se pudieron cargar tus documentos.");
    const datos = await res.json();
    documentos = datos.documentos || [];
    carpetas = datos.carpetas || [];
    pintarCuotaDocumentosMes(datos.cuota_documentos_mes);
    // Se inicializa siempre, incluso con la biblioteca vacía: el botón
    // "Subir documento" del estado vacío usa el mismo modal que el resto.
    inicializarEventos();

    if (documentos.length === 0) {
      document.getElementById("documentos-vacio").classList.remove("hidden");
      return;
    }

    document.getElementById("documentos-contenido").classList.remove("hidden");
    renderizarCarpetas();

    const qInicial = new URLSearchParams(window.location.search).get("q");
    if (qInicial) {
      document.getElementById("filtro-busqueda").value = qInicial;
      renderizarBusqueda(qInicial);
    } else {
      destacarDocumentoDesdeUrl();
    }
    iniciarSondeoBancosSiHaceFalta();
  } catch (e) {
    document.getElementById("documentos-cargando").textContent = e.message || "No se pudieron cargar tus documentos.";
    document.getElementById("documentos-cargando").classList.remove("hidden");
  } finally {
    marcarContenidoListo();
  }
}

cargarDocumentos();
