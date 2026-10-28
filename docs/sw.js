/* App shell cached for offline start (network first); scan data always fetched fresh (falls back to the last copy in the page). */
const SHELL = 'td-shell-v1';
const FILES = ['./', 'index.html', 'styles.css', 'app.js', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/icon-512.png',
  'https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js'];
self.addEventListener('install', (e) => e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES)).then(() => self.skipWaiting())));
self.addEventListener('activate', (e) => e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== SHELL).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener('fetch', (e) => {
  const u = new URL(e.request.url);
  if (u.hostname === 'raw.githubusercontent.com') {
    e.respondWith(fetch(e.request).then((r) => { const cp = r.clone(); caches.open('td-data').then((c) => c.put(e.request, cp)); return r; })
      .catch(() => caches.match(e.request)));
    return;
  }
  // app files: network first so updates show at once, cache when offline
  e.respondWith(fetch(e.request).then((r) => { if (r.ok && u.origin === location.origin) { const cp = r.clone(); caches.open(SHELL).then((c) => c.put(e.request, cp)); } return r; })
    .catch(() => caches.match(e.request)));
});
