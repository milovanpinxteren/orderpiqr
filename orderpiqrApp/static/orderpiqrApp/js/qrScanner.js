// qrScanner.js

export function initializeScanner(onScanCallback) {
    const width = window.innerWidth;
    const qrBoxSize = Math.min(width * 0.65, 350); // max 300px, but responsive
    const qrCodeScanner = new Html5QrcodeScanner("reader", {
        fps: 5,  // Frames per second
        qrbox: { width: qrBoxSize, height: qrBoxSize },
        aspectRatio: 1.0,
        readers: ["qr_code_reader", "ean_reader", "upc_reader", "code_128_reader"]
    });

    qrCodeScanner.render((scanResult) => {
        const scannedCode = scanResult;
        onScanCallback(scannedCode);
    });
}
