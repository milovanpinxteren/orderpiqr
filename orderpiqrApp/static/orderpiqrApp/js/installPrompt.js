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

    // force=true shows the banner even after it was dismissed once — used when
    // the picker explicitly asks via the persistent install link, which is not
    // the nag the one-time dismiss is meant to silence.
    function createBanner(content, force) {
        if (!force && localStorage.getItem(DISMISS_KEY)) return;
        if (document.getElementById('install-prompt-banner')) return;  // already showing

        const banner = document.createElement('div');
        banner.id = 'install-prompt-banner';
        banner.innerHTML =
            '<div class="install-prompt-inner">' +
                '<button class="install-prompt-close" id="install-prompt-close" aria-label="' + gettext('Close') + '">&times;</button>' +
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

    // The iOS "add to home screen" steps, shared by the one-time banner and the
    // persistent link (iOS has no programmatic install prompt, so instructions
    // are all we can offer).
    function iosStepsContent() {
        return '<div class="install-prompt-steps">' +
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
    }

    // Generic "add to home screen" steps for platforms with no programmatic
    // install prompt and no iOS Share sheet — chiefly Android Chrome when the
    // beforeinstallprompt event is not available (the app is already installed,
    // or the browser's install heuristics have not fired). Without this the link
    // used to open a banner with a title and no action at all.
    function genericStepsContent() {
        return '<div class="install-prompt-steps">' +
                '<div class="install-prompt-step">' +
                    '<span class="install-prompt-step-num">1</span>' +
                    '<span>' + gettext('Open your browser menu') + ' ⋮</span>' +
                '</div>' +
                '<div class="install-prompt-step">' +
                    '<span class="install-prompt-step-num">2</span>' +
                    '<span>' + gettext('Tap "Add to Home Screen"') + '</span>' +
                '</div>' +
            '</div>';
    }

    // A browser tab cannot see or launch the home-screen app, and there is no
    // web API to open an installed PWA from one. The best we can do is not offer
    // to install what is already installed: on Android, getInstalledRelatedApps
    // reports the installed PWA (via the manifest's related_applications
    // self-entry). Elsewhere — and on iOS — it is unavailable, so this resolves
    // false and the link stays visible; its click still gives real instructions.
    function isInstalledApp() {
        try {
            if (navigator.getInstalledRelatedApps) {
                return navigator.getInstalledRelatedApps()
                    .then(function (apps) { return !!(apps && apps.length); })
                    .catch(function () { return false; });
            }
        } catch (e) { /* fall through */ }
        return Promise.resolve(false);
    }

    // The persistent link. Unlike the banner it is never dismissed: a device
    // that has not installed the app keeps a small, out-of-the-way way to do so
    // from the settings menu. It is the holdouts that matter — a browser tab
    // loses its device identity and the offline pick queue to Safari's 7-day
    // storage eviction, which an installed app is exempt from.
    function setupInstallLink() {
        if (isStandalone()) return;
        isInstalledApp().then(function (installed) {
            if (installed) return;   // already on the home screen; nothing to offer
            showInstallLink();
        });
    }

    function showInstallLink() {
        const slot = document.getElementById('install-link-slot');
        const row = document.getElementById('install-row');
        if (!slot || document.getElementById('install-link')) return;

        const link = document.createElement('a');
        link.href = '#';
        link.id = 'install-link';
        link.className = 'install-link';
        link.setAttribute('role', 'button');
        // Reuses the banner's already-translated label, so the link adds no new
        // string to the catalogs.
        link.innerHTML =
            '<img src="/static/icons/icon-192.png" alt="" class="install-link-icon">' +
            '<span>' + gettext('Install Orderpiqr') + '</span>';
        slot.appendChild(link);
        if (row) row.hidden = false;

        link.addEventListener('click', function (e) {
            e.preventDefault();
            if (deferredPrompt) {
                // Android/Chrome: fire the real install prompt.
                deferredPrompt.prompt();
                deferredPrompt.userChoice.then(function () { deferredPrompt = null; });
                return;
            }
            // No native prompt: show platform-appropriate instructions, forced
            // past the one-time dismiss since the picker explicitly asked. Never
            // an empty banner — that is the dead modal this replaces.
            createBanner(isIOS() ? iosStepsContent() : genericStepsContent(), true);
        });
    }

    // --- iOS: one-time instruction banner (unchanged behaviour) + the link ---
    document.addEventListener('DOMContentLoaded', function () {
        setupInstallLink();
        if (isStandalone()) return;
        if (!isIOS()) return;
        createBanner(iosStepsContent());
    });
})();
