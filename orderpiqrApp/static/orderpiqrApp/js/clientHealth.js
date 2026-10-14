// clientHealth.js
//
// The silences: crashes, reloads, dead cameras and lost sessions produced no
// event at all, so the health dashboard looked clean while pickers reported the
// app crashing and logging them out. This module reports them.
//
// THIS IS A CLASSIC SCRIPT, DELIBERATELY. Two reasons it must stay that way:
//
//  1. It has to install its error handlers BEFORE the ES module graph runs. A
//     module that throws while binding a DOM node at import time cannot report
//     its own death — and that is exactly the failure that reads to a picker as
//     "the app crashed": the page renders, and nothing responds.
//  2. Because it imports nothing and nothing imports it, it is safe to load via
//     a hashed {% static %} URL. Any file inside the module import graph must
//     use {% get_static_prefix %} instead — hashing those URLs is what broke
//     production in v123 (two copies of the graph, every manual override lost).
//     If this file ever gains an `import`, that rule applies to it too.
//
// It also owns the offline queue, and exposes window.orderpiqrHealth so the
// module-side reporter can share it without an import.
(function () {
    'use strict';

    var ENDPOINT = '/orderpiqr/scan-event';
    var FINGERPRINT_KEY = 'orderpiqr_device_id';   // must match fingerprint.js
    var QUEUE_KEY = 'orderpiqr_health_queue';
    var MAX_QUEUED = 50;                 // bounded: a crash loop must not fill storage
    var MAX_QUEUED_BYTES = 32 * 1024;
    var MAX_PER_PAGE = 25;               // one runaway handler can fire thousands of times
    var REPEAT_WINDOW_MS = 60000;        // same error, same place: once a minute
    var MAX_MESSAGE = 500;

    var sentThisPage = 0;
    var lastSeen = {};                   // "type|reason|message" -> ts
    var flushing = false;

    function fingerprint() {
        try {
            return localStorage.getItem(FINGERPRINT_KEY) || '';
        } catch (e) {
            return '';   // storage can throw outright in private modes
        }
    }

    function displayMode() {
        try {
            if (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) {
                return 'standalone';
            }
            if (window.navigator.standalone === true) {
                return 'standalone';   // iOS home-screen app
            }
            return 'browser';
        } catch (e) {
            return '';
        }
    }

    function buildId() {
        try {
            return (window.SETTINGS && window.SETTINGS.build_id) || '';
        } catch (e) {
            return '';
        }
    }

    // Never send anything that could carry order contents, picker names or
    // customer identifiers: messages are truncated, and URLs are reduced to a
    // path with the query string dropped.
    function scrub(text) {
        if (!text) return '';
        return String(text).replace(/\?[^\s]*/g, '').slice(0, MAX_MESSAGE);
    }

    function readQueue() {
        try {
            var raw = localStorage.getItem(QUEUE_KEY);
            var parsed = raw ? JSON.parse(raw) : [];
            return Object.prototype.toString.call(parsed) === '[object Array]' ? parsed : [];
        } catch (e) {
            return [];
        }
    }

    function writeQueue(items) {
        try {
            while (items.length > MAX_QUEUED) { items.shift(); }
            var payload = JSON.stringify(items);
            while (payload.length > MAX_QUEUED_BYTES && items.length > 1) {
                items.shift();
                payload = JSON.stringify(items);
            }
            localStorage.setItem(QUEUE_KEY, payload);
        } catch (e) {
            // Storage full or unavailable — drop the queue rather than break.
            try { localStorage.removeItem(QUEUE_KEY); } catch (e2) { /* nothing left to try */ }
        }
    }

    function post(event) {
        var token = '';
        try { token = window.csrfToken || ''; } catch (e) { token = ''; }
        return fetch(ENDPOINT, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': token},
            body: JSON.stringify(event),
            keepalive: true   // survives the page going away mid-report
        }).then(function (response) {
            if (!response.ok) { throw new Error('rejected'); }
            return response;
        });
    }

    // Serialised: a reconnect must not fire 50 requests at the moment the
    // picker starts picking again.
    function flush() {
        if (flushing || !navigator.onLine) return;
        var queue = readQueue();
        if (!queue.length) return;
        flushing = true;

        var next = function () {
            var items = readQueue();
            if (!items.length || !navigator.onLine) {
                flushing = false;
                return;
            }
            var event = items[0];
            post(event).then(function () {
                var rest = readQueue();
                rest.shift();
                writeQueue(rest);
                next();
            }).catch(function () {
                flushing = false;   // still offline or server unhappy; try later
            });
        };
        next();
    }

    function report(eventType, options) {
        try {
            var opts = options || {};
            var message = scrub(opts.message);
            var reason = String(opts.reason || '').slice(0, 64);

            var key = eventType + '|' + reason + '|' + message;
            var now = Date.now();
            if (lastSeen[key] && now - lastSeen[key] < REPEAT_WINDOW_MS) return;
            lastSeen[key] = now;

            if (sentThisPage >= MAX_PER_PAGE) return;
            sentThisPage += 1;

            var event = {
                eventType: eventType,
                reason: reason,
                severity: opts.severity || '',
                message: message,
                scannedCode: String(opts.scannedCode || '').slice(0, 255),
                picklistCode: String(opts.picklistCode || '').slice(0, 255),
                deviceFingerprint: fingerprint(),
                displayMode: displayMode(),
                buildId: buildId(),
                clientTs: new Date().toISOString()
            };

            if (!navigator.onLine) {
                // Previously these were dropped outright, so every error during
                // a warehouse connectivity drop was invisible by construction.
                var queued = readQueue();
                queued.push(event);
                writeQueue(queued);
                return;
            }

            post(event).catch(function () {
                var queued = readQueue();
                queued.push(event);
                writeQueue(queued);
            });
        } catch (e) {
            // Health reporting must never break the page it is watching.
        }
    }

    window.orderpiqrHealth = {
        report: report,
        flush: flush,
        displayMode: displayMode,
        context: function () {
            return {displayMode: displayMode(), buildId: buildId(), clientTs: new Date().toISOString()};
        }
    };

    window.addEventListener('error', function (event) {
        // Resource errors (a failed <script>/<img>) arrive here too and have no
        // .error; they matter more than script errors, since a dead dependency
        // takes the whole module graph with it.
        var target = event && event.target;
        if (target && target !== window && (target.src || target.href)) {
            report('client_error', {
                reason: 'resource_failed',
                message: 'Failed to load ' + scrub(target.src || target.href)
            });
            return;
        }
        var where = event && event.filename
            ? ' (' + scrub(event.filename) + ':' + event.lineno + ')'
            : '';
        report('client_error', {
            reason: 'uncaught_error',
            message: ((event && event.message) || 'Unknown error') + where
        });
    }, true);

    window.addEventListener('unhandledrejection', function (event) {
        var reason = event && event.reason;
        var message = reason && reason.message ? reason.message : String(reason);
        report('client_error', {reason: 'unhandled_rejection', message: message});
    });

    window.addEventListener('online', flush);

    // Deliberately on load, not immediately: this file runs in <head>, before
    // the page defines csrfToken, so reporting any earlier guarantees a 403
    // (recoverable via the queue, but a wasted request on every single open).
    // Anything that throws before this point is queued and flushed here.
    window.addEventListener('load', function () {
        // The scanner is the one third-party runtime dependency. If it is
        // missing, the module that constructs it throws at import time and the
        // whole scan page goes inert — looking alive and doing nothing.
        if (typeof window.Html5Qrcode === 'undefined') {
            report('client_error', {
                reason: 'scanner_library_missing',
                message: 'Html5Qrcode failed to load — the scan page cannot start'
            });
        }
        report('app_lifecycle', {
            reason: 'app_open',
            severity: 'info',
            message: 'App opened in ' + displayMode() + ' mode'
                + (navigator.onLine ? '' : ' (offline)')
        });
        flush();
    });
}());
