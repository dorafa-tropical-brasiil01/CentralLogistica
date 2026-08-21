// REMO PWA — Service Worker minimalista
const CACHE_NAME = 'remo-pwa-v5';

self.addEventListener('install', e => {
  self.skipWaiting();
});

self.addEventListener('message', e => {
  if (e.data && e.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
    )).then(() => self.clients.claim())
  );
});

// Network-first para HTML, cache só para assets estáticos
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  // Não intercepta API
  if (url.pathname.startsWith('/api/')) return;
  // HTML sempre da rede
  if (e.request.mode === 'navigate' || e.request.headers.get('accept', '').includes('text/html')) {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }
  // Assets: cache-first
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(resp => {
        if (resp && resp.status === 200) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, clone)).catch(() => {});
        }
        return resp;
      }).catch(() => cached);
    })
  );
});

// --- Web Push ---
self.addEventListener('push', e => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch { data = { title: 'REMO', body: e.data ? e.data.text() : '' }; }
  const title = data.title || 'REMO';
  const options = {
    body: data.body || '',
    icon: '/static/logo-remo.png',
    badge: '/static/logo-remo.png',
    tag: data.tag || 'remo-ordem',
    requireInteraction: data.requireInteraction !== false,
    data: data.data || {},
    vibrate: [200, 100, 200],
  };
  e.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clients => {
      for (const c of clients) {
        if ('focus' in c) { c.focus(); return; }
      }
      if (self.clients.openWindow) return self.clients.openWindow('/');
    })
  );
});
