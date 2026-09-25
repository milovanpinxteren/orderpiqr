// scanEventReporter.js
//
// Fire-and-forget reporting of pick-flow health events (failed scans,
// unreadable picklists, sync errors) to the server so company admins can see
// them on their dashboard. Reporting is best-effort by design: every error is
// swallowed and callers must never await the result — a broken report must
// never break picking.
import {getDeviceFingerprint} from './fingerprint.js';

// Client-side dedupe: the scanner keeps re-firing while the phone hovers over
// the same code, which would flood the log with identical events.
const recentReports = new Map();  // "eventType|scannedCode" -> last report ts
const DEDUPE_WINDOW_MS = 5000;

export function reportScanEvent(eventType, {scannedCode = '', picklistCode = '', message = ''} = {}) {
    try {
        if (!navigator.onLine) {
            return;  // the report would fail anyway; picking continues offline
        }

        const now = Date.now();
        const dedupeKey = `${eventType}|${scannedCode}`;
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
                    deviceFingerprint
                })
            }))
            .catch(() => { /* reporting must never break picking */ });
    } catch (e) {
        // Swallow everything (including a missing csrfToken global).
    }
}
