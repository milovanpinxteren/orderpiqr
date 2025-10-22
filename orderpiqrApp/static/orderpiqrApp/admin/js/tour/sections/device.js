(function () {
    function getTour() {
        return (typeof introJs?.tour === "function") ? introJs.tour() : introJs();
    }

    function el(s) {
        return document.querySelector(s);
    }

    // Only run when arriving from Pick Lists → Devices
    if (localStorage.getItem('opqr_tour') !== 'go_devices') return;

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

    steps.push({intro: gettext("Devices control who can scan and pick. Use this page to manage access and track activity.")});

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
            intro: gettext("Open a device to view or update its details.")
        });
    }

    // Final: conclude the tour
    steps.push({intro: gettext("All set! You’ve completed the tour. You can now manage devices, picklists, orders, and products confidently.")});

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
            localStorage.removeItem('opqr_tour');
        } catch (e) {
        }
    }

    tour.oncomplete(endTour);
    tour.onexit(endTour);

    tour.start();
})();