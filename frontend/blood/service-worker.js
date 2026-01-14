/**
 * MIRS Blood Bank PWA Service Worker v2.8.0
 *
 * Based on DEV_SPEC_BLOOD_BANK_PWA_v2.7:
 * - Scope 隔離：/blood/ 獨立快取
 * - 離線優先策略
 * - API 請求 Network-first
 *
 * v2.7.0 Changes (MIRS Legacy Style):
 * - Big Colored Cards Grid (2x4) for blood types
 * - Click-to-filter dashboard
 * - Left border color coding by component type
 * - Prominent Unit ID & Expiry Date
 * - Emergency FAB (Panic Button) with blinking animation
 *
 * v2.7.1 Changes:
 * - Card-style receive button in Units tab
 * - WB (Whole Blood) demo data support
 * - Responsive max-width for laptop screens
 *
 * v2.8.0 Changes (Tab Restructure):
 * - 庫存總覽: 整合完整血袋清單 (FIFO/預約/發血按鈕)
 * - 入庫+標籤: 新 Tab (捐血中心/緊急捐血/補印標籤)
 * - Walking Blood Bank: 緊急捐血入庫流程
 */

const CACHE_NAME = 'mirs-blood-v2.8.0';
const SCOPE = '/blood/';

// 需要快取的靜態資源
const STATIC_ASSETS = [
    '/blood/',
    '/blood/manifest.json',
    '/static/css/tailwind.min.css',
    '/static/css/mirs-colors.css',
    '/static/js/alpine.min.js'
];

// Install event
self.addEventListener('install', (event) => {
    console.log('[Blood SW] Installing v2.8.0');
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => {
                console.log('[Blood SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
    );
});

// Activate event
self.addEventListener('activate', (event) => {
    console.log('[Blood SW] Activating');
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    .filter((name) => name.startsWith('mirs-blood-') && name !== CACHE_NAME)
                    .map((name) => {
                        console.log('[Blood SW] Deleting old cache:', name);
                        return caches.delete(name);
                    })
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch event
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // API 請求：Network-first
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(
            fetch(event.request)
                .then((response) => {
                    // 成功時快取 GET 請求
                    if (event.request.method === 'GET' && response.ok) {
                        const responseClone = response.clone();
                        caches.open(CACHE_NAME).then((cache) => {
                            cache.put(event.request, responseClone);
                        });
                    }
                    return response;
                })
                .catch(() => {
                    // 離線時從快取取得
                    return caches.match(event.request);
                })
        );
        return;
    }

    // 靜態資源：Cache-first
    event.respondWith(
        caches.match(event.request)
            .then((cachedResponse) => {
                if (cachedResponse) {
                    return cachedResponse;
                }
                return fetch(event.request).then((response) => {
                    // 快取新資源
                    if (response.ok) {
                        const responseClone = response.clone();
                        caches.open(CACHE_NAME).then((cache) => {
                            cache.put(event.request, responseClone);
                        });
                    }
                    return response;
                });
            })
    );
});
