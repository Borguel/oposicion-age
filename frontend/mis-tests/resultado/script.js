import { idToken } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";

const TIPO_INFO = {
  personalizado: { icono: "📝", label: "Personalizado" },
  oficial: { icono: "🏛️", label: "Oficial" },
  inteligente: { icono: "🤖", label: "Inteligente IA" },
  repetido: { icono: "🔁", label: "Repetido" },
  falladas: { icono: "❌", label: "Preguntas falladas" },
};

function tipoInfo(tipo) {
  return TIPO_INFO[tipo] || { icono: "🧪", label: tipo || "Test" };
}

function formatearFecha(iso) {
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
  } catch (e) {
    return "";
  }
}

async function cargarTemas(oposicion, token) {
  try {
    const res = await fetch(`${BACKEND_URL}/temas-disponibles?oposicion=${encodeURIComponent(oposicion)}`, { headers: { Authorization: `Bearer ${token}` } });
    const datos = await res.json();
    return (datos.temas || []).map((t) => ({ id: t.id, titulo: t.titulo }));
  } catch (e) {
    return [];
  }
}

async function inicializar() {
  const token = await idToken();
  if (!token) {
    window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname + window.location.search);
    return;
  }

  const params = new URLSearchParams(window.location.search);
  const testId = params.get("id");
  if (!testId) {
    document.getElementById("resultado-cargando").textContent = "Falta el identificador del test.";
    return;
  }

  document.querySelectorAll("[data-repetir-link]").forEach((a) => {
    a.href = `/repetir-test/?repetir=${testId}`;
  });

  try {
    const { obtenerOposicionActual } = await import("/assets/oposicion.js");
    const oposicion = obtenerOposicionActual();
    const [listaTemas, res] = await Promise.all([
      cargarTemas(oposicion, token),
      fetch(`${BACKEND_URL}/mi-test/${testId}`, { headers: { Authorization: `Bearer ${token}` } })
    ]);
    const datos = await res.json();
    if (!res.ok || !datos.test) throw new Error(datos.error || "No se pudo cargar el test.");

    const test = datos.test;
    const preguntas = test.preguntas || [];
    const respuestasUsuario = preguntas.map((p) => p.respuesta_usuario ?? null);

    const info = tipoInfo(test.tipo);
    document.getElementById("resultado-icono").textContent = info.icono;
    document.getElementById("resultado-titulo").textContent = `Resultados — ${info.label}`;
    document.getElementById("resultado-fecha").textContent = formatearFecha(test.fecha);

    const { renderizarResultadosTest } = await import("/assets/resultados-test.js");
    renderizarResultadosTest({
      contenedor: document.getElementById("resultado-render"),
      preguntas,
      respuestasUsuario,
      listaTemas
    });

    document.getElementById("resultado-cargando").classList.add("hidden");
    document.getElementById("resultado-contenido").classList.remove("hidden");
  } catch (e) {
    document.getElementById("resultado-cargando").textContent = e.message || "No se pudieron cargar los resultados.";
  }
}

inicializar();
