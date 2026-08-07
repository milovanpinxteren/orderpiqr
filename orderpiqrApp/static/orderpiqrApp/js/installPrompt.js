(function () {
    const DISMISS_KEY = 'install_prompt_dismissed';

    // Already running as installed PWA
    function isStandalone() {
        return window.matchMedia('(display-mode: standalone)').matches
            || window.navigator.standalone === true;
    }

    function isIOS() {
        const ua = navigator.userAgent;
        return /iPad|iPhone|iPod/.test(ua)
            || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    }

    function dismiss() {
        const banner = document.getElementById('install-prompt-banner');
        if (banner) {
            banner.style.opacity = '0';
            setTimeout(function () { banner.remove(); }, 300);
        }
        localStorage.setItem(DISMISS_KEY, 'true');
    }

    function createBanner(content) {
        if (localStorage.getItem(DISMISS_KEY)) return;

        const banner = document.createElement('div');
        banner.id = 'install-prompt-banner';
        banner.innerHTML =
            '<div class="install-prompt-inner">' +
                '<button class="install-prompt-close" id="install-prompt-close" aria-label="Close">&times;</button>' +
                '<div class="install-prompt-icon"><img src="/static/icons/icon-192.png" alt="Orderpiqr"></div>' +
                '<div class="install-prompt-title">' + gettext('Install Orderpiqr') + '</div>' +
                '<div class="install-prompt-desc">' + gettext('Add Orderpiqr to your home screen for quick access') + '</div>' +
                content +
            '</div>';

        // Insert after header
        const header = document.querySelector('.header');
        if (header && header.nextSibling) {
            header.parentNode.insertBefore(banner, header.nextSibling);
        } else {
            document.body.prepend(banner);
        }

        // Fade in
        requestAnimationFrame(function () {
            banner.style.opacity = '1';
        });

        document.getElementById('install-prompt-close').addEventListener('click', dismiss);
    }

    // --- Android / Chrome: beforeinstallprompt ---
    let deferredPrompt = null;

    window.addEventListener('beforeinstallprompt', function (e) {
        e.preventDefault();
        deferredPrompt = e;

        const content =
            '<button class="install-prompt-btn" id="install-prompt-install">' +
                gettext('Install') +
            '</button>';

        createBanner(content);

        // Wait for DOM update then attach handler
        setTimeout(function () {
            var btn = document.getElementById('install-prompt-install');
            if (btn) {
                btn.addEventListener('click', function () {
                    if (deferredPrompt) {
                        deferredPrompt.prompt();
                        deferredPrompt.userChoice.then(function (result) {
                            deferredPrompt = null;
                            dismiss();
                        });
                    }
                });
            }
        }, 0);
    });

    // --- iOS: show instructions ---
    document.addEventListener('DOMContentLoaded', function () {
        if (isStandalone()) return;
        if (!isIOS()) return;

        const content =
            '<div class="install-prompt-steps">' +
                '<div class="install-prompt-step">' +
                    '<span class="install-prompt-step-num">1</span>' +
                    '<span>' + gettext('Tap the Share button') +
                        ' <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#118f11" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle">' +
                            '<path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8"/>' +
                            '<polyline points="16 6 12 2 8 6"/>' +
                            '<line x1="12" y1="2" x2="12" y2="15"/>' +
                        '</svg>' +
                    '</span>' +
                '</div>' +
                '<div class="install-prompt-step">' +
                    '<span class="install-prompt-step-num">2</span>' +
                    '<span>' + gettext('Tap "Add to Home Screen"') +
                        ' <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#118f11" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle">' +
                            '<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>' +
                            '<line x1="12" y1="8" x2="12" y2="16"/>' +
                            '<line x1="8" y1="12" x2="16" y2="12"/>' +
                        '</svg>' +
                    '</span>' +
                '</div>' +
            '</div>';

        createBanner(content);
    });
})();
