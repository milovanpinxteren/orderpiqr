(function () {
    function getTour() {
        return (typeof introJs?.tour === "function") ? introJs.tour() : introJs();
    }

    function el(sel) {
        return document.querySelector(sel);
    }

    // Only run when arriving from Products → Orders
    if (
        localStorage.getItem('opqr_tour') !== 'go_orders' ||
        localStorage.getItem('opqr_tour_dismissed') === 'true'
    ) return;

    const tour = getTour();
    const steps = [];

    // Common Django admin selectors
    const thOrderCode = el('th.column-order_code') || el('#changelist thead th:nth-child(1)');
    const thCustomer = el('th.column-customer') || el('#changelist thead th:nth-child(2)');
    const thCreated = el('th.column-created_at') || el('#changelist thead th:nth-child(3)');
    const addBtn = el('.object-tools a.addlink');
    const searchInput = el('#searchbar') || el('input[name="q"]');
    const filterBox = el('#changelist-filter');
    const uploadInput = el('input[name="upload_file"]');
    const uploadForm = uploadInput ? uploadInput.closest('form') : null;

    // Bulk action bits (for generating picklists / PDFs)
    const actionSelect = el('select[name="action"]');
    const actionApply = el('button[name="index"]') || el('#changelist-form button[type="submit"]');
    // Try to detect a specific "Generate Picklists" action if you add one later
    const picklistActionOpt = actionSelect && Array.from(actionSelect.options)
        .find(o => /pick\s*list|picklist|generate.*pick/i.test((o.textContent || '') + ' ' + (o.value || '')));
    // Fallback: your current action that generates a batch QR PDF
    const qrActionOpt = actionSelect && Array.from(actionSelect.options)
        .find(o => /qr|pdf/i.test((o.textContent || '') + ' ' + (o.value || '')));

    // Find Pick Lists link anywhere (sidebar or main panel)
    const picklistsLink =
        el('#nav-sidebar .app-orderpiqrapp .model-picklist a') ||
        el('#nav-sidebar .model-picklist a') ||
        el('#content-main .model-picklist a') ||
        document.querySelector('a[href$="/orderpiqrApp/picklist/"]');

    // --- Steps ---
    steps.push({intro: gettext("This is your Orders page. Create or import orders, then generate picklists.")});

    if (thOrderCode) steps.push({
        element: thOrderCode, position: "bottom",
        intro: gettext("Order code — your primary identifier used across imports and PDFs.")
    });
    if (thCustomer) steps.push({
        element: thCustomer, position: "bottom",
        intro: gettext("Customer — company admins are scoped to their own customer automatically.")
    });
    if (thCreated) steps.push({
        element: thCreated, position: "bottom",
        intro: gettext("Created at — when the order was added.")
    });

    if (addBtn) steps.push({
        element: addBtn, position: "left",
        intro: gettext("Add a single order here. On the order page you can add lines.")
    });

    if (uploadForm) {
        steps.push({
            element: uploadForm, position: "left",
            intro: gettext("Bulk import orders via CSV/XLSX. Required headers: <code>order_code</code>, <code>product_code</code>, <code>quantity</code>. Unknown product codes are rejected. Existing orders with the same code are overwritten (their lines are replaced).")
        });
    }

    if (searchInput) steps.push({
        element: searchInput, position: "bottom",
        intro: gettext("Search by order code (and other fields) to find orders quickly.")
    });
    if (filterBox) steps.push({
        element: filterBox, position: "right",
        intro: gettext("Use filters (e.g., by date) to narrow the list.")
    });

    // Generate picklists step (prefer a dedicated action if present)
    if (actionSelect) {
        steps.push({
            element: actionSelect, position: "bottom",
            intro: picklistActionOpt
                ? gettext('Select one or more orders, then choose “%(label)s”.')
                    .replace("%(label)s", picklistActionOpt.textContent.trim())
                : qrActionOpt
                    ? gettext('Select one or more orders, then choose “%(label)s” to generate a batch of QR PDFs.')
                        .replace("%(label)s", qrActionOpt.textContent.trim())
                    : gettext("Select one or more orders, then choose your action to generate picklists or QR PDFs.")
        });
        if (actionApply) {
            steps.push({
                element: actionApply, position: "left",
                intro: gettext("Click Apply to run the action.")
            });
        }
    }

    // Final: highlight the Pick Lists link and invite navigation
    if (picklistsLink) {
        steps.push({
            element: picklistsLink, position: "left",
            intro: gettext("After generating, view results in <b>Pick Lists</b>: see who picked, duration, success, and items not picked.")
        });
    } else {
        steps.push({
            intro: gettext("Next, open <b>Pick Lists</b> to review and print PDFs with QR codes.")
        });
    }

    tour.setOptions({
        steps,
        showProgress: true,
        exitOnOverlayClick: false,
        doneLabel: gettext("Close")
    });

    // Persist state if user manually clicks Pick Lists
    document.addEventListener('click', function (e) {
        const a = e.target.closest('a[href$="/orderpiqrApp/picklist/"]');
        if (a) localStorage.setItem('opqr_tour', 'go_picklists');
    }, true);

    // Add explicit "Go to Pick Lists" button on the last step (no auto-redirect)
    tour.onafterchange(function () {
        const isLast = (typeof tour.currentStep === 'function')
            ? tour.currentStep() === steps.length - 1
            : (tour._currentStep || 0) === steps.length - 1;
        if (!isLast) return;

        const btns = document.querySelector('.introjs-tooltipbuttons');
        if (!btns || btns.querySelector('.opqr-go-picklists')) return;

        const goPicklists = document.createElement('button');
        goPicklists.className = 'opqr-go-picklists introjs-button';
        goPicklists.textContent = gettext('Go to Pick Lists');
        goPicklists.onclick = function () {
            localStorage.setItem('opqr_tour', 'go_picklists');
            window.location.href = '/admin/orderpiqrApp/picklist/';
        };
        btns.appendChild(goPicklists);
    });

    // Do not auto-redirect on complete/exit
    tour.onexit(function () {
        localStorage.setItem("opqr_tour_dismissed", "true");
    });

    tour.start();
})();