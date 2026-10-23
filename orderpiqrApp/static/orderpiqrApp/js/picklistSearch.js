// picklistSearch.js
//
// Search-and-claim: a magnifier floating over the camera opens a panel where
// the picker types part of an order code and taps a row to start picking it.
// This exists for phones that cannot decode a dense picklist QR at all — it is
// the only way those devices get a list, so every failure here has to be
// visible rather than a silent empty panel.
//
// Claiming goes through the SAME endpoint as the queue page
// (queue_claim_order) and ends the same way: the claimed order is written to
// sessionStorage and the page navigates to ?order=<code>, where the existing
// claimed-order flow in camera_page.js picks it up. Nothing here parses or
// renders a picklist — duplicating that is how the two paths would drift.

import {showNotification} from './notifications.js';
import {getDeviceFingerprint} from './fingerprint.js';

const gettext = window.gettext;
const ngettext = window.ngettext;
const interpolate = window.interpolate;

// Long enough that typing a 6-character order code is one request, short
// enough that the picker does not think the panel is dead.
const DEBOUNCE_MS = 300;

// The browse-mode (empty query) response is the only one worth keeping: it is
// the full pick-day list, so any later query can be served out of it offline
// by filtering client-side. A filtered response is a subset and would make a
// worse cache than the one already on disk, so only browse mode overwrites it.
const SNAPSHOT_KEY = 'orderpiqr_queue_snapshot';

const toggle = document.getElementById('picklist-search-toggle');
const panel = document.getElementById('picklist-search-panel');
const input = document.getElementById('picklist-search-input');
const resultsBox = document.getElementById('picklist-search-results');
const closeBtn = document.getElementById('picklist-search-close');

// Every URL comes off the panel's data-* attributes. The whole site is served
// under an i18n language prefix, so a path written into this file 404s in five
// of the six locales.
const searchUrl = panel ? (panel.dataset.searchUrl || '') : '';
const claimUrlTemplate = panel ? (panel.dataset.claimUrl || '') : '';
const indexUrl = panel ? (panel.dataset.indexUrl || '') : '';

let debounceTimer = null;
// Responses can arrive out of order; only the newest request may paint, or a
// slow early keystroke overwrites the list the picker is actually looking at.
let requestSeq = 0;
// One claim at a time: two in flight means one of them loses its picklist.
let claiming = false;

function claimUrlFor(orderId) {
    // The server-rendered template carries a placeholder id of 0 as the last
    // path segment. Anchored to the end on purpose: a plain replace('0', id)
    // would hit a 0 anywhere earlier in the path or language prefix.
    return claimUrlTemplate.replace(/0(\/?)$/, orderId + '$1');
}

function itemSummary(order) {
    const itemCount = Number(order.item_count) || 0;
    const lineCount = Number(order.line_count) || 0;
    const items = interpolate(
        ngettext('%(count)s item', '%(count)s items', itemCount),
        {count: itemCount}, true);
    const lines = interpolate(
        ngettext('%(count)s line', '%(count)s lines', lineCount),
        {count: lineCount}, true);
    return items + ' · ' + lines;
}

function createdDate(order) {
    // The contract is a plain YYYY-MM-DD date, but the endpoint may hand back a
    // full ISO timestamp; keep only the day either way rather than printing a
    // "T" at the picker.
    return String(order.created_at || '').slice(0, 10);
}

function takeoverMessage(holder) {
    // Name the colleague who gets interrupted — the same wording the queue page
    // uses. An abstract confirm gets clicked through; "take this over from
    // Mariana" does not.
    if (holder) {
        return interpolate(
            gettext('%(name)s is picking this order right now. Take it over? Picks they already recorded are kept.'),
            {name: holder}, true);
    }
    return gettext('This order is being picked by someone else. Take it over? Picks they already recorded are kept.');
}

function renderMessage(text) {
    resultsBox.textContent = '';
    const empty = document.createElement('p');
    empty.className = 'picklist-search-empty';
    empty.textContent = text;
    resultsBox.appendChild(empty);
}

// `offline` threads through to startClaim rather than being handled here, so
// there is exactly one place a tap can turn into a POST — easy to miss if the
// check only lived at the call site instead.
function renderResults(results, offline) {
    resultsBox.textContent = '';
    if (!results.length) {
        renderMessage(gettext('No matching orders'));
        return;
    }
    results.forEach(order => {
        const inProgress = order.status === 'in_progress';

        // The whole row is the button: a gloved thumb on a phone should not
        // have to find a small action target.
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'picklist-search-row' + (inProgress ? ' in-progress' : '');
        row.dataset.orderId = order.order_id;

        const code = document.createElement('span');
        code.className = 'picklist-search-row-code';
        code.textContent = order.order_code;
        row.appendChild(code);

        const meta = document.createElement('span');
        meta.className = 'picklist-search-row-meta';
        meta.textContent = itemSummary(order) + ' · ' + createdDate(order);
        row.appendChild(meta);

        const action = document.createElement('span');
        action.className = 'picklist-search-row-action';
        if (inProgress) {
            const holder = document.createElement('span');
            holder.className = 'picklist-search-row-holder';
            holder.textContent = order.picked_by
                ? interpolate(gettext('Picking: %(name)s'), {name: order.picked_by}, true)
                : gettext('In Progress');
            action.appendChild(holder);

            const takeover = document.createElement('span');
            takeover.className = 'picklist-search-row-takeover';
            takeover.textContent = gettext('Take Over');
            action.appendChild(takeover);
        } else {
            const start = document.createElement('span');
            start.className = 'picklist-search-row-start';
            start.textContent = gettext('Start Picking');
            action.appendChild(start);
        }
        row.appendChild(action);

        row.addEventListener('click', () => startClaim(order, row, offline));
        resultsBox.appendChild(row);
    });
}

function saveSnapshot(results) {
    try {
        localStorage.setItem(SNAPSHOT_KEY, JSON.stringify({ts: Date.now(), results: results}));
    } catch (e) {
        // Best-effort: a snapshot that fails to write just means no offline
        // fallback later, not a broken search panel now.
    }
}

function readSnapshot() {
    try {
        const raw = localStorage.getItem(SNAPSHOT_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || Object.prototype.toString.call(parsed.results) !== '[object Array]') return null;
        return parsed;
    } catch (e) {
        return null;    // storage can throw outright in private modes
    }
}

function renderOfflineBanner(ts) {
    const banner = document.createElement('div');
    banner.className = 'picklist-search-offline-banner';
    banner.textContent = interpolate(
        gettext('Offline — showing the list from %(time)s'),
        {time: new Date(ts).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})},
        true);
    resultsBox.insertBefore(banner, resultsBox.firstChild);
}

// Called wherever runSearch gives up on the network. Returns false when there
// is nothing to fall back to, so the caller can fall through to the plain
// "Could not search orders" message that existed before this queue existed.
function tryOfflineFallback(query) {
    const snapshot = readSnapshot();
    if (!snapshot) return false;

    const needle = query.toLowerCase();
    const filtered = needle
        ? snapshot.results.filter(order => String(order.order_code || '').toLowerCase().indexOf(needle) !== -1)
        : snapshot.results;

    renderResults(filtered, true);
    renderOfflineBanner(snapshot.ts);
    return true;
}

function runSearch(query) {
    const seq = ++requestSeq;
    const url = query ? searchUrl + '?q=' + encodeURIComponent(query) : searchUrl;

    fetch(url, {headers: {'Accept': 'application/json'}})
        .then(response => response.json()
            .then(data => ({httpStatus: response.status, data: data}))
            .catch(() => ({httpStatus: response.status, data: null})))
        .then(({httpStatus, data}) => {
            if (seq !== requestSeq) return;   // a later keystroke already answered
            if (httpStatus === 403) {
                // The feature was switched off for this customer while the page
                // was open. Take the entry point away instead of leaving a
                // button that only ever errors.
                closePanel();
                if (toggle) toggle.style.display = 'none';
                showNotification(
                    (data && data.message) || gettext('Order search is not available.'), true);
                return;
            }
            if (!data) {
                // No parseable body at all reads the same to the picker as no
                // response ever arriving — try the cached list before the
                // generic failure message.
                if (tryOfflineFallback(query)) return;
                renderMessage(gettext('Could not search orders'));
                showNotification(gettext('Could not search orders'), true);
                return;
            }
            if (data.status !== 'ok') {
                // A real response that says "no" (a feature-off message, a
                // validation error) is not a connectivity problem, so it does
                // not get the offline fallback.
                renderMessage(gettext('Could not search orders'));
                showNotification(data.message || gettext('Could not search orders'), true);
                return;
            }
            if (!query) {
                saveSnapshot(data.results || []);
            }
            renderResults(data.results || [], false);
        })
        .catch(() => {
            if (seq !== requestSeq) return;
            if (tryOfflineFallback(query)) return;
            renderMessage(gettext('Could not search orders'));
            showNotification(gettext('Could not search orders'), true);
        });
}

function startClaim(order, row, offline) {
    if (claiming) return;
    if (offline) {
        // The row came from the cached snapshot, not a live search — claiming
        // is out of scope while offline, so the tap must not reach fetch at all.
        showNotification(gettext("You're offline — reconnect to claim orders."), true);
        return;
    }

    const force = order.status === 'in_progress';
    const message = force
        ? takeoverMessage(order.picked_by)
        : interpolate(gettext('Start picking order %(code)s?'),
                      {code: order.order_code}, true);
    if (!confirm(message)) return;

    postClaim(order, row, force);
}

function postClaim(order, row, force) {
    claiming = true;
    row.disabled = true;
    row.classList.add('busy');

    getDeviceFingerprint().then(deviceFingerprint => {
        const body = {deviceFingerprint: deviceFingerprint};
        if (force) body.force = true;

        return fetch(claimUrlFor(order.order_id), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(body)
        })
            .then(response => response.json()
                .then(data => ({httpStatus: response.status, data: data}))
                .catch(() => ({httpStatus: response.status, data: null})))
            .then(({httpStatus, data}) => {
                if (data && data.status === 'ok') {
                    sessionStorage.setItem('claimed_order', JSON.stringify({
                        order_code: data.order_code,
                        picklist: data.picklist
                    }));
                    showNotification(gettext('Order claimed! Redirecting...'), false);
                    // Same short delay as the queue page: the picker gets to see
                    // which order they are now on before the page swaps.
                    setTimeout(() => {
                        window.location.href =
                            indexUrl + '?order=' + encodeURIComponent(data.order_code);
                    }, 500);
                    return;
                }

                if (httpStatus === 409 && !force) {
                    // The row was queued when it was drawn and somebody claimed
                    // it while the panel sat open. Offer the takeover now rather
                    // than failing a tap the picker made in good faith.
                    releaseRow(row, order);
                    const holder = (data && data.picked_by) || order.picked_by || '';
                    if (confirm(takeoverMessage(holder))) {
                        postClaim(order, row, true);
                    }
                    return;
                }

                showNotification(
                    (data && data.message) || gettext('Error claiming order'), true);
                if (data && data.redirect_url) {
                    // Device could not be resolved — send the picker to name entry.
                    setTimeout(() => { window.location.href = data.redirect_url; }, 1500);
                    return;
                }
                releaseRow(row, order);
            })
            .catch(() => {
                showNotification(gettext('Error claiming order'), true);
                releaseRow(row, order);
            });
    }).catch(() => {
        showNotification(gettext('Error claiming order'), true);
        releaseRow(row, order);
    });
}

function releaseRow(row, order) {
    claiming = false;
    row.disabled = false;
    row.classList.remove('busy');
    if (order) row.dataset.orderId = order.order_id;
}

function openPanel() {
    panel.classList.remove('hidden');
    toggle.setAttribute('aria-expanded', 'true');
    // Browse mode: an empty query lists the current pick days' orders, so the
    // panel is useful before a single character is typed.
    renderMessage(gettext('Searching…'));
    runSearch(input.value.trim());
    input.focus();
}

function closePanel() {
    panel.classList.add('hidden');
    toggle.setAttribute('aria-expanded', 'false');
    clearTimeout(debounceTimer);
}

function init() {
    if (!toggle || !panel || !input || !resultsBox) return;
    // The toggle itself is revealed by the settings gate in index.html; this
    // guard keeps the panel from ever fetching when the feature is off, even if
    // something else unhides the button.
    if (window.SETTINGS?.picklist_search_enabled !== true) return;

    toggle.addEventListener('click', () => {
        if (panel.classList.contains('hidden')) {
            // Both floating panels open covers the whole feed, even though the
            // two buttons sit on opposite corners.
            const cameraControls = document.getElementById('camera-controls');
            if (cameraControls) cameraControls.classList.add('hidden');
            openPanel();
        } else {
            closePanel();
        }
    });

    if (closeBtn) closeBtn.addEventListener('click', closePanel);

    input.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        const query = input.value.trim();
        debounceTimer = setTimeout(() => runSearch(query), DEBOUNCE_MS);
    });

    input.addEventListener('keydown', event => {
        if (event.key === 'Enter') {
            // A phone keyboard's search key should not wait out the debounce.
            event.preventDefault();
            clearTimeout(debounceTimer);
            runSearch(input.value.trim());
        }
    });

    // Reception is back: an open panel showing snapshot rows (whose taps
    // refuse to claim) should swap to live rows without waiting for a
    // keystroke.
    window.addEventListener('online', () => {
        if (!panel.classList.contains('hidden')) {
            runSearch(input.value.trim());
        }
    });

    // Close when tapping anywhere else on the page, like the camera options
    // panel — the feed underneath has to stay reachable.
    document.addEventListener('click', event => {
        if (!toggle.contains(event.target) && !panel.contains(event.target)) {
            closePanel();
        }
    });
}

init();
