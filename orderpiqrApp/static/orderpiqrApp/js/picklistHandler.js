// picklistHandler.js
import {updateScannedList} from './domUpdater.js';
import {getDeviceFingerprint} from './fingerprint.js';  // Import the fingerprint function
import {showNotification} from './notifications.js';



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
    if (isProcessingPicklist) {
        console.log("Picklist is already being processed, ignoring duplicate scan.");
        return currentPicklist;  // Do nothing if a picklist is already being processed
    }

    const confirmStart = confirm("New list found, start this list?");
    console.log("Confirm start:", confirmStart);  // Debug this

    if (confirmStart) {
        isProcessingPicklist = true;  // Set flag to true to indicate processing has started
        currentPicklist = []; // Reset the picklist
        const rows = code.split("\n");  // Split the picklist into rows (assuming multi-line)
        // Skip the first row (orderID) and process the remaining rows
        const validRows = rows.slice(1).filter(row => row.trim() !== "");  // Remove empty rows
        for (let i = 0; i < validRows.length; i++) {
            const row = validRows[i];
            const parts = parsePicklistRow(row);  // Parse each row
            if (parts) {
                const [quantity, productCode] = parts;
                // Add the product code multiple times based on quantity
                for (let i = 0; i < quantity; i++) {
                    currentPicklist.push(productCode);
                }
            } else {
                console.log("Skipping invalid row:", row);  // Debug invalid row
            }
        }
        if (!productData || Object.keys(productData).length === 0) {
            console.log("Product data is empty, cannot update list.");
        } else {
            updateScannedList(currentPicklist, productData);
            showNotification(`Picklist added`);
        }

        // If you need to save the orderID, you can handle it here separately later
        const orderID = rows[0];  // First row is the orderID
        // console.log('Order ID:', orderID);  // Debug this
        getDeviceFingerprint()
            .then(deviceFingerprint => {

                console.log('csrfToken', csrfToken)
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
                        console.log('Picklist sent successfully:', data);
                    })
                    .catch(error => {
                        console.error('Error sending picklist:', error);
                    });
            })
            .catch(error => {
                console.error('Error getting device fingerprint:', error);
            });

        // Reset flag after processing the picklist
        isProcessingPicklist = false;

        return currentPicklist;  // Return the updated picklist
    }

    // Reset flag if the user cancels the picklist
    isProcessingPicklist = false;
    return currentPicklist;  // Return the unchanged picklist if the user cancels
}
