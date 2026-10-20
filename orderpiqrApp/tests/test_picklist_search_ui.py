"""The search-and-claim UI on the scan page.

A picker whose phone cannot decode a dense picklist QR has no other way into a
list, so the entry point has to actually be in the rendered page: the floating
magnifier, the panel with its reversed URLs, and the module tag that drives
them. The module tag is also the regression guard from the v123 incident — a
hashed URL loads a second shadow copy of the module graph.
"""
import re

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import activate

from orderpiqrApp.models import (
    Customer, CustomerSettingValue, Device, SettingDefinition, UserProfile,
)

FINGERPRINT = 'picklist-search-ui-fp'


class PicklistSearchUITests(TestCase):
    def setUp(self):
        activate('en')
        self.customer = Customer.objects.create(name='QR-blind Warehouse')
        picker_group, _ = Group.objects.get_or_create(name='orderpicker')
        self.picker = User.objects.create_user(username='picker1', password='pw12345678')
        self.picker.groups.add(picker_group)
        UserProfile.objects.create(user=self.picker, customer=self.customer)
        Device.objects.create(
            user=self.picker, customer=self.customer, device_fingerprint=FINGERPRINT,
            name='Test phone', description='', last_login=timezone.now(), lists_picked=0)
        self.client.login(username='picker1', password='pw12345678')
        session = self.client.session
        session['device_fingerprint'] = FINGERPRINT
        session.save()

    def set_setting(self, key, value):
        CustomerSettingValue.objects.update_or_create(
            customer=self.customer,
            definition=SettingDefinition.objects.get(key=key),
            defaults={'value': value})

    def scan_page(self):
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_toggle_and_panel_are_rendered(self):
        html = self.scan_page()
        self.assertIn('id="picklist-search-toggle"', html)
        self.assertIn('id="picklist-search-panel"', html)
        self.assertIn('id="picklist-search-input"', html)
        self.assertIn('id="picklist-search-results"', html)
        self.assertIn('id="picklist-search-close"', html)
        # Screen-reader label and panel wiring: the button is an icon only.
        self.assertIn('aria-label="Search orders"', html)
        self.assertIn('aria-controls="picklist-search-panel"', html)
        self.assertIn('type="search"', html)

    def test_panel_carries_reversed_urls_not_hardcoded_paths(self):
        """Every page is served under a language prefix, so the module must get
        its URLs from the template rather than build them."""
        html = self.scan_page()
        self.assertIn('data-search-url="%s"' % reverse('picklist_search'), html)
        self.assertIn('data-claim-url="%s"' % reverse('queue_claim_order', args=[0]), html)
        self.assertIn('data-index-url="%s"' % reverse('index'), html)

    def test_toggle_starts_hidden_and_is_revealed_only_by_the_setting(self):
        """A warehouse that only scans printed QRs must not be offered a claim
        path: claiming an order it will never pick strands the picklist."""
        html = self.scan_page()
        toggle = re.search(r'<button id="picklist-search-toggle".*?>', html, re.S).group(0)
        self.assertIn('style="display: none;"', toggle)
        self.assertIn("window.SETTINGS.picklist_search_enabled === true", html)

    def test_setting_reaches_the_client_settings_blob(self):
        self.assertIn('"picklist_search_enabled": false', self.scan_page())
        self.set_setting('picklist_search_enabled', 'true')
        self.assertIn('"picklist_search_enabled": true', self.scan_page())

    def test_module_tag_is_unhashed(self):
        """Manifest storage hashes a {% static %} tag URL but not the relative
        import specifiers inside the module, so a hashed tag loads a second
        shadow copy of the whole graph (pick day 2026-10-11)."""
        html = self.scan_page()
        self.assertIn(
            '<script src="/static/orderpiqrApp/js/picklistSearch.js" type="module"></script>',
            html)
        self.assertNotRegex(html, r'picklistSearch\.[0-9a-f]{8,}\.js')
