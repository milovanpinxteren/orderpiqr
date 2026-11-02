{% load static build_tags %}
// serviceWorker.js — rendered by orderpiqrApp.views.scan_picklist_view.service_worker,
// not served as a static file. CACHE_NAME carries the build id so a deploy
// forces every open phone onto a fresh pre-cache instead of silently keeping
// the previous one forever (see 'activate' below, which deletes anything
// that isn't this name).
const CACHE_NAME = '{{ cache_name }}';

// Every entry below must be the EXACT URL the page itself requests, or the
// cache is dead weight: `cache.match(req)` keys on the full URL, so a
// pre-cached copy under any other spelling is never served and the request
// goes to the network — which, offline, means it simply fails.
//
// That makes the tag that renders each URL load-bearing, and there are three:
//   STATIC_PREFIX   unhashed, for files the page requests unhashed
//   the static tag  hashed, for the classic scripts index.html tags hashed
//   MODULE_PREFIX   build-scoped, for the ES-module graph
// (Spelling the static tag out above would be parsed as a tag, not a comment —
// this file is a Django template, and it does not know what a // comment is.)
const STATIC_PREFIX = '{% get_static_prefix %}';
// The module graph's build-scoped directory — the same prefix index.html tags
// its module entry points with. Relative import specifiers inherit the
// directory, so caching the graph under this prefix is what keeps a build's
// modules together: a page from a later build asks for a different directory,
// misses, and goes to the network instead of being handed a half-stale graph
// (the 2026-10-26 breakage). See orderpiqrApp.views.static_views.
const MODULE_PREFIX = '{% build_static_prefix %}';
const urlsToCache = [
    '/',
    '/offline/',
    // The gettext catalog. Every scan-page module starts with
    // `const gettext = window.gettext`, so a shell that loads without this
    // one script throws on its first user-visible string — an offline reload
    // would survive everything except its own translations.
    '/jsi18n/',
    '{% static "orderpiqrApp/css/camera_page.css" %}',
    '{% static "orderpiqrApp/css/camera_controls.css" %}',
    '{% static "icons/icon-192.png" %}',
    '{% static "icons/icon-512.png" %}',
    '{% static "manifest.json" %}',
    // Classic scripts the scan page loads outside the module graph, tagged
    // hashed in index.html — so they are pre-cached hashed too. Pre-caching
    // these unhashed is how an offline reload used to come up without its own
    // error reporter: the entry existed but under a URL nothing asks for.
    '{% static "orderpiqrApp/js/clientHealth.js" %}',
    '{% static "orderpiqrApp/js/installPrompt.js" %}',
    // The vendor scanner library: self-hosted precisely so a bad CDN minute
    // can't take the scan page down, which is exactly the kind of failure
    // this cache exists to survive too. Classic script, hashed tag.
    '{% static "orderpiqrApp/js/vendor/html5-qrcode-2.3.8.min.js" %}',
    // The ES module graph camera_page.js pulls in — entries the page tags
    // directly, plus the import-only modules (fingerprint.js, pickOutbox.js,
    // appUpdater.js) nothing in templates/index.html references by URL.
    MODULE_PREFIX + 'orderpiqrApp/js/qrScanner.js',
    MODULE_PREFIX + 'orderpiqrApp/js/notifications.js',
    MODULE_PREFIX + 'orderpiqrApp/js/orderImportance.js',
    MODULE_PREFIX + 'orderpiqrApp/js/picklistHandler.js',
    MODULE_PREFIX + 'orderpiqrApp/js/domUpdater.js',
    MODULE_PREFIX + 'orderpiqrApp/js/scanEventReporter.js',
    MODULE_PREFIX + 'orderpiqrApp/js/manualOverride.js',
    MODULE_PREFIX + 'orderpiqrApp/js/picklistSearch.js',
    MODULE_PREFIX + 'orderpiqrApp/js/shortPick.js',
    // Its own graph entry, not imported by camera_page — and needed most on
    // an offline reload: it is the module that tells the picker their queued
    // picks are queued rather than lost.
    MODULE_PREFIX + 'orderpiqrApp/js/syncBadge.js',
    MODULE_PREFIX + 'orderpiqrApp/js/fingerprint.js',
    MODULE_PREFIX + 'orderpiqrApp/js/pickOutbox.js',
    // Import-only (shortPick.js and domUpdater.js pull it in), so no tag in
    // index.html names it — exactly the category this block exists for.
    MODULE_PREFIX + 'orderpiqrApp/js/shortReasons.js',
    MODULE_PREFIX + 'orderpiqrApp/js/appUpdater.js',
    MODULE_PREFIX + 'orderpiqrApp/js/camera_page.js',
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
        // Build-scoped module URLs start with STATIC_PREFIX too
        // ('/static/b/<build>/...'), so they land here as well — deliberately.
        //
        // Stale-while-revalidate: serve the cached copy instantly (a picker
        // mid-shift cannot wait on a round trip for a script they already
        // have), and refresh the cache in the background for next time. This
        // is only *correct* because every URL it can answer is build-scoped or
        // content-hashed: stale bytes are then always the right bytes for the
        // page that asked. A cached copy under a URL two builds share is what
        // made this handler serve a mixed module graph on 2026-10-26.
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
