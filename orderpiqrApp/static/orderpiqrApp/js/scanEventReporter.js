// scanEventReporter.js
//
// Fire-and-forget reporting of pick-flow health events (failed scans,
// unreadable picklists, sync errors) to the server so company admins can see
// them on their dashboard. Reporting is best-effort by design: every error is
// swallowed and callers must never await the result — a broken report must
// never break picking.
//
// Delivery is delegated to window.orderpiqrHealth (clientHealth.js, a classic
// script loaded in <head>) so that both reporters share one offline queue.
// It is reached through the global rather than an import on purpose: pulling
// clientHealth.js into this module graph would subject it to the hashed-static
// rule that broke v123.
import {getDeviceFingerprint} from './fingerprint.js';

// Client-side dedupe: the scanner keeps re-firing while the phone hovers over
// the same code, which would flood the log with identical events.
const recentReports = new Map();  // "eventType|scannedCode" -> last report ts
const DEDUPE_WINDOW_MS = 5000;

export function reportScanEvent(eventType, {scannedCode = '', picklistCode = '', message = '', reason = ''} = {}) {
    try {
        const now = Date.now();
        const dedupeKey = `${eventType}|${scannedCode}|${reason}`;
        const lastReported = recentReports.get(dedupeKey);
        if (lastReported && now - lastReported < DEDUPE_WINDOW_MS) {
            return;
        }
        recentReports.set(dedupeKey, now);

        // Keep the dedupe map from growing over a long picking session.
        for (const [key, ts] of recentReports) {
            if (now - ts >= DEDUPE_WINDOW_MS) {
                recentReports.delete(key);
            }
        }

        // Preferred path: queues when offline instead of dropping. Events used
        // to be discarded outright whenever navigator.onLine was false, so the
        // errors that happen during a warehouse connectivity drop — the ones
        // that look most like a crash — were invisible by construction.
        if (window.orderpiqrHealth) {
            window.orderpiqrHealth.report(eventType, {scannedCode, picklistCode, message, reason});
            return;
        }

        // Fallback for pages that don't load clientHealth.js.
        getDeviceFingerprint()
            .then(deviceFingerprint => fetch('/orderpiqr/scan-event', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    eventType,
                    scannedCode,
                    picklistCode,
                    message,
                    reason,
                    deviceFingerprint,
                    buildId: window.SETTINGS?.build_id || '',
                    clientTs: new Date().toISOString()
                })
            }))
            .catch(() => { /* reporting must never break picking */ });
    } catch (e) {
        // Swallow everything (including a missing csrfToken global).
    }
}
