// camera_page.js
import {initializeScanner, pauseScanner, resumeScanner} from './qrScanner.js';
import {showNotification} from './notifications.js';
import {toggleOrderImportance, updateOrderImportanceButton, getIsOrderImportant} from './orderImportance.js';
import {handlePicklist, sortPicklist} from './picklistHandler.js';
import {updateScannedList} from './domUpdater.js';
import {getDeviceFingerprint} from './fingerprint.js';  // Import the fingerprint function

const gettext = window.gettext;
// Access the productData object injected into the HTML
export let productData;
// top-level (near other state)
let lastPickTs = null;

if (navigator.onLine) {
    // ✅ Online: trust server-rendered data
    const el = document.getElementById("product-data");
    if (el && el.textContent) {
        try {
            productData = JSON.parse(el.textContent);
            window.productData = productData;
            localStorage.setItem('product_data', JSON.stringify(productData));
        } catch (e) {
            console.error("Failed to parse product data from DOM", e);
            showNotification(gettext("Could not load product data from server"), true);
        }
    } else {
        console.warn("No server-rendered product data found");
        showNotification(gettext("No product data found on page"), true);
    }
} else {
    // 🚨 Offline: fall back to cache
    const cached = localStorage.getItem('product_data');
    if (cached) {
        try {
            productData = JSON.parse(cached);
            window.productData = productData;
            showNotification(gettext("Offline mode: using cached product data"), true);
        } catch (e) {
            console.error("Corrupted cached product data", e);
            showNotification(gettext("Cached product data is not usable"), true);
        }
    } else {
        showNotification(gettext("No product data available while offline"), true);
    }
}


// export let productData = window.productData || {};  // Fallback in case the data is not injected
export let currentPicklist = []; // Array to store the current picklist
export let currentOrderID = null;
let originalPicklistOrder = []; // Store the original order for re-sorting

// Toggle button for order importance
const toggleButton = document.getElementById('toggle-order-btn');

// Event listener for toggling order importance
toggleButton.addEventListener('click', function () {
    toggleOrderImportance();
    updateOrderImportanceButton(toggleButton);
});

let isProcessingScan = false;  // Flag to ensure only one scan is processed at a time
let originalProductCounts = {}
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
        if (!result) {
            console.warn("Picklist processing failed, resetting scan flag");
            isProcessingScan = false;
            return;
        }
        currentPicklist = result.currentPicklist
        currentOrderID = result.orderID
        originalProductCounts = result.originalCounts;  // Add this line
        originalPicklistOrder = result.originalOrder || [...currentPicklist]; // Store original order
        updatePicklistCodeDisplay(currentOrderID);

        lastPickTs = Date.now();
        setTimeout(() => {
            console.log('scan picklist done done')
            isProcessingScan = false; // Reset the flag after the delay

        }, 1000);
        console.log('processing flag to false')
    } else {
        handleProductCode(scannedCode, currentPicklist, productData, getIsOrderImportant(), currentOrderID);
        setTimeout(() => {
            console.log('handle done')
            isProcessingScan = false; // Reset the flag after the delay
        }, 1000);
    }
});


// Function to check if a scanned code is a picklist
function isPicklist(code) {
    return code.includes("\t") || code.includes(",") || code.includes(";");
}

// Function to handle scanned product codes
export function handleProductCode(code, currentPicklist, productData, isOrderImportant, currentOrderID) {
    try {
        code = String(code).trim();
        if (isOrderImportant) {
            const firstProductCode = currentPicklist[0];
            if (code === firstProductCode) {
                // Correct scan, remove the first product from the list
                currentPicklist.splice(0, 1);
                updateScannedList(currentPicklist, productData); // Update the table after removing the first product
                onSuccessfulPick(firstProductCode)

                const product = productData.find(item => item.code === firstProductCode);  // Match code in productData
                showNotification(gettext("Scanned %(product)s").replace("%(product)s", product.description));
                console.log('currentPicklist.length', currentPicklist.length)
// Check if same product still exists in remaining picklist
                const remainingCount = currentPicklist.filter(c => c === firstProductCode).length;
                if (remainingCount > 0) {
                    const totalCount = originalProductCounts[firstProductCode] || remainingCount + 1;
                    pauseScanner();
                    showConfirmationOverlay(product.description, remainingCount, totalCount);
                }


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
                onSuccessfulPick(code);

                const product = productData.find(item => item.code === code);
                showNotification(gettext("Scanned %(product)s").replace("%(product)s", product.description));

// Check if same product still exists in remaining picklist
                const remainingCount = currentPicklist.filter(c => c === code).length;
                if (remainingCount > 0) {
                    const totalCount = originalProductCounts[code] || remainingCount + 1;
                    pauseScanner();
                    showConfirmationOverlay(product.description, remainingCount, totalCount);
                }

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

// camera_page.js
export function onSuccessfulPick(scannedCode) {
    try {
        const now = Date.now();
        const timeTakenMs = lastPickTs ? (now - lastPickTs) : null;
        lastPickTs = now;

        notifyProductPicked({
            orderID: currentOrderID,
            productCode: scannedCode,
            timeTakenMs,
            csrfToken
        }).catch(err => {
            console.error('product-pick update failed', err);
            showNotification(gettext("Could not update product pick."), true);
        });
    } catch (e) {
        console.error('onSuccessfulPick error', e);
    }
}


function notifyProductPicked({orderID, productCode, timeTakenMs, csrfToken}) {
    return getDeviceFingerprint()
        .then(deviceFingerprint => {
            return fetch('/orderpiqr/product-pick', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    orderID,                 // your PickList/Order identifier
                    productCode,             // e.g. SKU/code string
                    successful: true,        // this call is only for successful scans
                    timeTakenMs,             // duration since previous successful pick
                    deviceFingerprint,
                    scannedAt: new Date().toISOString()
                })
            });
        });
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


// Overlay elements
const overlay = document.getElementById('scan-confirmation-overlay');
const overlayProductName = document.getElementById('overlay-product-name');
const overlayRemainingCount = document.getElementById('overlay-remaining-count');

// Event listener for full overlay tap
overlay.addEventListener('click', function () {
    hideConfirmationOverlay();
    isProcessingScan = false;
    resumeScanner();
});

function showConfirmationOverlay(productDescription, remainingCount, totalCount) {
    overlayProductName.textContent = productDescription;
    overlayRemainingCount.innerHTML = gettext("<strong>%(remaining)s</strong> of <strong>%(total)s</strong> remaining")
        .replace("%(remaining)s", remainingCount)
        .replace("%(total)s", totalCount);
    overlay.classList.remove('hidden');
}

function hideConfirmationOverlay() {
    overlay.classList.add('hidden');
}

function updatePicklistCodeDisplay(orderID) {
    const display = document.getElementById('picklist-code-display');
    const valueSpan = document.getElementById('picklist-code-value');
    if (display && valueSpan && orderID) {
        valueSpan.textContent = orderID;
        display.style.display = 'block';
    }
}

// Re-sort the current picklist with a new sorting mode
export function resortCurrentPicklist(sortingMode) {
    if (currentPicklist.length === 0) {
        return; // Nothing to sort
    }
    const sorted = sortPicklist(currentPicklist, productData, sortingMode, originalPicklistOrder);
    // Update the array in place to maintain reference
    currentPicklist.length = 0;
    currentPicklist.push(...sorted);
    updateScannedList(currentPicklist, productData);
}

// Listen for sort change events from the dropdown
document.addEventListener('picklist-sort-change', function (e) {
    resortCurrentPicklist(e.detail.sortingMode);
});