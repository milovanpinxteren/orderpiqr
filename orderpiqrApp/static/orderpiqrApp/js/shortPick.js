// shortPick.js
//
// The "I cannot fill this line" flow: the flag button on every picklist row
// opens a sheet asking how many are missing and why, and a second overlay
// blocks the completion of a list that still has declared shorts on it.
//
// Two rules this module exists to respect:
//
//  1. The click handler is DELEGATED on document. The table body is redrawn
//     with innerHTML on every pick (domUpdater.js), so a listener bound to a
//     button disappears the moment the picker scans anything.
//  2. Nothing it touches carries data-product-code. manualOverride.js reads
//     event.target.dataset.productCode straight off the click target, so a
//     flag button carrying the code would turn three impatient taps into
//     three override picks of the line being reported as missing. The handler
//     also stops propagation, which keeps the triple-tap counter from seeing
//     these clicks at all.
//
// camera_page.js owns the list state and the scanner; this module only calls
// into it. The dependency runs one way on purpose — the completion overlay is
// requested through a `short-complete-request` event rather than an import
// back, so the two modules cannot form a cycle.
import {
    declareShort, finishList, pauseForOverlay, productLabelFor,
    remainingForProduct, resumeFromOverlay,
} from './camera_page.js';
import {SHORT_REASON_SLUGS, shortReasonLabel} from './shortReasons.js';

const gettext = window.gettext;
const ngettext = window.ngettext;
const interpolate = window.interpolate;

// {code, label, max} while the sheet is open, null otherwise.
let shortContext = null;

function el(id) {
    return document.getElementById(id);
}

// ---------------------------------------------------------------------------
// The short-pick sheet
// ---------------------------------------------------------------------------

// Built from shortReasons.js rather than written out in the template: the row
// labels come from the same function, so a reason can never read one way on
// the button and another way on the row it produces.
function buildReasonGrid() {
    const grid = el('short-reason-grid');
    if (!grid || grid.dataset.built === '1') return;
    grid.dataset.built = '1';
    SHORT_REASON_SLUGS.forEach(function (slug) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'overlay-btn short-reason-btn';
        button.dataset.shortReason = slug;
        button.textContent = shortReasonLabel(slug);
        grid.appendChild(button);
    });
}

function openShortPickOverlay(code) {
    const overlay = el('short-pick-overlay');
    if (!overlay) return;
    const max = remainingForProduct(code);
    if (max <= 0) return;

    buildReasonGrid();
    shortContext = {code: String(code), max: max, label: productLabelFor(code)};

    const nameEl = el('short-overlay-product-name');
    if (nameEl) nameEl.textContent = shortContext.label;
    const infoEl = el('short-overlay-line-info');
    if (infoEl) {
        infoEl.textContent = interpolate(ngettext(
            '%(count)s unit still to pick',
            '%(count)s units still to pick',
            max), {count: max}, true);
    }

    const input = el('short-pick-quantity');
    if (input) {
        // Defaulting to the whole remaining line is the common case: a picker
        // at an empty shelf is missing all of it, so the usual path is two
        // taps (flag, reason) with no stepper work at all.
        input.min = 1;
        input.max = max;
        input.value = max;
    }
    const text = el('short-reason-text');
    if (text) text.value = '';
    const otherSection = el('short-other-section');
    if (otherSection) otherSection.classList.add('hidden');

    pauseForOverlay();
    overlay.classList.remove('hidden');
}

function hideShortPickOverlay() {
    const overlay = el('short-pick-overlay');
    if (overlay) overlay.classList.add('hidden');
    shortContext = null;
}

function currentQuantity() {
    const input = el('short-pick-quantity');
    const max = shortContext ? shortContext.max : 1;
    let qty = input ? parseInt(input.value, 10) : 1;
    if (isNaN(qty) || qty < 1) qty = 1;
    if (qty > max) qty = max;
    return qty;
}

function confirmShort(reason, reasonText) {
    const ctx = shortContext;
    if (!ctx) return;
    const qty = currentQuantity();
    hideShortPickOverlay();
    // declareShort returns true when the completion summary took over the
    // scanner; resuming on top of that would put the camera back behind a
    // modal the picker has not answered.
    if (!declareShort(ctx.code, qty, reason, reasonText || '')) {
        resumeFromOverlay();
    }
}

// Delegated, and the only place [data-short-code] is read.
document.addEventListener('click', function (event) {
    const target = event.target;
    if (!target || typeof target.closest !== 'function') return;
    const trigger = target.closest('[data-short-code]');
    if (!trigger) return;
    event.preventDefault();
    event.stopPropagation();
    openShortPickOverlay(trigger.dataset.shortCode);
});

const reasonGrid = el('short-reason-grid');
if (reasonGrid) {
    buildReasonGrid();
    reasonGrid.addEventListener('click', function (event) {
        const target = event.target;
        if (!target || typeof target.closest !== 'function') return;
        const button = target.closest('[data-short-reason]');
        if (!button) return;
        const slug = button.dataset.shortReason;
        if (slug === 'other') {
            // The only reason that needs a second step: everything else
            // confirms on the first tap, which is the point of the big grid.
            const section = el('short-other-section');
            if (section) section.classList.remove('hidden');
            const text = el('short-reason-text');
            if (text) text.focus();
            return;
        }
        confirmShort(slug, '');
    });
}

const otherConfirmBtn = el('short-other-confirm-btn');
if (otherConfirmBtn) {
    otherConfirmBtn.addEventListener('click', function () {
        const text = el('short-reason-text');
        confirmShort('other', text ? text.value.trim() : '');
    });
}

const shortCancelBtn = el('short-cancel-btn');
if (shortCancelBtn) {
    shortCancelBtn.addEventListener('click', function () {
        hideShortPickOverlay();
        resumeFromOverlay();
    });
}

const shortMinusBtn = el('short-qty-minus');
if (shortMinusBtn) {
    shortMinusBtn.addEventListener('click', function () {
        const input = el('short-pick-quantity');
        if (!input) return;
        const current = parseInt(input.value, 10) || 1;
        if (current > 1) input.value = current - 1;
    });
}

const shortPlusBtn = el('short-qty-plus');
if (shortPlusBtn) {
    shortPlusBtn.addEventListener('click', function () {
        const input = el('short-pick-quantity');
        if (!input || !shortContext) return;
        const current = parseInt(input.value, 10) || 0;
        if (current < shortContext.max) input.value = current + 1;
    });
}

const shortQtyInput = el('short-pick-quantity');
if (shortQtyInput) {
    shortQtyInput.addEventListener('blur', function () {
        this.value = currentQuantity();
    });
}

// ---------------------------------------------------------------------------
// The completion summary
//
// "Nothing left to pick" stopped meaning "everything was picked" the moment
// shorts existed, so a list with declared shorts is finished deliberately,
// not as a side effect of the last scan. camera_page.js has already paused
// the scanner when this fires.
// ---------------------------------------------------------------------------
document.addEventListener('short-complete-request', function (event) {
    const overlay = el('short-complete-overlay');
    const shorts = (event.detail && event.detail.shorts) || [];
    // Leaving it hidden is a defined outcome, not a failure: camera_page.js
    // checks whether this handler actually opened the overlay and finishes
    // the list itself if it did not.
    if (!overlay) return;
    const list = el('short-complete-summary');
    if (list) {
        list.innerHTML = '';
        shorts.forEach(function (entry) {
            const item = document.createElement('li');
            item.className = 'short-complete-item';
            item.textContent = interpolate(
                gettext("%(count)s× %(product)s — %(reason)s"),
                {
                    count: entry.qty,
                    product: entry.label,
                    reason: shortReasonLabel(entry.reason),
                }, true);
            list.appendChild(item);
        });
    }
    overlay.classList.remove('hidden');
});

const shortFinishBtn = el('short-finish-btn');
if (shortFinishBtn) {
    shortFinishBtn.addEventListener('click', function () {
        const overlay = el('short-complete-overlay');
        if (overlay) overlay.classList.add('hidden');
        finishList();
        resumeFromOverlay();
    });
}

const shortKeepPickingBtn = el('short-keep-picking-btn');
if (shortKeepPickingBtn) {
    shortKeepPickingBtn.addEventListener('click', function () {
        // Back to the camera with the shorts still open: scanning one of them
        // reclaims it (camera_page.js), which is how a picker corrects a line
        // they reported too early.
        const overlay = el('short-complete-overlay');
        if (overlay) overlay.classList.add('hidden');
        resumeFromOverlay();
    });
}
