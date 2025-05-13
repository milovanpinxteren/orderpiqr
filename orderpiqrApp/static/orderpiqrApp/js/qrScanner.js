// qrScanner.js

export function initializeScanner(onScanCallback) {
    const qrCodeScanner = new Html5QrcodeScanner("reader", {
        fps: 10,  // Frames per second
        qrbox: 250,  // Size of the scanning area
        readers: ["qr_code_reader", "ean_reader", "upc_reader", "code_128_reader"]
    });

    qrCodeScanner.render((scanResult) => {
        const scannedCode = scanResult;
        onScanCallback(scannedCode);
    });
}
