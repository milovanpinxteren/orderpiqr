// camera_page.js
import {initializeScanner} from './qrScanner.js';
import {showNotification} from './notifications.js';
import {toggleOrderImportance, updateOrderImportanceButton} from './orderImportance.js';
import {handlePicklist} from './picklistHandler.js';
import {updateScannedList} from './domUpdater.js';
import {getDeviceFingerprint} from './fingerprint.js';  // Import the fingerprint function

const gettext = window.gettext;
// Access the productData object injected into the HTML
export let productData = window.productData || {};  // Fallback in case the data is not injected
export let currentPicklist = []; // Array to store the current picklist
export let isOrderImportant = true
let currentOrderID = null;

// Toggle button for order importance
const toggleButton = document.getElementById('toggle-order-btn');

// Event listener for toggling order importance
toggleButton.addEventListener('click', function () {
    isOrderImportant = toggleOrderImportance(); // Toggle the order importance state
    updateOrderImportanceButton(toggleButton); // Update button appearance
});

let isProcessingScan = false;  // Flag to ensure only one scan is processed at a time

// Initialize the QR code scanner
initializeScanner((scannedCode) => {
    if (isProcessingScan) {
        console.log("Scan already in process, ignoring duplicate scan.");
        return;  // Exit if a scan is already being processed
    }

    // Set the flag to indicate that scanning is in progress
    isProcessingScan = true;
    console.log("scanned code", scannedCode);
    if (isPicklist(scannedCode)) {
        const result = handlePicklist(scannedCode, currentPicklist, productData);
        currentPicklist = result.currentPicklist
        currentOrderID = result.orderID
        setTimeout(() => {
            console.log('scan picklist done done')
            isProcessingScan = false; // Reset the flag after the delay

        }, 1000);
        console.log('processing flag to false')

        // isProcessingScan = false;

    } else {
        handleProductCode(scannedCode, currentPicklist, productData, isOrderImportant, currentOrderID);
        setTimeout(() => {
            console.log('handle done')
            isProcessingScan = false; // Reset the flag after the delay
        }, 1000);
    }

    // Reset the flag after processing the scan
});


// Function to check if a scanned code is a picklist
function isPicklist(code) {
    return code.includes("\t") || code.includes(",") || code.includes(";");
}

// Function to handle scanned product codes
export function handleProductCode(code, currentPicklist, productData, isOrderImportant, currentOrderID) {
    try {
        if (isOrderImportant) {
            const firstProductCode = currentPicklist[0];
            if (code === firstProductCode) {
                // Correct scan, remove the first product from the list
                currentPicklist.splice(0, 1);
                updateScannedList(currentPicklist, productData); // Update the table after removing the first product
                const product = productData.find(item => item.code === firstProductCode);  // Match code in productData
                showNotification(gettext("Scanned %(product)s").replace("%(product)s", product.description));
                console.log('currentPicklist.length', currentPicklist.length)
                if (currentPicklist.length === 0) {
                    notifyPicklistCompleted(currentOrderID, csrfToken);  // <- you'll need to make csrfToken available
                }
            } else {
                // Incorrect scan, show error notification
                showNotification(gettext("Incorrect scan, please try again."), true);
            }
        } else {
            const index = currentPicklist.indexOf(code);
            if (index !== -1) {
                // Valid scan, remove the product from the list
                currentPicklist.splice(index, 1);
                updateScannedList(currentPicklist, productData);  // Update the table after a valid scan
                showNotification(gettext("Scanned %(product)s").replace("%(product)s", productData[code].picknaam));
                if (currentPicklist.length === 0) {
                    notifyPicklistCompleted(currentOrderID, csrfToken);  // <- you'll need to make csrfToken available
                }
            } else {
                showNotification(gettext("Product code not found in the list."), true);
            }
        }
    } catch (error) {
        console.error('Error in handleProductCode:', error);
        showNotification(gettext("An unexpected error occurred, please try again. If this issue persists, contact support"), true);
    }
}

export function notifyPicklistCompleted(orderID, csrfToken) {
    getDeviceFingerprint()
        .then(deviceFingerprint => {
            fetch('/orderpiqr/complete-picklist', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    orderID,
                    deviceFingerprint  // ✅ include fingerprint
                })
            })
            .then(response => response.json())
            .then(data => {
                console.log('Picklist completed successfully:', data);
                showNotification(gettext("Picklist completed!"), false);
            })
            .catch(error => {
                console.error('Error completing picklist:', error);
                showNotification(gettext("Error completing picklist."), true);
            });
        })
        .catch(error => {
            console.error('Error getting device fingerprint:', error);
            showNotification(gettext("Error getting device fingerprint."), true);
        });
}



// Fallback if the window.productData is not available
if (Object.keys(productData).length === 0) {
    console.error('No product data found!');
    showNotification(gettext("No product data was found, cannot update list"), true);

}
