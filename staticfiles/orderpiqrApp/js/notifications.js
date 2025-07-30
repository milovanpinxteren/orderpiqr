// notifications.js

export function showNotification(message, isError = false) {
    const notificationContainer = document.getElementById('notification-container');
    const body = document.body;
    let timeout = isError ? 5000 : 10000;
    // Create a new notification element
    const notification = document.createElement('div');
    notification.classList.add('notification');
    if (isError) {
        notification.classList.add('error');
        body.classList.add('screen-error');
    } else {
        body.classList.add('screen-success');
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
            body.classList.remove('screen-success', 'screen-error');

        }, 500);  // Wait for fade-out before removing
    }, timeout);  // Show for 5 seconds
}

window.showNotification = showNotification;

