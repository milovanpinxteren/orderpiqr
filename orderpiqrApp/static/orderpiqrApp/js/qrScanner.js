// qrScanner.js
//
// Wrapper around the html5-qrcode core API (Html5Qrcode). The library's
// bundled Html5QrcodeScanner UI stacks a camera dropdown and start/stop
// buttons under the video, eating most of the screen — here the camera
// starts on its own and those controls live in a panel behind the small
// options button overlaid on the camera card (see index.html).

// Fallback keeps the module working on pages without the JS i18n catalog.
const gettext = window.gettext || (s => s);

const LAST_CAMERA_KEY = 'orderpiqr_last_camera_id';
// Sentinel value of the iOS-only "let the phone choose" dropdown entry. Not a
// device id, so it can never collide with one.
const AUTO_CAMERA_VALUE = '__auto__';
// No qrbox/formatsToSupport: the full frame is scanned and every format the
// library knows is accepted, matching the old Html5QrcodeScanner behavior.
const SCAN_CONFIG = {fps: 5, aspectRatio: 1.0};

// Resolution hints. iOS getUserMedia hands back ~640x480 when nothing is asked
// for, which is marginal for a dense DataMatrix or a small GS1-128 — the camera
// looks fine and simply never decodes. "ideal" is a hint, not a requirement: a
// phone that cannot do 1080p returns its best instead of failing.
//
// These CANNOT go in start()'s first argument. html5-qrcode 2.3.8 runs that
// argument through createVideoConstraints(), which throws unless the object has
// exactly one key and that key is 'deviceId' or 'facingMode'. The supported
// route is the scan config's videoConstraints, which start() passes to
// getUserMedia *instead of* the first argument:
//     var a = c ? s.videoConstraints : h.createVideoConstraints(t);
// (vendor/html5-qrcode-2.3.8.min.js). The first argument is still required to
// be truthy, so both start paths keep passing a library-legal one — it is also
// what the bare retry below falls back to.
const RESOLUTION_HINTS = {width: {ideal: 1920}, height: {ideal: 1080}};
// Library-legal facing-mode argument. Note the *string* form: the same 2.3.8
// validator only accepts {facingMode: "environment"} or {facingMode: {exact:
// ...}} — the {ideal: ...} form this file used before was rejected outright,
// which sent every iOS start straight down the device-id fallback the
// facing-mode fix existed to avoid.
const FACING_MODE_ARG = {facingMode: 'environment'};

let scannerInstance = null;
let cameras = [];
let onScan = null;
let isRunning = false;
let isPaused = false;
// Set once the picker explicitly chooses a camera from the dropdown this
// session. Until then iOS starts by facing-mode, not by a stored device id —
// see startPreferred().
let userPickedCamera = false;

// iPhones/iPads: a stored deviceId frequently resolves to the ultra-wide lens,
// which cannot focus on a close barcode, so the camera runs but never decodes.
// Prod bore this out — iOS pickers fell back to the manual-override triple-tap
// on ~19% of picks versus ~6% on Android, with zero camera errors because the
// camera *starts* fine. Starting by {facingMode:"environment"} instead lets
// iOS choose its autofocus wide camera. iPadOS 13+ reports as "MacIntel" with
// touch points, so the platform check mirrors installPrompt.js.
function isIOS() {
    try {
        const ua = navigator.userAgent || '';
        return /iPad|iPhone|iPod/.test(ua)
            || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    } catch (e) {
        return false;
    }
}

// Running as the installed home-screen app rather than a browser tab. Matches
// installPrompt.js; it matters here because iOS scopes the camera permission to
// the installed app separately from Safari, so the fix we tell the picker about
// depends on which one they are in.
function isStandalone() {
    try {
        return window.matchMedia('(display-mode: standalone)').matches
            || window.navigator.standalone === true;
    } catch (e) {
        return false;
    }
}

// Errors reach us in two shapes: getCameras() rejects with the raw DOMException
// (so err.name is "NotAllowedError"), while start() rejects with a *string* the
// library builds — "Error getting userMedia, error = NotAllowedError: ...".
// Flatten both before matching.
function describeError(err) {
    try {
        if (!err) return '';
        return String(err.name || '') + ' ' + String(err.message || err);
    } catch (e) {
        return '';
    }
}

function looksDenied(err) {
    return /NotAllowedError|PermissionDeniedError|Permission denied/i
        .test(describeError(err));
}

// A camera that is absent is not a camera that is blocked; sending it down the
// permission path would tell the picker to go fix a setting that does not exist.
function looksMissing(err) {
    return /NotFoundError|DevicesNotFoundError/i.test(describeError(err));
}

// Best-effort permission state, resolving to 'denied' / 'granted' / 'prompt' /
// 'unknown' and never rejecting. Safari has not reliably supported the 'camera'
// permission name — query() may reject or throw synchronously — so the error we
// already have is the fallback, and also the tie-breaker: a NotAllowedError is
// authoritative even if query() cheerfully answers 'prompt'.
function cameraPermissionState(err) {
    const sniffed = looksDenied(err) ? 'denied' : 'unknown';
    try {
        if (navigator.permissions && navigator.permissions.query) {
            return navigator.permissions.query({name: 'camera'})
                .then(status => {
                    const state = (status && status.state) || 'unknown';
                    return sniffed === 'denied' ? 'denied' : state;
                })
                .catch(() => sniffed);
        }
    } catch (e) { /* unsupported permission name: fall through to the sniff */ }
    return Promise.resolve(sniffed);
}

// Reached through the global rather than an import: clientHealth.js is a
// classic script and must stay outside this module graph.
function reportCameraError(reason, message) {
    try {
        if (window.orderpiqrHealth) {
            window.orderpiqrHealth.report('camera_error', {reason, message});
        }
    } catch (e) { /* diagnostics must never break the scanner */ }
}

export function initializeScanner(onScanCallback) {
    onScan = onScanCallback;
    scannerInstance = new Html5Qrcode("reader");
    wireControls();
    startCamera();
}

// Enumerate cameras (this triggers the browser permission prompt on first
// use) and start the preferred one.
function startCamera() {
    hideCameraError();
    Html5Qrcode.getCameras()
        .then(found => {
            cameras = found || [];
            if (cameras.length === 0) {
                reportCameraError('no_camera', 'No camera found on this device');
                showCameraError(gettext("No camera found on this device."));
                return;
            }
            populateCameraSelect();
            startPreferred();
        })
        .catch(err => {
            console.error('Camera permission/enumeration failed:', err);
            // A denied camera is otherwise indistinguishable from a picker who
            // simply stopped scanning.
            handlePermissionFailure(err);
        });
}

// The generic "we were refused" text, kept for every platform whose fix really
// is "flip the switch in browser settings and tap retry".
function genericDeniedMessage() {
    return gettext("Camera access was denied. Allow camera access for this site in your browser settings, then tap the button below.");
}

// Shared handling for a blocked camera. The message has to differ by platform
// because the fix does. On iOS the old text was actively wrong twice over:
//   - An installed PWA has its own camera permission. Granting it to Safari
//     changes nothing, and WebKit keeps serving the cached denial until the app
//     is force-quit and relaunched — so the retry button *cannot* succeed from
//     inside the app, and must stop claiming it will.
//   - In a Safari tab the switch is not in iOS Settings at all but behind the
//     "aA" menu in the address bar.
// Everywhere else iOS also differs from Android in that getCameras() fails
// instantly with no re-prompt, so a retry re-renders the identical error and
// the tap reads as dead. The relabel plus the exact steps are the only honest
// feedback available.
function handlePermissionFailure(err) {
    if (looksMissing(err)) {
        reportCameraError('no_camera', 'No usable camera: ' + describeError(err));
        showCameraError(gettext("No camera found on this device."));
        setRetryLabel(null);
        return;
    }
    cameraPermissionState(err).then(state => {
        if (isIOS() && state === 'denied') {
            if (isStandalone()) {
                reportCameraError('permission_denied_standalone', 'Camera blocked for the installed iOS app');
                showCameraError(gettext("Camera access is blocked for this app. Open iPhone Settings, find this app, allow Camera, then close the app fully and reopen it."));
                setRetryLabel(gettext("Try again after reopening the app"));
                return;
            }
            reportCameraError('permission_denied_browser', 'Camera blocked in iOS Safari');
            showCameraError(gettext("Camera access is blocked. In Safari, tap the ‘aA’ icon in the address bar → Website Settings → Camera → Allow, then tap the button below."));
            setRetryLabel(null);
            return;
        }
        reportCameraError('permission_denied', 'Camera denied or enumeration failed: ' + describeError(err));
        showCameraError(genericDeniedMessage());
        setRetryLabel(null);
    });
}

// Decide how to start the camera. The picker's explicit dropdown choice always
// wins. Otherwise iOS starts by facing-mode (see isIOS()); every other platform
// keeps the device-id path that already works well there.
function startPreferred() {
    const saved = localStorage.getItem(LAST_CAMERA_KEY);
    const savedValid = saved && cameras.some(c => c.id === saved);
    if (userPickedCamera && savedValid) {
        startWith(saved);
        return;
    }
    if (isIOS()) {
        startWithFacingMode();
        return;
    }
    if (savedValid) {
        startWith(saved);
        return;
    }
    startWith(pickDefaultCamera());
}

function pickDefaultCamera() {
    const saved = localStorage.getItem(LAST_CAMERA_KEY);
    if (saved && cameras.some(c => c.id === saved)) {
        return saved;
    }
    // Prefer a back-facing camera, but skip the ultra-wide and telephoto lenses:
    // the ultra-wide cannot focus on a close barcode and the telephoto's framing
    // is wrong for one. "Wide"/"dual wide" is the main autofocus camera and is
    // kept. Phones usually list the front camera first, so the last entry is the
    // better blind guess when no label matches.
    const backCams = cameras.filter(c => /back|rear|environment|achter|rück|arrière/i.test(c.label || ''));
    const focusable = backCams.find(c => !/ultra|tele|groothoek/i.test(c.label || ''));
    const chosen = focusable || backCams[0] || cameras[cameras.length - 1];
    return chosen.id;
}

// Single entry point to the library's start(). Tries the resolution-hinted
// constraints first and, if they are refused (OverconstrainedError on a phone
// that dislikes 1080p is the expected case), retries once with the bare
// argument that worked before. A sharper picture is never worth costing a
// picker a working camera.
function startStream(legacyArg, videoConstraints) {
    const config = Object.assign({}, SCAN_CONFIG, {videoConstraints: videoConstraints});
    const onDecode = decodedText => onScan(decodedText);
    const onMiss = () => { /* per-frame decode misses are expected noise */ };
    // start() validates its arguments *synchronously* and throws plain strings;
    // only getUserMedia failures come back as a rejection. Normalising both to a
    // rejection keeps every caller's .catch the single error path.
    let first;
    try {
        first = scannerInstance.start(legacyArg, config, onDecode, onMiss);
    } catch (e) {
        return Promise.reject(e);
    }
    return first
        .catch(err => {
            if (looksDenied(err)) throw err;   // retrying a refusal just fails twice
            console.warn('Camera start with resolution hints failed, retrying bare:', err);
            reportCameraError('resolution_fallback', 'Resolution hints refused: ' + describeError(err));
            return scannerInstance.start(legacyArg, SCAN_CONFIG, onDecode, onMiss);
        });
}

// iOS start path: hand the library a facing-mode constraint instead of a device
// id so iOS selects its default autofocus wide camera. Falls back to explicit
// device selection if the constraint is refused (e.g. a device with no
// environment-facing camera).
function startWithFacingMode() {
    hideCameraError();
    startStream(
        FACING_MODE_ARG,
        Object.assign({facingMode: {ideal: 'environment'}}, RESOLUTION_HINTS)
    )
        .then(() => {
            isRunning = true;
            isPaused = false;
            syncStopButton();
            // We did not pick a device id, so there is nothing stable to persist;
            // the dropdown shows the "automatic" entry instead of a lens, which
            // is what is actually in force.
            const select = document.getElementById('camera-select');
            if (select && select.querySelector('option[value="' + AUTO_CAMERA_VALUE + '"]')) {
                select.value = AUTO_CAMERA_VALUE;
            }
        })
        .catch(err => {
            console.error('facingMode start failed, falling back to device id:', err);
            if (looksDenied(err)) {
                // No lens choice fixes a refused permission; retrying every
                // device id would only stack identical failures.
                isRunning = false;
                syncStopButton();
                handlePermissionFailure(err);
                return;
            }
            reportCameraError('facingmode_failed', 'environment facingMode refused: ' + describeError(err));
            if (cameras.length > 0) {
                startWith(pickDefaultCamera());
            } else {
                isRunning = false;
                syncStopButton();
                showCameraError(gettext("Could not start the camera."));
            }
        });
}

function startWith(cameraId) {
    hideCameraError();
    startStream(
        cameraId,
        Object.assign({deviceId: {exact: cameraId}}, RESOLUTION_HINTS)
    )
        .then(() => {
            isRunning = true;
            isPaused = false;
            localStorage.setItem(LAST_CAMERA_KEY, cameraId);
            const select = document.getElementById('camera-select');
            if (select) select.value = cameraId;
            syncStopButton();
        })
        .catch(err => {
            console.error('Error starting camera:', err);
            isRunning = false;
            syncStopButton();
            if (looksDenied(err)) {
                handlePermissionFailure(err);
                return;
            }
            reportCameraError('start_failed', 'Camera failed to start: ' + describeError(err));
            showCameraError(gettext("Could not start the camera."));
        });
}

function stopCamera() {
    if (!scannerInstance || !isRunning) return Promise.resolve();
    return scannerInstance.stop()
        .catch(e => console.error("Error stopping scanner:", e))
        .then(() => {
            isRunning = false;
            isPaused = false;
            syncStopButton();
        });
}

function switchCamera(cameraId) {
    stopCamera().then(() => startWith(cameraId));
}

function wireControls() {
    const toggle = document.getElementById('camera-options-toggle');
    const panel = document.getElementById('camera-controls');
    const select = document.getElementById('camera-select');
    const stopBtn = document.getElementById('camera-stop-btn');
    const retryBtn = document.getElementById('camera-retry-btn');
    if (!toggle || !panel || !select || !stopBtn) return;

    toggle.addEventListener('click', () => panel.classList.toggle('hidden'));

    // Close the panel when tapping anywhere else on the page.
    document.addEventListener('click', e => {
        if (!toggle.contains(e.target) && !panel.contains(e.target)) {
            panel.classList.add('hidden');
        }
    });

    select.addEventListener('change', () => {
        if (!select.value) return;
        if (select.value === AUTO_CAMERA_VALUE) {
            // Back to the platform default lens. Nothing is persisted on
            // purpose: the stored device id is precisely what this steps away
            // from, and writing one would resurrect it on the next session.
            userPickedCamera = false;
            stopCamera().then(startWithFacingMode);
            return;
        }
        // An explicit choice overrides the iOS facing-mode default for the
        // rest of this session (startPreferred honours userPickedCamera).
        userPickedCamera = true;
        switchCamera(select.value);
    });

    stopBtn.addEventListener('click', () => {
        if (isRunning) {
            stopCamera();
        } else {
            // Full restart path: re-enumerates cameras, so it also recovers
            // when permission was granted after the initial refusal.
            startCamera();
        }
        panel.classList.add('hidden');
    });

    if (retryBtn) retryBtn.addEventListener('click', startCamera);
}

function populateCameraSelect() {
    const select = document.getElementById('camera-select');
    if (!select) return;
    select.innerHTML = '';
    // iOS only. The raw lens list is a trap here: picking any entry leaves the
    // facing-mode path for a device id, which is how pickers land back on the
    // ultra-wide that cannot focus on a close barcode — the exact failure the
    // facing-mode default removed. Without this entry there is also no way back
    // once a lens has been chosen. Other platforms are fine on device ids and
    // keep the plain list.
    if (isIOS()) {
        const auto = document.createElement('option');
        auto.value = AUTO_CAMERA_VALUE;
        auto.textContent = gettext("Automatic (recommended)");
        select.appendChild(auto);
    }
    cameras.forEach((camera, index) => {
        const option = document.createElement('option');
        option.value = camera.id;
        option.textContent = camera.label ||
            gettext("Camera %(number)s").replace("%(number)s", index + 1);
        select.appendChild(option);
    });
    // Reflect the mode actually in force; startWith() overwrites this with the
    // device id once a concrete lens is running.
    if (isIOS() && !userPickedCamera) select.value = AUTO_CAMERA_VALUE;
}

function syncStopButton() {
    const stopBtn = document.getElementById('camera-stop-btn');
    if (stopBtn) {
        stopBtn.textContent = isRunning ? gettext("Stop camera") : gettext("Start camera");
    }
}

// The template ships the retry button's default label already translated, so
// the original is captured once and reused rather than restated here. Passing
// null restores it — the relabel is per-error, not sticky.
let defaultRetryLabel = null;
function setRetryLabel(label) {
    const btn = document.getElementById('camera-retry-btn');
    if (!btn) return;
    if (defaultRetryLabel === null) defaultRetryLabel = btn.textContent;
    btn.textContent = label || defaultRetryLabel;
}

function showCameraError(message) {
    const box = document.getElementById('camera-error');
    const text = document.getElementById('camera-error-text');
    if (text) text.textContent = message;
    if (box) box.classList.remove('hidden');
}

function hideCameraError() {
    const box = document.getElementById('camera-error');
    if (box) box.classList.add('hidden');
    // Every start attempt begins here, so the button goes back to its default
    // promise before the next error decides whether to override it again.
    setRetryLabel(null);
}

export function pauseScanner() {
    if (scannerInstance && isRunning && !isPaused) {
        try {
            // pause(true) freezes the video feed
            scannerInstance.pause(true);
            isPaused = true;
            console.log("Scanner paused");
        } catch (e) {
            console.error("Error pausing scanner:", e);
        }
    }
}

export function resumeScanner() {
    if (scannerInstance && isRunning && isPaused) {
        try {
            scannerInstance.resume();
            isPaused = false;
            console.log("Scanner resumed");
        } catch (e) {
            console.error("Error resuming scanner:", e);
        }
    }
}
