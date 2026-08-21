const CACHE_NAME = 'remo-pwa-v3';
const ASSETS = ['/', '/static/manifest.json', '/static/icon.svg'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(ASSETS)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    caches.match(e.request).then(cached => {
      const fetchPromise = fetch(e.request).then(response => {
        if (response && response.status === 200 && e.request.url.startsWith(self.location.origin)) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, clone)).catch(() => {});
        }
        return response;
      }).catch(() => cached);
      return cached || fetchPromise;
    })
  );
});

// --- Web Push ---
self.addEventListener('push', e => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch { data = { title: 'REMO', body: e.data ? e.data.text() : '' }; }
  const title = data.title || 'REMO Logística';
  const options = {
    body: data.body || '',
    icon: data.icon || '/static/icon-192.png',
    badge: data.badge || '/static/badge-72.png',
    tag: data.tag || 'remo-ordem',
    requireInteraction: data.requireInteraction !== false,
    data: data.data || {},
    vibrate: [200, 100, 200],
    actions: [
      { action: 'ver', title: 'Ver entregas' },
      { action: 'fechar', title: 'Fechar' },
    ],
  };
  e.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  if (e.action === 'fechar') return;
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clients => {
      for (const c of clients) {
        if ('focus' in c) { c.focus(); return; }
      }
      if (self.clients.openWindow) return self.clients.openWindow('/');
    })
  );
});
