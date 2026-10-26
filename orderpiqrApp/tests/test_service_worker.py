"""The service worker that gives the scan page an offline app shell.

Rendered rather than served as a static file: the whole point is that its
cache name carries the current build id, so a deploy can force every open
phone off its old pre-cache (see orderpiqrApp.views.scan_picklist_view.
service_worker)."""
from django.test import TestCase

from orderpiqrApp.utils.build_id import get_build_id


class ServiceWorkerViewTests(TestCase):
    def test_served_at_root_path(self):
        response = self.client.get('/serviceWorker.js')
        self.assertEqual(response.status_code, 200)

    def test_content_type_is_javascript(self):
        response = self.client.get('/serviceWorker.js')
        self.assertEqual(response['Content-Type'], 'application/javascript')

    def test_cache_control_is_no_cache(self):
        # Deploys must propagate: a cached rendering of the previous build's
        # serviceWorker.js would keep every phone on a stale pre-cache.
        response = self.client.get('/serviceWorker.js')
        self.assertEqual(response['Cache-Control'], 'no-cache')

    def test_cache_name_carries_the_build_id(self):
        response = self.client.get('/serviceWorker.js')
        body = response.content.decode('utf-8')
        self.assertIn("CACHE_NAME = 'orderpiqr-shell-%s'" % get_build_id(), body)

    def test_post_is_rejected(self):
        response = self.client.post('/serviceWorker.js')
        self.assertEqual(response.status_code, 405)

    def test_precaches_the_app_shell(self):
        # Spot-check a representative entry from each category the design
        # calls for, rather than the whole list — this test should not have
        # to change every time a new module joins the scan-page graph.
        body = self.client.get('/serviceWorker.js').content.decode('utf-8')
        for expected in (
            "'/'", "'/offline/'",
            "orderpiqrApp/js/camera_page.js",
            "orderpiqrApp/js/pickOutbox.js",
            "orderpiqrApp/js/vendor/html5-qrcode-2.3.8.min.js",
            "orderpiqrApp/css/camera_page.css",
            "icons/icon-192.png",
        ):
            self.assertIn(expected, body)

    def test_precaches_the_short_pick_modules(self):
        # Both of these are load-bearing offline: shortPick.js is how a picker
        # reports a line they cannot fill (the case most likely to happen in
        # the cold corner of the warehouse where reception dies), and
        # shortReasons.js is import-only — no tag in index.html names it, so
        # nothing else would ever put it in the cache.
        body = self.client.get('/serviceWorker.js').content.decode('utf-8')
        self.assertIn("orderpiqrApp/js/shortPick.js", body)
        self.assertIn("orderpiqrApp/js/shortReasons.js", body)

    def test_fetch_handler_never_intercepts_non_get(self):
        # The four business-critical POSTs must reach the network untouched;
        # this just guards the early-return is still present in the source.
        body = self.client.get('/serviceWorker.js').content.decode('utf-8')
        self.assertIn("req.method !== 'GET'", body)
