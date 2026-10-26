// pickOutbox.js
//
// The four business-critical POSTs of the pick flow (claim a list, pick, bulk
// pick, complete) used to be single fire-and-forget fetches: no timeout, no
// retry, no queue. In a cooled warehouse with bad reception that means the list
// advances on screen while the server hears nothing, and the pick is lost for
// good. They now go through this queue instead.
//
// Three properties carry the correctness:
//
//  1. STRICT FIFO, head blocks tail. A claim must reach the server before any
//     pick for that order, or the pick is rejected against a list the server
//     has never heard of. The head op therefore blocks the whole queue while it
//     is retrying — ordering beats throughput here.
//  2. Idempotency. Every pick/bulk op carries a generated pickId, so a retry of
//     an op whose response was lost cannot double-count (see the server-side
//     client_pick_id check).
//  3. Durability. The queue lives in localStorage, so a reload, a crash or the
//     picker closing the app mid-flush does not lose what was queued.
//
// Style follows clientHealth.js: every storage access is wrapped, the queue is
// bounded, and flushing is serialised. Unlike clientHealth.js this file IS part
// of the ES module graph, so it must never be referenced from a template with
// {% static %} — see the v123 note at the top of clientHealth.js.
//
// It reaches health reporting through window.orderpiqrHealth rather than an
// import, for the same reason scanEventReporter.js does.
import {getDeviceFingerprint} from './fingerprint.js';

const STORAGE_KEY = 'orderpiqr_pick_outbox';
// 'short' targets the same URL as 'pick' (/orderpiqr/product-pick, with
// successful:false). The kind is kept distinct because it drives client-side
// semantics — never shed, carries a pickId, its own rejection copy — which
// are independent of the endpoint it happens to share.
const KINDS = ['claim', 'pick', 'bulk', 'complete', 'short'];

// Ops nobody can reconstruct. A dropped short is as bad as a dropped pick: it
// is the picker's declaration that a line could not be filled, and losing it
// turns a recorded short back into an invisible "lost" line — exactly the
// distinction this feature exists to record.
const WORK_KINDS = ['pick', 'bulk', 'short'];

function isWork(kind) {
    return WORK_KINDS.indexOf(kind) !== -1;
}

const MAX_OPS = 200;
const MAX_BYTES = 128 * 1024;
// A claim payload carries the whole list and can exceed the browser's cap on
// keepalive request bodies (64KB); asking for keepalive above it makes fetch
// reject outright, so only small ops get it. Small ops are the ones that need
// it most: a pick made as the picker pockets the phone must still go out.
const KEEPALIVE_MAX_BYTES = 60 * 1024;
const REQUEST_TIMEOUT_MS = 10000;
const BACKOFF_STEP_MS = 5000;
const BACKOFF_MAX_MS = 60000;
const FLUSH_INTERVAL_MS = 15000;
// ~8 minutes of failing on the same op. The op is never dropped (it is a
// picker's work), but a queue wedged this long is worth one health event.
const STUCK_ATTEMPTS = 10;

let flushing = false;
let flushTimer = null;
let lastFlushFailed = false;
let cachedFingerprint = '';
const stuckReported = new Set();
// Fallback store, used only while localStorage refuses to hold the queue
// (private modes throw outright, and a full origin can refuse a write). It
// loses the queue on reload — but losing it at reload beats never queueing at
// all, which is what dropping straight through to storage errors would mean.
let memoryOps = null;
let storageWarned = false;

// Primed once, so enqueue() can stay synchronous — see the note in enqueue().
try {
    getDeviceFingerprint().then(value => { cachedFingerprint = value || ''; }).catch(() => { /* resolved again at send time */ });
} catch (e) {
    // fingerprint.js is defensive itself; nothing to do here.
}

function newId() {
    try {
        if (typeof crypto !== 'undefined' && crypto.randomUUID) {
            return crypto.randomUUID();
        }
    } catch (e) {
        // Some embedded webviews expose crypto but throw on use.
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

function csrf() {
    try {
        if (window.csrfToken) return window.csrfToken;
    } catch (e) {
        // fall through
    }
    try {
        return typeof csrfToken !== 'undefined' ? csrfToken : '';
    } catch (e) {
        return '';
    }
}

function reportHealth(message, reason) {
    try {
        if (window.orderpiqrHealth) {
            window.orderpiqrHealth.report('sync_error', {reason: reason || 'outbox', message: message});
        }
    } catch (e) {
        // Reporting must never break picking.
    }
}

// An op written by an older build (or a half-written entry) must not be able to
// wedge the head of the queue forever, so anything unusable is skipped on read.
function isUsableOp(op) {
    return !!op && typeof op === 'object'
        && typeof op.id === 'string' && op.id !== ''
        && typeof op.url === 'string' && op.url !== ''
        && KINDS.indexOf(op.kind) !== -1
        && !!op.payload && typeof op.payload === 'object';
}

function readOps() {
    if (memoryOps !== null) return memoryOps.slice();
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        if (Object.prototype.toString.call(parsed) !== '[object Array]') return [];
        return parsed.filter(isUsableOp);
    } catch (e) {
        return [];   // storage can throw outright in private modes
    }
}

// Which op to sacrifice when the queue is over its bounds: a 'complete' can be
// re-derived (the list empties again, or an admin closes it), a 'claim' only
// costs a re-scan — a pick or bulk pick is work nobody can reconstruct.
function dropIndex(ops) {
    let index = ops.findIndex(op => op.kind === 'complete');
    if (index === -1) index = ops.findIndex(op => op.kind === 'claim');
    return index === -1 ? 0 : index;
}

function overBounds(ops) {
    if (ops.length > MAX_OPS) return true;
    try {
        return JSON.stringify(ops).length > MAX_BYTES;
    } catch (e) {
        return true;   // unserialisable: shed something and try again
    }
}

// Returns true when the list is on disk. On a quota failure it sheds droppable
// ops and retries, but it will never trade a queued pick for storage space:
// that case falls back to the memory store instead, where the pick survives at
// least until the page is closed.
function persist(ops) {
    for (;;) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(ops));
            return true;
        } catch (e) {
            if (ops.length === 0) {
                try { localStorage.removeItem(STORAGE_KEY); } catch (e2) { /* nothing left to try */ }
                return false;
            }
            const index = dropIndex(ops);
            if (isWork(ops[index].kind)) return false;
            ops.splice(index, 1);
        }
    }
}

function writeOps(ops) {
    const kept = ops.slice();
    let droppedWork = 0;

    while (kept.length > 0 && overBounds(kept)) {
        const index = dropIndex(kept);
        if (isWork(kept[index].kind)) droppedWork += 1;
        kept.splice(index, 1);
    }

    if (persist(kept)) {
        memoryOps = null;
    } else {
        memoryOps = kept.slice();
        if (!storageWarned) {
            storageWarned = true;
            reportHealth('pick outbox cannot write localStorage; queue is memory-only '
                + 'for this page session', 'outbox_storage_unavailable');
        }
    }

    if (droppedWork > 0) {
        // Never silent: a dropped pick is a line the warehouse will ship short.
        reportHealth('pick outbox overflow: dropped ' + droppedWork + ' queued pick op(s)', 'outbox_overflow');
    }
    return kept;
}

// The three events this module speaks, all on `document`:
//
//   outbox-changed       {count, lastFlushFailed}  every queue mutation, and
//                                                  once at the end of a flush
//   outbox-op-done       {op, data}                2xx; data is null when the
//                                                  body was not parseable JSON
//   outbox-op-rejected   {op, status, data}        4xx, never retried
//
// A pure network failure produces no op event at all — that is the whole point
// of the queue; outbox-changed with lastFlushFailed is how it becomes visible.
function emitChanged(count) {
    try {
        document.dispatchEvent(new CustomEvent('outbox-changed', {
            detail: {count: count, lastFlushFailed: lastFlushFailed}
        }));
    } catch (e) {
        // A listener that throws must not take the outbox with it.
    }
}

function emitResult(name, detail) {
    try {
        document.dispatchEvent(new CustomEvent(name, {detail: detail}));
    } catch (e) {
        // Same contract: the queue has already been persisted at this point.
    }
}

function stopTimer() {
    if (flushTimer !== null) {
        clearInterval(flushTimer);
        flushTimer = null;
    }
}

// The interval exists only while there is something to send; an idle app must
// not wake up every 15 seconds for nothing.
function syncTimer(count) {
    if (count > 0 && flushTimer === null) {
        flushTimer = setInterval(() => { flush(); }, FLUSH_INTERVAL_MS);
    } else if (count === 0) {
        stopTimer();
    }
}

function startTimeout() {
    try {
        if (typeof AbortSignal !== 'undefined' && AbortSignal.timeout) {
            return {signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS), done: () => {}};
        }
        if (typeof AbortController !== 'undefined') {
            const controller = new AbortController();
            const timer = setTimeout(() => { try { controller.abort(); } catch (e) { /* already settled */ } }, REQUEST_TIMEOUT_MS);
            return {signal: controller.signal, done: () => clearTimeout(timer)};
        }
    } catch (e) {
        // fall through to an unguarded request rather than no request
    }
    return {signal: undefined, done: () => {}};
}

async function sendOp(op) {
    const payload = Object.assign({}, op.payload);
    if (!payload.deviceFingerprint) {
        // Enqueued before the fingerprint was available. Sending without one
        // earns a rejection, which would pop a real pick, so resolve it here.
        try {
            payload.deviceFingerprint = cachedFingerprint || (await getDeviceFingerprint()) || '';
        } catch (e) {
            payload.deviceFingerprint = '';
        }
    }

    const body = JSON.stringify(payload);
    const timeout = startTimeout();
    let response;
    try {
        response = await fetch(op.url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrf()
            },
            body: body,
            signal: timeout.signal,
            keepalive: body.length < KEEPALIVE_MAX_BYTES
        });
    } catch (e) {
        return {outcome: 'retry'};      // offline, timed out, or request refused
    } finally {
        timeout.done();
    }

    // 5xx and anything else unexpected is the server's problem, not the
    // payload's: keep the op and come back to it. The body is deliberately not
    // read on that path — it is usually an HTML error page, and the response
    // stream can stall on the same bad link that caused the failure.
    if (!response.ok && (response.status < 400 || response.status >= 500)) {
        return {outcome: 'retry'};
    }

    let data = null;
    try {
        data = await response.json();
    } catch (e) {
        data = null;    // empty or non-JSON body; callers must tolerate null
    }

    if (response.ok) return {outcome: 'done', status: response.status, data: data};
    return {outcome: 'reject', status: response.status, data: data};
}

// Serialised and strictly in order: one op in flight, and the head blocks the
// tail until it either lands or is rejected. Never rejects — callers fire and
// forget it.
export async function flush() {
    if (flushing) return;

    const ops = readOps();
    if (ops.length === 0) {
        lastFlushFailed = false;
        syncTimer(0);
        return;
    }
    if (!navigator.onLine) {
        // Nothing to learn from trying, and a burnt attempt would push the
        // backoff out for the moment reception comes back.
        lastFlushFailed = true;
        emitChanged(ops.length);
        syncTimer(ops.length);
        return;
    }

    flushing = true;    // set before the first await, so two callers in one tick cannot both pass
    let failed = false;
    try {
        for (;;) {
            const current = readOps();
            if (current.length === 0) break;

            const op = current[0];
            if (op.nextAttemptAt && Date.now() < op.nextAttemptAt) {
                failed = true;          // still in backoff; the head owns the queue
                break;
            }

            const result = await sendOp(op);

            if (result.outcome === 'retry') {
                const latest = readOps();
                if (latest.length > 0 && latest[0].id === op.id) {
                    latest[0].attempts = (latest[0].attempts || 0) + 1;
                    latest[0].nextAttemptAt = Date.now()
                        + Math.min(latest[0].attempts * BACKOFF_STEP_MS, BACKOFF_MAX_MS);
                    writeOps(latest);
                    if (latest[0].attempts === STUCK_ATTEMPTS && !stuckReported.has(op.id)) {
                        stuckReported.add(op.id);
                        reportHealth('pick outbox stuck on ' + op.kind + ' after '
                            + latest[0].attempts + ' attempts', 'outbox_stuck');
                    }
                }
                failed = true;
                break;
            }

            // Pop before announcing: a listener that reloads, clears the list or
            // enqueues something else must never see state that is not on disk
            // yet. Guarded on the id because another tab may have popped it.
            const latest = readOps();
            if (latest.length > 0 && latest[0].id === op.id) {
                latest.shift();
                emitChanged(writeOps(latest).length);
            }
            const stillHead = readOps();
            const popFailed = stillHead.length > 0 && stillHead[0].id === op.id;

            // The result is announced either way: the server has already acted
            // on this op, and the listeners (already-picked trimming, the
            // stop-the-line overlay) must hear about it even if the queue could
            // not be updated.
            if (result.outcome === 'done') {
                emitResult('outbox-op-done', {op: op, data: result.data});
            } else {
                emitResult('outbox-op-rejected', {op: op, status: result.status, data: result.data});
            }

            if (popFailed) {
                // Stopping is the only safe move: looping would re-send this op
                // forever. It is re-sent on a later flush, which the server's
                // pickId check makes harmless.
                reportHealth('pick outbox could not pop a settled ' + op.kind + ' op', 'outbox_pop_failed');
                failed = true;
                break;
            }

            if (!navigator.onLine) {
                failed = true;
                break;
            }
        }
    } catch (e) {
        // Unexpected (a listener throwing, storage vanishing). Leave the queue
        // as it is and let the interval come back to it.
        failed = true;
    } finally {
        flushing = false;
        lastFlushFailed = failed;
        const remaining = readOps().length;
        emitChanged(remaining);
        syncTimer(remaining);
    }
}

// Synchronous on purpose, and that is load-bearing: handlePicklist enqueues the
// claim before it hands the list to camera_page.js, so there is no window in
// which a pick for an order can be queued ahead of that order's claim. An
// awaited device fingerprint here would reopen exactly that window, which is
// why the fingerprint is primed at module load and re-resolved at send time if
// it is somehow still missing.
export function enqueue(kind, url, payload) {
    try {
        if (KINDS.indexOf(kind) === -1 || !url) {
            console.error('pickOutbox: refusing op', kind, url);
            return null;
        }
        const body = Object.assign({}, payload || {});
        if (!body.deviceFingerprint) body.deviceFingerprint = cachedFingerprint || '';
        if (isWork(kind) && !body.pickId) {
            // The server deduplicates on this: a retry of an op whose response
            // was lost must not mark a second row.
            body.pickId = newId();
        }

        const op = {
            id: newId(),
            kind: kind,
            url: url,
            payload: body,
            queuedAt: new Date().toISOString(),
            attempts: 0,
            nextAttemptAt: 0
        };

        const ops = readOps();
        ops.push(op);
        emitChanged(writeOps(ops).length);
        flush();
        return op.id;
    } catch (e) {
        console.error('pickOutbox: enqueue failed', e);
        reportHealth('pick outbox could not queue a ' + kind + ' op', 'outbox_enqueue_failed');
        return null;
    }
}

export function count() {
    return readOps().length;
}

window.addEventListener('online', function () {
    // Clear the head's backoff: reception is back, and waiting out a 60s timer
    // set while offline is exactly the lag pickers read as "nothing is syncing".
    const ops = readOps();
    if (ops.length > 0 && ops[0].nextAttemptAt) {
        ops[0].nextAttemptAt = 0;
        ops[0].attempts = 0;
        writeOps(ops);
    }
    flush();
});

// On load, drain whatever the previous session left behind. This module is
// evaluated before camera_page.js (which imports it, transitively), so the
// first request may well be in flight before the result listeners exist — that
// is safe, because a response can only be dispatched in a later task, after
// the whole module graph has finished evaluating.
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { flush(); });
} else {
    flush();
}
