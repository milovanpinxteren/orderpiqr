(function () {
    function getTour() {
        return (typeof introJs?.tour === "function") ? introJs.tour() : introJs();
    }

    function el(sel) {
        return document.querySelector(sel);
    }

    // Only run when arriving from the homepage step
    if (
        localStorage.getItem('opqr_tour') !== 'on_products' ||
        localStorage.getItem('opqr_tour_dismissed') === 'true'
    ) return;

    const tour = getTour();
    const steps = [];

    // Likely selectors in Django admin
    const thCode = el('th.column-code') || el('#changelist thead th:nth-child(1)');
    const thDesc = el('th.column-description') || el('#changelist thead th:nth-child(2)');
    const thLocation = el('th.column-location') || el('#changelist thead th:nth-child(3)');
    const thCustomer = el('th.column-customer') || el('#changelist thead th:nth-child(4)');
    const addBtn = el('.object-tools a.addlink');
    const uploadInput = el('input[name="upload_file"]');
    const uploadForm = uploadInput ? uploadInput.closest('form') : null;
    const searchInput = el('#searchbar') || el('input[name="q"]');
    const firstRowLink = el('#result_list tbody tr:first-child th a');
    const ordersLink = document.querySelector('#nav-sidebar .app-orderpiqrapp .model-order a')
        || document.querySelector('#content-main .model-order a')
        || document.querySelector('a[href$="/orderpiqrApp/order/"]');

    steps.push({intro: gettext("This is your product catalog. Let's set it up.")});

    if (thCode) steps.push({
        element: thCode, position: "bottom",
        intro: gettext("Code (SKU). Unique scannable code which is on the product. If no code exists, you can create one. Used for scanning/imports.")
    });
    if (thDesc) steps.push({
        element: thDesc, position: "bottom",
        intro: gettext("Description. Human-readable item name for pickers.")
    });
    if (thLocation) steps.push({
        element: thLocation, position: "bottom",
        intro: gettext("Location. Bin/shelf—helps optimize walking route.")
    });
    if (thCustomer) steps.push({
        element: thCustomer, position: "bottom",
        intro: gettext("Customer. Auto-filled for company admins")
    });

    if (addBtn) steps.push({element: addBtn, position: "left", intro: gettext("Add a single product here.")});

    // Import step (CSV/XLSX)
    if (uploadForm) {
        steps.push({
            element: uploadForm, position: "left",
            intro: gettext("Bulk import via CSV/XLSX. Required headers: <code>code</code>, <code>description</code>, <code>location</code>. Existing products with the same code are updated; new ones are added.")
        });
    } else {
        steps.push({intro: gettext("You can also enable a CSV/XLSX upload on this page. When present, it adds or overwrites by product code for the current customer.")});
    }

    if (searchInput) steps.push({
        element: searchInput, position: "bottom",
        intro: gettext("Search by code or description to find items quickly.")
    });
    if (firstRowLink) steps.push({
        element: firstRowLink, position: "right",
        intro: gettext("Click a row to edit a product. Duplicates are prevented per customer.")
    });

    // Final: prompt to proceed (no auto-redirect)
    if (ordersLink) {
        steps.push({
            element: ordersLink,
            position: "left",
            intro: gettext("All set here. Continue to <b>Orders</b> to generate an order. Make sure you have created/imported products before you do.")
        });
    } else {
        steps.push({
            intro: gettext("All set here. Continue to <b>Orders</b> to generate an order. Make sure you have created/imported products before you do.")
        });
    }
    tour.setOptions({
        steps,
        showProgress: true,
        exitOnOverlayClick: false,
        doneLabel: gettext("Close")
    });

    // If they click an Orders or Pick Lists link manually, keep the tour state
    document.addEventListener('click', function (e) {
        const a = e.target.closest('a[href$="/orderpiqrApp/order/"], a[href$="/orderpiqrApp/picklist/"]');
        if (!a) return;
        if (a.href.endsWith('/orderpiqrApp/order/')) {
            localStorage.setItem('opqr_tour', 'go_orders');
        } else if (a.href.endsWith('/orderpiqrApp/picklist/')) {
            localStorage.setItem('opqr_tour', 'go_picklists');
        }
    }, true);

    tour.onafterchange(function () {
        // Only inject on the final step
        const isLast = (typeof tour.currentStep === 'function')
            ? tour.currentStep() === steps.length - 1
            : (tour._currentStep || 0) === steps.length - 1;

        if (!isLast) return;

        const btns = document.querySelector('.introjs-tooltipbuttons');
        if (!btns || btns.querySelector('.opqr-next-orders')) return;

        const toOrders = document.createElement('button');
        toOrders.className = 'opqr-next-orders introjs-button';
        toOrders.textContent = gettext('Go to Orders');
        toOrders.onclick = function () {
            localStorage.setItem('opqr_tour', 'go_orders');
            window.location.href = '/admin/orderpiqrApp/order/';
        };

        const toPicklists = document.createElement('button');
        toPicklists.className = 'opqr-next-picklists introjs-button';
        toPicklists.textContent = gettext('Skip to Pick Lists');
        toPicklists.onclick = function () {
            localStorage.setItem('opqr_tour', 'go_picklists');
            window.location.href = '/admin/orderpiqrApp/picklist/';
        };

        btns.appendChild(toOrders);
        btns.appendChild(toPicklists);

        // Optional: hide the default "Done" button to encourage choosing a path
        const doneBtn = btns.querySelector('.introjs-donebutton');
        if (doneBtn) doneBtn.style.display = 'none';
    });

    // No auto-redirect on complete/exit
    tour.oncomplete(function () { /* intentionally empty */
    });
    tour.onexit(function () {
        localStorage.setItem("opqr_tour_dismissed", "true");
    });

    tour.start();
})();