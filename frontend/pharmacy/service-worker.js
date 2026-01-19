/**
 * MIRS Pharmacy Sub-Hub Service Worker
 * Built with xIRS SDK from Day 1
 */

const CACHE_NAME = 'mirs-pharmacy-v1.0.0';
const PWA_ID = 'mirs-pharmacy';

// Assets to pre-cache
const PRECACHE_ASSETS = [
    '/frontend/pharmacy/',
    '/frontend/pharmacy/index.html',
    '/frontend/pharmacy/manifest.json',
    '/static/css/tailwind.min.css',
    '/static/css/mirs-colors.css',
    '/static/js/alpine.min.js',
    '/static/js/html5-qrcode.min.js',
    '/shared/sdk/xirs-config.js',
    '/shared/sdk/xirs-auth.js',
    '/shared/sdk/xirs-api.js',
    '/shared/sdk/xirs-bus.js',
    '/shared/sdk/xirs-offline.js',
    '/shared/sdk/xirs-ui.js',
    '/shared/sdk/index.js'
];

// API routes to use network-first strategy
const API_ROUTES = [
    '/api/pharmacy/'
];

// Install: Pre-cache assets
self.addEventListener('install', (event) => {
    console.log(`[SW ${PWA_ID}] Installing...`);

    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log(`[SW ${PWA_ID}] Pre-caching assets`);
                return cache.addAll(PRECACHE_ASSETS);
            })
            .then(() => self.skipWaiting())
    );
});

// Activate: Clean old caches
self.addEventListener('activate', (event) => {
    console.log(`[SW ${PWA_ID}] Activating...`);

    event.waitUntil(
        caches.keys()
            .then(cacheNames => {
                return Promise.all(
                    cacheNames
                        .filter(name => name.startsWith('mirs-pharmacy-') && name !== CACHE_NAME)
                        .map(name => {
                            console.log(`[SW ${PWA_ID}] Deleting old cache:`, name);
                            return caches.delete(name);
                        })
                );
            })
            .then(() => self.clients.claim())
    );
});

// Fetch: Network-first for API, cache-first for assets
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Skip non-GET requests
    if (event.request.method !== 'GET') {
        return;
    }

    // API routes: Network-first
    if (API_ROUTES.some(route => url.pathname.startsWith(route))) {
        event.respondWith(networkFirst(event.request));
        return;
    }

    // Static assets: Cache-first
    event.respondWith(cacheFirst(event.request));
});

// Network-first strategy
async function networkFirst(request) {
    try {
        const response = await fetch(request);

        // Cache successful responses
        if (response.ok) {
            const cache = await caches.open(CACHE_NAME);
            cache.put(request, response.clone());
        }

        return response;
    } catch (error) {
        // Fallback to cache
        const cached = await caches.match(request);
        if (cached) {
            return cached;
        }

        // Return offline response for API
        return new Response(
            JSON.stringify({ error: 'offline', message: '離線模式' }),
            {
                status: 503,
                headers: { 'Content-Type': 'application/json' }
            }
        );
    }
}

// Cache-first strategy
async function cacheFirst(request) {
    const cached = await caches.match(request);
    if (cached) {
        return cached;
    }

    try {
        const response = await fetch(request);

        // Cache successful responses
        if (response.ok) {
            const cache = await caches.open(CACHE_NAME);
            cache.put(request, response.clone());
        }

        return response;
    } catch (error) {
        // Return offline page if available
        return caches.match('/frontend/pharmacy/index.html');
    }
}

// Handle sync events (Background Sync)
self.addEventListener('sync', (event) => {
    if (event.tag === 'xirs-sync') {
        console.log(`[SW ${PWA_ID}] Background sync triggered`);

        event.waitUntil(
            self.clients.matchAll().then(clients => {
                clients.forEach(client => {
                    client.postMessage({ type: 'SYNC_TRIGGERED' });
                });
            })
        );
    }
});

// Handle messages from main thread
self.addEventListener('message', (event) => {
    if (event.data?.type === 'XIRS_SYNC_REQUEST') {
        // Try Background Sync
        if (self.registration.sync) {
            self.registration.sync.register('xirs-sync').catch(() => {
                // Fallback: notify client
                event.source.postMessage({ type: 'SYNC_FALLBACK_NEEDED' });
            });
        } else {
            event.source.postMessage({ type: 'SYNC_FALLBACK_NEEDED' });
        }
    }

    if (event.data?.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});

console.log(`[SW ${PWA_ID}] Service Worker loaded`);
