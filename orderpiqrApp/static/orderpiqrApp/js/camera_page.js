// camera_page.js

// Importing the necessary functions from the modular JS files
import {initializeScanner} from './qrScanner.js';
import {showNotification} from './notifications.js';
import {toggleOrderImportance, updateOrderImportanceButton} from './orderImportance.js';
import {handlePicklist} from './picklistHandler.js';
import {updateScannedList} from './domUpdater.js';

// Access the productData object injected into the HTML
const productData = window.productData || {};  // Fallback in case the data is not injected
let scannedCodes = []; // Array to store scanned codes
let currentPicklist = []; // Array to store the current picklist

// Toggle button for order importance
const toggleButton = document.getElementById('toggle-order-btn');
let isOrderImportant = true

// Event listener for toggling order importance
toggleButton.addEventListener('click', function () {
    isOrderImportant = toggleOrderImportance(); // Toggle the order importance state
    updateOrderImportanceButton(toggleButton); // Update button appearance
    console.log("Order importance toggled:", isOrderImportant ? "On" : "Off");
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

    if (isPicklist(scannedCode)) {
        currentPicklist = handlePicklist(scannedCode, currentPicklist, productData);
        setTimeout(() => {
            console.log('scan picklist done done')
            isProcessingScan = false; // Reset the flag after the delay

        }, 1000);
        console.log('processing flag to false')

        // isProcessingScan = false;

    } else {
        console.log('handling product codeisProcessingScan, isOrderImportant', isProcessingScan, isOrderImportant)
        handleProductCode(scannedCode, currentPicklist, productData, isOrderImportant);
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
function handleProductCode(code, currentPicklist, productData, isOrderImportant) {
    try {
        if (isOrderImportant) {
            const firstProductCode = currentPicklist[0];
            if (code === firstProductCode) {
                // Correct scan, remove the first product from the list
                currentPicklist.splice(0, 1);
                console.log('correct code scanned', productData)
                updateScannedList(currentPicklist, productData); // Update the table after removing the first product
                const product = productData.find(item => item.code === firstProductCode);  // Match code in productData
                showNotification(`Scanned ${product.description}`); // Show success notification
                // setTimeout(() => {
                //     isProcessingScan = false; // Allow scanning again after 1 second
                // }, "1000");

            } else {
                // Incorrect scan, show error notification
                showNotification("Incorrect scan, please try again.", true);
            }
        } else {
            const index = currentPicklist.indexOf(code);
            if (index !== -1) {
                // Valid scan, remove the product from the list
                currentPicklist.splice(index, 1);
                updateScannedList(currentPicklist, productData);  // Update the table after a valid scan
                showNotification(`Scanned ${productData[code].picknaam}`);  // Show success notification
            } else {
                showNotification("Product code not found in the list.", true);  // Show error notification
            }
        }
    } catch (error) {
        console.error('Error in handleProductCode:', error);
    }
}


// Fallback if the window.productData is not available
if (Object.keys(productData).length === 0) {
    console.error('No product data found!');
}
