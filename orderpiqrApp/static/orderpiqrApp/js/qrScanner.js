// qrScanner.js

let scannerInstance = null;

export function initializeScanner(onScanCallback) {
    const width = window.innerWidth;
    const qrBoxSize = Math.floor(width * 0.6);

    const qrCodeScanner = new Html5QrcodeScanner("reader", {
        fps: 5,
        aspectRatio: 1.0,
        readers: ["qr_code_reader", "ean_reader", "upc_reader", "code_128_reader", "data_matrix_reader"]
    });

    // Store instance at module level
    scannerInstance = qrCodeScanner;

    qrCodeScanner.render((scanResult) => {
        const scannedCode = scanResult;
        onScanCallback(scannedCode);
    });
}

export function pauseScanner() {
    if (scannerInstance) {
        try {
            // pause(true) freezes the video feed
            scannerInstance.pause(true);
            console.log("Scanner paused");
        } catch (e) {
            console.error("Error pausing scanner:", e);
        }
    }
}

export function resumeScanner() {
    if (scannerInstance) {
        try {
            scannerInstance.resume();
            console.log("Scanner resumed");
        } catch (e) {
            console.error("Error resuming scanner:", e);
        }
    }
}