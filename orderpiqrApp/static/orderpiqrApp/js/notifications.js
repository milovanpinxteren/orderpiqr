// notifications.js

export function showNotification(message, isError = false) {
    const notificationContainer = document.getElementById('notification-container');

    // Create a new notification element
    const notification = document.createElement('div');
    notification.classList.add('notification');
    if (isError) {
        notification.classList.add('error');
    }

    // Set the notification message
    notification.textContent = message;

    // Append the new notification to the container
    notificationContainer.appendChild(notification);

    // Fade in the notification
    setTimeout(() => {
        notification.classList.add('show');
    }, 50);  // Small delay to allow visibility

    // Remove the notification after 5 seconds
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => {
            notification.remove();  // Remove from DOM after fade-out
        }, 300);  // Wait for fade-out before removing
    }, 5000);  // Show for 5 seconds
}
