// picklistHandler.js

export function parsePicklistRow(row) {
    const separators = ['\t', ',', ';'];  // Define possible separators
    for (const separator of separators) {
        const parts = row.split(separator);
        if (parts.length === 2) {
            const quantity = parseInt(parts[0].trim(), 10);
            const productCode = parts[1].trim();
            if (!isNaN(quantity)) {
                return [quantity, productCode];
            }
        }
    }
    return null;  // If row can't be parsed, return null
}

export function handlePicklist(code, currentPicklist) {
    const confirmStart = confirm("New list found, start this list?");
    if (confirmStart) {
        currentPicklist = [];
        const rows = code.split("\n");  // Assuming the picklist is a multi-line string
        rows.forEach(row => {
            const parts = parsePicklistRow(row);
            if (parts) {
                const [quantity, productCode] = parts;
                for (let i = 0; i < quantity; i++) {
                    currentPicklist.push(productCode);  // Add product code multiple times based on quantity
                }
            }
        });
    }
}
