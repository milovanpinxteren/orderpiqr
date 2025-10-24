// orderpiqrApp/static/orderpiqr/js/tour/picklist.js
(function () {
    function getTour() {
        return (typeof introJs?.tour === "function") ? introJs.tour() : introJs();
    }

    function el(s) {
        return document.querySelector(s);
    }

    const _ = window.gettext || ((s) => s);

    const path = location.pathname;
    const onPicklistList = /\/admin\/orderpiqrApp\/picklist\/?$/.test(path);
    const onPicklistDetail = /\/admin\/orderpiqrApp\/picklist\/\d+\/change\/?$/.test(path) || !!el('form[action*="/orderpiqrApp/picklist/"][action$="/change/"]');
    const state = localStorage.getItem('opqr_tour');

    // -----------------------------
    // A) Pick Lists — CHANGELIST
    // -----------------------------
    if (onPicklistList && state === 'go_picklists' && localStorage.getItem('opqr_tour_dismissed') !== 'true') {
        document.addEventListener('DOMContentLoaded', function () {
            const tour = getTour();
            const steps = [];

            const thCode = el('th.column-picklist_code') || el('#changelist thead th:nth-child(1)');
            const thDevice = el('th.column-device') || el('#changelist thead th:nth-child(2)');
            const thPickTime = el('th.column-pick_time') || el('#changelist thead th:nth-child(3)');
            const thDuration = el('th.column-time_taken') || el('#changelist thead th:nth-child(4)');
            const thSuccess = el('th.column-successful') || el('#changelist thead th:nth-child(5)');
            const searchInput = el('#searchbar') || el('input[name="q"]');
            const firstRowLink = el('#result_list tbody tr:first-child th a');

            const devicesLink =
                el('#nav-sidebar .app-orderpiqrapp .model-device a') ||
                el('#nav-sidebar .model-device a') ||
                el('#content-main .model-device a') ||
                document.querySelector('a[href$="/orderpiqrApp/device/"]');

            steps.push({intro: _("These are your Pick Lists — the actual picking tasks. They can be generated from Orders, or auto-created when scanning a QR that doesn't exist yet.")});

            if (thCode) steps.push({
                element: thCode,
                position: "bottom",
                intro: _("Picklist code — unique ID used in the app/QRs.")
            });
            if (thDevice) steps.push({
                element: thDevice,
                position: "bottom",
                intro: _("Device — who/what performed the picking (helps with accountability).")
            });
            if (thPickTime) steps.push({
                element: thPickTime,
                position: "bottom",
                intro: _("Pick time — when the pick started.")
            });
            if (thDuration) steps.push({
                element: thDuration,
                position: "bottom",
                intro: _("Time taken — how long the pick took (performance metric).")
            });
            if (thSuccess) steps.push({
                element: thSuccess,
                position: "bottom",
                intro: _("Successful — overall result. Issues are investigated on the detail page.")
            });
            if (searchInput) steps.push({
                element: searchInput,
                position: "bottom",
                intro: _("Search by device name or pick time to find a list quickly.")
            });

            if (firstRowLink) {
                steps.push({
                    element: firstRowLink, position: "right",
                    intro: _("Open a picklist to review item-level results: which products were picked, timing, and which items were not picked.")
                });
            }

            if (devicesLink) {
                steps.push({
                    element: devicesLink, position: "left",
                    intro: _("Next: <b>Devices</b> — manage which devices can scan and see who picked what.")
                });
            } else {
                steps.push({intro: _("Next: open <b>Devices</b> to manage scanners and see who picked what.")});
            }

            tour.setOptions({steps, showProgress: true, exitOnOverlayClick: false, doneLabel: _("Close")});

            // Persist state when user clicks a picklist row or Devices
            document.addEventListener('click', function (e) {
                const a = e.target.closest('a[href*="/orderpiqrApp/picklist/"], a[href$="/orderpiqrApp/device/"]');
                if (!a) return;
                const href = a.getAttribute('href') || '';
                if (/\/orderpiqrApp\/picklist\/\d+\/change\/?/.test(href)) {
                    localStorage.setItem('opqr_tour', 'on_picklist_detail');
                } else if (href.endsWith('/orderpiqrApp/device/') || a.href?.endsWith('/orderpiqrApp/device/')) {
                    localStorage.setItem('opqr_tour', 'go_devices');
                }
            }, true);

            // Add explicit buttons on the last step
            tour.onafterchange(function () {
                const idx = (typeof tour.currentStep === 'function') ? tour.currentStep() : (tour._currentStep || 0);
                const isLast = idx === steps.length - 1;
                if (!isLast) return;

                const btns = document.querySelector('.introjs-tooltipbuttons');
                if (!btns) return;

                if (devicesLink && !btns.querySelector('.opqr-go-devices')) {
                    const goDevices = document.createElement('button');
                    goDevices.className = 'opqr-go-devices introjs-button';
                    goDevices.textContent = _('Go to Devices');
                    goDevices.onclick = function () {
                        localStorage.setItem('opqr_tour', 'go_devices');
                        window.location.href = '/admin/orderpiqrApp/device/';
                    };
                    btns.appendChild(goDevices);
                }

                if (firstRowLink && !btns.querySelector('.opqr-open-first-picklist')) {
                    const openFirst = document.createElement('button');
                    openFirst.className = 'opqr-open-first-picklist introjs-button';
                    openFirst.textContent = _('Open first picklist');
                    openFirst.onclick = function () {
                        localStorage.setItem('opqr_tour', 'on_picklist_detail');
                        window.location.href = firstRowLink.href;
                    };
                    btns.appendChild(openFirst);
                }
            });

            tour.start();
        });
        return;
    }

    // -----------------------------
    // B) Pick List — DETAIL (change form)
    // -----------------------------
    if (onPicklistDetail && state === 'on_picklist_detail' && localStorage.getItem('opqr_tour_dismissed') !== 'true') {
        document.addEventListener('DOMContentLoaded', function () {
            const tour = getTour();
            const steps = [];

            const inlineWrapper = el('#picklist_set-group, .inline-group') || el('.inline-group');
            const thProd = el('.inline-group table thead th .column-product') ? el('.inline-group table thead th .column-product').closest('th')
                : el('.inline-group table thead th:nth-child(1)');
            const thQty = el('.inline-group table thead th .column-quantity') ? el('.inline-group table thead th .column-quantity').closest('th')
                : el('.inline-group table thead th:nth-child(2)');
            const thItemTime = el('.inline-group table thead th .column-time_taken') ? el('.inline-group table thead th .column-time_taken').closest('th')
                : el('.inline-group table thead th:nth-child(3)');
            const thItemOK = el('.inline-group table thead th .column-successful') ? el('.inline-group table thead th .column-successful').closest('th')
                : el('.inline-group table thead th:nth-child(4)');

            const fieldPickTime = el('#id_pick_time')?.closest('.form-row') || el('.form-row.field-pick_time');
            const fieldDuration = el('#id_time_taken')?.closest('.form-row') || el('.form-row.field-time_taken');
            const fieldSuccess = el('#id_successful')?.closest('.form-row') || el('.form-row.field-successful');

            steps.push({intro: _("This picklist shows item-level results. Use it to review issues and performance.")});

            if (fieldPickTime) steps.push({
                element: fieldPickTime,
                position: "bottom",
                intro: _("Pick time — when the pick started.")
            });
            if (fieldDuration) steps.push({
                element: fieldDuration,
                position: "bottom",
                intro: _("Total time taken — duration of this picklist.")
            });
            if (fieldSuccess) steps.push({
                element: fieldSuccess,
                position: "bottom",
                intro: _("Overall success — quick status at a glance.")
            });

            if (inlineWrapper) steps.push({
                element: inlineWrapper,
                position: "top",
                intro: _("Item-level results (Product Picks). Each row shows what happened per product.")
            });

            if (thProd) steps.push({
                element: thProd,
                position: "bottom",
                intro: _("Product — what was supposed to be picked.")
            });
            if (thQty) steps.push({
                element: thQty,
                position: "bottom",
                intro: _("Quantity — units picked for this product.")
            });
            if (thItemTime) steps.push({
                element: thItemTime,
                position: "bottom",
                intro: _("Time taken — how long this item took to pick.")
            });
            if (thItemOK) steps.push({
                element: thItemOK,
                position: "bottom",
                intro: _("Successful — if not checked, this item was not picked successfully.")
            });

            steps.push({intro: _("Tip: items not picked (unsuccessful) help you spot shortages or scanning mistakes.")});

            tour.setOptions({steps, showProgress: true, exitOnOverlayClick: false, doneLabel: _("Close")});

            let finishedNormally = false;

            tour.oncomplete(() => {
                finishedNormally = true;               // finished this section normally
                localStorage.setItem('opqr_tour_dismissed', 'false');
            });

            tour.onexit(() => {
                if (!finishedNormally) {
                    localStorage.setItem('opqr_tour_dismissed', 'true'); // user clicked ✕
                }
            });


            tour.start();
        });
        return;
    }

    // Otherwise: do nothing
})();
