// Service worker mínimo: solo cachea los estáticos propios (/assets/) con
// estrategia cache-first para que la web cargue más rápido en visitas
// repetidas y sea instalable como PWA. Deliberadamente NO cachea HTML ni
// llamadas a la API (todo lo demás pasa siempre por red) para no servir
// nunca datos de usuario o resultados de tests obsoletos.
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

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || !url.pathname.startsWith("/assets/")) {
    return;
  }

  event.respondWith(
    caches.open(CACHE).then(async (cache) => {
      const enCache = await cache.match(event.request);
      if (enCache) return enCache;
      const respuesta = await fetch(event.request);
      if (respuesta.ok) cache.put(event.request, respuesta.clone());
      return respuesta;
    })
  );
});
