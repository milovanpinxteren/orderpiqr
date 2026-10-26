// shortReasons.js
//
// The five reasons a picker can give for a line they could not fill, as one
// leaf module: the slugs are the server's ProductPick.ShortReason values
// (orderpiqrApp/models/picklists.py) and the labels are the single source of
// truth for both the reason buttons on the short-pick overlay and the short
// rows in the picklist table. Keeping them here — rather than as {% trans %}
// in the template for the buttons and a second set of strings for the rows —
// is what stops the two from drifting apart in a locale.
//
// Import-only: nothing in templates/index.html references it by URL, so it
// must be pre-cached by templates/serviceWorker.js explicitly (same category
// as fingerprint.js and pickOutbox.js).
const gettext = window.gettext;

// Order matters: this is the order the buttons appear in, most common first.
export const SHORT_REASON_SLUGS = [
    'not_found',
    'insufficient_stock',
    'damaged',
    'wrong_product',
    'other',
];

// A slug the client does not know (an older build's catalog, or a row the
// server normalised) still has to render as something — the server does the
// same thing with an unrecognised shortReason.
export function shortReasonLabel(slug) {
    switch (slug) {
        case 'not_found':
            return gettext("Not at location");
        case 'insufficient_stock':
            return gettext("Not enough stock");
        case 'damaged':
            return gettext("Damaged");
        case 'wrong_product':
            return gettext("Wrong product in the spot");
        default:
            return gettext("Other");
    }
}
