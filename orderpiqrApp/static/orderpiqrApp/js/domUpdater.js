// domUpdater.js

export function updateScannedList(scannedCodes, productData) {
    const listBody = document.getElementById('scanned-list').getElementsByTagName('tbody')[0];
    listBody.innerHTML = '';  // Clear previous list
    console.log('updating scanned list', scannedCodes, productData)
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
