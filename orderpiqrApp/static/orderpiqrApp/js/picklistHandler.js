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
                        .then(response => {
                            console.log("first reponse", response)
                        })
                        .then(data => {
                            console.log('Picklist sent successfully:', data);
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

            return {currentPicklist, orderID};  // Return the updated picklist
        }

        // Reset flag if the user cancels the picklist
        isProcessingPicklist = false;
        return {currentPicklist, orderID};  // Return the unchanged picklist if the user cancels

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
