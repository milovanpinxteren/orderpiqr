import {showNotification} from './notifications.js';
import {currentPicklist, productData, completeIfFinished, onSuccessfulPick, renderList, showPickFollowUpOverlay} from './camera_page.js';  // Import currentPicklist and productData
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
    // Through camera_page's single render entry point, so the declared-short
    // rows at the bottom of the table survive an override.
    renderList();
    const product = productData.find(item => item.code === code);  // Match code in productData
    // The override is logged server-side via the product-pick call itself
    // (manualOverride flag) — no separate scan event, to avoid double counting.
    onSuccessfulPick(code, {manualOverride: true});
    // Show notification for the manual override
    if (product) {
        // showNotification(`Manual override: ${product.description} confirmed`);
        showNotification(gettext("Manual override: %(product)s confirmed").replace("%(product)s", product.description));
    } else {
        // showNotification(`Manual override: ${code} confirmed`);
        showNotification(gettext("Manual override: %(code)s confirmed").replace("%(code)s", code));
    }

    // Same follow-up as a scan: for a multi-quantity line this opens the bulk
    // overlay ("All N taken" / stepper), so products without a barcode don't
    // need a triple-tap per unit.
    // manualOverride: true so that "All N taken" on this overlay is logged as an
    // override as well — otherwise only the first unit of an unscannable line
    // ever counted.
    showPickFollowUpOverlay(code, product ? product.description : code, {manualOverride: true});

    // One completion path for all four 0-length sites. (This used to call
    // notifyPicklistCompleted(currentOrderID, csrfToken) — csrfToken is not in
    // scope in a module, so the last override on a list threw instead of
    // completing it.)
    completeIfFinished();
}
