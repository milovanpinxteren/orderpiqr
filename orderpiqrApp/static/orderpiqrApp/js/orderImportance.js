// orderImportance.js
const gettext = window.gettext;  // Pull it from the global scope
// let isOrderImportant = true;  // Flag to track if order matters

export let isOrderImportant = window.SETTINGS?.order_importance ?? true;
console.log('isorderimportant', isOrderImportant)

export function toggleOrderImportance() {
    isOrderImportant = !isOrderImportant;
    return isOrderImportant;
}

export function updateOrderImportanceButton(button) {
    if (isOrderImportant) {
        console.log('order is important')
        button.textContent = gettext('Order Importance: Enabled');
        button.style.backgroundColor = "#28a745";  // Green for enabled
        isOrderImportant = true
    } else {
        console.log('order is not important')

        button.textContent = gettext('Order Importance: Disabled');
        button.style.backgroundColor = "#dc3545";  // Red for disabled
        isOrderImportant = false
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const toggleBtn = document.getElementById("toggle-order-btn");

    if (toggleBtn) {
        // Set initial button state based on window.SETTINGS
        updateOrderImportanceButton(toggleBtn);

        // Toggle on click
        toggleBtn.addEventListener("click", () => {
            toggleOrderImportance();
            updateOrderImportanceButton(toggleBtn);
        });
    }
});

