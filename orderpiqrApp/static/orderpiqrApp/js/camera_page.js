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
                    if (window.SETTINGS?.bulk_pick_enabled === true && remainingCount > 1) {
                        showBulkPickOverlay(product.description, firstProductCode, remainingCount, totalCount);
                    } else {
                        showConfirmationOverlay(product.description, remainingCount, totalCount);
                    }
                }


                if (currentPicklist.length === 0) {
                    notifyPicklistCompleted(currentOrderID, csrfToken);
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
                    if (window.SETTINGS?.bulk_pick_enabled === true && remainingCount > 1) {
                        showBulkPickOverlay(product.description, code, remainingCount, totalCount);
                    } else {
                        showConfirmationOverlay(product.description, remainingCount, totalCount);
                    }
                }

                if (currentPicklist.length === 0) {
                    notifyPicklistCompleted(currentOrderID, csrfToken);
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

// Bulk pick overlay elements
const bulkOverlay = document.getElementById('bulk-pick-overlay');
const bulkOverlayProductName = document.getElementById('bulk-overlay-product-name');
const bulkOverlayRemainingCount = document.getElementById('bulk-overlay-remaining-count');
const bulkConfirmAllBtn = document.getElementById('bulk-confirm-all-btn');
const bulkConfirmQtyBtn = document.getElementById('bulk-confirm-qty-btn');
const bulkPickOneBtn = document.getElementById('bulk-pick-one-btn');
const bulkPickQuantityInput = document.getElementById('bulk-pick-quantity');
const bulkPickMinusBtn = document.getElementById('bulk-pick-minus');
const bulkPickPlusBtn = document.getElementById('bulk-pick-plus');

let bulkPickContext = null;

function showBulkPickOverlay(productDescription, productCode, remainingCount, totalCount) {
    bulkPickContext = { productCode, remainingCount, totalCount, productDescription };

    bulkOverlayProductName.textContent = productDescription;
    bulkOverlayRemainingCount.innerHTML = gettext("<strong>%(remaining)s</strong> of <strong>%(total)s</strong> remaining")
        .replace("%(remaining)s", remainingCount)
        .replace("%(total)s", totalCount);

    bulkPickQuantityInput.value = remainingCount;
    bulkPickQuantityInput.max = remainingCount;
    bulkPickQuantityInput.min = 1;

    bulkOverlay.classList.remove('hidden');
}

function hideBulkPickOverlay() {
    bulkOverlay.classList.add('hidden');
    bulkPickContext = null;
}

function executeBulkPick(productCode, quantity, returnToScanner) {
    const ctx = bulkPickContext;
    if (!ctx) return;

    const now = Date.now();
    const timeTakenMs = lastPickTs ? (now - lastPickTs) : null;
    lastPickTs = now;

    // Remove quantity instances from currentPicklist
    let removed = 0;
    for (let i = currentPicklist.length - 1; i >= 0 && removed < quantity; i--) {
        if (currentPicklist[i] === productCode) {
            currentPicklist.splice(i, 1);
            removed++;
        }
    }

    updateScannedList(currentPicklist, productData);

    // Send to server
    notifyBulkProductPicked({ orderID: currentOrderID, productCode, quantity, timeTakenMs, csrfToken })
        .catch(function (err) {
            console.error('bulk-product-pick update failed', err);
            showNotification(gettext("Could not update bulk product pick."), true);
        });

    // Show notification
    const product = productData.find(function (item) { return item.code === productCode; });
    const desc = product ? product.description : productCode;
    showNotification(
        gettext("Picked %(quantity)s of %(product)s")
            .replace("%(quantity)s", quantity)
            .replace("%(product)s", desc)
    );

    // Check remaining
    const newRemaining = currentPicklist.filter(function (c) { return c === productCode; }).length;

    hideBulkPickOverlay();

    if (currentPicklist.length === 0) {
        isProcessingScan = false;
        resumeScanner();
        notifyPicklistCompleted(currentOrderID, csrfToken);
    } else if (returnToScanner) {
        isProcessingScan = false;
        resumeScanner();
    } else if (newRemaining > 1) {
        const totalCount = originalProductCounts[productCode] || 0;
        showBulkPickOverlay(desc, productCode, newRemaining, totalCount);
    } else if (newRemaining === 1) {
        const totalCount = originalProductCounts[productCode] || 0;
        showConfirmationOverlay(desc, newRemaining, totalCount);
    } else {
        isProcessingScan = false;
        resumeScanner();
    }
}

function notifyBulkProductPicked({orderID, productCode, quantity, timeTakenMs, csrfToken}) {
    return getDeviceFingerprint()
        .then(function (deviceFingerprint) {
            return fetch('/orderpiqr/bulk-product-pick', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    orderID,
                    productCode,
                    quantity,
                    timeTakenMs,
                    deviceFingerprint,
                    scannedAt: new Date().toISOString()
                })
            });
        });
}

// Bulk overlay event listeners
bulkConfirmAllBtn.addEventListener('click', function () {
    if (!bulkPickContext) return;
    executeBulkPick(bulkPickContext.productCode, bulkPickContext.remainingCount, true);
});

bulkPickOneBtn.addEventListener('click', function () {
    if (!bulkPickContext) return;
    executeBulkPick(bulkPickContext.productCode, 1, true);
});

bulkConfirmQtyBtn.addEventListener('click', function () {
    if (!bulkPickContext) return;
    var qty = parseInt(bulkPickQuantityInput.value, 10);
    if (isNaN(qty) || qty < 1 || qty > bulkPickContext.remainingCount) {
        showNotification(gettext("Please enter a valid quantity"), true);
        return;
    }
    executeBulkPick(bulkPickContext.productCode, qty, true);
});

bulkPickMinusBtn.addEventListener('click', function () {
    var current = parseInt(bulkPickQuantityInput.value, 10) || 1;
    if (current > 1) {
        bulkPickQuantityInput.value = current - 1;
    }
});

bulkPickPlusBtn.addEventListener('click', function () {
    if (!bulkPickContext) return;
    var current = parseInt(bulkPickQuantityInput.value, 10) || 0;
    if (current < bulkPickContext.remainingCount) {
        bulkPickQuantityInput.value = current + 1;
    }
});

bulkPickQuantityInput.addEventListener('blur', function () {
    if (!bulkPickContext) return;
    var val = parseInt(this.value, 10);
    if (isNaN(val) || val < 1) val = 1;
    if (val > bulkPickContext.remainingCount) val = bulkPickContext.remainingCount;
    this.value = val;
});

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

// Check for claimed order from queue on page load
function loadClaimedOrder() {
    console.log('[Queue] Checking for claimed order...');

    // First, check for server-provided data (from URL parameter)
    let data = null;
    const serverDataEl = document.getElementById('claimed-order-data');
    if (serverDataEl) {
        try {
            data = JSON.parse(serverDataEl.textContent);
            console.log('[Queue] Found server-provided order data:', data);
        } catch (e) {
            console.error('[Queue] Error parsing server data:', e);
        }
    }

    // Fallback to sessionStorage
    if (!data) {
        const claimedOrderData = sessionStorage.getItem('claimed_order');
        console.log('[Queue] sessionStorage claimed_order:', claimedOrderData);
        if (claimedOrderData) {
            try {
                data = JSON.parse(claimedOrderData);
                console.log('[Queue] Parsed sessionStorage data:', data);
                // Clear the sessionStorage immediately to prevent re-loading on refresh
                sessionStorage.removeItem('claimed_order');
            } catch (e) {
                console.error('[Queue] Error parsing sessionStorage:', e);
            }
        }
    }

    if (data && data.order_code && data.picklist && data.picklist.length > 0) {
        console.log('[Queue] Loading order:', data.order_code, 'with', data.picklist.length, 'items');
        console.log('[Queue] Product data available:', productData ? productData.length : 0, 'products');

        if (!productData || productData.length === 0) {
            console.error('[Queue] Cannot load order: productData is empty or undefined');
            showNotification(gettext("Cannot load order: product data not available"), true);
            return;
        }

        // Initialize the picklist from the claimed order
        currentPicklist.length = 0;
        const originalCounts = {};

        for (const code of data.picklist) {
            currentPicklist.push(code);
            originalCounts[code] = (originalCounts[code] || 0) + 1;
        }
        console.log('[Queue] currentPicklist populated:', currentPicklist);

        currentOrderID = data.order_code;
        originalPicklistOrder = [...currentPicklist];

        // Apply sorting preference
        const sortingPreference = window.SETTINGS?.picklist_sorting ?? "original";
        console.log('[Queue] Sorting preference:', sortingPreference);
        const sorted = sortPicklist(currentPicklist, productData, sortingPreference, originalPicklistOrder);
        currentPicklist.length = 0;
        currentPicklist.push(...sorted);
        console.log('[Queue] After sorting:', currentPicklist);

        // Update the display
        console.log('[Queue] Calling updateScannedList...');
        updateScannedList(currentPicklist, productData);
        updatePicklistCodeDisplay(currentOrderID);

        // Store original counts for overlay display
        // Update the module-level variable
        Object.keys(originalProductCounts).forEach(key => delete originalProductCounts[key]);
        Object.assign(originalProductCounts, originalCounts);

        // Set the last pick timestamp
        lastPickTs = Date.now();

        showNotification(gettext("Order loaded from queue"), false);
        console.log('[Queue] Order loaded successfully');
    } else {
        console.log('[Queue] No claimed order found or invalid data');
    }
}

// Wait for DOM to be fully ready before loading claimed order
// ES modules are deferred but may still run before all elements are rendered
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadClaimedOrder);
} else {
    // DOM is already ready
    loadClaimedOrder();
}