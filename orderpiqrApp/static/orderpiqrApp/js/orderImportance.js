// orderImportance.js

let isOrderImportant = true;  // Flag to track if order matters

export function toggleOrderImportance() {
    isOrderImportant = !isOrderImportant;
    return isOrderImportant;
}

export function updateOrderImportanceButton(button) {
    if (isOrderImportant) {
        button.textContent = "Order Importance: Enabled";
        button.style.backgroundColor = "#28a745";  // Green for enabled
        isOrderImportant = true
    } else {
        button.textContent = "Order Importance: Disabled";
        button.style.backgroundColor = "#dc3545";  // Red for disabled
        isOrderImportant = false
    }
}
