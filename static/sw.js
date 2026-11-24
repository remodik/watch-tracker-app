const cachePrefix = "watch-tracker-release-";
const cacheName = cachePrefix + "__WATCH_RELEASE__";
const prefix = "/assets/__WATCH_RELEASE__/";
const offline = prefix + "offline.html";
const assets = /* RELEASE_ASSETS */ [];

async function install() {
  const exists = await caches.has(cacheName);
  const cache = await caches.open(cacheName);
  try {
    await cache.addAll(
      assets.map((url) => new Request(url, { cache: "reload" })),
    );
  } catch (error) {
    if (!exists) await caches.delete(cacheName);
    throw error;
  }
}

self.addEventListener("install", (event) => event.waitUntil(install()));

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      const prior = names.filter(
        (name) => name.startsWith(cachePrefix) && name !== cacheName,
      );
      // Keep the previous release available to open tabs and immediate rollbacks.
      await Promise.all(prior.slice(0, -1).map((name) => caches.delete(name)));
      await Promise.all(
        names
          .filter((name) => name.startsWith("watch-tracker-static-"))
          .map((name) => caches.delete(name)),
      );
      await self.clients.claim();
    })(),
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
    url.pathname === "/api" ||
    url.pathname.startsWith("/api/")
  )
    return;
  if (request.mode === "navigate" && !url.pathname.startsWith("/assets/")) {
    event.respondWith(
      fetch(request).catch(() =>
        caches.open(cacheName).then((cache) => cache.match(offline)),
      ),
    );
  } else if (/^\/assets\/[a-f0-9]{24}\//.test(url.pathname) && !url.search) {
    event.respondWith(
      (async () => {
        const version = url.pathname.split("/")[2];
        const cache = await caches.match(request, {
          cacheName: cachePrefix + version,
        });
        return cache ?? fetch(request);
      })(),
    );
  }
});
