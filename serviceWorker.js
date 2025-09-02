const CACHE_NAME = 'django-pwa-cache-v8';
const urlsToCache = [
    '/',
    '/offline/',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png',
    // '/static/orderpiqrApp/css/camera_page.css',
    // '/static/orderpiqrApp/js/camera_page.js',
    // '/static/orderpiqrApp/js/picklistHandler.js',
    // '/static/orderpiqrApp/js/notifications.js',
    // '/static/orderpiqrApp/js/domUpdater.js',
    // '/static/orderpiqrApp/js/fingerprint.js',
    // '/static/orderpiqrApp/js/qrScanner.js',
    // '/static/orderpiqrApp/js/orderImportance.js',
    // '/static/orderpiqrApp/js/manualOverride.js',
    // 'https://cdn.jsdelivr.net/npm/@fingerprintjs/fingerprintjs@3.0.0/dist/fp.min.js',
    // 'https://unpkg.com/html5-qrcode',
];


self.addEventListener('install', event => {
    console.log('[SW] Installing...');
    self.skipWaiting();

    event.waitUntil(
        caches.open(CACHE_NAME).then(async cache => {
            console.log('[SW] Caching assets:', urlsToCache);

            // Only cache assets that return 200 OK
            const cacheableResponses = await Promise.all(
                urlsToCache.map(async url => {
                    try {
                        const response = await fetch(url, {redirect: 'follow'});
                        if (response.ok) {
                            await cache.put(url, response);
                            return true;
                        } else {
                            console.warn(`[SW] Skipped caching ${url}: status ${response.status}`);
                            return false;
                        }
                    } catch (e) {
                        console.warn(`[SW] Failed to fetch ${url} for caching`, e);
                        return false;
                    }
                })
            );

            console.log('[SW] Finished selective caching:', cacheableResponses);
        })
    );
});


self.addEventListener('activate', event => {
    console.log('[SW] Activating...');
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys.filter(key => key !== CACHE_NAME).map(key => {
                    console.log('[SW] Deleting old cache:', key);
                    return caches.delete(key);
                })
            )
        )
    );
});


