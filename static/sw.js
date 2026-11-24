const cacheName = "watch-tracker-static-v2.0.0";
const offline = "/assets/offline.html";
const assets = [
  offline,
  "/manifest.webmanifest",
  "/assets/css/app.css",
  "/assets/css/tokens.css",
  "/assets/css/layout.css",
  "/assets/css/components.css",
  "/assets/css/responsive.css",
  "/assets/js/app.js",
  "/assets/js/api.js",
  "/assets/js/components.js",
  "/assets/js/router.js",
  "/assets/js/state.js",
  "/assets/js/pages/editor.js",
  "/assets/js/pages/dashboard.js",
  "/assets/js/pages/library.js",
  "/assets/js/pages/detail.js",
  "/assets/js/pages/settings.js",
  "/assets/js/pages/calendar.js",
  "/assets/js/pages/statistics.js",
  "/assets/vendor/chart.umd.min.js",
  "/assets/vendor/manrope-latin.woff2",
  "/assets/vendor/manrope-cyrillic.woff2",
  "/assets/vendor/onest-latin.woff2",
  "/assets/vendor/onest-cyrillic.woff2",
  "/assets/icons/lucide.svg",
  "/assets/icons/banner.webp",
  "/assets/icons/tmdb.svg",
  "/assets/icons/icon-192.png",
  "/assets/icons/icon-512.png",
  "/assets/icons/maskable-512.png",
];
const staticPaths = new Set(assets);

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(cacheName)
      .then((cache) =>
        cache.addAll(
          assets.map((url) => new Request(url, { cache: "reload" })),
        ),
      ),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter(
              (key) =>
                key.startsWith("watch-tracker-static-") && key !== cacheName,
            )
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "activate" && event.source?.type === "window")
    event.waitUntil(self.skipWaiting());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (
    url.origin !== self.location.origin ||
    request.method !== "GET" ||
    url.pathname.startsWith("/api/")
  )
    return;
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() =>
        caches.open(cacheName).then((cache) => cache.match(offline)),
      ),
    );
  } else if (staticPaths.has(url.pathname) && !url.search) {
    event.respondWith(
      caches
        .open(cacheName)
        .then((cache) => cache.match(request))
        .then((cached) => cached || fetch(request)),
    );
  }
});
