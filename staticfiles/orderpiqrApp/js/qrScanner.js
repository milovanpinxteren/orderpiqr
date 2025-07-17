// qrScanner.js

export function initializeScanner(onScanCallback) {
    const width = window.innerWidth;
    // console.log('WIDHT',width);
    // const qrBoxSize = Math.min(width * 0.6, 350);
    const qrBoxSize = Math.floor(width * 0.6);  // 80% of width, up to max

    const qrCodeScanner = new Html5QrcodeScanner("reader", {
        fps: 5,  // Frames per second
        // qrbox: { width: qrBoxSize, height: qrBoxSize },
        // aspectRatio: 1.333334,
        aspectRatio: 1.0,
        readers: ["qr_code_reader", "ean_reader", "upc_reader", "code_128_reader", "data_matrix_reader"]
    });

    qrCodeScanner.render((scanResult) => {
        const scannedCode = scanResult;
        onScanCallback(scannedCode);
    });
}

