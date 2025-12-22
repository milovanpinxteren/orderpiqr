// orderImportance.js
const gettext = window.gettext;

let isOrderImportant = window.SETTINGS?.order_importance ?? true;

export function getIsOrderImportant() {
    return isOrderImportant;
}

export function toggleOrderImportance() {
    isOrderImportant = !isOrderImportant;
    return isOrderImportant;
}

export function updateOrderImportanceButton(button) {
    if (isOrderImportant) {
        button.textContent = gettext('Order Importance: Enabled');
        button.style.backgroundColor = "#28a745";
    } else {
        button.textContent = gettext('Order Importance: Disabled');
        button.style.backgroundColor = "#dc3545";
    }
}