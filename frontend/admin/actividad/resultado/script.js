// Página propia para que un admin vea el resultado de UN test de un
// usuario exactamente igual que lo ve el propio usuario (mismo módulo de
// render que /mis-tests/resultado/ y otras 8 páginas de usuario:
// /assets/resultados-test.js). Sustituye al antiguo "Ver" en línea de
// /admin/actividad/ para coleccion="tests", que reventaba con un
// TypeError sin capturar (p.opciones es un objeto por letra, no un
// array) y se quedaba colgado en "Cargando…" para siempre.
import { obtenerPermisos, obtenerAuthHeaders, marcarContenidoListo } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { icono } from "/assets/icons.js";

// Mismo mapa que TIPO_INFO en mis-tests/resultado/script.js, para que la
// cabecera de esta página se lea igual que la de un usuario normal.
const TIPO_INFO = {
  personalizado: { iconoHtml: icono("lapiz", 26), label: "Personalizado" },
  oficial: { iconoHtml: icono("edificio", 26), label: "Oficial" },
  inteligente: { iconoHtml: icono("robot", 26), label: "Inteligente IA" },
  repetido: { iconoHtml: icono("repetir", 26), label: "Repetido" },
  falladas: { iconoHtml: icono("cruz", 26), label: "Preguntas falladas" },
  favoritas: { iconoHtml: icono("estrella", 26), label: "Preguntas favoritas" },
  test_pdf: { iconoHtml: icono("subir", 26), label: "Desde un PDF" },
};

function tipoInfo(tipo) {
  return TIPO_INFO[tipo] || { iconoHtml: icono("matraz", 26), label: tipo || "Test" };
}

function escapeHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto == null ? "" : String(texto);
  return div.innerHTML;
}

function formatearFecha(iso) {
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
  } catch {
    return "";
  }
}

function toast(mensaje, tipo = "ok") {
  const cont = document.getElementById("act-res-toasts");
  if (!cont) return;
  const el = document.createElement("div");
  el.className = `admin-toast admin-toast-${tipo}`;
  const nombreIcono = tipo === "error" ? "alerta" : tipo === "ok" ? "check" : "informacion";
  el.innerHTML = `<span class="admin-toast-icono">${icono(nombreIcono, 16)}</span><span>${escapeHtml(mensaje)}</span>`;
  cont.appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transform = "translateY(12px)"; }, 3200);
  setTimeout(() => el.remove(), 3600);
}

async function apiGet(ruta) {
  const headers = await obtenerAuthHeaders();
  if (!headers) return null;
  let resp;
  try {
    resp = await fetch(BACKEND_URL + ruta, { headers });
  } catch {
    toast("Sin conexión con el servidor.", "error");
    return null;
  }
  let datos = {};
  try { datos = await resp.json(); } catch { datos = {}; }
  if (!resp.ok) {
    toast(datos.error || "Ha ocurrido un error.", "error");
    return null;
  }
  return datos;
}

function mostrarErrorPanel(contenedor, mensaje, reintentar) {
  contenedor.innerHTML = `
    <p class="admin-cargando">${escapeHtml(mensaje)}</p>
    <button type="button" class="age-btn age-btn-outline admin-mini act-res-reintentar">Reintentar</button>
  `;
  contenedor.querySelector(".act-res-reintentar").addEventListener("click", reintentar);
}

// listaTemas es solo para agrupar por tema en el resumen -- si el fetch
// falla (o no hay oposición conocida), el resto de la página sigue
// funcionando igual, solo se pierde ese agrupado (mismo criterio que
// mis-tests/resultado/script.js::cargarTemas).
async function cargarTemas(oposicion) {
  if (!oposicion) return [];
  try {
    const headers = await obtenerAuthHeaders();
    if (!headers) return [];
    const res = await fetch(`${BACKEND_URL}/temas-disponibles?oposicion=${encodeURIComponent(oposicion)}`, { headers });
    const datos = await res.json();
    return (datos.temas || []).map((t) => ({ id: t.id, titulo: t.titulo }));
  } catch {
    return [];
  }
}

function pintarCabecera({ uid, coleccion, tipo, fecha }) {
  const info = tipoInfo(tipo);
  document.getElementById("act-res-cabecera").innerHTML = `
    <span class="act-res-cabecera-ico">${info.iconoHtml}</span>
    <div>
      <h1 class="act-res-cabecera-titulo">Resultado — ${escapeHtml(info.label)}</h1>
      <p class="act-res-cabecera-fecha">${escapeHtml(formatearFecha(fecha))}${coleccion === "tests_pdf" ? " · test generado desde un PDF" : ""}</p>
    </div>
  `;
}

async function cargar({ uid, coleccion, id, oposicion, tipo, fecha }) {
  pintarCabecera({ uid, coleccion, tipo, fecha });

  const cargando = document.getElementById("act-res-cargando");
  const render = document.getElementById("act-res-render");

  const [datosItem, listaTemas] = await Promise.all([
    apiGet(`/admin/api/usuarios/${uid}/actividad-completa/item?coleccion=${encodeURIComponent(coleccion)}&id=${encodeURIComponent(id)}`),
    cargarTemas(oposicion),
  ]);

  const preguntas = datosItem && Array.isArray(datosItem.preguntas) ? datosItem.preguntas : null;
  if (!preguntas) {
    mostrarErrorPanel(cargando, "No se ha podido cargar este test.", () => cargar({ uid, coleccion, id, oposicion, tipo, fecha }));
    return;
  }

  const respuestasUsuario = preguntas.map((p) => p.respuesta_usuario ?? null);
  const marcadasDuda = preguntas.map((p) => p.marcada_duda ?? false);

  const { renderizarResultadosTest } = await import("/assets/resultados-test.js");
  renderizarResultadosTest({ contenedor: render, preguntas, respuestasUsuario, listaTemas, marcadasDuda });

  cargando.hidden = true;
}

document.addEventListener("DOMContentLoaded", async () => {
  const permisos = await obtenerPermisos();
  if (!permisos.admin) {
    document.getElementById("act-res-no-autorizado").style.display = "block";
    marcarContenidoListo();
    return;
  }

  const params = new URLSearchParams(location.search);
  const uid = params.get("uid");
  const id = params.get("id");
  const coleccion = params.get("coleccion") || "tests";
  const oposicion = params.get("oposicion") || "";
  const tipo = params.get("tipo") || "";
  const fecha = params.get("fecha") || "";

  if (!uid || !id) {
    document.getElementById("act-res-cargando").innerHTML = `
      <p>Falta el usuario o el test a mostrar en la URL.</p>
      <a href="/admin/actividad/" class="age-btn age-btn-outline">Ir a Actividad completa</a>
    `;
    document.getElementById("act-res-contenido").style.display = "block";
    marcarContenidoListo();
    return;
  }

  document.getElementById("act-res-volver").href = `/admin/actividad/?uid=${encodeURIComponent(uid)}`;
  document.getElementById("act-res-contenido").style.display = "block";
  cargar({ uid, coleccion, id, oposicion, tipo, fecha });
  marcarContenidoListo();
});
