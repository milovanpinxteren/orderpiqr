const CACHE_NAME = 'django-pwa-cache-v1';
const urlsToCache = [
  '/',
  '/offline/',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png'
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

