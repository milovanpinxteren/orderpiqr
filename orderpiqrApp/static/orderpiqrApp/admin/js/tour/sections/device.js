(function () {
    function getTour() {
        return (typeof introJs?.tour === "function") ? introJs.tour() : introJs();
    }

    function el(s) {
        return document.querySelector(s);
    }

    // Only run when arriving from Pick Lists → Devices
    if (
        localStorage.getItem('opqr_tour') !== 'go_devices' ||
        localStorage.getItem('opqr_tour_dismissed') === 'true'
    ) return;


    const tour = getTour();
    const steps = [];

    // Columns from list_display
    const thName = el('th.column-name') || el('#changelist thead th:nth-child(1)');
    const thDesc = el('th.column-description') || el('#changelist thead th:nth-child(2)');
    const thLastLogin = el('th.column-last_login') || el('#changelist thead th:nth-child(3)');
    const thListsPicked = el('th.column-lists_picked') || el('#changelist thead th:nth-child(4)');
    const thCustomer = el('th.column-customer') || el('#changelist thead th:nth-child(5)');

    const addBtn = el('.object-tools a.addlink');
    const searchInput = el('#searchbar') || el('input[name="q"]');
    const firstRowLink = el('#result_list tbody tr:first-child th a');

    steps.push({intro: gettext("Devices show who scanned and picked. Use this page to track activity.")});

    if (thName) steps.push({
        element: thName,
        position: "bottom",
        intro: gettext("Name — device or scanner name shown to admins.")
    });
    if (thDesc) steps.push({
        element: thDesc,
        position: "bottom",
        intro: gettext("Description — optional notes about the device or location.")
    });
    if (thLastLogin) steps.push({
        element: thLastLogin,
        position: "bottom",
        intro: gettext("Last login — when this device last authenticated/was used.")
    });
    if (thListsPicked) steps.push({
        element: thListsPicked,
        position: "bottom",
        intro: gettext("Lists picked — how many picklists this device/user completed.")
    });
    if (thCustomer) steps.push({
        element: thCustomer,
        position: "bottom",
        intro: gettext("Customer — company admins only see their own devices.")
    });

    if (addBtn) steps.push({
        element: addBtn,
        position: "left",
        intro: gettext("Add a new device here when granting scanning access.")
    });
    if (searchInput) steps.push({
        element: searchInput,
        position: "bottom",
        intro: gettext("Search devices by name or description.")
    });

    if (firstRowLink) {
        steps.push({
            element: firstRowLink, position: "right",
            intro: gettext("Open a device to view its details.")
        });
    }

    // Final: conclude the tour
    steps.push({
        intro: gettext(
            "<h1>🎉 All set! You’ve completed the Orderpiqr tour.</h1><br>\
        Next steps:<br>\
        • <b>Add your products</b> in the admin panel.<br>\
        • <b>Create an order</b> and <b>generate a PDF picklist</b> for your team.<br>\
        • On your phone, visit <a href='https://app.orderpiqr.nl' target='_blank'>app.orderpiqr.nl</a> \
        and log in with your order picker account.<br>\
        • <b>Scan the QR code</b> on your newly created picklist.<br>\
        • Start picking your first order!<br><br>\
        \
        <h2>Important information</h2>\
        We recommend using <b>Google Chrome</b> for full functionality — you can also \
        <b>install the web app</b> directly from your browser for quick access.<br><br>\
        On your phone, you can adjust settings such as <b>language</b>, <b>picking order</b>, \
        and <b>sorting order</b>. If you’d like us to set up default preferences for you, just let us know.<br><br>\
        If you have any questions or would like additional features, email \
        <a href='mailto:info@orderpiqr.nl'>info@orderpiqr.nl</a> or schedule a call via \
        <a href='https://www.orderpiqr.nl' target='_blank'>www.orderpiqr.nl</a>.<br><br>\
        Your first <b>50 picklists per month are free</b>! After that, you’ll receive a notification \
        before any billing begins — no subscriptions, no hidden costs."
        ),
        tooltipClass: "tour-final-step"
    });

    tour.setOptions({
        steps,
        showProgress: true,
        exitOnOverlayClick: false,
        doneLabel: gettext("Finish")
    });

    // Conclude: clear state on finish/exit
    function endTour() {
        // Clear only our state key; keep anything else in localStorage intact
        try {
            localStorage.setItem('opqr_tour_dismissed', 'true');
            localStorage.removeItem('opqr_tour');
        } catch (e) {
        }
    }

    tour.oncomplete(endTour);
    tour.onexit(endTour);

    tour.start();
})();