import { idToken, marcarContenidoListo, esAdmin } from "/assets/auth.js";
import { mostrarErrorGlobal } from "/assets/notificaciones.js";
import { icono } from "/assets/icons.js";
import { activarAccesibilidadModal } from "/assets/modal-accesible.js";

const BACKEND_URL = "https://oposicion-age.onrender.com";
const NUEVA_CARPETA = "__nueva__";
// Carpeta especial que agrupa los documentos sin asignar -- no existe como
// tal en el catálogo de carpetas del backend, se calcula aquí a partir de
// qué documentos tienen "carpeta" vacío.
const SIN_CARPETA = "__sin_carpeta__";

document.querySelectorAll("[data-icon]").forEach((el) => {
  el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 24));
});

// Contador de segundos transcurridos mientras se genera un resumen/esquema
// (10/08/2026, a petición del usuario: "algo tipo cuenta atrás real...
// para que el usuario no se desespere"). No es posible dar una cuenta atrás
// exacta -- no hay forma de predecir cuánto tardará DeepSeek en responder --
// pero un contador de tiempo TRANSCURRIDO, en vivo, deja claro que sigue
// habiendo actividad real aunque pase un rato entre un fragmento y el
// siguiente. Actualiza directamente los nodos [data-generando-desde] del
// DOM en vez de volver a pintar la lista entera cada segundo (mucho más
// barato) -- ver filaContenido, que es quien pinta esos nodos con el
// timestamp guardado en el estado persistido (ver leerEstadoProgreso).
function formatearDuracionGenerando(segundos) {
  if (segundos < 60) return `${segundos}s`;
  const minutos = Math.floor(segundos / 60);
  const resto = String(segundos % 60).padStart(2, "0");
  return `${minutos}m ${resto}s`;
}

// Estado de progreso persistido en localStorage (12/08/2026, a petición del
// usuario: "quiero ver el tiempo exacto" -- antes horaInicioProgresoPorClave
// era un objeto en memoria que se reiniciaba a 0 cada vez que se recargaba
// la página, aunque la generación en el servidor siguiera exactamente por
// donde iba). Clave = "documentoId:tipo" (resumen/esquema). Cada entrada
// guarda cuándo empezó de verdad (inicio) y, aparte, en qué fragmento iba
// (completadasEnActualizacion) y cuándo se vio por ÚLTIMA VEZ ese valor
// (momentoActualizacion) -- ver el porqué de estos dos últimos en el
// comentario largo del setInterval de más abajo.
const PREFIJO_ALMACEN_PROGRESO = "mis-documentos:progreso:";

function leerEstadoProgreso(clave) {
  try {
    const bruto = localStorage.getItem(PREFIJO_ALMACEN_PROGRESO + clave);
    return bruto ? JSON.parse(bruto) : null;
  } catch (e) {
    return null; // localStorage deshabilitado/corrupto: se pierde la persistencia, no es crítico.
  }
}

function guardarEstadoProgreso(clave, estado) {
  try {
    localStorage.setItem(PREFIJO_ALMACEN_PROGRESO + clave, JSON.stringify(estado));
  } catch (e) {
    // Igual que arriba: si falla, el contador simplemente no persiste.
  }
}

function borrarEstadoProgreso(clave) {
  try {
    localStorage.removeItem(PREFIJO_ALMACEN_PROGRESO + clave);
  } catch (e) {}
}

setInterval(() => {
  document.querySelectorAll("[data-generando-desde]").forEach((el) => {
    const desde = Number(el.dataset.generandoDesde);
    if (!desde) return;
    const transcurrido = Math.max(0, Math.floor((Date.now() - desde) / 1000));
    // Estimación de tiempo restante (12/08/2026, a petición del usuario:
    // "que se vea cuánto falta, no solo cuánto lleva") -- bug real
    // reportado por el usuario en la primera versión de esto: la fórmula
    // usaba (transcurrido/completadas), y como "transcurrido" crece cada
    // segundo mientras "completadas" se queda fijo hasta el siguiente
    // fragmento, el resultado SUBÍA a la misma velocidad que el propio
    // contador de tiempo transcurrido -- daba la sensación de que cada vez
    // faltaba MÁS, no menos. Ahora es una cuenta atrás real: se calcula UNA
    // estimación fija en el momento en que se vio el último avance real
    // (data-momento-actualizacion, ver filaContenido) y, a partir de ahí,
    // se resta el tiempo que ha pasado desde entonces -- baja segundo a
    // segundo como cualquier cuenta atrás, y solo se recalcula (puede subir
    // o bajar de golpe) cuando de verdad llega un fragmento nuevo.
    const total = Number(el.dataset.total);
    const completadasEnActualizacion = Number(el.dataset.completadasEnActualizacion);
    const momentoActualizacion = Number(el.dataset.momentoActualizacion);
    let estimacion = "";
    if (total && completadasEnActualizacion > 0 && completadasEnActualizacion < total && momentoActualizacion) {
      const transcurridoHastaEsaActualizacion = Math.max(0, (momentoActualizacion - desde) / 1000);
      const tiempoPorFragmento = transcurridoHastaEsaActualizacion / completadasEnActualizacion;
      const estimadoEnEseMomento = tiempoPorFragmento * (total - completadasEnActualizacion);
      const segundosDesdeEsaActualizacion = Math.max(0, (Date.now() - momentoActualizacion) / 1000);
      const segundosRestantes = Math.round(estimadoEnEseMomento - segundosDesdeEsaActualizacion);
      estimacion = ` (~${formatearDuracionGenerando(Math.max(1, segundosRestantes))} más)`;
    }
    el.textContent = ` · ${formatearDuracionGenerando(transcurrido)}${estimacion}`;
  });
}, 1000);

let documentos = [];
let carpetas = [];
// limiteGeneracionesContenido (17/08/2026, ver LIMITE_GENERACIONES_POR_
// DOCUMENTO en documentos_pdf.py): 2 es el valor por defecto real del
// backend, solo para el primer pintado antes de que llegue la respuesta de
// /mis-documentos -- se sobrescribe con el valor real en cuanto llega.
let limiteGeneracionesContenido = 2;
let carpetaActual = null; // null = viendo el listado de carpetas
// esUsuarioAdmin (10/08/2026, a petición del usuario: "quiero un botón
// para parar una generación mía en curso"): se resuelve UNA vez al cargar
// la página (ver cargarDocumentos) y se usa de forma síncrona en los
// render -- esAdmin() es async y filaContenido/filaBanco no lo son, igual
// que documentos/carpetas ya se cargan una vez y se leen sin volver a
// pedirlas en cada render. Solo sirve para MOSTRAR/OCULTAR el botón -- la
// protección real está en requiere_admin, en el backend.
let esUsuarioAdmin = false;

function escaparHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto == null ? "" : String(texto);
  return div.innerHTML;
}

function normalizarTexto(texto) {
  return (texto || "").toString().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
}

// Cuota mensual de documentos NUEVOS SUBIDOS (05/08/2026, alcance corregido
// el 17/08/2026 -- ver banco_pdf_mensual en limites_uso.py): aviso discreto
// para que no te enteres del límite solo cuando lo agotas y sale el 429 --
// sin ninguna cifra de coste, solo el conteo de documentos. Reutilizar un
// documento ya subido en cualquier herramienta no cuenta para este número.
function pintarCuotaDocumentosMes(cuota) {
  const el = document.getElementById("cuota-documentos-mes");
  if (!el) return;
  const usados = cuota?.usados ?? 0;
  const limite = cuota?.limite ?? 0;
  if (!limite || limite <= 0) {
    el.classList.add("hidden");
    return;
  }
  el.textContent = `${usados} de ${limite} documentos subidos este mes`;
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

// Accesibilidad de teclado/foco (25/08/2026): instanciados una sola vez a
// nivel de módulo porque los elementos del DOM son fijos (el modal se
// reutiliza en cada llamada a mostrarConfirmacion/mostrarPrompt, no se crea
// de nuevo) -- ver assets/modal-accesible.js.
const a11yModalConfirmar = activarAccesibilidadModal(document.getElementById("modal-confirmar"), document.getElementById("confirmar-cerrar"));
const a11yModalPrompt = activarAccesibilidadModal(document.getElementById("modal-prompt"), document.getElementById("prompt-cerrar"));

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
      a11yModalConfirmar.alCerrar();
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
    a11yModalConfirmar.alAbrir();
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
      a11yModalPrompt.alCerrar();
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
    // alAbrir() enfoca el contenedor (tabindex="-1") por defecto, pero aquí
    // el propio input de texto es mejor destino de foco inicial -- se pisa
    // justo después, sin renunciar al resto (atrapar Tab, restaurar el foco
    // al cerrar), que sigue haciendo falta.
    a11yModalPrompt.alAbrir();
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

function filaContenido({
  label, iconoHtml, existe, cantidad, urlVer, urlGenerar, urlAleatorias, textoGenerar, urlContinuar,
  textoGenerarDeNuevo = "Generar más", generando = false, progreso = null, error = null,
  documentoId = null, tipoInline = null, limiteAlcanzado = false,
}) {
  // botonGenerar (10/08/2026, a petición del usuario: "que haga lo mismo
  // que banco de preguntas, no te lleve a ningún sitio"): con tipoInline
  // ("resumen"|"esquema") el botón dispara iniciarResumenOEsquema en el
  // sitio en vez de navegar a /subida-pdf-resumen//subida-pdf-esquemas y
  // volver -- mismo patrón data-* que ya usan tarjetas/banco de preguntas
  // (ver data-banco-generar). Tarjetas/Test individuales no pasan
  // tipoInline y se quedan como enlaces, sin cambios.
  const botonGenerar = (texto, clases) => tipoInline
    ? `<button type="button" class="documento-card-btn${clases}" data-generar-contenido="${tipoInline}" data-id="${documentoId}">${texto}</button>`
    : `<a class="documento-card-btn${clases}" href="${urlGenerar}">${texto}</a>`;
  const acciones = [];
  // "Continuar" (test autoguardado sin terminar, ver
  // obtener_tests_en_progreso_por_documento en documentos_pdf.py) se
  // ofrece SIEMPRE que exista, incluso si todavía no hay ningún test
  // finalizado de este documento -- antes, un test empezado y no acabado
  // no aparecía por ningún sitio en la biblioteca, solo "Ver"/"Generar
  // más" (que dependen de haber finalizado al menos uno) o "Generar test"
  // desde cero. Es la única acción que se pinta sólida (".principal"): al
  // ser la única realmente urgente/de sesión y aparecer sola (nunca varias
  // a la vez), no se suma al "muro de naranja" que sí generarían varias
  // acciones sólidas repetidas en la misma cuadrícula (ver ".orange" más
  // abajo, a petición del usuario 05/08/2026).
  if (urlContinuar) {
    acciones.push(`<a class="documento-card-btn principal" href="${urlContinuar}">Continuar</a>`);
  }
  // generando manda sobre existe (10/08/2026, a petición del usuario): al
  // pulsar "Regenerar" sobre un tipo que YA existía, antes se seguían
  // mostrando los botones "Ver"/"Regenerar" de la versión vieja mientras
  // se generaba la nueva -- daba la sensación de que no había pasado nada
  // al pulsar. Mientras se está regenerando no se ofrece ningún botón,
  // igual que la primera vez que se genera algo, hasta que el sondeo
  // confirma que la nueva versión ya está guardada.
  if (generando) {
    // Botón "Detener" (10/08/2026, a petición explícita del usuario:
    // "quiero un botón para parar una generación mía en curso, no quiero
    // consumir tokens de más haciendo pruebas") -- solo visible para
    // cuentas admin (ver esUsuarioAdmin) y solo en resumen/esquema
    // (tipoInline), las únicas dos que pasan por aquí con generando=true;
    // el resto de las acciones se ocultan igual que antes.
    if (esUsuarioAdmin && tipoInline) {
      acciones.push(`<button type="button" class="documento-card-btn" data-detener-contenido="${tipoInline}" data-id="${documentoId}">Detener</button>`);
    }
  } else if (existe) {
    acciones.push(`<a class="documento-card-btn orange" href="${urlVer}">Ver</a>`);
    if (urlAleatorias) {
      acciones.push(`<a class="documento-card-btn" href="${urlAleatorias}">10 aleatorias</a>`);
    }
    // limiteAlcanzado (17/08/2026, ver LIMITE_GENERACIONES_POR_DOCUMENTO en
    // documentos_pdf.py): sin esto, "Regenerar" seguiría pulsándose y el
    // backend lo rechazaría con un 429 -- mejor no ofrecerlo directamente
    // en cuanto se agota, con una nota que explique por qué.
    if (tipoInline && limiteAlcanzado) {
      acciones.push(`<span class="documento-card-limite-nota">Límite de regeneraciones alcanzado</span>`);
    } else {
      acciones.push(botonGenerar(textoGenerarDeNuevo, ""));
    }
  } else {
    acciones.push(botonGenerar(textoGenerar, " orange"));
  }
  const etiquetaCantidad = existe && cantidad ? ` (${cantidad})` : "";
  // Estado (05/08/2026, rediseño visual): antes la única señal de si un
  // tipo de contenido ya existía era el propio texto del botón ("Ver" vs.
  // "Generar resumen") -- fácil de pasar por alto en un vistazo rápido.
  // Ahora cada tipo lleva un estado explícito (Generado/En progreso/Aún no
  // generado) junto al icono, igual que ya hacía el banco adaptativo con
  // sus propios estados más abajo.
  // "generando" (10/08/2026, a petición del usuario): resumen/esquema se
  // generan en el servidor sin bloquear la pestaña (ver mostrarRedireccion
  // AMisDocumentos en subida-pdf-resumen/subida-pdf-esquemas), así que al
  // llegar aquí recién redirigido no había ninguna señal de que se
  // estuviera trabajando en ello -- solo "Aún no generado", indistinguible
  // de no haberlo pedido nunca. El estado lo arma destacarDocumentoDesdeUrl
  // a partir de ?generando=resumen|esquema y lo sondea sondearBancosEnGeneracion.
  // Texto de progreso real (10/08/2026, a petición del usuario: "no sé qué
  // está pasando, pon una barra o un contador") -- progreso viene de
  // doc.progreso_resumen/progreso_esquema, que refleja de verdad en qué
  // fragmento va la generación en el servidor (ver actualizar_progreso_
  // generacion en documentos_pdf.py), no una estimación ni una barra
  // decorativa.
  const textoGenerando = progreso && progreso.total
    ? progreso.fase === "fusionando"
      ? "Generando… uniendo las partes"
      : `Generando… (${progreso.completadas}/${progreso.total})`
    : "Generando…";
  // Timestamp para el contador de tiempo transcurrido (ver el setInterval
  // global junto a formatearDuracionGenerando): el estado persistido (ver
  // leerEstadoProgreso) ya lo deja puesto la propia llamada a
  // esperandoGeneracionDe que calculó "generando"
  // (progresoDelServidorSigueSiendoValido lo arma la primera vez que ve
  // progreso real de este documento+tipo), así que aquí solo hace falta
  // leerlo -- y, si el nº de fragmentos completados avanzó desde la última
  // vez, actualizar también el punto de referencia de la estimación de
  // tiempo restante (ver el comentario largo del setInterval).
  const claveGenerando = documentoId && tipoInline ? `${documentoId}:${tipoInline}` : null;
  let estadoGenerando = claveGenerando ? leerEstadoProgreso(claveGenerando) : null;
  if (estadoGenerando && progreso && progreso.completadas > 0
      && progreso.completadas !== estadoGenerando.completadasEnActualizacion) {
    estadoGenerando = { ...estadoGenerando, completadasEnActualizacion: progreso.completadas, momentoActualizacion: Date.now() };
    guardarEstadoProgreso(claveGenerando, estadoGenerando);
  }
  const desdeGenerando = estadoGenerando ? estadoGenerando.inicio : null;
  // data-total/data-completadas-en-actualizacion/data-momento-actualizacion
  // (12/08/2026, a petición del usuario: "que se vea cuánto falta, no solo
  // cuánto lleva"): el setInterval global los lee en cada tick para
  // calcular una ESTIMACIÓN de tiempo restante a partir de la velocidad
  // real observada hasta el último avance, nunca de una cuenta atrás
  // inventada. Solo tiene sentido en fase "generando" (con fracción real
  // de progreso) y con al menos 1 completada -- con 0 no hay ninguna
  // velocidad que extrapolar todavía.
  const datosEstimacion = generando && progreso && progreso.fase !== "fusionando" && estadoGenerando && estadoGenerando.completadasEnActualizacion > 0
    ? ` data-total="${progreso.total}" data-completadas-en-actualizacion="${estadoGenerando.completadasEnActualizacion}" data-momento-actualizacion="${estadoGenerando.momentoActualizacion}"`
    : "";
  const contadorTiempoHtml = generando && desdeGenerando
    ? `<span data-generando-desde="${desdeGenerando}"${datosEstimacion}></span>`
    : "";
  // Barra de progreso real (12/08/2026, refuerzo visual del texto de
  // arriba): solo con fracción real disponible (progreso.total), igual que
  // textoGenerando -- en fase "fusionando" completadas==total, así que se
  // ve llena (correcto: el MAP ya terminó, solo falta el último paso).
  const barraProgresoHtml = generando && progreso && progreso.total
    ? `<div class="documento-card-progreso-barra"><div class="documento-card-progreso-barra-relleno" style="width: ${Math.round((progreso.completadas / progreso.total) * 100)}%"></div></div>`
    : "";
  const estadoHtml = urlContinuar
    ? `<span class="documento-card-tipo-estado documento-card-tipo-estado-progreso">${icono("reloj", 12)} Test en progreso</span>`
    : generando
      ? `<span class="documento-card-tipo-estado documento-card-tipo-estado-progreso">${icono("reloj", 12)} ${textoGenerando}${contadorTiempoHtml}</span>${barraProgresoHtml}`
      : existe
        ? `<span class="documento-card-tipo-estado documento-card-tipo-estado-generado">${icono("check", 12)} Generado</span>`
        : `<span class="documento-card-tipo-estado">Aún no generado</span>`;
  // Aviso de que el ÚLTIMO intento falló (10/08/2026, a petición del
  // usuario: "que regenere de verdad, no que cargue datos antiguos") --
  // sin esto, un "Regenerar" que falla es indistinguible de uno que nunca
  // se pidió: el resumen/esquema anterior (si lo había) se queda tal
  // cual, sin ninguna señal de que el intento nuevo no funcionó. No se
  // muestra mientras generando (el aviso de arriba ya lo deja claro) ni
  // se pisa a sí mismo si justo se acaba de generar bien.
  const avisoErrorHtml = (!generando && error)
    ? `<span class="documento-card-tipo-estado documento-card-tipo-estado-error">${icono("alerta", 12)} El último intento de generar falló${existe ? " -- sigue viéndose la versión anterior" : ""}</span>`
    : "";
  return `
    <div class="documento-card-tipo">
      <div class="documento-card-tipo-cabecera">
        <span class="documento-card-tipo-icono">${iconoHtml}</span>
        <div class="documento-card-tipo-info">
          <span class="documento-card-tipo-label">${label}${etiquetaCantidad}</span>
          ${estadoHtml}
          ${avisoErrorHtml}
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
    acciones.push(`<button type="button" class="documento-card-btn orange" data-banco-generar="${tipo}" data-id="${doc.id}">Generar</button>`);
  } else {
    if (estado === "generando") {
      // Sin el tope interno (antes "1/100"): el usuario no tiene por qué
      // saber cuál es el techo de seguridad del banco, solo cuántas lleva
      // generadas hasta ahora -- este número se actualiza en vivo según
      // van llegando eventos de progreso (ver iniciarBanco).
      estadoHtml = `<span class="documento-card-tipo-estado documento-card-tipo-estado-progreso">${icono("reloj", 12)} Generando… ${total} ${nombreItem}${total === 1 ? "" : "s"} hasta ahora</span>`;
      // Botón "Detener" (10/08/2026, a petición explícita del usuario) --
      // ver el mismo comentario largo en filaContenido.
      if (esUsuarioAdmin) {
        acciones.push(`<button type="button" class="documento-card-btn" data-detener-banco="${tipo}" data-id="${doc.id}">Detener</button>`);
      }
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
      acciones.push(`<a class="documento-card-btn${estado === "completo" ? " orange" : ""}" href="${rutaPractica}?documento_id=${doc.id}&ver=${paramVer}">${etiquetaAccion} de todas (${total})</a>`);
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

// iniciarResumenOEsquema (10/08/2026, a petición explícita del usuario:
// "que haga lo mismo que banco de preguntas, no te lleve a ningún sitio y
// que salga lo de generando"): calcada de iniciarBanco -- POST en el
// sitio, sin navegar, leyendo el SSE completo para reflejar el progreso
// real de inmediato (no solo al llegar el siguiente sondeo de 4s). Antes,
// Generar/Regenerar en Resumen/Esquema navegaban a /subida-pdf-resumen//
// subida-pdf-esquemas y volvían -- las únicas dos herramientas de
// "Contenido generado" que aún sacaban al usuario de "Mis documentos"
// (Tarjetas/Test individuales, y el banco adaptativo, ya no lo hacían).
//
// documentoEsperandoContenido/tipoContenidoEsperando/intentosSondeoContenido
// (ver más abajo, junto a esperandoGeneracionDe) son el mismo estado que
// arma destacarDocumentoDesdeUrl al volver redirigido con
// ?generando=resumen|esquema -- reutilizado aquí tal cual para que la
// tarjeta muestre "Generando…" desde el primer instante, sin inventar un
// mecanismo aparte.
async function iniciarResumenOEsquema(documentoId, tipo) {
  const doc = documentos.find((d) => d.id === documentoId);
  documentoEsperandoContenido = documentoId;
  tipoContenidoEsperando = tipo;
  intentosSondeoContenido = MAX_INTENTOS_SONDEO_CONTENIDO;
  const refrescar = () => {
    if (carpetaActual !== null) renderizarDocumentosDeCarpeta();
    const query = document.getElementById("filtro-busqueda")?.value;
    if (query) renderizarBusqueda(query);
  };
  refrescar();
  iniciarSondeoBancosSiHaceFalta();

  try {
    const token = await idToken();
    const ruta = tipo === "resumen" ? "resumir-documento" : "generar-esquema-desde-pdf";
    const formData = new FormData();
    formData.append("documento_id", documentoId);
    const res = await fetch(`${BACKEND_URL}/${ruta}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData
    });
    if (!res.ok || !res.body) {
      const datos = await res.json().catch(() => ({}));
      throw new Error(datos.error || "No se pudo iniciar la generación.");
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
          if (doc) doc[`progreso_${tipo}`] = { completadas: evento.completadas, total: evento.total, fase: evento.fase };
          refrescar();
        } else if (evento.tipo === "fin") {
          terminado = true;
          intentosSondeoContenido = 0;
          if (doc) {
            doc[`progreso_${tipo}`] = null;
            if (evento[tipo]) {
              doc[tipo === "resumen" ? "tiene_resumen" : "tiene_esquema"] = true;
              // generaciones_resumen/generaciones_esquema (17/08/2026): se
              // incrementa aquí en local para que "Regenerar" desaparezca
              // de inmediato al agotar el límite, sin esperar a una
              // recarga completa de /mis-documentos (ver limiteAlcanzado
              // en filaContenido).
              doc[`generaciones_${tipo}`] = (doc[`generaciones_${tipo}`] || 0) + 1;
              doc[`error_${tipo}`] = null;
            } else {
              doc[`error_${tipo}`] = { mensaje: evento.error || "Error desconocido" };
            }
          }
        }
      }
    }
  } catch (e) {
    intentosSondeoContenido = 0;
    if (doc) doc[`progreso_${tipo}`] = null;
    mostrarErrorGlobal(e.message || "No se pudo generar el contenido.");
  } finally {
    refrescar();
  }
}

// detenerGeneracion (10/08/2026, a petición explícita del usuario: "quiero
// un botón para parar una generación mía en curso, no quiero consumir
// tokens de más haciendo pruebas") -- solo llega aquí si esUsuarioAdmin
// pintó el botón, pero la protección real es requiere_admin en el
// backend. herramienta es "resumen"|"esquema"|"banco_preguntas"|
// "banco_tarjetas". No cierra el stream SSE en curso ni cambia el estado
// local al momento: el propio hilo de fondo (deepseek_utils.py/
// test_generator.py/tarjetas_generator.py) deja de lanzar rondas nuevas en
// su siguiente punto de control y termina con lo que ya tuviera, así que
// el sondeo/SSE que ya está en marcha reflejará el resultado final solo.
async function detenerGeneracion(documentoId, herramienta) {
  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/pdf-ia/documento/${documentoId}/detener/${herramienta}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      const datos = await res.json().catch(() => ({}));
      throw new Error(datos.error || "No se pudo detener la generación.");
    }
  } catch (e) {
    mostrarErrorGlobal(e.message || "No se pudo detener la generación.");
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
      textoGenerar: "Generar",
      // "Regenerar" (05/08/2026, a petición del usuario), no "Generar más":
      // a diferencia de tarjetas/test (que SÍ acumulan, "más" es literal),
      // solo existe UN resumen/esquema por documento -- volver a pulsar
      // sustituye el que ya había, no añade otro. "Generar más" daba a
      // entender que se acumulaba algo, cuando en realidad se sobrescribe.
      textoGenerarDeNuevo: "Regenerar",
      generando: esperandoGeneracionDe(doc, "resumen"),
      progreso: doc.progreso_resumen,
      error: doc.error_resumen,
      // documentoId/tipoInline (10/08/2026): genera en el sitio, sin
      // navegar -- ver botonGenerar/iniciarResumenOEsquema.
      documentoId: doc.id, tipoInline: "resumen",
      limiteAlcanzado: (doc.generaciones_resumen || 0) >= limiteGeneracionesContenido
    }),
    filaContenido({
      label: "Esquema", iconoHtml: icono("esquema", 18), existe: doc.tiene_esquema,
      urlVer: `/subida-pdf-esquemas/?documento_id=${doc.id}&ver=esquema`,
      textoGenerar: "Generar",
      textoGenerarDeNuevo: "Regenerar",
      generando: esperandoGeneracionDe(doc, "esquema"),
      progreso: doc.progreso_esquema,
      error: doc.error_esquema,
      documentoId: doc.id, tipoInline: "esquema",
      limiteAlcanzado: (doc.generaciones_esquema || 0) >= limiteGeneracionesContenido
    }),
    filaContenido({
      label: "Tarjetas", iconoHtml: icono("tarjeta", 18), existe: doc.num_tarjetas > 0, cantidad: doc.num_tarjetas,
      urlVer: `/subida-pdf-tarjetas/?documento_id=${doc.id}&ver=tarjetas&modo=todas`,
      urlAleatorias: `/subida-pdf-tarjetas/?documento_id=${doc.id}&ver=tarjetas&modo=aleatorias&cantidad=10`,
      urlGenerar: `/subida-pdf-tarjetas/?documento_id=${doc.id}`,
      textoGenerar: "Generar"
    }),
    filaContenido({
      label: "Test", iconoHtml: icono("matraz", 18), existe: doc.num_tests > 0,
      cantidad: doc.num_tests ? `${doc.num_tests} intento${doc.num_tests > 1 ? "s" : ""}` : null,
      urlVer: `/subida-pdf-generar-test/?documento_id=${doc.id}&ver=test`,
      urlGenerar: `/subida-pdf-generar-test/?documento_id=${doc.id}`,
      urlContinuar: doc.test_en_progreso ? `/subida-pdf-generar-test/?resume=${doc.test_en_progreso}` : null,
      textoGenerar: "Generar"
    })
  ].join("");
  const filasBanco = [filaBanco(doc, "preguntas"), filaBanco(doc, "tarjetas")].join("");

  return `
    <div class="documento-card" data-id="${doc.id}">
      <div class="documento-card-header">
        <div class="documento-card-icon">${icono("libro", 26)}</div>
        <div class="documento-card-header-info">
          <p class="documento-card-titulo">
            ${escaparHtml(nombreCorto)}
            <button type="button" class="documento-card-renombrar" data-id="${doc.id}" aria-label="Renombrar documento" title="Renombrar documento">${icono("lapiz", 14)}</button>
            <button type="button" class="documento-card-eliminar" data-id="${doc.id}" aria-label="Eliminar documento" title="Eliminar documento">${icono("papelera", 14)}</button>
          </p>
          <p class="documento-card-meta">${escaparHtml(meta)}</p>
        </div>
      </div>
      ${seccionCarpeta(doc, modoCarpeta)}
      <a class="documento-card-chat-btn" href="/subida-pdf-chat-pdf/?documento_id=${doc.id}">${icono("chat", 18)} Chat PDF</a>
      <p class="documento-card-seccion-titulo">Contenido generado</p>
      <div class="documento-card-tipos documento-card-tipos-grid">${filasContenido}</div>
      <p class="documento-card-seccion-titulo">Banco de práctica</p>
      <div class="documento-card-tipos">${filasBanco}</div>
    </div>
  `;
}

function tarjetaCarpeta(idCarpeta, nombreMostrado, cantidad, esEspecial) {
  return `
    <button type="button" class="carpeta-tile${esEspecial ? " carpeta-tile-especial" : ""}" data-carpeta="${escaparHtml(idCarpeta)}">
      <span class="carpeta-tile-flecha" aria-hidden="true">→</span>
      <span class="carpeta-tile-icono">${esEspecial ? icono("documento", 22) : icono("carpeta", 22)}</span>
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
      <span class="carpeta-tile-flecha" aria-hidden="true">→</span>
      <span class="carpeta-tile-icono">${icono("documento", 22)}</span>
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
  contenedor.querySelectorAll("[data-generar-contenido]").forEach((boton) => {
    boton.addEventListener("click", () => iniciarResumenOEsquema(boton.dataset.id, boton.dataset.generarContenido));
  });
  contenedor.querySelectorAll("[data-detener-contenido]").forEach((boton) => {
    boton.addEventListener("click", () => detenerGeneracion(boton.dataset.id, boton.dataset.detenerContenido));
  });
  contenedor.querySelectorAll("[data-detener-banco]").forEach((boton) => {
    boton.addEventListener("click", () => detenerGeneracion(boton.dataset.id, `banco_${boton.dataset.detenerBanco}`));
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
  const cantidad = documentos.filter((d) => (esSinCarpeta ? !d.carpeta : d.carpeta === idCarpeta)).length;
  document.getElementById("carpeta-detalle-subtitulo").textContent = `${cantidad} documento${cantidad === 1 ? "" : "s"}`;
  const iconoCabecera = document.getElementById("carpeta-detalle-icono");
  iconoCabecera.innerHTML = icono(esSinCarpeta ? "documento" : "carpeta", 20);
  iconoCabecera.classList.toggle("carpeta-detalle-icono-especial", esSinCarpeta);
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
  resultados.querySelectorAll("[data-generar-contenido]").forEach((boton) => {
    boton.addEventListener("click", () => iniciarResumenOEsquema(boton.dataset.id, boton.dataset.generarContenido));
  });
  resultados.querySelectorAll("[data-detener-contenido]").forEach((boton) => {
    boton.addEventListener("click", () => detenerGeneracion(boton.dataset.id, boton.dataset.detenerContenido));
  });
  resultados.querySelectorAll("[data-detener-banco]").forEach((boton) => {
    boton.addEventListener("click", () => detenerGeneracion(boton.dataset.id, `banco_${boton.dataset.detenerBanco}`));
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

const a11yModalAnadir = activarAccesibilidadModal(document.getElementById("modal-anadir-documentos"), document.getElementById("modal-anadir-cerrar"));

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
  a11yModalAnadir.alAbrir();
}

function cerrarModalAnadir() {
  document.getElementById("modal-anadir-documentos").classList.add("hidden");
  a11yModalAnadir.alCerrar();
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

const a11yModalSubir = activarAccesibilidadModal(document.getElementById("modal-subir-documento"), document.getElementById("modal-subir-cerrar"));

function abrirModalSubirDocumento(carpetaDestino) {
  subirDocCarpetaDestino = carpetaDestino || null;
  subirDocIdActual = null;
  subirDocArchivoActual = null;
  document.getElementById("subir-doc-input").value = "";
  document.getElementById("subir-doc-paso-elegir").classList.add("hidden");
  document.getElementById("subir-doc-paso-cargando").classList.add("hidden");
  document.getElementById("subir-doc-paso-archivo").classList.remove("hidden");
  document.getElementById("modal-subir-documento").classList.remove("hidden");
  a11yModalSubir.alAbrir();
}

function cerrarModalSubirDocumento() {
  document.getElementById("modal-subir-documento").classList.add("hidden");
  a11yModalSubir.alCerrar();
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
  if (datos.limite_generaciones_contenido) limiteGeneracionesContenido = datos.limite_generaciones_contenido;
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

// Resumen/esquema "sin esperar" (05/08/2026): igual que el banco, ahora
// /resumir-pdf y /generar-esquema-desde-pdf redirigen aquí ANTES de que la
// generación termine (ver mostrarRedireccionAMisDocumentos en subida-pdf-
// resumen/subida-pdf-esquemas), guardándose sola en el servidor.
//
// documentoEsperandoContenido/tipoContenidoEsperando/intentosSondeoContenido
// (armados por destacarDocumentoDesdeUrl al llegar con
// ?generando=resumen|esquema) cubren "acabo de llegar redirigido, sigo
// atento un rato" -- pero un usuario real puede haber cerrado la pestaña
// y vuelto más tarde, o refrescado la página, perdiendo ese estado aunque
// el servidor SIGA generando de verdad. doc.progreso_resumen/
// progreso_esquema (10/08/2026, ver actualizar_progreso_generacion en
// documentos_pdf.py) es la fuente de verdad real -- lo pone el propio
// servidor mientras trabaja y lo quita al terminar, así que decir
// "generando" en base a esto es fiable pase lo que pase en el navegador.
let documentoEsperandoContenido = null;
let tipoContenidoEsperando = null; // "resumen" | "esquema"
let intentosSondeoContenido = 0;
const MAX_INTENTOS_SONDEO_CONTENIDO = 20; // ~80s a 4s cada uno, margen amplio

// Tope de seguridad del lado del cliente (10/08/2026): el servidor limpia
// progreso_resumen/progreso_esquema SIEMPRE al terminar, con éxito o sin
// él -- pero un fallo catastrófico de verdad (el proceso muriendo a media
// generación, no un error normal ya cubierto) podría dejarlo pegado en
// Firestore para siempre, lo que enseñaría "Generando…" de forma
// indefinida a cualquiera que mirara ese documento en el futuro. Pasado
// este margen desde que se VIO por primera vez el progreso de un
// documento+tipo concreto, se deja de confiar en él aunque Firestore siga
// diciendo que sigue activo.
// 5 minutos desde que empezó DE VERDAD (estado.inicio, persistido -- ver
// leerEstadoProgreso/guardarEstadoProgreso más arriba), no desde que el
// navegador lo vio por primera vez: antes, al recargar la página a mitad
// de una generación larga, este margen se reiniciaba sin querer.
const MAX_ESPERA_PROGRESO_SERVIDOR_MS = 5 * 60 * 1000; // 5 minutos

function progresoDelServidorSigueSiendoValido(doc, tipo) {
  const clave = `${doc.id}:${tipo}`;
  if (!doc[`progreso_${tipo}`]) {
    borrarEstadoProgreso(clave);
    return false;
  }
  let estado = leerEstadoProgreso(clave);
  if (!estado) {
    estado = { inicio: Date.now(), completadasEnActualizacion: 0, momentoActualizacion: Date.now() };
    guardarEstadoProgreso(clave, estado);
  }
  const sigueSiendoValido = Date.now() - estado.inicio < MAX_ESPERA_PROGRESO_SERVIDOR_MS;
  // Si se supera el margen, se deja de confiar en el progreso Y se borra el
  // estado guardado (12/08/2026, bug real evitado: al persistir en
  // localStorage en vez de en memoria, un estado "atascado" que antes se
  // perdía solo con recargar la página ahora podría sobrevivir para
  // siempre -- y si el usuario vuelve a generar el mismo documento+tipo
  // más adelante, reutilizaría por error el inicio/última actualización
  // de aquel intento fallido en vez de empezar un cronómetro limpio).
  if (!sigueSiendoValido) borrarEstadoProgreso(clave);
  return sigueSiendoValido;
}

// Usado por tarjetaDocumento/filaContenido (10/08/2026) para pintar el
// estado "Generando…" del tipo concreto que se está sondeando -- antes
// este sondeo solo servía para saber cuándo parar y resaltar la tarjeta,
// sin ningún reflejo visual mientras tanto, así que el usuario no tenía
// forma de saber si había pasado algo al pulsar "Generar" y volver aquí.
function esperandoGeneracionDe(doc, tipo) {
  const porLlegadaReciente =
    intentosSondeoContenido > 0 && documentoEsperandoContenido === doc.id && tipoContenidoEsperando === tipo;
  return porLlegadaReciente || progresoDelServidorSigueSiendoValido(doc, tipo);
}

function hayBancosGenerando() {
  return documentos.some((d) => d.banco_preguntas_estado === "generando" || d.banco_tarjetas_estado === "generando");
}

function hayResumenesOEsquemasGenerando() {
  return documentos.some((d) =>
    progresoDelServidorSigueSiendoValido(d, "resumen") || progresoDelServidorSigueSiendoValido(d, "esquema")
  );
}

function hayAlgoGenerando() {
  return hayBancosGenerando() || hayResumenesOEsquemasGenerando() || intentosSondeoContenido > 0;
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
      if (datos.limite_generaciones_contenido) limiteGeneracionesContenido = datos.limite_generaciones_contenido;
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
        doc.tiene_resumen = actualizado.tiene_resumen;
        doc.tiene_esquema = actualizado.tiene_esquema;
        // progreso_resumen/progreso_esquema (10/08/2026, a petición del
        // usuario: "no sé qué está pasando, pon una barra o un contador"):
        // {completadas, total, fase} mientras el servidor sigue
        // generando, o null si no hay ninguna generación en curso -- ver
        // actualizar_progreso_generacion en documentos_pdf.py.
        doc.progreso_resumen = actualizado.progreso_resumen;
        doc.progreso_esquema = actualizado.progreso_esquema;
        // error_resumen/error_esquema (10/08/2026, a petición del usuario:
        // "que regenere de verdad, no que cargue datos antiguos"): último
        // intento fallido, ver marcar_error_generacion en documentos_pdf.py.
        doc.error_resumen = actualizado.error_resumen;
        doc.error_esquema = actualizado.error_esquema;
      });
      if (intentosSondeoContenido > 0) {
        intentosSondeoContenido--;
        const docEsperado = documentos.find((d) => d.id === documentoEsperandoContenido);
        const listo = docEsperado && (
          (tipoContenidoEsperando === "resumen" && docEsperado.tiene_resumen) ||
          (tipoContenidoEsperando === "esquema" && docEsperado.tiene_esquema)
        );
        if (listo) intentosSondeoContenido = 0;
      }
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
  if (temporizadorSondeoBancos || !hayAlgoGenerando()) return;
  temporizadorSondeoBancos = setTimeout(sondearBancosEnGeneracion, 4000);
}

// Llegada desde "Subir PDF" con ?destacar=<documento_id> (03/08/2026): en
// vez de dejar al usuario buscando en qué carpeta cayó el documento recién
// subido, se abre directamente la vista donde está (o "Sin carpeta") y se
// resalta su tarjeta un momento, para que sea evidente de un vistazo dónde
// seguir el progreso de su banco. Con &generando=resumen|esquema
// (05/08/2026, ver subida-pdf-resumen/subida-pdf-esquemas) arranca además
// el sondeo de ese contenido concreto -- ver intentosSondeoContenido.
function destacarDocumentoDesdeUrl() {
  const params = new URLSearchParams(window.location.search);
  const id = params.get("destacar");
  if (!id) return;
  const generando = params.get("generando");
  if (generando === "resumen" || generando === "esquema") {
    documentoEsperandoContenido = id;
    tipoContenidoEsperando = generando;
    intentosSondeoContenido = MAX_INTENTOS_SONDEO_CONTENIDO;
    iniciarSondeoBancosSiHaceFalta();
  }
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
  esUsuarioAdmin = await esAdmin();

  try {
    const res = await fetch(`${BACKEND_URL}/mis-documentos`, { headers: { Authorization: `Bearer ${token}` } });
    document.getElementById("documentos-cargando").classList.add("hidden");
    if (!res.ok) throw new Error("No se pudieron cargar tus documentos.");
    const datos = await res.json();
    documentos = datos.documentos || [];
    carpetas = datos.carpetas || [];
    pintarCuotaDocumentosMes(datos.cuota_documentos_mes);
    if (datos.limite_generaciones_contenido) limiteGeneracionesContenido = datos.limite_generaciones_contenido;
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
    // Botón "Reintentar" (25/08/2026, bug real de la auditoría): antes se
    // dejaba el mensaje de error fijo, sin ninguna forma de recargar salvo
    // refrescar la página entera a mano.
    const cont = document.getElementById("documentos-cargando");
    cont.innerHTML = `
      <p>${escaparHtml(e.message || "No se pudieron cargar tus documentos.")}</p>
      <button type="button" class="age-btn age-btn-outline" id="documentos-reintentar">Reintentar</button>
    `;
    cont.classList.remove("hidden");
    document.getElementById("documentos-reintentar").addEventListener("click", cargarDocumentos);
  } finally {
    marcarContenidoListo();
  }
}

cargarDocumentos();
