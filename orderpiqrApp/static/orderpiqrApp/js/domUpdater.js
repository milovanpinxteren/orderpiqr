// domUpdater.js
import {shortReasonLabel} from './shortReasons.js';

const gettext = window.gettext;
const interpolate = window.interpolate;

// Whether the trailing "report missing" column exists at all. Strict true, so
// a missing settings key leaves the column (and the whole short-pick flow)
// out, the same way picklist search is gated.
function shortPickEnabled() {
    return window.SETTINGS?.short_pick_enabled === true;
}

export function updateScannedList(scannedCodes, productData, shortedLines) {
    console.log('[domUpdater] updateScannedList called');
    console.log('[domUpdater] scannedCodes:', scannedCodes);
    console.log('[domUpdater] productData length:', productData ? productData.length : 'null/undefined');

    const table = document.getElementById('scanned-list');
    if (!table) {
        console.error('[domUpdater] #scanned-list table not found!');
        return;
    }
    const listBody = table.getElementsByTagName('tbody')[0];
    if (!listBody) {
        console.error('[domUpdater] tbody not found in #scanned-list!');
        return;
    }

    const grouped = window.SETTINGS?.grouped_picklist_view === true;
    table.classList.toggle('grouped-view', grouped);

    listBody.innerHTML = '';  // Clear previous list
    if (grouped) {
        renderGroupedRows(listBody, scannedCodes, productData);
    } else {
        renderIndividualRows(listBody, scannedCodes, productData);
    }
    // Appended after the work that is still open: lines the picker has already
    // declared missing are a record, not a task.
    renderShortRows(listBody, shortedLines, productData);
    console.log('[domUpdater] Table updated, mode:', grouped ? 'grouped' : 'individual');
}

// The trailing per-row action: tapping it opens the short-pick overlay
// (shortPick.js, which listens for [data-short-code] on document).
//
// NOTHING in this subtree may carry data-product-code. manualOverride.js reads
// event.target.dataset.productCode straight off the click target, so a flag
// button that carried the code would turn three quick taps — exactly what an
// impatient picker does — into three override picks of a line they are trying
// to report as missing.
function appendActionCell(row, code) {
    if (!shortPickEnabled()) return;
    const cell = document.createElement('td');
    cell.className = 'cell-action';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'row-short-btn';
    button.dataset.shortCode = code;
    button.setAttribute('aria-label', gettext("Report missing"));
    button.textContent = '⚑';
    cell.appendChild(button);
    row.appendChild(cell);
}

function renderIndividualRows(listBody, scannedCodes, productData) {
    scannedCodes.forEach((code, index) => {
        const stringCode = String(code);

        const product = productData.find(item => item.code === stringCode);  // Match code in productData
        if (product) {
            const row = document.createElement('tr');
            row.classList.add(index % 2 === 0 ? 'even' : 'odd');
            row.innerHTML = `
                    <td data-product-code="${code}">${code}</td>
                    <td>${product.description}</td>
                    <td>${product.location}</td>
                `;
            appendActionCell(row, stringCode);
            listBody.appendChild(row);
        } else {
            const row = document.createElement('tr');
            row.classList.add(index % 2 === 0 ? 'even' : 'odd');
            row.innerHTML = `
                    <td data-product-code="${code}">${code}</td>
                    <td></td>
                    <td></td>
                `;
            appendActionCell(row, stringCode);
            listBody.appendChild(row);
        }
    });
}

// Lines the picker reported missing, rendered amber/muted at the bottom of the
// table so the list reads as "what is left" followed by "what will not come".
//
// Same rule as the flag button: no data-product-code anywhere in these rows. A
// triple-tap on a line that was just declared short must not quietly register
// a pick for it — the reclaim path is a real scan, which the server turns back
// into a picked row.
function renderShortRows(listBody, shortedLines, productData) {
    if (!shortedLines) return;
    const columns = shortPickEnabled() ? 4 : 3;
    // Continue the zebra striping of whatever was just rendered above —
    // grouped view emits one row per product, individual one per unit.
    let index = listBody.children.length;
    for (const code of Object.keys(shortedLines)) {
        const entry = shortedLines[code];
        if (!entry || !(entry.qty > 0)) continue;
        const product = (productData || []).find(item => item.code === code);

        const row = document.createElement('tr');
        row.classList.add('short-row', index % 2 === 0 ? 'even' : 'odd');
        index++;

        const qtyCell = document.createElement('td');
        qtyCell.className = 'short-qty';
        qtyCell.textContent = `${entry.qty}×`;

        const infoCell = document.createElement('td');
        infoCell.className = 'short-info';
        infoCell.colSpan = columns - 1;

        const nameLine = document.createElement('div');
        nameLine.className = 'short-name';
        nameLine.textContent = product ? product.description : code;

        const reasonLine = document.createElement('div');
        reasonLine.className = 'short-reason';
        reasonLine.textContent = interpolate(
            gettext("Missing — %(reason)s"),
            {reason: shortReasonLabel(entry.reason)}, true);

        infoCell.appendChild(nameLine);
        infoCell.appendChild(reasonLine);
        row.appendChild(qtyCell);
        row.appendChild(infoCell);
        listBody.appendChild(row);
    }
}

// Fill the location cell so line breaks fall after separators (',' or ';'):
// "Magazijn 2, Gang 14" renders as "Magazijn 2," on one line and "Gang 14"
// on the next. Display-only — the location text itself is not altered.
// Short segments are kept whole with nowrap; unusually long ones (and
// locations without separators) wrap normally so they can never overflow
// the capped column.
function renderLocation(cell, location, productCode) {
    const parts = String(location).split(/([,;])/);  // keep separators as tokens
    const segments = [];
    for (let i = 0; i < parts.length; i += 2) {
        const segment = (parts[i] + (parts[i + 1] || '')).trim();
        if (segment) segments.push(segment);
    }
    segments.forEach((segment, index) => {
        if (index > 0) {
            cell.appendChild(document.createElement('br'));
        }
        const span = document.createElement('span');
        span.className = 'grouped-location-part';
        if (segment.length <= 18) {
            span.classList.add('nowrap');
        }
        span.dataset.productCode = productCode;
        span.textContent = segment;
        cell.appendChild(span);
    });
}

// One row per product with a remaining-quantity badge. Groups keep the order
// of their first occurrence in the (already sorted) picklist — order matters
// between products, not within the same product.
function renderGroupedRows(listBody, scannedCodes, productData) {
    const groups = [];
    const groupsByCode = new Map();
    for (const rawCode of scannedCodes) {
        const code = String(rawCode);
        let group = groupsByCode.get(code);
        if (!group) {
            group = {code, count: 0};
            groupsByCode.set(code, group);
            groups.push(group);
        }
        group.count++;
    }

    groups.forEach((group, index) => {
        const product = productData.find(item => item.code === group.code);
        const row = document.createElement('tr');
        row.classList.add('grouped-row', index % 2 === 0 ? 'even' : 'odd');
        // data-product-code on the cells keeps triple-tap manual override working
        row.dataset.productCode = group.code;

        const qtyCell = document.createElement('td');
        qtyCell.className = 'grouped-qty';
        qtyCell.dataset.productCode = group.code;
        qtyCell.textContent = `${group.count}×`;

        const locationCell = document.createElement('td');
        locationCell.className = 'grouped-location';
        locationCell.dataset.productCode = group.code;
        renderLocation(locationCell, product?.location ?? '', group.code);

        const infoCell = document.createElement('td');
        infoCell.className = 'grouped-info';
        infoCell.dataset.productCode = group.code;

        const nameLine = document.createElement('div');
        nameLine.className = 'grouped-name';
        nameLine.dataset.productCode = group.code;
        nameLine.textContent = product?.description ?? '';

        const codeLine = document.createElement('div');
        codeLine.className = 'grouped-code';
        codeLine.dataset.productCode = group.code;
        codeLine.textContent = group.code;

        infoCell.appendChild(nameLine);
        infoCell.appendChild(codeLine);

        row.appendChild(qtyCell);
        row.appendChild(locationCell);
        row.appendChild(infoCell);
        appendActionCell(row, group.code);
        listBody.appendChild(row);
    });
}
