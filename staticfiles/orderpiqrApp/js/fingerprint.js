// fingerprint.js
export function getDeviceFingerprint() {
    return new Promise((resolve, reject) => {
        FingerprintJS.load().then(fingerprintJS => {
            fingerprintJS.get().then(result => {
                const deviceFingerprint = result.visitorId;
                resolve(deviceFingerprint);
            }).catch(reject);
        }).catch(reject);
    });
}
