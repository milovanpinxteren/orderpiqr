// fingerprint.js
const STORAGE_KEY = 'orderpiqr_device_id';

function generateUUID() {
    // Use crypto.randomUUID if available, otherwise fallback
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
        return crypto.randomUUID();
    }
    // Fallback for older browsers
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

export function getDeviceFingerprint() {
    return new Promise((resolve) => {
        let deviceId = localStorage.getItem(STORAGE_KEY);
        if (!deviceId) {
            deviceId = generateUUID();
            localStorage.setItem(STORAGE_KEY, deviceId);
        }
        resolve(deviceId);
    });
}
