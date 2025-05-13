// camera_page.js

// Importing the necessary functions from the modular JS files
import { initializeScanner } from './qrScanner.js';
import { showNotification } from './notifications.js';
import { toggleOrderImportance, updateOrderImportanceButton } from './orderImportance.js';
import { handlePicklist } from './picklistHandler.js';
import { updateScannedList } from './domUpdater.js';

// Access the productData object injected into the HTML
const productData = window.productData || {};  // Fallback in case the data is not injected

let scannedCodes = []; // Array to store scanned codes
let currentPicklist = []; // Array to store the current picklist

// Toggle button for order importance
const toggleButton = document.getElementById('toggle-order-btn');

// Event listener for toggling order importance
toggleButton.addEventListener('click', function () {
    const isOrderImportant = toggleOrderImportance(); // Toggle the order importance state
    updateOrderImportanceButton(toggleButton); // Update button appearance
    console.log("Order importance toggled:", isOrderImportant ? "On" : "Off");
});

// Initialize the QR code scanner
initializeScanner((scannedCode) => {
    if (isPicklist(scannedCode)) {
        handlePicklist(scannedCode, currentPicklist);
    } else {
        handleProductCode(scannedCode, currentPicklist, productData);
    }
});

// Function to check if a scanned code is a picklist
function isPicklist(code) {
    return code.includes("\t") || code.includes(",") || code.includes(";");
}

// Function to handle scanned product codes
function handleProductCode(code, currentPicklist, productData) {
    if (isOrderImportant) {
        const firstProductCode = currentPicklist[0];
        if (code === firstProductCode) {
            // Correct scan, remove the first product from the list
            currentPicklist.splice(0, 1);
            updateScannedList(currentPicklist, productData); // Update the table
            showNotification(`Scanned ${productData[code].picknaam}`); // Show success notification
        } else {
            // Incorrect scan, show error notification
            showNotification("Incorrect scan, please try again.", true);
        }
    } else {
        const index = currentPicklist.indexOf(code);
        if (index !== -1) {
            // Valid scan, remove the product from the list
            currentPicklist.splice(index, 1);
            updateScannedList(currentPicklist, productData);
            showNotification(`Scanned ${productData[code].picknaam}`);  // Show success notification
        } else {
            showNotification("Product code not found in the list.", true);  // Show error notification
        }
    }
}

// Fallback if the window.productData is not available
if (Object.keys(productData).length === 0) {
    console.error('No product data found!');
}
