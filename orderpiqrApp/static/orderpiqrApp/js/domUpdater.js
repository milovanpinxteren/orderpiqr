// domUpdater.js

export function updateScannedList(scannedCodes, productData) {
    const listBody = document.getElementById('scanned-list').getElementsByTagName('tbody')[0];
    listBody.innerHTML = '';  // Clear previous list
    scannedCodes.forEach((code, index) => {
        const product = productData[code];
        if (product) {
            const row = document.createElement('tr');
            row.classList.add(index % 2 === 0 ? 'even' : 'odd');
            row.innerHTML = `
                    <td>${code}</td>
                    <td>${product.picknaam}</td>
                    <td>${product.pickvolgorde}</td>
                `;
            listBody.appendChild(row);
        }
    });
}
