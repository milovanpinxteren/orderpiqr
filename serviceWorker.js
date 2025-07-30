const CACHE_NAME = 'django-pwa-cache-v1';
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
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
  );
});


self.addEventListener('fetch', event => {
  event.respondWith(
    fetch(event.request).catch(() => {
      // If the requested page is not cached, serve the offline fallback
      return caches.match(event.request).then(response => {
        return response || caches.match('/offline/');
      });
    })
  );
});

