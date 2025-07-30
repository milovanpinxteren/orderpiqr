const CACHE_NAME = 'django-pwa-cache-v6';
const urlsToCache = [
    '/',
    '/offline/',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png',
    '/static/orderpiqrApp/css/camera_page.css',
    '/static/orderpiqrApp/js/camera_page.js',
    '/static/orderpiqrApp/js/picklistHandler.js',
    '/static/orderpiqrApp/js/notifications.js',
    '/static/orderpiqrApp/js/domUpdater.js',
    '/static/orderpiqrApp/js/fingerprint.js',
    '/static/orderpiqrApp/js/qrScanner.js',
    '/static/orderpiqrApp/js/orderImportance.js',
    '/static/orderpiqrApp/js/manualOverride.js',
    'https://cdn.jsdelivr.net/npm/@fingerprintjs/fingerprintjs@3.0.0/dist/fp.min.js',
    'https://unpkg.com/html5-qrcode',
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


// self.addEventListener('install', event => {
//     self.skipWaiting();
//     event.waitUntil(
//         caches.open(CACHE_NAME)
//             .then(cache => cache.addAll(urlsToCache))
//     );
// });

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
self.addEventListener('fetch', event => {
    console.log('[SW] Fetch request for:', event.request.url);

    if (event.request.mode === 'navigate') {
        console.log('[SW] Navigation request detected:', event.request.url);

        event.respondWith(
            fetch(event.request.clone())
                .then(response => {
                    console.log('[SW] Fetched from network:', event.request.url);
                    return response;
                })
                .catch(error => {
                    console.warn('[SW] Network fetch failed:', event.request.url, error);
                    return caches.match('/offline/');
                })
        );

    } else {
        event.respondWith(
            fetch(event.request)
                .then(response => {
                    console.log('[SW] Fetched asset:', event.request.url);
                    return response;
                })
                .catch(() => {
                    return caches.match(event.request).then(response => {
                        if (response) {
                            console.log('[SW] Served from cache:', event.request.url);
                            return response;
                        }
                        console.log('[SW] Falling back to /offline/ for:', event.request.url);
                        return caches.match('/offline/');
                    });
                })
        );
    }
});


// self.addEventListener('fetch', event => {
//   if (event.request.mode === 'navigate') {
//     // Handle navigation (Back button, typing URL, refreshing)
//     event.respondWith(
//       fetch(event.request).catch(() => caches.match('/'))  // fallback to cached homepage
//     );
//   } else {
//     // Handle other requests (static files, scripts, etc.)
//     event.respondWith(
//       fetch(event.request).catch(() =>
//         caches.match(event.request).then(response =>
//           response || caches.match('/offline/')
//         )
//       )
//     );
//   }
// });


// self.addEventListener('fetch', event => {
//   event.respondWith(
//     fetch(event.request).catch(() => {
//       // If the requested page is not cached, serve the offline fallback
//       return caches.match(event.request).then(response => {
//         return response || caches.match('/offline/');
//       });
//     })
//   );
// });

