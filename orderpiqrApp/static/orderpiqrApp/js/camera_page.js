// camera_page.js
import {initializeScanner, pauseScanner, resumeScanner} from './qrScanner.js';
import {showNotification} from './notifications.js';
import {toggleOrderImportance, updateOrderImportanceButton, getIsOrderImportant} from './orderImportance.js';
import {handlePicklist, sortPicklist, canonicalCode, findProductByCode} from './picklistHandler.js';
import {updateScannedList} from './domUpdater.js';
import {reportScanEvent} from './scanEventReporter.js';
import {initAppUpdater} from './appUpdater.js';
import {enqueue} from './pickOutbox.js';

const gettext = window.gettext;
const ngettext = window.ngettext;
const interpolate = window.interpolate;
// Access the productData object injected into the HTML
export let productData;
// top-level (near other state)
let lastPickTs = null;

// The scanner keeps firing while the phone is held over the same picklist QR.
// Re-starting the list makes the server reject it as already claimed, wiping
// the picker's progress — so re-scans of the active list are ignored, and an
// identical picklist payload is ignored until the phone has been away from
// the code for a few seconds.
let lastPicklistScan = {code: null, ts: 0};
const PICKLIST_RESCAN_COOLDOWN_MS = 4000;

if (navigator.onLine) {
    // ✅ Online: trust server-rendered data
    const el = document.getElementById("product-data");
    if (el && el.textContent) {
        try {
            productData = JSON.parse(el.textContent);
            window.productData = productData;
            localStorage.setItem('product_data', JSON.stringify(productData));
        } catch (e) {
            console.error("Failed to parse product data from DOM", e);
            showNotification(gettext("Could not load product data from server"), true);
        }
    } else {
        console.warn("No server-rendered product data found");
        showNotification(gettext("No product data found on page"), true);
    }
} else {
    // 🚨 Offline: fall back to cache
    const cached = localStorage.getItem('product_data');
    if (cached) {
        try {
            productData = JSON.parse(cached);
            window.productData = productData;
            showNotification(gettext("Offline mode: using cached product data"), true);
        } catch (e) {
            console.error("Corrupted cached product data", e);
            showNotification(gettext("Cached product data is not usable"), true);
        }
    } else {
        showNotification(gettext("No product data available while offline"), true);
    }
}


// export let productData = window.productData || {};  // Fallback in case the data is not injected
export let currentPicklist = []; // Array to store the current picklist
export let currentOrderID = null;
let originalPicklistOrder = []; // Store the original order for re-sorting

// ---------------------------------------------------------------------------
// Declared shorts
//
// Lines the picker could not fill: {productCode: {qty, reason}}. They are
// taken OFF currentPicklist (there is nothing left to pick) but they are not
// gone — the server recorded them as outcome='short', they render at the
// bottom of the table, they survive a reload, and a later scan of the same
// product reclaims one of them.
//
// Cleared wherever currentPicklist is cleared, and nowhere else: a short that
// outlived its list would be attributed to the next one.
// ---------------------------------------------------------------------------
const shortedLines = {};

function clearShortedLines() {
    Object.keys(shortedLines).forEach(key => delete shortedLines[key]);
}

// One render entry point, so that nothing can redraw the table and silently
// drop the short rows (manualOverride.js reaches it through this export).
export function renderList() {
    updateScannedList(currentPicklist, productData, shortedLines);
}

// ---------------------------------------------------------------------------
// Active-list persistence
//
// currentPicklist otherwise lives only in page memory: a reload while a list
// is in progress — a deploy, a crash, the picker switching apps and the
// browser reclaiming the tab — used to lose it outright even though the
// server still has every pick that reached it. This mirrors it to
// localStorage on every mutation so a reload can pick the list back up.
//
// It does NOT re-claim anything: the server already has this list (the claim
// was queued before the list ever reached the screen), and any outbox ops
// still pending for it are untouched — they flush on their own once the page
// is back, same as any other reload.
// ---------------------------------------------------------------------------

const ACTIVE_LIST_KEY = 'orderpiqr_active_list';
const ACTIVE_LIST_MAX_AGE_MS = 12 * 60 * 60 * 1000;

function persistActiveList() {
    try {
        // An empty list has nothing to restore, and is about to be (or just
        // was) cleared by the completion path — never resurrect it.
        //
        // Unless shorts are open: "nothing left to pick, two lines missing" is
        // a real state the picker can sit in (the summary overlay's "Keep
        // picking"), and it is precisely the state a reload used to erase.
        // Every completion path calls clearActiveList(), so an empty list with
        // no shorts still never survives.
        if (!currentOrderID) return;
        if (currentPicklist.length === 0 && Object.keys(shortedLines).length === 0) return;
        localStorage.setItem(ACTIVE_LIST_KEY, JSON.stringify({
            orderID: currentOrderID,
            picklist: currentPicklist,
            shorted: shortedLines,
            originalCounts: originalProductCounts,
            originalOrder: originalPicklistOrder,
            savedAt: Date.now(),
        }));
    } catch (e) {
        // Storage can throw outright in private modes; the restore safety
        // net is best-effort and must never block picking.
    }
}

function clearActiveList() {
    try {
        localStorage.removeItem(ACTIVE_LIST_KEY);
    } catch (e) {
        // Nothing left to try.
    }
}

// Only called when loadClaimedOrder() found no server-rendered or
// sessionStorage claim — those both mean a fresh list was just handed to
// this device, which must win over whatever was saved from before.
function restoreActiveList() {
    try {
        const raw = localStorage.getItem(ACTIVE_LIST_KEY);
        if (!raw) return false;
        const saved = JSON.parse(raw);
        if (!saved || !saved.orderID || !Array.isArray(saved.picklist)) {
            return false;
        }
        const savedShorts = (saved.shorted && typeof saved.shorted === 'object') ? saved.shorted : {};
        if (saved.picklist.length === 0 && Object.keys(savedShorts).length === 0) {
            return false;
        }
        if (!saved.savedAt || Date.now() - saved.savedAt >= ACTIVE_LIST_MAX_AGE_MS) {
            // Stale enough that the server lock has almost certainly moved on
            // (STALE_LOCK_AFTER on the server is 10 minutes); resurrecting it
            // would hand the picker a list someone else may now hold.
            clearActiveList();
            return false;
        }
        if (!productData || productData.length === 0) {
            // Nothing to render the list against yet; leave the saved entry
            // in place and try again on a later load.
            return false;
        }

        currentPicklist.length = 0;
        currentPicklist.push(...saved.picklist);
        currentOrderID = saved.orderID;
        originalPicklistOrder = Array.isArray(saved.originalOrder) && saved.originalOrder.length > 0
            ? saved.originalOrder : [...currentPicklist];
        Object.keys(originalProductCounts).forEach(key => delete originalProductCounts[key]);
        Object.assign(originalProductCounts, saved.originalCounts || {});
        clearShortedLines();
        Object.assign(shortedLines, savedShorts);

        renderList();
        updatePicklistCodeDisplay(currentOrderID);
        lastPickTs = Date.now();

        showNotification(gettext("Restored your list in progress."), false);
        return true;
    } catch (e) {
        console.error('Error restoring active list', e);
        return false;
    }
}

// Toggle button for order importance
const toggleButton = document.getElementById('toggle-order-btn');

// Event listener for toggling order importance
toggleButton.addEventListener('click', function () {
    toggleOrderImportance();
    updateOrderImportanceButton(toggleButton);
});

let isProcessingScan = false;  // Flag to ensure only one scan is processed at a time
let originalProductCounts = {}
// Initialize the QR code scanner
initializeScanner((scannedCode) => {
    if (isProcessingScan) {
        console.log("Scan already in process, ignoring duplicate scan.");
        return;  // Exit if a scan is already being processed
    }

    // Set the flag to indicate that scanning is in progress
    isProcessingScan = true;
    console.log("scanned code", scannedCode);
    if (isPicklist(scannedCode)) {
        const scannedOrderID = String(scannedCode).split("\n")[0].trim();
        const isActiveList = currentPicklist.length > 0 && currentOrderID &&
            scannedOrderID === String(currentOrderID).trim();
        const seenRecently = scannedCode === lastPicklistScan.code &&
            Date.now() - lastPicklistScan.ts < PICKLIST_RESCAN_COOLDOWN_MS;
        lastPicklistScan.code = scannedCode;
        lastPicklistScan.ts = Date.now();

        if (seenRecently) {
            // The phone never left the QR — the scanner just re-fired.
            isProcessingScan = false;
            return;
        }

        let skipConfirm = false;
        if (isActiveList) {
            // Deliberate re-scan of the list already on screen (the phone was
            // away from the code for a while). Restarting resets all recorded
            // progress, so ask first.
            const restart = confirm(gettext("This picklist is already in progress. Restart it from the beginning?"));
            lastPicklistScan.ts = Date.now();  // confirm() blocks JS; restart the cooldown once it closes
            if (!restart) {
                isProcessingScan = false;
                return;
            }
            skipConfirm = true;
        }

        const result = handlePicklist(scannedCode, currentPicklist, productData, skipConfirm);
        lastPicklistScan.ts = Date.now();  // the "start list?" dialog blocks JS too
        if (!result) {
            console.warn("Picklist processing failed, resetting scan flag");
            isProcessingScan = false;
            return;
        }
        currentPicklist = result.currentPicklist
        currentOrderID = result.orderID
        originalProductCounts = result.originalCounts;  // Add this line
        originalPicklistOrder = result.originalOrder || [...currentPicklist]; // Store original order
        // A new (or restarted) list starts with no declared shorts. On a
        // restart the server sends back what it kept, in already_short on the
        // claim response — applied by applyAlreadyShort once that lands.
        clearShortedLines();
        renderList();
        updatePicklistCodeDisplay(currentOrderID);
        persistActiveList();

        lastPickTs = Date.now();
        setTimeout(() => {
            console.log('scan picklist done done')
            isProcessingScan = false; // Reset the flag after the delay

        }, 1000);
        console.log('processing flag to false')
    } else {
        handleProductCode(scannedCode, currentPicklist, productData, getIsOrderImportant(), currentOrderID);
        setTimeout(() => {
            console.log('handle done')
            isProcessingScan = false; // Reset the flag after the delay
        }, 1000);
    }
});


// Function to check if a scanned code is a picklist
function isPicklist(code) {
    return code.includes("\t") || code.includes(",") || code.includes(";");
}

// Function to handle scanned product codes
export function handleProductCode(code, currentPicklist, productData, isOrderImportant, currentOrderID) {
    try {
        // The physical item may carry any of the product's barcodes (a rotated
        // EAN, or the primary code); the picklist stores primary codes. The
        // raw code is kept for health logging: it tells which physical label
        // generation was scanned, which the canonical code hides.
        const rawCode = String(code).trim();
        // Fridge-QR stickers and login QRs get caught by the camera; they are
        // not product barcodes and must not pollute pick-flow health.
        if (/^https?:\/\//i.test(rawCode)) {
            showNotification(gettext("That is not a product barcode."), true);
            return;
        }
        code = canonicalCode(productData, rawCode);
        const rawSuffix = rawCode !== code ? ` (scanned as ${rawCode})` : '';
        // Client-side list state, for diagnosing client/server mismatches
        // from the health page after the fact.
        const listState = ` [device list: ${currentPicklist.length} left]`;
        if (isOrderImportant) {
            const firstProductCode = currentPicklist[0];
            if (code === firstProductCode) {
                // Correct scan, remove the first product from the list
                currentPicklist.splice(0, 1);
                renderList(); // Update the table after removing the first product
                persistActiveList();
                onSuccessfulPick(rawCode)

                const product = productData.find(item => item.code === firstProductCode);  // Match code in productData
                const productLabel = product ? product.description : firstProductCode;
                showNotification(gettext("Scanned %(product)s").replace("%(product)s", productLabel));
                console.log('currentPicklist.length', currentPicklist.length)
                showPickFollowUpOverlay(firstProductCode, productLabel);

                maybeCompleteList();
            } else if (!reclaimShort(code, rawCode)) {
                // Incorrect scan, show error notification
                showNotification(gettext("Incorrect scan, please try again."), true);
                reportScanEvent('wrong_product', {
                    scannedCode: rawCode,
                    picklistCode: currentOrderID ? String(currentOrderID) : '',
                    reason: 'order_mismatch',
                    message: `expected ${firstProductCode}` + (rawSuffix ? `; resolves to ${code}` : '') + listState
                });
            }
        } else {
            const index = currentPicklist.indexOf(code);
            if (index !== -1) {
                // Valid scan, remove the product from the list
                currentPicklist.splice(index, 1);
                renderList();  // Update the table after a valid scan
                persistActiveList();
                onSuccessfulPick(rawCode);

                const product = productData.find(item => item.code === code);
                const productLabel = product ? product.description : code;
                showNotification(gettext("Scanned %(product)s").replace("%(product)s", productLabel));

                showPickFollowUpOverlay(code, productLabel);

                maybeCompleteList();
            } else if (!reclaimShort(code, rawCode)) {
                // Three different problems used to share one message. Telling
                // them apart matters on the floor: an over-scan of a finished
                // line needs no action, a wrong grab needs a different item,
                // and a truly unknown code needs the admin.
                //
                // Reclaiming a declared short is checked first (above): the
                // item is off the list precisely because the picker said it
                // was missing, so without that check finding it after all
                // would be logged as a wrong grab.
                const knownProduct = findProductByCode(productData, rawCode);
                const originalTotal = knownProduct ? (originalProductCounts[code] || 0) : 0;
                if (knownProduct && originalTotal > 0) {
                    showNotification(
                        gettext("%(product)s: all %(total)s already picked.")
                            .replace("%(product)s", knownProduct.description || code)
                            .replace("%(total)s", originalTotal),
                        true
                    );
                    // Stays unknown_product on purpose: the scanner re-fires
                    // while the phone hovers over a line that is already done,
                    // and counting those as wrong grabs would drown the
                    // lookalike-pair signal below in noise.
                    reportScanEvent('unknown_product', {
                        scannedCode: rawCode,
                        picklistCode: currentOrderID ? String(currentOrderID) : '',
                        reason: 'already_picked',
                        message: `already picked: all ${originalTotal} units of ${code} registered` + listState
                    });
                } else if (knownProduct) {
                    showNotification(
                        gettext("%(product)s is not in this order.")
                            .replace("%(product)s", knownProduct.description || code),
                        true
                    );
                    // THE wrong grab: a product this warehouse stocks, scanned
                    // against an order that does not contain it — the picker
                    // took the wrong item off the shelf. It was logged as
                    // unknown_product for years, which is why wrong_product has
                    // never once been recorded in production.
                    //
                    // The order's codes ride along so the pairs can be mined
                    // later ("whenever they grab X, the order wanted Y"), which
                    // is the whole point of telling this case apart. Capped at
                    // 30 distinct codes: the message column is not a transcript.
                    reportScanEvent('wrong_product', {
                        scannedCode: rawCode,
                        picklistCode: currentOrderID ? String(currentOrderID) : '',
                        reason: 'not_in_order',
                        message: `wrong grab: scanned ${code}; order lines: [${orderLineCodes(currentPicklist)}]` + listState
                    });
                } else {
                    showNotification(gettext("Product code not found in the list."), true);
                    reportScanEvent('unknown_product', {
                        scannedCode: rawCode,
                        picklistCode: currentOrderID ? String(currentOrderID) : '',
                        reason: 'unknown_code',
                        message: (rawSuffix ? `resolves to ${code}, which is not on the list` : 'code unknown to catalog') + listState
                    });
                }
            }
        }
    } catch (error) {
        console.error('Error in handleProductCode:', error);
        showNotification(gettext("An unexpected error occurred, please try again. If this issue persists, contact support"), true);
    }
}

// The order's distinct product codes, for the wrong-grab pair-mining payload.
// Capped so one scan of the wrong box on a 200-line order cannot write a
// kilobyte into the health log.
const MAX_PAIR_MINING_CODES = 30;

function orderLineCodes(list) {
    const seen = [];
    for (const raw of list) {
        const code = String(raw);
        if (seen.indexOf(code) === -1) {
            seen.push(code);
            if (seen.length >= MAX_PAIR_MINING_CODES) break;
        }
    }
    return seen.join(', ');
}


// ---------------------------------------------------------------------------
// Short picks (R1)
//
// A line the picker cannot fill is a fact worth recording: without it the row
// simply stays pending, the completion sweep turns it into 'lost', and nobody
// can tell "we were out of stock" from "the app never heard about the pick".
// ---------------------------------------------------------------------------

// Units of this product still to pick, i.e. the ceiling for a short.
export function remainingForProduct(code) {
    return currentPicklist.filter(c => c === String(code)).length;
}

export function productLabelFor(code) {
    const product = (productData || []).find(item => item.code === String(code));
    return product ? product.description : String(code);
}

// Declared shorts, newest state, for the completion summary.
export function shortSummary() {
    return Object.keys(shortedLines)
        .filter(code => shortedLines[code] && shortedLines[code].qty > 0)
        .map(code => ({
            code: code,
            qty: shortedLines[code].qty,
            reason: shortedLines[code].reason,
            label: productLabelFor(code),
        }));
}

// Scanner handover for the short overlays. Every overlay on this page follows
// the same contract (see #bulk-pick-overlay): pause on open, and on close
// resume AND release isProcessingScan — forgetting the flag leaves the page
// looking alive while silently ignoring every further scan.
export function pauseForOverlay() {
    pauseScanner();
}

export function resumeFromOverlay() {
    isProcessingScan = false;
    resumeScanner();
}

// The picker reports N units of a line as missing. Returns true when a
// blocking overlay has taken ownership of the scanner (the completion
// summary), so the caller knows not to resume it itself.
export function declareShort(code, quantity, reason, reasonText) {
    const stringCode = String(code);
    if (!currentOrderID) {
        // Same contract as onSuccessfulPick: unattributable work is refused
        // rather than queued into the void.
        console.error('declareShort without an active order', stringCode);
        showNotification(gettext("No active picklist — scan the list QR first."), true);
        return false;
    }
    const available = remainingForProduct(stringCode);
    if (available === 0) return false;

    let qty = parseInt(quantity, 10);
    if (isNaN(qty) || qty < 1) qty = 1;
    if (qty > available) qty = available;

    let removed = 0;
    for (let i = currentPicklist.length - 1; i >= 0 && removed < qty; i--) {
        if (currentPicklist[i] === stringCode) {
            currentPicklist.splice(i, 1);
            removed++;
        }
    }

    const existing = shortedLines[stringCode];
    shortedLines[stringCode] = {
        qty: (existing ? existing.qty : 0) + removed,
        // The latest reason wins for display; the server keeps one reason per
        // row, so an earlier batch's reason is not rewritten there.
        reason: reason,
    };

    renderList();
    persistActiveList();

    // Queued like every other business-critical POST: a short declared in the
    // cold aisle with no reception must not be the one thing that is lost.
    // Same endpoint as a pick, with successful:false — the kind is what makes
    // the outbox treat it as unsheddable work.
    queuedThisSession(enqueue('short', '/orderpiqr/product-pick', {
        orderID: currentOrderID,
        productCode: stringCode,
        successful: false,
        shortReason: reason,
        quantity: removed,
        reasonText: reasonText || '',
        scannedAt: new Date().toISOString()
    }));

    showNotification(interpolate(ngettext(
        'Reported %(count)s item missing: %(product)s',
        'Reported %(count)s items missing: %(product)s',
        removed), {count: removed, product: productLabelFor(stringCode)}, true));

    return maybeCompleteList();
}

// The picker declared this line short and then found the item after all. The
// server reclaims the short row on the next successful pick of the product
// (flipping it back to picked and clearing the reason), so the client only
// has to undo its own bookkeeping and send the ordinary pick.
function reclaimShort(code, rawCode) {
    const entry = shortedLines[String(code)];
    if (!entry || !(entry.qty > 0)) return false;

    entry.qty -= 1;
    if (entry.qty <= 0) delete shortedLines[String(code)];

    renderList();
    onSuccessfulPick(rawCode);      // persists the list itself
    showNotification(gettext("Found after all: %(product)s")
        .replace("%(product)s", productLabelFor(code)));
    return true;
}

// The single place a list is finished. There were four of these (two scan
// paths, the bulk overlay and the manual override), and a list finished with
// declared shorts has to stop and ask — "nothing left to pick" no longer
// means "everything was picked".
//
// Returns true when the blocking summary overlay now owns the scanner.
function maybeCompleteList() {
    if (currentPicklist.length > 0) return false;
    if (!currentOrderID) return false;

    const shorts = shortSummary();
    if (shorts.length === 0) {
        notifyPicklistCompleted(currentOrderID);
        return false;
    }

    const summaryOverlay = document.getElementById('short-complete-overlay');
    if (summaryOverlay) {
        // shortPick.js owns the overlay; reached by event rather than import
        // so this module stays the leaf of that pair. dispatchEvent is
        // synchronous, so the overlay is either open by the time this returns
        // or nothing handled the request.
        pauseScanner();
        document.dispatchEvent(new CustomEvent('short-complete-request', {detail: {shorts: shorts}}));
        if (!summaryOverlay.classList.contains('hidden')) return true;
        // Nobody opened it (shortPick.js failed to load, a listener threw).
        // Stranding the picker behind a paused scanner on a finished list is
        // far worse than finishing it unasked, so fall through.
        resumeScanner();
    }

    notifyPicklistCompleted(currentOrderID);
    clearShortedLines();
    renderList();
    return false;
}

// "Finish list" on the summary overlay.
export function finishList() {
    if (!currentOrderID) return;
    notifyPicklistCompleted(currentOrderID);
    clearShortedLines();
    renderList();
}

// Exported for manualOverride.js, whose own 0-length check used to call
// notifyPicklistCompleted directly (with an undefined csrfToken argument).
export function completeIfFinished() {
    return maybeCompleteList();
}

// Stop-the-line: the server no longer has this device's picklist (taken
// over by another picker, unlocked by an admin, ...). Every further scan of
// this dead list would be lost the same way, so picking is blocked until the
// picker acknowledges — one lost pick instead of a whole list.
let picklistLostShown = false;

function showPicklistLostOverlay() {
    if (picklistLostShown) return;
    picklistLostShown = true;
    const lostOverlay = document.getElementById('picklist-lost-overlay');
    if (!lostOverlay) {
        picklistLostShown = false;
        showNotification(gettext("This list is no longer assigned to you. Scan the list QR again."), true);
        return;
    }
    pauseScanner();
    hideBulkPickOverlay();
    hideConfirmationOverlay();
    hideShortOverlays();
    lostOverlay.classList.remove('hidden');
}

// Reached by id rather than through shortPick.js so that the stop-the-line
// path keeps working even if that module failed to load — the one overlay
// that must always win.
function hideShortOverlays() {
    ['short-pick-overlay', 'short-complete-overlay'].forEach(function (id) {
        const node = document.getElementById(id);
        if (node) node.classList.add('hidden');
    });
}

// Guarded against double-binding: if this module ever loads twice (as it
// did when hashed and unhashed copies coexisted), a second handler would
// clear the OTHER instance's live list when the overlay is dismissed.
const picklistLostOkBtn = document.getElementById('picklist-lost-ok-btn');
if (picklistLostOkBtn && !picklistLostOkBtn.dataset.bound) {
    picklistLostOkBtn.dataset.bound = '1';
    picklistLostOkBtn.addEventListener('click', function () {
        document.getElementById('picklist-lost-overlay').classList.add('hidden');
        picklistLostShown = false;
        // The list is dead server-side; clear it locally so the picker starts
        // over by scanning a list QR instead of picking into the void.
        currentPicklist.length = 0;
        currentOrderID = null;
        Object.keys(originalProductCounts).forEach(key => delete originalProductCounts[key]);
        clearShortedLines();
        clearActiveList();
        renderList();
        const codeDisplay = document.getElementById('picklist-code-display');
        if (codeDisplay) codeDisplay.style.display = 'none';
        isProcessingScan = false;
        resumeScanner();
    });
}

// camera_page.js
export function onSuccessfulPick(scannedCode, {manualOverride = false} = {}) {
    try {
        if (!currentOrderID) {
            // Without an active order the pick cannot be attributed; POSTing
            // it anyway earns a 404 whose stop-the-line overlay then clears a
            // list that never existed here. Refuse loudly instead.
            console.error('onSuccessfulPick without an active order', scannedCode);
            showNotification(gettext("No active picklist — scan the list QR first."), true);
            reportScanEvent('sync_error', {
                scannedCode,
                message: 'pick attempted with no active order on this device'
            });
            return;
        }
        // Persisted here, not only at the scan-path splice sites: the manual
        // override (manualOverride.js) splices the list itself and reaches
        // this function as its only stop in this module — without this line a
        // reload would restore an overridden item back onto the list.
        persistActiveList();

        const now = Date.now();
        const timeTakenMs = lastPickTs ? (now - lastPickTs) : null;
        lastPickTs = now;

        notifyProductPicked({
            orderID: currentOrderID,
            productCode: scannedCode,
            timeTakenMs,
            manualOverride
        });
    } catch (e) {
        console.error('onSuccessfulPick error', e);
    }
}


// Queued rather than sent (pickOutbox.js): a pick made during a reception drop
// used to be lost outright while the list advanced on screen. The outbox owns
// the retry and the idempotency key; the rejection path lives in the
// outbox-op-rejected listener further down, because the response can now
// arrive long after this call — even in a later page session.
function notifyProductPicked({orderID, productCode, timeTakenMs, manualOverride = false}) {
    return queuedThisSession(enqueue('pick', '/orderpiqr/product-pick', {
        orderID,                 // your PickList/Order identifier
        productCode,             // e.g. SKU/code string
        successful: true,        // this call is only for successful scans
        timeTakenMs,             // duration since previous successful pick
        manualOverride,          // triple-tap override; logged server-side
        scannedAt: new Date().toISOString()
    }));
}


// Op ids this page session queued. An op that only reaches the server after a
// reload belongs to a session that is over: it must still be recorded and
// reported, but it must not congratulate — or alarm — a picker who has since
// moved on to another list. Ids are removed again as the ops settle.
const sessionOpIds = new Set();

function queuedThisSession(opId) {
    if (opId) sessionOpIds.add(opId);
    return opId;
}

export function notifyPicklistCompleted(orderID) {
    if (!orderID) {
        // Same contract as onSuccessfulPick: no order, nothing to complete.
        console.error('notifyPicklistCompleted without an order id');
        return;
    }
    // The list is finished — nothing left to offer a reload, and restoring it
    // later would hand the picker a phantom list for an order the server (and
    // every call site here) just marked done.
    clearActiveList();
    queuedThisSession(enqueue('complete', '/orderpiqr/complete-picklist', {orderID}));
}


// ---------------------------------------------------------------------------
// Outbox results
//
// The four pick-flow POSTs are queued, not awaited (pickOutbox.js), so their
// responses arrive here instead of at the call site — seconds, or a reload,
// later. Every handler therefore re-checks that the response still concerns
// the list currently on screen before it touches it. A pure network failure
// produces no event at all: the outbox retries, and the sync badge is what
// makes the wait visible.
// ---------------------------------------------------------------------------

function sameOrder(orderID) {
    return currentOrderID !== null && orderID !== null && orderID !== undefined
        && String(orderID).trim() === String(currentOrderID).trim();
}

// Restart of a list with recorded work: the server kept those picks, so drop
// them from the fresh list instead of making the picker redo (and double-
// record) them.
function applyAlreadyPicked(alreadyPicked) {
    let kept = 0;
    for (const [code, n] of Object.entries(alreadyPicked)) {
        for (let i = 0; i < n; i++) {
            const idx = currentPicklist.indexOf(code);
            if (idx === -1) break;
            currentPicklist.splice(idx, 1);
            kept++;
        }
    }
    if (kept > 0) {
        renderList();
        persistActiveList();
        showNotification(
            interpolate(ngettext(
                'Kept %(count)s already-picked item from the previous attempt.',
                'Kept %(count)s already-picked items from the previous attempt.',
                kept), {count: kept}, true)
        );
    }
}

// Same contract as applyAlreadyPicked, for the lines the previous attempt
// declared missing: the server kept those rows as outcome='short', so they
// come off the fresh list and reappear as short rows instead of asking the
// picker to walk back to a shelf they already found empty.
//
// The response carries counts, not reasons (the restart answer is a map of
// code -> units), so a restored short shows the generic reason until the
// picker re-declares it. Deliberate: inventing a reason here would put words
// in the picker's mouth on a health metric.
function applyAlreadyShort(alreadyShort) {
    let kept = 0;
    for (const [code, n] of Object.entries(alreadyShort)) {
        let taken = 0;
        for (let i = 0; i < n; i++) {
            const idx = currentPicklist.indexOf(code);
            if (idx === -1) break;
            currentPicklist.splice(idx, 1);
            taken++;
        }
        if (taken === 0) continue;
        const existing = shortedLines[code];
        shortedLines[code] = {
            qty: (existing ? existing.qty : 0) + taken,
            reason: existing ? existing.reason : 'other',
        };
        kept += taken;
    }
    if (kept > 0) {
        renderList();
        persistActiveList();
        showNotification(
            interpolate(ngettext(
                'Kept %(count)s item reported missing in the previous attempt.',
                'Kept %(count)s items reported missing in the previous attempt.',
                kept), {count: kept}, true)
        );
    }
}

// The server refused the list (unknown product, order picked elsewhere, ...).
// Clear it locally: picking a list that was never registered would silently
// record nothing. The order id goes too, so the next pick is refused with
// "scan the list QR first" instead of queueing into the void.
function claimRejected(orderID, data) {
    console.error('Picklist rejected by server:', data);
    if (sameOrder(orderID)) {
        currentPicklist.length = 0;
        currentOrderID = null;
        Object.keys(originalProductCounts).forEach(key => delete originalProductCounts[key]);
        clearShortedLines();
        clearActiveList();
        renderList();
        const codeDisplay = document.getElementById('picklist-code-display');
        if (codeDisplay) codeDisplay.style.display = 'none';
        showNotification((data && data.message) || gettext("Error sending picklist."), true);
    }
    reportScanEvent('sync_error', {
        picklistCode: orderID ? String(orderID) : '',
        message: (data && data.message) || 'scan-picklist rejected by server'
    });
}

// A rejected pick is a pick the server did NOT record — the one case the
// outbox cannot fix by trying again, so it is always reported. The picker is
// only told about picks they can still do something about: a stale op from a
// previous session would otherwise greet them with a stack of red toasts on
// page open, about a list they finished hours ago.
function pickRejected(op, status, data, thisSession) {
    const payload = op.payload || {};
    const endpoint = op.kind === 'bulk' ? 'bulk-product-pick' : 'product-pick';
    reportScanEvent('sync_error', {
        scannedCode: payload.productCode || '',
        picklistCode: payload.orderID ? String(payload.orderID) : '',
        message: (data && data.message) || `${endpoint} rejected (HTTP ${status})`
    });
    if (thisSession || sameOrder(payload.orderID)) {
        let message;
        if (op.kind === 'bulk') {
            message = gettext("Could not update bulk product pick.");
        } else if (op.kind === 'short') {
            // Not a pick that failed: a declaration the server refused, so the
            // line is back to looking like ordinary un-picked work.
            message = gettext("Could not report missing items.");
        } else {
            message = gettext("Could not update product pick.");
        }
        showNotification(message, true);
    }
    if (data && data.error_code === 'picklist_not_found' && sameOrder(payload.orderID)) {
        // Stop the line only for the list in the picker's hands; a 404 for an
        // older list would otherwise clear the current one.
        showPicklistLostOverlay();
    }
}

function completeRejected(op, status, data, thisSession) {
    console.error('Complete-picklist rejected:', data);
    const orderID = (op.payload || {}).orderID;
    if (thisSession || sameOrder(orderID)) {
        showNotification(gettext("Error completing picklist."), true);
    }
    reportScanEvent('sync_error', {
        picklistCode: orderID ? String(orderID) : '',
        message: (data && data.message) || `complete-picklist rejected (HTTP ${status})`
    });
    if (data && data.error_code === 'picklist_not_found' && sameOrder(orderID)) {
        showPicklistLostOverlay();
    }
}

// Claims whose already_picked has been applied. Trimming is not idempotent —
// applying the same response twice would remove items nobody picked — and an
// op can be answered twice if the queue could not record that it was sent.
const trimmedClaims = new Set();

document.addEventListener('outbox-op-done', function (event) {
    const detail = event.detail || {};
    const op = detail.op;
    if (!op) return;
    const data = detail.data;            // null when the body was not JSON
    const payload = op.payload || {};
    const thisSession = sessionOpIds.delete(op.id);

    // A response carrying duplicate:true is a retry of an op that had already
    // landed. It is deliberately invisible: the list on screen already reflects
    // the pick, and the server changed nothing.
    if (op.kind === 'claim') {
        if (data && data.status && data.status !== 'ok') {
            // A 200 that says "error" is still a refusal — that is how the
            // view reports a list it will not claim.
            claimRejected(payload.orderID, data);
            return;
        }
        if (data && (data.already_picked || data.already_short)
            && sameOrder(payload.orderID) && !trimmedClaims.has(op.id)) {
            trimmedClaims.add(op.id);
            if (data.already_picked) applyAlreadyPicked(data.already_picked);
            // After the picked trim, not before: both consume units of the
            // same codes off the fresh list, and picked work outranks a short.
            if (data.already_short) applyAlreadyShort(data.already_short);
        }
        return;
    }

    if (op.kind === 'complete') {
        if (data && data.status && data.status !== 'ok') {
            completeRejected(op, 200, data, thisSession);
            return;
        }
        // Only celebrate a completion the picker is still waiting for.
        if (thisSession) {
            console.log('Picklist completed successfully:', data);
            showNotification(gettext("Picklist completed!"), false);
        }
    }
});

document.addEventListener('outbox-op-rejected', function (event) {
    const detail = event.detail || {};
    const op = detail.op;
    if (!op) return;
    const data = detail.data;
    const status = detail.status;
    const thisSession = sessionOpIds.delete(op.id);

    if (op.kind === 'claim') {
        claimRejected((op.payload || {}).orderID, data);
    } else if (op.kind === 'complete') {
        completeRejected(op, status, data, thisSession);
    } else {
        pickRejected(op, status, data, thisSession);
    }
});


// Fallback if the window.productData is not available
if (Object.keys(productData).length === 0) {
    console.error('No product data found!');
    showNotification(gettext("No product data was found, cannot update list"), true);

}


// Overlay elements
const overlay = document.getElementById('scan-confirmation-overlay');
const overlayProductName = document.getElementById('overlay-product-name');
const overlayPickedProgress = document.getElementById('overlay-picked-progress');
const overlayProgressFill = document.getElementById('overlay-progress-fill');
const overlayRemainingCount = document.getElementById('overlay-remaining-count');
const overlaySecondaryCount = document.getElementById('overlay-secondary-count');

// Fill the "Picked X of Y" line, progress bar and the prominent/secondary
// number lines of an overlay. The prominent number is a customer/picker
// preference (bulk_pick_prominent_number): "remaining" emphasizes how many
// MORE to take, "total" emphasizes the full line quantity — both numbers are
// always shown so neither reading is off by one.
function renderPickProgress(progressEl, fillEl, prominentEl, secondaryEl, remainingCount, totalCount) {
    const pickedCount = Math.max(totalCount - remainingCount, 0);
    progressEl.textContent = gettext("Picked %(picked)s of %(total)s")
        .replace("%(picked)s", pickedCount)
        .replace("%(total)s", totalCount);
    fillEl.style.width = totalCount > 0 ? `${(pickedCount / totalCount) * 100}%` : '0%';

    if (window.SETTINGS?.bulk_pick_prominent_number === 'total') {
        prominentEl.innerHTML = gettext("<strong>%(total)s</strong> in total")
            .replace("%(total)s", totalCount);
        secondaryEl.textContent = gettext("Take %(remaining)s more")
            .replace("%(remaining)s", remainingCount);
    } else {
        prominentEl.innerHTML = gettext("Take <strong>%(remaining)s</strong> more")
            .replace("%(remaining)s", remainingCount);
        secondaryEl.textContent = gettext("%(total)s in total")
            .replace("%(total)s", totalCount);
    }
}

// After one instance of a product is registered (scan or triple-tap manual
// override), show the follow-up overlay when more of the same product remain:
// the bulk overlay when enabled and more than one is left, the tap-to-continue
// confirmation otherwise. The overlay's dismiss handlers resume the scanner.
export function showPickFollowUpOverlay(productCode, productLabel, {manualOverride = false} = {}) {
    const remainingCount = currentPicklist.filter(c => c === productCode).length;
    if (remainingCount === 0) return;
    const totalCount = originalProductCounts[productCode] || remainingCount + 1;
    pauseScanner();
    if (window.SETTINGS?.bulk_pick_enabled === true && remainingCount > 1) {
        showBulkPickOverlay(productLabel, productCode, remainingCount, totalCount, manualOverride);
    } else {
        showConfirmationOverlay(productLabel, remainingCount, totalCount);
    }
}

// Event listener for full overlay tap
overlay.addEventListener('click', function () {
    hideConfirmationOverlay();
    isProcessingScan = false;
    resumeScanner();
});

function showConfirmationOverlay(productDescription, remainingCount, totalCount) {
    overlayProductName.textContent = productDescription;
    renderPickProgress(overlayPickedProgress, overlayProgressFill, overlayRemainingCount, overlaySecondaryCount, remainingCount, totalCount);
    overlay.classList.remove('hidden');
}

function hideConfirmationOverlay() {
    overlay.classList.add('hidden');
}

// Bulk pick overlay elements
const bulkOverlay = document.getElementById('bulk-pick-overlay');
const bulkOverlayProductName = document.getElementById('bulk-overlay-product-name');
const bulkOverlayPickedProgress = document.getElementById('bulk-overlay-picked-progress');
const bulkOverlayProgressFill = document.getElementById('bulk-overlay-progress-fill');
const bulkOverlayRemainingCount = document.getElementById('bulk-overlay-remaining-count');
const bulkOverlaySecondaryCount = document.getElementById('bulk-overlay-secondary-count');
const bulkConfirmAllBtn = document.getElementById('bulk-confirm-all-btn');
const bulkContinueBtn = document.getElementById('bulk-continue-btn');
const bulkConfirmQtyBtn = document.getElementById('bulk-confirm-qty-btn');
const bulkPickOneBtn = document.getElementById('bulk-pick-one-btn');
const bulkPickQuantityInput = document.getElementById('bulk-pick-quantity');
const bulkPickMinusBtn = document.getElementById('bulk-pick-minus');
const bulkPickPlusBtn = document.getElementById('bulk-pick-plus');

let bulkPickContext = null;

function showBulkPickOverlay(productDescription, productCode, remainingCount, totalCount, manualOverride = false) {
    // manualOverride rides along so that confirming the rest of an unscannable
    // line is counted as an override too, not just the triple-tap that opened
    // this overlay.
    bulkPickContext = { productCode, remainingCount, totalCount, productDescription, manualOverride };

    bulkOverlayProductName.textContent = productDescription;
    renderPickProgress(bulkOverlayPickedProgress, bulkOverlayProgressFill, bulkOverlayRemainingCount, bulkOverlaySecondaryCount, remainingCount, totalCount);

    // "All 15 taken" confirms the picker's physical total for the line
    // (registers the remaining picks); fall back to a generic label when the
    // total is unknown.
    bulkConfirmAllBtn.textContent = totalCount > 0
        ? gettext("All %(total)s taken").replace("%(total)s", totalCount)
        : gettext("Pick All");

    bulkPickQuantityInput.value = remainingCount;
    bulkPickQuantityInput.max = remainingCount;
    bulkPickQuantityInput.min = 1;

    bulkOverlay.classList.remove('hidden');
}

function hideBulkPickOverlay() {
    bulkOverlay.classList.add('hidden');
    bulkPickContext = null;
}

function executeBulkPick(productCode, quantity, returnToScanner) {
    const ctx = bulkPickContext;
    if (!ctx) return;
    if (!currentOrderID) {
        // Same contract as onSuccessfulPick: unattributable picks are refused.
        console.error('executeBulkPick without an active order', productCode);
        showNotification(gettext("No active picklist — scan the list QR first."), true);
        hideBulkPickOverlay();
        isProcessingScan = false;
        resumeScanner();
        return;
    }

    const now = Date.now();
    const timeTakenMs = lastPickTs ? (now - lastPickTs) : null;
    lastPickTs = now;

    // Remove quantity instances from currentPicklist
    let removed = 0;
    for (let i = currentPicklist.length - 1; i >= 0 && removed < quantity; i--) {
        if (currentPicklist[i] === productCode) {
            currentPicklist.splice(i, 1);
            removed++;
        }
    }

    renderList();
    persistActiveList();

    // Send to server
    notifyBulkProductPicked({
        orderID: currentOrderID, productCode, quantity, timeTakenMs,
        manualOverride: ctx.manualOverride === true
    });

    // Show notification
    const product = productData.find(function (item) { return item.code === productCode; });
    const desc = product ? product.description : productCode;
    showNotification(
        gettext("Picked %(quantity)s of %(product)s")
            .replace("%(quantity)s", quantity)
            .replace("%(product)s", desc)
    );

    // Check remaining
    const newRemaining = currentPicklist.filter(function (c) { return c === productCode; }).length;

    hideBulkPickOverlay();

    if (currentPicklist.length === 0) {
        // maybeCompleteList() returns true when it opened the blocking shorts
        // summary, which then owns the scanner — resuming here would put the
        // camera back behind a modal the picker has not answered yet.
        if (!maybeCompleteList()) {
            isProcessingScan = false;
            resumeScanner();
        }
    } else if (returnToScanner) {
        isProcessingScan = false;
        resumeScanner();
    } else if (newRemaining > 1) {
        const totalCount = originalProductCounts[productCode] || 0;
        // ctx was captured before hideBulkPickOverlay() cleared it — keep the
        // override flag across a chained bulk confirmation.
        showBulkPickOverlay(desc, productCode, newRemaining, totalCount, ctx.manualOverride === true);
    } else if (newRemaining === 1) {
        const totalCount = originalProductCounts[productCode] || 0;
        showConfirmationOverlay(desc, newRemaining, totalCount);
    } else {
        isProcessingScan = false;
        resumeScanner();
    }
}

// Same contract as notifyProductPicked: queued, idempotent, and answered by
// the outbox listeners rather than here.
function notifyBulkProductPicked({orderID, productCode, quantity, timeTakenMs, manualOverride = false}) {
    return queuedThisSession(enqueue('bulk', '/orderpiqr/bulk-product-pick', {
        orderID,
        productCode,
        quantity,
        timeTakenMs,
        manualOverride,          // bulk confirm of an unscannable line
        scannedAt: new Date().toISOString()
    }));
}

// Bulk overlay event listeners
bulkConfirmAllBtn.addEventListener('click', function () {
    if (!bulkPickContext) return;
    executeBulkPick(bulkPickContext.productCode, bulkPickContext.remainingCount, true);
});

bulkPickOneBtn.addEventListener('click', function () {
    if (!bulkPickContext) return;
    executeBulkPick(bulkPickContext.productCode, 1, true);
});

// Close without registering anything — for pickers who scan each item
// individually. ("+1 more" registers an extra pick, so it must not be the
// only way out of this overlay.)
bulkContinueBtn.addEventListener('click', function () {
    hideBulkPickOverlay();
    isProcessingScan = false;
    resumeScanner();
});

bulkConfirmQtyBtn.addEventListener('click', function () {
    if (!bulkPickContext) return;
    var qty = parseInt(bulkPickQuantityInput.value, 10);
    if (isNaN(qty) || qty < 1 || qty > bulkPickContext.remainingCount) {
        showNotification(gettext("Please enter a valid quantity"), true);
        return;
    }
    executeBulkPick(bulkPickContext.productCode, qty, true);
});

bulkPickMinusBtn.addEventListener('click', function () {
    var current = parseInt(bulkPickQuantityInput.value, 10) || 1;
    if (current > 1) {
        bulkPickQuantityInput.value = current - 1;
    }
});

bulkPickPlusBtn.addEventListener('click', function () {
    if (!bulkPickContext) return;
    var current = parseInt(bulkPickQuantityInput.value, 10) || 0;
    if (current < bulkPickContext.remainingCount) {
        bulkPickQuantityInput.value = current + 1;
    }
});

bulkPickQuantityInput.addEventListener('blur', function () {
    if (!bulkPickContext) return;
    var val = parseInt(this.value, 10);
    if (isNaN(val) || val < 1) val = 1;
    if (val > bulkPickContext.remainingCount) val = bulkPickContext.remainingCount;
    this.value = val;
});

function updatePicklistCodeDisplay(orderID) {
    const display = document.getElementById('picklist-code-display');
    const valueSpan = document.getElementById('picklist-code-value');
    if (display && valueSpan && orderID) {
        valueSpan.textContent = orderID;
        display.style.display = 'block';
    }
}

// Re-sort the current picklist with a new sorting mode
export function resortCurrentPicklist(sortingMode) {
    if (currentPicklist.length === 0) {
        return; // Nothing to sort
    }
    const sorted = sortPicklist(currentPicklist, productData, sortingMode, originalPicklistOrder);
    // Update the array in place to maintain reference
    currentPicklist.length = 0;
    currentPicklist.push(...sorted);
    renderList();
    // The order of the saved copy matters as much as its contents: a picker
    // who sorted by location and then reloads must not get the pre-sort order
    // back mid-aisle.
    persistActiveList();
}

// Listen for sort change events from the dropdown
document.addEventListener('picklist-sort-change', function (e) {
    resortCurrentPicklist(e.detail.sortingMode);
});

// Listen for list view changes (individual vs grouped) from the dropdown.
// Display-only: updateScannedList reads the mode from window.SETTINGS.
document.addEventListener('picklist-view-change', function () {
    renderList();
});

// Check for claimed order from queue on page load
function loadClaimedOrder() {
    console.log('[Queue] Checking for claimed order...');

    // First, check for server-provided data (from URL parameter)
    let data = null;
    const serverDataEl = document.getElementById('claimed-order-data');
    if (serverDataEl) {
        try {
            data = JSON.parse(serverDataEl.textContent);
            console.log('[Queue] Found server-provided order data:', data);
        } catch (e) {
            console.error('[Queue] Error parsing server data:', e);
        }
    }

    // Fallback to sessionStorage
    if (!data) {
        const claimedOrderData = sessionStorage.getItem('claimed_order');
        console.log('[Queue] sessionStorage claimed_order:', claimedOrderData);
        if (claimedOrderData) {
            try {
                data = JSON.parse(claimedOrderData);
                console.log('[Queue] Parsed sessionStorage data:', data);
                // Clear the sessionStorage immediately to prevent re-loading on refresh
                sessionStorage.removeItem('claimed_order');
            } catch (e) {
                console.error('[Queue] Error parsing sessionStorage:', e);
            }
        }
    }

    if (data && data.order_code && data.picklist && data.picklist.length > 0) {
        console.log('[Queue] Loading order:', data.order_code, 'with', data.picklist.length, 'items');
        console.log('[Queue] Product data available:', productData ? productData.length : 0, 'products');

        if (!productData || productData.length === 0) {
            console.error('[Queue] Cannot load order: productData is empty or undefined');
            showNotification(gettext("Cannot load order: product data not available"), true);
            return;
        }

        // Initialize the picklist from the claimed order
        currentPicklist.length = 0;
        const originalCounts = {};

        for (const code of data.picklist) {
            currentPicklist.push(code);
            originalCounts[code] = (originalCounts[code] || 0) + 1;
        }
        console.log('[Queue] currentPicklist populated:', currentPicklist);

        currentOrderID = data.order_code;
        originalPicklistOrder = [...currentPicklist];
        // A freshly claimed order carries no shorts from whatever this device
        // was holding before.
        clearShortedLines();

        // Apply sorting preference
        const sortingPreference = window.SETTINGS?.picklist_sorting ?? "original";
        console.log('[Queue] Sorting preference:', sortingPreference);
        const sorted = sortPicklist(currentPicklist, productData, sortingPreference, originalPicklistOrder);
        currentPicklist.length = 0;
        currentPicklist.push(...sorted);
        console.log('[Queue] After sorting:', currentPicklist);

        // Update the display
        console.log('[Queue] Calling updateScannedList...');
        renderList();
        updatePicklistCodeDisplay(currentOrderID);

        // Store original counts for overlay display
        // Update the module-level variable
        Object.keys(originalProductCounts).forEach(key => delete originalProductCounts[key]);
        Object.assign(originalProductCounts, originalCounts);

        // Set the last pick timestamp
        lastPickTs = Date.now();
        persistActiveList();

        showNotification(gettext("Order loaded from queue"), false);
        console.log('[Queue] Order loaded successfully');
    } else {
        console.log('[Queue] No claimed order found or invalid data');
        // Neither the server nor sessionStorage handed this page a list — the
        // only remaining candidate is whatever this device itself saved
        // before a reload. Both sources above take precedence because they
        // mean a NEW list was just assigned; restoring an old one over that
        // would silently discard it.
        restoreActiveList();
    }
}

// Wait for DOM to be fully ready before loading claimed order
// ES modules are deferred but may still run before all elements are rendered
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadClaimedOrder);
} else {
    // DOM is already ready
    loadClaimedOrder();
}

// Self-update: reload for a new deploy, but only while no list is in
// progress — currentPicklist lives in page memory, a reload would lose it.
// Open shorts count as in progress: an empty list with declared shorts is the
// picker sitting in front of the completion summary.
initAppUpdater(() => currentPicklist.length === 0
    && Object.keys(shortedLines).length === 0
    && !isProcessingScan);