const CACHE = "kaptia-pages-v18";
const APP_SHELL = ["./", "./index.html"];
const OPTIONAL_FILES = ["./manifest.webmanifest"];
const NAVIGATION_TIMEOUT_MS = 8000;

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // The HTML shell is essential; a failed optional manifest must not brick installation.
    await cache.addAll(APP_SHELL);
    await Promise.all(OPTIONAL_FILES.map(async path => {
      try { await cache.add(path); } catch (_) { /* Optional offline asset. */ }
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys
      .filter(key => key.startsWith("kaptia-pages-") && key !== CACHE)
      .map(key => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", event => {
  const request = event.request;
  let url;
  try { url = new URL(request.url); } catch (_) { return; }
  if (request.method !== "GET" || url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith((async () => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), NAVIGATION_TIMEOUT_MS);
      try {
        const response = await fetch(request, {
          cache: "no-cache",
          redirect: "follow",
          signal: controller.signal
        });
        if (response.ok && response.type === "basic") {
          try {
            const cache = await caches.open(CACHE);
            await cache.put(new URL("./index.html", self.registration.scope).href, response.clone());
            await cache.put(new URL("./", self.registration.scope).href, response.clone());
          } catch (_) { /* A storage/quota failure must not discard a good network response. */ }
          return response;
        }
        // Server-side failures may be transient; preserve a cached shell when available.
        if (response.status >= 500) {
          const cached = await caches.match(new URL("./index.html", self.registration.scope).href);
          if (cached) return cached;
        }
        return response;
      } catch (_) {
        const cached = await caches.match(new URL("./index.html", self.registration.scope).href);
        if (cached) return cached;
        // No fallback exists on first visit: allow the browser's normal network error UI.
        throw _;
      } finally {
        clearTimeout(timer);
      }
    })());
    return;
  }

  // Release metadata must stay fresh, and large installers should never fill the offline cache.
  if (url.pathname.endsWith("/releases.json") || url.pathname.endsWith("/downloads/Kaptia-Setup.exe")) {
    event.respondWith(fetch(request, { cache: "no-store" }));
    return;
  }

  event.respondWith((async () => {
    let cached = null;
    try { cached = await caches.match(request); } catch (_) { /* Continue to network. */ }
    if (cached) return cached;
    const response = await fetch(request);
    if (response.ok && response.type === "basic") {
      try {
        const cache = await caches.open(CACHE);
        await cache.put(request, response.clone());
      } catch (_) { /* Caching is best effort; return the successful response. */ }
    }
    return response;
  })());
});
