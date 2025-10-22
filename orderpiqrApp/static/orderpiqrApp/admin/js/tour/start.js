// orderpiqrApp/static/orderpiqr/js/tour/start.js
(function () {
  // v7/v8 safe
  function getTour() {
    return (typeof introJs?.tour === "function") ? introJs.tour() : introJs();
  }
  function $(sel) { return document.querySelector(sel); }

  // Expose the same global the button calls
  window.startAdminTour = function () {
    // reset / start fresh
    localStorage.removeItem("opqr_tour");

    const _ = window.gettext || ((s) => s);
    const productsLink =
      $('#nav-sidebar .app-orderpiqrapp .model-product a') ||
      $('#content-main .model-product a') ||
      document.querySelector('a[href$="/orderpiqrApp/product/"]');

    const ordersLink =
      $('#nav-sidebar .app-orderpiqrapp .model-order a') ||
      $('#content-main .model-order a') ||
      document.querySelector('a[href$="/orderpiqrApp/order/"]');

    const picklistsLink =
      $('#nav-sidebar .app-orderpiqrapp .model-picklist a') ||
      $('#content-main .model-picklist a') ||
      document.querySelector('a[href$="/orderpiqrApp/picklist/"]');

    const devicesLink =
      $('#nav-sidebar .app-orderpiqrapp .model-device a') ||
      $('#content-main .model-device a') ||
      document.querySelector('a[href$="/orderpiqrApp/device/"]');

    const steps = [
      { intro: _("👋 Quick tour of the essentials. If you prefer talking to an employee, you can schedule a meeting or contact us at www.orderpiqr.nl") },
      productsLink
        ? { element: productsLink, position: "left",
            intro: _("Products — Create items to pick with (bar)code, name/description and physical location.") }
        : { intro: _("Products — Create items to pick with (bar)code, name/description and physical location.") },
      ordersLink
        ? { element: ordersLink, position: "left",
            intro: _("Orders — Create orders manually or via API/import. (Scanning a Picklist QR can also create a picklist on the fly.)") }
        : { intro: _("Orders — Create orders manually or via API/import. (Scanning a Picklist QR can also create a picklist on the fly.)") },
      picklistsLink
        ? { element: picklistsLink, position: "left",
            intro: _("Pick Lists — The actual picking tasks. Generate from Orders, or have them created automatically when a QR is scanned.") }
        : { intro: _("Pick Lists — The actual picking tasks. Generate from Orders, or have them created automatically when a QR is scanned.") },
      devicesLink
        ? { element: devicesLink, position: "left",
            intro: _("Devices — See who picked what and control access.") }
        : { intro: _("Devices — See who picked what and control access.") },
      productsLink
        ? { element: productsLink, position: "left", intro: _("Ready? Click <b>Products</b> to begin.") }
        : { intro: _("Open <b>Products</b> to begin.") },
    ];

    const tour = getTour();
    tour.setOptions({ steps, showProgress: true, exitOnOverlayClick: false });

    // Persist if they navigate to Products
    document.addEventListener("click", function (e) {
      const a = e.target.closest('a[href$="/orderpiqrApp/product/"]');
      if (a) localStorage.setItem("opqr_tour", "on_products");
    }, true);

    // Add explicit “Go to Products” button in the tooltip
    tour.onafterchange(function () {
      if (!productsLink) return;
      const btns = document.querySelector(".introjs-tooltipbuttons");
      if (!btns || btns.querySelector(".opqr-go-products")) return;

      const btn = document.createElement("button");
      btn.className = "opqr-go-products introjs-button";
      btn.textContent = _("Go to Products");
      btn.onclick = () => {
        localStorage.setItem("opqr_tour", "on_products");
        window.location.href = productsLink.href;
      };
      btns.appendChild(btn);
    });

    tour.start();
  };
})();
