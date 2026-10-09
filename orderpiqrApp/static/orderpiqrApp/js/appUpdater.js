// Keeps the long-lived scan page on the current build without ever
// interrupting a pick. Pickers leave the PWA open for days, so a deploy only
// reaches a device when the page reloads; this module polls the server's
// build id and reloads at a safe moment (no picklist in progress, no scan
// being processed). An in-progress list lives only in page memory, so the
// idle guard is what makes the reload lossless.

const FIRST_CHECK_MS = 30 * 1000;
const CHECK_INTERVAL_MS = 5 * 60 * 1000;
const IDLE_RETRY_MS = 60 * 1000;
// Idle right now can mean "just completed, about to scan the next list":
// wait out the completion toast and re-check before actually reloading.
const IDLE_SETTLE_MS = 8000;

let updatePending = false;
let settleTimer = null;

export function initAppUpdater(isIdle) {
    const loadedBuildId = window.SETTINGS?.build_id;
    if (!loadedBuildId || loadedBuildId === 'dev') return;

    async function checkForUpdate() {
        // Nudge the service worker too, so a new serviceWorker.js installs
        // alongside the page reload instead of a day later.
        navigator.serviceWorker?.getRegistration()
            .then(reg => reg?.update())
            .catch(() => {});
        try {
            const res = await fetch('/orderpiqr/client-version', {cache: 'no-store'});
            if (!res.ok) return;
            const data = await res.json();
            if (data.buildId && data.buildId !== loadedBuildId) {
                updatePending = true;
                maybeReload();
            }
        } catch (e) {
            // Offline or flaky network: the next interval tries again.
        }
    }

    function maybeReload() {
        if (!updatePending || settleTimer || !isIdle()) return;
        settleTimer = setTimeout(() => {
            settleTimer = null;
            if (isIdle()) {
                console.log('[AppUpdater] New build available, reloading');
                location.reload();
            }
        }, IDLE_SETTLE_MS);
    }

    document.addEventListener('visibilitychange', () => {
        // App sent to the background: nothing on screen to interrupt.
        if (document.visibilityState === 'hidden' && updatePending && isIdle()) {
            location.reload();
        }
    });

    setTimeout(checkForUpdate, FIRST_CHECK_MS);
    setInterval(checkForUpdate, CHECK_INTERVAL_MS);
    setInterval(maybeReload, IDLE_RETRY_MS);
}
