/* App shell cached for offline start (network first); scan data always fetched fresh (falls back to the last copy in the page). */
const SHELL = 'td-shell-v4';
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
  // 12 Nov 2026: a navigation Request can't be cloned with new options (it threw, so the phone fell back to the 10-min HTTP
  // cache and showed old versions). Fetch the page by URL with no-store instead; other app files revalidate.
  const req = e.request.mode === 'navigate' ? new Request(u.href, { cache: 'no-store', credentials: 'same-origin' })
    : u.origin === location.origin ? new Request(u.href, { cache: 'no-cache' }) : e.request;
  e.respondWith(fetch(req).then((r) => { if (r.ok && u.origin === location.origin) { const cp = r.clone(); caches.open(SHELL).then((c) => c.put(e.request, cp)); } return r; })
    .catch(() => caches.match(e.request)));
});
/* phone alerts (11 Nov 2026): the server pushes stop hits, fills, sells, sell signals and stop raises */
self.addEventListener('push', (e) => {
  let d = {}; try { d = e.data ? e.data.json() : {}; } catch (x) { d = { body: e.data ? e.data.text() : '' }; }
  e.waitUntil(self.registration.showNotification(d.title || 'Trend Desk', { body: d.body || '', tag: d.tag, icon: 'icons/icon-192.png', badge: 'icons/icon-192.png', data: { url: './' } }));
});
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((cs) => { for (const c of cs) { if ('focus' in c) return c.focus(); } return self.clients.openWindow('./'); }));
});
