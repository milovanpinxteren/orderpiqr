// orderImportance.js
const gettext = window.gettext;  // Pull it from the global scope
let isOrderImportant = true;  // Flag to track if order matters

export function toggleOrderImportance() {
    isOrderImportant = !isOrderImportant;
    return isOrderImportant;
}

export function updateOrderImportanceButton(button) {
    if (isOrderImportant) {
        button.textContent = gettext('Order Importance: Enabled');
        button.style.backgroundColor = "#28a745";  // Green for enabled
        isOrderImportant = true
    } else {
        button.textContent = gettext('Order Importance: Disabled');
        button.style.backgroundColor = "#dc3545";  // Red for disabled
        isOrderImportant = false
    }
}
