function copyTokenToClipboard(inputId, buttonEl) {
    const input = document.getElementById(inputId);
    const feedback = buttonEl.nextElementSibling; // assumes feedback <span> is right after the button

    if (!input) return;

    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(input.value).then(() => {
            feedback.textContent = "Copied!";
            setTimeout(() => feedback.textContent = "", 2000);
        }).catch(() => {
            feedback.textContent = "Failed to copy.";
        });
    } else {
        input.select();
        input.setSelectionRange(0, 99999); // for mobile
        try {
            document.execCommand("copy");
            feedback.textContent = "Copied!";
        } catch (err) {
            feedback.textContent = "Failed to copy.";
        }
        setTimeout(() => feedback.textContent = "", 2000);
    }
}
