import {updateScannedList} from './domUpdater.js';
import {showNotification} from './notifications.js';
import {currentPicklist, productData, notifyPicklistCompleted, currentOrderID, onSuccessfulPick} from './camera_page.js';  // Import currentPicklist and productData
const gettext = window.gettext;


let clickTimes = {}; // Store click timestamps for each product
const clickThreshold = 2 * 1000; // 2 seconds in milliseconds
const clickCountThreshold = 3; // 3 clicks required


// Event listener to handle manual override through rapid clicks
document.addEventListener('click', function (event) {
    const clickedCode = event.target.dataset.productCode;
    if (clickedCode) {
        if (!clickTimes[clickedCode]) {
            clickTimes[clickedCode] = [];
        }

        // Record the current timestamp of the click
        const currentTime = Date.now();
        clickTimes[clickedCode].push(currentTime);

        // Remove clicks older than 2 seconds
        clickTimes[clickedCode] = clickTimes[clickedCode].filter(time => currentTime - time <= clickThreshold);

        // Check if we have 3 clicks within the threshold
        if (clickTimes[clickedCode].length >= clickCountThreshold) {
            handleManualOverride(clickedCode);
        }
    }
});

// Function to handle manual override
function handleManualOverride(code) {
    const productIndex = currentPicklist.indexOf(code);
    if (productIndex !== -1) {
        currentPicklist.splice(productIndex, 1); // Remove the product from the picklist
    }
    clickTimes[code] = []; // Reset the click counter for this product
    updateScannedList(currentPicklist, productData); // Update the table after removing the product
    const product = productData.find(item => item.code === code);  // Match code in productData
    onSuccessfulPick(code);
    // Show notification for the manual override
    if (product) {
        // showNotification(`Manual override: ${product.description} confirmed`);
        showNotification(gettext("Manual override: %(product)s confirmed").replace("%(product)s", product.description));
        if (currentPicklist.length === 0) {
            notifyPicklistCompleted(currentOrderID, csrfToken);  // <- you'll need to make csrfToken available
        }

    } else {
        // showNotification(`Manual override: ${code} confirmed`);
        showNotification(gettext("Manual override: %(code)s confirmed").replace("%(code)s", code));
        if (currentPicklist.length === 0) {
            notifyPicklistCompleted(currentOrderID, csrfToken);  // <- you'll need to make csrfToken available
        }
    }
}
