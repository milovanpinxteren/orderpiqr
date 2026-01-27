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
    console.log('[domUpdater] listBody element:', listBody);

    listBody.innerHTML = '';  // Clear previous list
    scannedCodes.forEach((code, index) => {
        const stringCode = String(code);

        const product = productData.find(item => item.code === stringCode);  // Match code in productData
        console.log(`[domUpdater] Code ${stringCode}: found product:`, product ? 'yes' : 'no');
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
    console.log('[domUpdater] Table updated, rows added:', scannedCodes.length);
}
