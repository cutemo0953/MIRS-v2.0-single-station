/**
 * MIRS EMT Transfer - Service Worker
 * Version: 3.2.0
 * Offline-first architecture
 *
 * v1.1.0: O2 flow options changed to 無/3/6/10/15
 * v3.0.0: CIRS Handoff integration (accept/reject, arrival vitals)
 * v3.0.2: User-selectable ISBAR/MIST format, GCS E/V/M input, pink color scheme
 * v3.0.3: Format-aware display (ISBAR cards vs MIST trauma cards)
 * v3.0.4: Clickable step indicator for navigation back to previous steps
 * v3.2.0: Internal transfer ISBAR/MIST support, station name display, tab-style format selector
 */

const CACHE_NAME = 'mirs-emt-v3.2.0';
const OFFLINE_URL = '/static/emt/';

const STATIC_ASSETS = [
  '/static/emt/',
  '/static/emt/index.html',
  '/static/emt/manifest.json',
  '/static/css/tailwind.min.css',
  '/static/css/mirs-colors.css',
  '/static/js/alpine.min.js',
  '/static/icons/icon-192.png'
];

// Install: cache static assets
self.addEventListener('install', (event) => {
  console.log('[EMT-SW] Installing...');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('[EMT-SW] Caching static assets');
        return cache.addAll(STATIC_ASSETS);
      })
      .then(() => self.skipWaiting())
  );
});

// Activate: clean old caches
self.addEventListener('activate', (event) => {
  console.log('[EMT-SW] Activating...');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name.startsWith('mirs-emt-') && name !== CACHE_NAME)
          .map((name) => {
            console.log('[EMT-SW] Deleting old cache:', name);
            return caches.delete(name);
          })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch: stale-while-revalidate for static, network-first for API
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API requests: network-first, queue if offline
  if (url.pathname.startsWith('/api/transfer')) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          return response;
        })
        .catch(() => {
          // Offline: return cached response or queue for sync
          if (event.request.method === 'GET') {
            return caches.match(event.request);
          }
          // POST/PUT/DELETE: queue for background sync
          return new Response(
            JSON.stringify({
              queued: true,
              message: 'Request queued for sync when online'
            }),
            {
              status: 202,
              headers: { 'Content-Type': 'application/json' }
            }
          );
        })
    );
    return;
  }

  // Static assets: stale-while-revalidate
  event.respondWith(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.match(event.request).then((cachedResponse) => {
        const fetchPromise = fetch(event.request).then((networkResponse) => {
          if (networkResponse.ok) {
            cache.put(event.request, networkResponse.clone());
          }
          return networkResponse;
        }).catch(() => cachedResponse);

        return cachedResponse || fetchPromise;
      });
    })
  );
});

// Background sync (when back online)
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-transfer-events') {
    console.log('[EMT-SW] Syncing transfer events...');
    event.waitUntil(syncTransferEvents());
  }
});

async function syncTransferEvents() {
  // Get queued events from IndexedDB and POST to server
  // This is handled by the main app when it detects online status
  const clients = await self.clients.matchAll();
  clients.forEach(client => {
    client.postMessage({ type: 'SYNC_REQUESTED' });
  });
}

// Push notifications (optional)
self.addEventListener('push', (event) => {
  if (!event.data) return;

  const data = event.data.json();
  const options = {
    body: data.body,
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-72.png',
    vibrate: [100, 50, 100],
    data: { url: data.url || '/static/emt/' }
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    clients.openWindow(event.notification.data.url)
  );
});
