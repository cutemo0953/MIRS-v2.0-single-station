/**
 * MIRS BioMed PWA Service Worker v1.2.4
 *
 * Provides offline caching for BioMed PWA.
 * Key features:
 * - Cache core assets for offline use
 * - Equipment management offline support
 * - Resilience calculation data caching
 *
 * v1.0.0: Initial release - equipment management + resilience
 * v1.1.2: Fix resilience resources display issue
 * v1.1.3: Unit management + API path fix + equipment color scheme
 * v1.1.4: Per-unit check + level editing + resilience $nextTick fix
 * v1.1.5: Fix resilience resources - use inventory.items, fix Vercel mock
 * v1.1.6: Status dropdown + Vercel mock Chinese names
 * v1.2.0: Interactive Survival Calculator with scenario inputs
 * v1.2.1: Medical-grade O2 formulas (cannula=0.3, mask=0.6, ventilator=1.0)
 *         + Oxygen color changed from blue to orange
 *         + Oxygen concentrator support (reduces bottle consumption)
 * v1.2.2: Vercel serverless demo warning
 *         + Simplified scenario input UI (2-column layout)
 *         + amber/orange/red only color scheme (no blue/green)
 *         + MIRS-style formula explanation with ▎ headers
 * v1.2.3: Unchecked equipment grayscale display
 *         + Individual oxygen bottle bars with PSI
 *         + Separate concentrator display (not using PSI)
 * v1.2.4: Fix oxygen unit confirm API (422 error)
 *         + Gray progress bar for unchecked items
 *         + Amber/orange/red bar for checked items
 *         + Remove x-collapse (use x-transition instead)
 *         + Check icon (✓ green / clock gray)
 *         + n/n 已檢查 counter
 */

const CACHE_NAME = 'mirs-biomed-v1.2.4';

const CORE_ASSETS = [
    '/biomed/',
    '/biomed/index.html',
    '/biomed/manifest.json',
    // Local static assets (offline support)
    '/static/css/tailwind.min.css',
    '/static/css/mirs-colors.css',
    '/static/js/alpine.min.js'
];

// Install
self.addEventListener('install', (event) => {
    console.log('[BioMed SW] Installing...');

    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(CORE_ASSETS);
        }).then(() => {
            console.log('[BioMed SW] Install complete');
            return self.skipWaiting();
        })
    );
});

// Activate
self.addEventListener('activate', (event) => {
    console.log('[BioMed SW] Activating...');

    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    .filter(name => name.startsWith('mirs-biomed-') && name !== CACHE_NAME)
                    .map(name => {
                        console.log('[BioMed SW] Deleting old cache:', name);
                        return caches.delete(name);
                    })
            );
        }).then(() => {
            console.log('[BioMed SW] Activate complete');
            return self.clients.claim();
        })
    );
});

// Fetch - Network first, fallback to cache
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Skip non-GET requests
    if (event.request.method !== 'GET') return;

    // Skip API requests (let them go to network)
    if (url.pathname.startsWith('/api/')) return;

    event.respondWith(
        fetch(event.request)
            .then((response) => {
                // Clone and cache successful responses
                if (response.ok) {
                    const responseClone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, responseClone);
                    });
                }
                return response;
            })
            .catch(() => {
                // Network failed, try cache
                return caches.match(event.request).then((cachedResponse) => {
                    if (cachedResponse) {
                        return cachedResponse;
                    }
                    // If not in cache and it's navigation, return the main page
                    if (event.request.mode === 'navigate') {
                        return caches.match('/biomed/index.html');
                    }
                    return new Response('Offline', { status: 503 });
                });
            })
    );
});

// Handle messages from main thread
self.addEventListener('message', (event) => {
    if (event.data === 'skipWaiting') {
        self.skipWaiting();
    }
});
