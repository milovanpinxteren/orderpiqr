// picklistHandler.js
import {updateScannedList} from './domUpdater.js';
import {getDeviceFingerprint} from './fingerprint.js';  // Import the fingerprint function
import {showNotification} from './notifications.js';

const gettext = window.gettext;  // Pull it from the global scope


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


let isProcessingPicklist = false;  // Flag to track if a picklist is being processed

export function handlePicklist(code, currentPicklist, productData) {
    try {
        if (isProcessingPicklist) {
            console.log("Picklist is already being processed, ignoring duplicate scan.");
            return currentPicklist;  // Do nothing if a picklist is already being processed
        }

        const confirmStart = confirm(gettext("New list found, start this list?"));

        if (confirmStart) {
            isProcessingPicklist = true;  // Set flag to true to indicate processing has started
            currentPicklist = []; // Reset the picklist
            const originalCounts = {};
            let originalOrder = [];


            const rows = code.split("\n");  // Split the picklist into rows (assuming multi-line)
            // Skip the first row (orderID) and process the remaining rows
            const validRows = rows.slice(1).filter(row => row.trim() !== "");  // Remove empty rows
            const fieldOrder = determineFieldOrder(validRows[0], productData);
            if (!fieldOrder) {
                showNotification(gettext("Could not determine product/quantity structure in picklist."), true);
                isProcessingPicklist = false;
                return;
            }
            for (let i = 0; i < validRows.length; i++) {
                const row = validRows[i];
                const parts = parsePicklistRow(row);  // Parse each row
                if (parts && parts.length === 2) {
                    const productCode = String(parts[fieldOrder.productIndex]).trim();
                    const quantity = parseInt(parts[fieldOrder.quantityIndex]);
                    // Add the product code multiple times based on quantity
                    for (let j = 0; j < quantity; j++) {
                        currentPicklist.push(productCode);
                    }
                } else {
                    showNotification(gettext("Product row is invalid"), true);
                    console.log("Skipping invalid row:", row);  // Debug invalid row
                }
            }
            if (!productData || Object.keys(productData).length === 0) {
                showNotification(gettext("Product data is empty, cannot update list."), true);
            } else {
                // Store the original order before sorting
                originalOrder = [...currentPicklist];

                // Calculate original counts per product code (before sorting)
                for (const code of currentPicklist) {
                    originalCounts[code] = (originalCounts[code] || 0) + 1;
                }

                const sortingPreference = window.SETTINGS?.picklist_sorting ?? "original";
                currentPicklist = sortPicklist(currentPicklist, productData, sortingPreference, originalOrder);

                isProcessingPicklist = false;
                updateScannedList(currentPicklist, productData);
                showNotification(gettext("Picklist added"));
            }
            // If you need to save the orderID, you can handle it here separately later
            const orderID = rows[0];  // First row is the orderID
            getDeviceFingerprint()
                .then(deviceFingerprint => {
                    // Send the request with picklist and device fingerprint
                    fetch('/orderpiqr/scan-picklist', {  // Update the URL to your endpoint
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken  // Include CSRF token in the headers
                        },
                        body: JSON.stringify({
                            orderID: orderID,
                            picklist: currentPicklist,
                            deviceFingerprint: deviceFingerprint,  // Add fingerprint to the request
                        })
                    })
                        .then(response => response.json())
                        .then(data => {
                            // Picklist sent successfully
                        })
                        .catch(error => {
                            console.error('Error sending picklist:', error);
                            showNotification(gettext("Error sending picklist."), true);
                        });
                })
                .catch(error => {
                    console.error('Error getting device fingerprint:', error);
                    showNotification(gettext("Error getting device fingerprint."), true);
                });

            // Reset flag after processing the picklist
            isProcessingPicklist = false;

            return {currentPicklist, orderID, originalCounts, originalOrder};  // Return the updated picklist
        }

        // Reset flag if the user cancels the picklist
        isProcessingPicklist = false;
        return {currentPicklist, orderID, originalCounts: {}, originalOrder: []};  // Return the unchanged picklist if the user cancels

    } catch (err) {
        console.error("Error in handlePicklist:", err);
        showNotification(gettext("Unexpected error while parsing picklist."), true);
    } finally {
        isProcessingPicklist = false;  // ✅ Always reset
    }
}


function determineFieldOrder(exampleRow, productData) {
    const parts = parsePicklistRow(exampleRow);
    if (!parts || parts.length !== 2) {
        showNotification(gettext("Invalid QR code structure. Please check the format"), true);
        return null;
    }

    const [first, second] = parts.map(p => String(p).trim());
    const firstIsProduct = productData.find(item => item.code === first);
    const secondIsProduct = productData.find(item => item.code === second);
    if (firstIsProduct && !secondIsProduct) {
        return {productIndex: 0, quantityIndex: 1};
    } else if (secondIsProduct && !firstIsProduct) {
        return {productIndex: 1, quantityIndex: 0};
    } else if (firstIsProduct && secondIsProduct) {
        showNotification(gettext("Ambiguous picklist: both fields look like product codes. Please check your format."), true);
        return null;  // Ambiguous or invalid
    } else {
        showNotification(gettext("Neither field in the picklist row matches a known product code."), true);
        return null;  // Ambiguous or invalid
    }
}

// Natural sort comparator - handles mixed strings and numbers correctly
// e.g., "A2" < "A10", "12" < "100"
function naturalCompare(a, b) {
    const aStr = String(a);
    const bStr = String(b);

    // Split into chunks of digits and non-digits, filtering out empty strings
    const aParts = aStr.split(/(\d+)/).filter(part => part !== "");
    const bParts = bStr.split(/(\d+)/).filter(part => part !== "");

    const maxLen = Math.max(aParts.length, bParts.length);

    for (let i = 0; i < maxLen; i++) {
        // If one array is shorter, it comes first
        if (i >= aParts.length) return -1;
        if (i >= bParts.length) return 1;

        const aPart = aParts[i];
        const bPart = bParts[i];

        // Check if both parts are purely numeric
        const aIsNum = /^\d+$/.test(aPart);
        const bIsNum = /^\d+$/.test(bPart);

        if (aIsNum && bIsNum) {
            // Compare as numbers
            const aNum = parseInt(aPart, 10);
            const bNum = parseInt(bPart, 10);
            if (aNum !== bNum) return aNum - bNum;
        } else {
            // Compare as strings (case-insensitive)
            const cmp = aPart.localeCompare(bPart, undefined, {sensitivity: 'base'});
            if (cmp !== 0) return cmp;
        }
    }
    return 0;
}

export function sortPicklist(productCodes, productData, sortingMode, originalOrder = null) {
    const dataMap = {};
    for (const product of productData) {
        dataMap[product.code] = product;
    }
    // Use provided originalOrder, or fall back to current order
    const orderReference = originalOrder || productCodes;

    const enriched = productCodes.map((code, idx) => ({
        code,
        location: dataMap[code]?.location ?? "",
        description: dataMap[code]?.description ?? "",
        originalIndex: originalOrder ? originalOrder.indexOf(code) : idx,
    }));

    switch (sortingMode) {
        case "location":
            enriched.sort((a, b) => naturalCompare(a.location, b.location));
            break;
        case "description":
            enriched.sort((a, b) => naturalCompare(a.description, b.description));
            break;
        case "original":
        default:
            enriched.sort((a, b) => a.originalIndex - b.originalIndex);
            break;
    }

    return enriched.map(item => item.code);
}
