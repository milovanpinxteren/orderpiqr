// domUpdater.js

export function updateScannedList(scannedCodes, productData) {
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
    console.log('[domUpdater] Table updated, mode:', grouped ? 'grouped' : 'individual');
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
            listBody.appendChild(row);
        } else {
            const row = document.createElement('tr');
            row.classList.add(index % 2 === 0 ? 'even' : 'odd');
            row.innerHTML = `
                    <td data-product-code="${code}">${code}</td>
                    <td></td>
                    <td></td>
                `;
            listBody.appendChild(row);
        }
    });
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
        listBody.appendChild(row);
    });
}
