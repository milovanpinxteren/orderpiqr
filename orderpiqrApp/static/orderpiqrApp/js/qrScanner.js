// qrScanner.js
//
// Wrapper around the html5-qrcode core API (Html5Qrcode). The library's
// bundled Html5QrcodeScanner UI stacks a camera dropdown and start/stop
// buttons under the video, eating most of the screen — here the camera
// starts on its own and those controls live in a panel behind the small
// options button overlaid on the camera card (see index.html).

const gettext = window.gettext;

const LAST_CAMERA_KEY = 'orderpiqr_last_camera_id';
// No qrbox/formatsToSupport: the full frame is scanned and every format the
// library knows is accepted, matching the old Html5QrcodeScanner behavior.
const SCAN_CONFIG = {fps: 5, aspectRatio: 1.0};

let scannerInstance = null;
let cameras = [];
let onScan = null;
let isRunning = false;
let isPaused = false;

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
                showCameraError(gettext("No camera found on this device."));
                return;
            }
            populateCameraSelect();
            startWith(pickDefaultCamera());
        })
        .catch(err => {
            console.error('Camera permission/enumeration failed:', err);
            showCameraError(gettext("Camera access was denied. Allow camera access for this site in your browser settings, then tap the button below."));
        });
}

function pickDefaultCamera() {
    const saved = localStorage.getItem(LAST_CAMERA_KEY);
    if (saved && cameras.some(c => c.id === saved)) {
        return saved;
    }
    // Prefer a back-facing camera by label; phones usually list the front
    // camera first, so the last one is the better blind guess.
    const back = cameras.find(c => /back|rear|environment|achter/i.test(c.label || ''));
    return back ? back.id : cameras[cameras.length - 1].id;
}

function startWith(cameraId) {
    hideCameraError();
    scannerInstance.start(
        cameraId,
        SCAN_CONFIG,
        decodedText => onScan(decodedText),
        () => { /* per-frame decode misses are expected noise */ }
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
        if (select.value) switchCamera(select.value);
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
    cameras.forEach((camera, index) => {
        const option = document.createElement('option');
        option.value = camera.id;
        option.textContent = camera.label ||
            gettext("Camera %(number)s").replace("%(number)s", index + 1);
        select.appendChild(option);
    });
}

function syncStopButton() {
    const stopBtn = document.getElementById('camera-stop-btn');
    if (stopBtn) {
        stopBtn.textContent = isRunning ? gettext("Stop camera") : gettext("Start camera");
    }
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
