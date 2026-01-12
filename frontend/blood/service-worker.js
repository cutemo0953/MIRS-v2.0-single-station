/**
 * MIRS Blood Bank PWA Service Worker v2.6.0
 *
 * Based on DEV_SPEC_BLOOD_BANK_PWA_v2.6:
 * - Scope 隔離：/blood/ 獨立快取
 * - 離線優先策略
 * - API 請求 Network-first
 *
 * v2.6.0 Changes:
 * - 血型庫存統計區 (仿原始 MIRS 深紅色背景)
 * - 血品類型色塊系統 (WB/PRBC/FFP/PLT/CRYO)
 * - 新增 WB (全血) 血品類型
 * - 血袋清單 UI 簡化
 * - 列印標籤功能
 * - 手動位置輸入 + 血品類型選擇
 */

const CACHE_NAME = 'mirs-blood-v2.6.0';
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
    console.log('[Blood SW] Installing v2.6.0');
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
