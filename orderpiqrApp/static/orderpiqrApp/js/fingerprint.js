// fingerprint.js
//
// The device identity. Losing it is not cosmetic: the server scopes a
// picklist lock to (fingerprint, customer), so a phone that comes back with a
// new id is treated as "another device" and refused its own list — the picker
// experiences that as being kicked out with no way back in.
//
// It used to live in localStorage alone, which iOS Safari evicts after 7 days
// of no interaction for sites that are not installed to the home screen. So it
// is now read from three places, in order of durability:
//
//   1. localStorage          — fast, but script-writable and therefore capped
//   2. a server-set cookie   — set via Set-Cookie by Django, which is NOT
//                              subject to the script-writable storage cap, so
//                              it is the one most likely to survive
//   3. a freshly generated   — last resort; this is the case that used to
//      UUID                    silently create a duplicate device row
//
// Whatever is found is mirrored back into localStorage, and the server
// re-pins its cookie on every page load (see utils/devices.pin_device_cookie).
const STORAGE_KEY = 'orderpiqr_device_id';
const COOKIE_KEY = 'orderpiqr_device_id';
// Mirrored from the server cookie's age; a client-set cookie is capped far
// shorter than this by Safari, which is exactly why the server sets it too.
const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 730;

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

function readLocalStorage() {
    try {
        return localStorage.getItem(STORAGE_KEY) || '';
    } catch (e) {
        return '';   // storage access can throw outright in private modes
    }
}

function writeLocalStorage(value) {
    try {
        localStorage.setItem(STORAGE_KEY, value);
    } catch (e) {
        // Full or unavailable: the cookie is still carrying the identity.
    }
}

function readCookie() {
    try {
        const match = document.cookie.match(
            new RegExp('(?:^|; )' + COOKIE_KEY + '=([^;]*)'));
        return match ? decodeURIComponent(match[1]) : '';
    } catch (e) {
        return '';
    }
}

function writeCookie(value) {
    try {
        const secure = location.protocol === 'https:' ? '; Secure' : '';
        document.cookie = COOKIE_KEY + '=' + encodeURIComponent(value)
            + '; Path=/; Max-Age=' + COOKIE_MAX_AGE_SECONDS
            + '; SameSite=Lax' + secure;
    } catch (e) {
        // Nothing further to try.
    }
}

export function getDeviceFingerprint() {
    return new Promise((resolve) => {
        let deviceId = readLocalStorage();

        if (!deviceId) {
            // localStorage was wiped (or never had it). Recovering from the
            // cookie here is what keeps the picker the same device.
            deviceId = readCookie();
        }

        if (!deviceId) {
            deviceId = generateUUID();
        }

        // Mirror into both, always: whichever store was emptied gets refilled.
        writeLocalStorage(deviceId);
        writeCookie(deviceId);
        resolve(deviceId);
    });
}
