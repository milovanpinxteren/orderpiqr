// syncBadge.js
//
// The pick outbox (pickOutbox.js) makes queued-but-unsent picks invisible by
// design — that is the whole point of not blocking the picker on a bad
// connection. But invisible-by-design and invisible-by-accident look the same
// to a picker standing in a dead zone, so something on screen has to say
// "this is queued, not lost" as long as anything is waiting.
//
// This module speaks only to that one event. It does not poll, and it does
// not import pickOutbox's flush machinery — count() at load time for the
// first paint is the one exception, because the outbox-changed event that
// would otherwise supply that number may already have fired before this
// module's listener existed (module evaluation order is not a promise here).
import {count} from './pickOutbox.js';

const gettext = window.gettext;
const ngettext = window.ngettext;
const interpolate = window.interpolate;

const FLASH_MS = 3000;

const badge = document.getElementById('sync-badge');
const countEl = badge ? badge.querySelector('.sync-badge-count') : null;
const flagEl = badge ? badge.querySelector('.sync-badge-flag') : null;

// Tracked so the online/offline listeners (which carry no count of their own)
// and the >0-to-0 drain check have something to repaint against.
let lastCount = 0;
let lastFailed = false;
let flashTimer = null;

function countText(n) {
    return interpolate(
        ngettext('%(count)s pick waiting to sync', '%(count)s picks waiting to sync', n),
        {count: n}, true);
}

// Offline is shown either because the outbox itself just failed to reach the
// server, or because the browser already knows there is no point trying —
// the two cases read identically to a picker, so they share one state.
function isOffline(failed) {
    return !!failed || !navigator.onLine;
}

function render(n, failed) {
    clearTimeout(flashTimer);
    flashTimer = null;
    badge.classList.remove('sync-badge-flash');

    if (n <= 0) {
        badge.classList.add('hidden');
        badge.classList.remove('sync-badge-offline');
        return;
    }

    badge.classList.remove('hidden');
    if (countEl) countEl.textContent = countText(n);
    const offline = isOffline(failed);
    badge.classList.toggle('sync-badge-offline', offline);
    if (flagEl) flagEl.textContent = offline ? gettext('offline') : '';
}

// A drain deserves its own brief, calmer state rather than snapping straight
// to hidden — "it's gone" and "it's done" are different things to see happen.
function flashSynced() {
    badge.classList.remove('hidden', 'sync-badge-offline');
    badge.classList.add('sync-badge-flash');
    if (countEl) countEl.textContent = gettext('All picks synced');
    if (flagEl) flagEl.textContent = '';

    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => {
        badge.classList.add('hidden');
        badge.classList.remove('sync-badge-flash');
    }, FLASH_MS);
}

function handleChanged(event) {
    const detail = (event && event.detail) || {};
    const n = typeof detail.count === 'number' ? detail.count : 0;
    const failed = !!detail.lastFlushFailed;

    if (lastCount > 0 && n === 0) {
        flashSynced();
    } else if (n === 0 && flashTimer !== null) {
        // The outbox announces a drain twice (once at the pop, once at the end
        // of the flush run). The second event must not cut the flash short.
    } else {
        render(n, failed);
    }
    lastCount = n;
    lastFailed = failed;
}

// Defensive no-op: a page that never got the badge markup (or a markup typo)
// must lose the feature, not throw into the rest of the module graph.
if (badge) {
    try {
        lastCount = count();
    } catch (e) {
        lastCount = 0;
    }
    render(lastCount, false);

    document.addEventListener('outbox-changed', handleChanged);
    // These carry no count of their own — repaint with whatever outbox-changed
    // last reported, since only the online/offline state changed.
    window.addEventListener('online', () => render(lastCount, lastFailed));
    window.addEventListener('offline', () => render(lastCount, lastFailed));
}
