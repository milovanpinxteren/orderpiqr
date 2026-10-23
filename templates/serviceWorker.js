{% load static %}
// serviceWorker.js — rendered by orderpiqrApp.views.scan_picklist_view.service_worker,
// not served as a static file. CACHE_NAME carries the build id so a deploy
// forces every open phone onto a fresh pre-cache instead of silently keeping
// the previous one forever (see 'activate' below, which deletes anything
// that isn't this name).
const CACHE_NAME = '{{ cache_name }}';

// The unhashed static-prefix tag on purpose, never the hashed one: these are
// fetched by URL string at install time, not imported, so the v123 module-
// graph hashing rule doesn't apply to them directly — but the cache name is
// already the cache-buster, so a second hash on the URL would just make
// every one of these fail to resolve against what the page itself requests.
const STATIC_PREFIX = '{% get_static_prefix %}';
const urlsToCache = [
    '/',
    '/offline/',
    // The gettext catalog. Every scan-page module starts with
    // `const gettext = window.gettext`, so a shell that loads without this
    // one script throws on its first user-visible string — an offline reload
    // would survive everything except its own translations.
    '/jsi18n/',
    STATIC_PREFIX + 'orderpiqrApp/css/camera_page.css',
    STATIC_PREFIX + 'orderpiqrApp/css/camera_controls.css',
    STATIC_PREFIX + 'icons/icon-192.png',
    STATIC_PREFIX + 'icons/icon-512.png',
    STATIC_PREFIX + 'manifest.json',
    // Classic scripts the scan page loads outside the module graph.
    STATIC_PREFIX + 'orderpiqrApp/js/clientHealth.js',
    STATIC_PREFIX + 'orderpiqrApp/js/installPrompt.js',
    // The vendor scanner library: self-hosted precisely so a bad CDN minute
    // can't take the scan page down, which is exactly the kind of failure
    // this cache exists to survive too.
    STATIC_PREFIX + 'orderpiqrApp/js/vendor/html5-qrcode-2.3.8.min.js',
    // The ES module graph camera_page.js pulls in — entries the page tags
    // directly, plus the import-only modules (fingerprint.js, pickOutbox.js,
    // appUpdater.js) nothing in templates/index.html references by URL.
    STATIC_PREFIX + 'orderpiqrApp/js/qrScanner.js',
    STATIC_PREFIX + 'orderpiqrApp/js/notifications.js',
    STATIC_PREFIX + 'orderpiqrApp/js/orderImportance.js',
    STATIC_PREFIX + 'orderpiqrApp/js/picklistHandler.js',
    STATIC_PREFIX + 'orderpiqrApp/js/domUpdater.js',
    STATIC_PREFIX + 'orderpiqrApp/js/scanEventReporter.js',
    STATIC_PREFIX + 'orderpiqrApp/js/manualOverride.js',
    STATIC_PREFIX + 'orderpiqrApp/js/picklistSearch.js',
    // Its own graph entry, not imported by camera_page — and needed most on
    // an offline reload: it is the module that tells the picker their queued
    // picks are queued rather than lost.
    STATIC_PREFIX + 'orderpiqrApp/js/syncBadge.js',
    STATIC_PREFIX + 'orderpiqrApp/js/fingerprint.js',
    STATIC_PREFIX + 'orderpiqrApp/js/pickOutbox.js',
    STATIC_PREFIX + 'orderpiqrApp/js/appUpdater.js',
    STATIC_PREFIX + 'orderpiqrApp/js/camera_page.js',
];


self.addEventListener('install', event => {
    console.log('[SW] Installing...', CACHE_NAME);
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
    console.log('[SW] Activating...', CACHE_NAME);
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys.filter(key => key !== CACHE_NAME).map(key => {
                    console.log('[SW] Deleting old cache:', key);
                    return caches.delete(key);
                })
            )
        // Take over open pages immediately so a stale worker never keeps
        // serving them until the next full navigation.
        ).then(() => self.clients.claim())
    );
});


self.addEventListener('fetch', (event) => {
    const req = event.request;
    // Anything that isn't GET (claim/pick/bulk/complete, scan-event, ...)
    // must reach the network untouched — intercepting a business-critical
    // POST here would double the job pickOutbox.js already does, and worse,
    // hide a real failure behind a cache that was never meant to hold it.
    if (req.method !== 'GET') return;

    if (req.mode === 'navigate') {
        // A reload always wants the freshest HTML (it carries claimed-order
        // data, CSRF token, settings); only fall back to a cached shell when
        // the network is truly unreachable, and only then fall back further
        // to the dead-end offline page.
        event.respondWith((async () => {
            try {
                return await fetch(req, {cache: 'no-store'});
            } catch (e) {
                const cache = await caches.open(CACHE_NAME);
                const shell = await cache.match('/');
                return shell || (await cache.match('/offline/'));
            }
        })());
        return;
    }

    const url = new URL(req.url);
    if (url.pathname.startsWith(STATIC_PREFIX)) {
        // Stale-while-revalidate: serve the cached copy instantly (a picker
        // mid-shift cannot wait on a round trip for a script they already
        // have), and refresh the cache in the background for next time. The
        // cache name — not this logic — is what makes a deploy actually
        // propagate; see CACHE_NAME above.
        event.respondWith((async () => {
            const cache = await caches.open(CACHE_NAME);
            const cached = await cache.match(req);
            const revalidate = fetch(req).then(res => {
                if (res && res.ok) cache.put(req, res.clone());
                return res;
            }).catch(() => null);
            if (cached) return cached;
            return (await revalidate) || Response.error();
        })());
        return;
    }

    if (url.pathname === '/jsi18n/') {
        // Network-first, unlike the static assets: the catalog's content
        // follows the session language, so a cached copy must only ever be
        // the last resort — but it must exist, or an offline reload loads a
        // shell whose every gettext() call throws.
        event.respondWith((async () => {
            const cache = await caches.open(CACHE_NAME);
            try {
                const res = await fetch(req);
                if (res && res.ok) cache.put(req, res.clone());
                return res;
            } catch (e) {
                const cached = await cache.match('/jsi18n/');
                return cached || Response.error();
            }
        })());
        return;
    }

    // Everything else (API GETs, admin, ...): untouched, pass through to the
    // network. No cache has ever claimed to speak for these.
});
