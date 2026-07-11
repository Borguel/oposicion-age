// Service worker mínimo: solo cachea los estáticos propios (/assets/) para
// que la web sea instalable como PWA y funcione algo incluso sin red.
// Deliberadamente NO cachea HTML ni llamadas a la API (todo lo demás pasa
// siempre por red) para no servir nunca datos de usuario o resultados de
// tests obsoletos.
//
// Estrategia red-primero (con la caché como fallback offline), no
// cache-first: con cache-first, un dispositivo que ya hubiera visitado la
// web se quedaba sirviendo para siempre el CSS/JS de la primera visita,
// sin enterarse nunca de despliegues posteriores (esto llegó a pasar de
// verdad: un usuario veía un rediseño ya publicado sin los estilos nuevos
// en una tablet que llevaba tiempo sin cerrar la pestaña). Con red-primero,
// cada carga intenta la red primero (así siempre se ve la última versión)
// y solo cae a la caché si de verdad no hay conexión.
const CACHE = "age-static-v1";

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((claves) =>
      Promise.all(claves.filter((c) => c !== CACHE).map((c) => caches.delete(c)))
    )
  );
  self.clients.claim();
});

// Notificaciones push (recordatorio de racha, enviado por el cron del
// backend). El payload es JSON con {title, body, url}; al hacer clic se
// enfoca una pestaña ya abierta de la web si existe, o si no se abre una.
self.addEventListener("push", (event) => {
  let datos = { title: "Domina tu Opo", body: "Tienes novedades.", url: "/zona-opositor/" };
  if (event.data) {
    try {
      datos = { ...datos, ...event.data.json() };
    } catch (e) {
      datos.body = event.data.text();
    }
  }
  event.waitUntil(
    self.registration.showNotification(datos.title, {
      body: datos.body,
      icon: "/assets/apple-touch-icon.png",
      badge: "/assets/apple-touch-icon.png",
      data: { url: datos.url },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/zona-opositor/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((listaClientes) => {
      for (const cliente of listaClientes) {
        if (new URL(cliente.url).pathname === url && "focus" in cliente) return cliente.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || !url.pathname.startsWith("/assets/")) {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((respuesta) => {
        if (respuesta.ok) {
          caches.open(CACHE).then((cache) => cache.put(event.request, respuesta.clone()));
        }
        return respuesta;
      })
      .catch(() => caches.open(CACHE).then((cache) => cache.match(event.request)))
  );
});
