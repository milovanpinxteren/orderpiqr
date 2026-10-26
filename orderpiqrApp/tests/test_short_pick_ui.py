"""The short-pick UI on the scan page.

A picker who cannot fill a line has to be able to say so from the scan screen
— that declaration is the whole point of the measurement work, and it only
exists if the entry points are actually in the rendered page: the trailing
action column, the two overlays, and the module tag that drives them.

The module tag is also the regression guard from the v123 incident: a hashed
URL on an ES-module tag loads a second shadow copy of the whole graph, and the
shadow camera_page has an empty picklist.
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

FINGERPRINT = 'short-pick-ui-fp'


class ShortPickUITests(TestCase):
    def setUp(self):
        activate('en')
        self.customer = Customer.objects.create(name='Short Warehouse')
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

    def test_short_pick_overlay_is_rendered(self):
        html = self.scan_page()
        for element_id in (
            'short-pick-overlay',
            'short-overlay-product-name',
            'short-overlay-line-info',
            'short-pick-quantity',
            'short-qty-minus',
            'short-qty-plus',
            'short-reason-grid',
            'short-other-section',
            'short-reason-text',
            'short-other-confirm-btn',
            'short-cancel-btn',
        ):
            self.assertIn('id="%s"' % element_id, html)

    def test_completion_summary_overlay_is_rendered(self):
        """A list with declared shorts must be finished deliberately, so the
        blocking summary has to exist in the DOM before it is ever needed."""
        html = self.scan_page()
        for element_id in ('short-complete-overlay', 'short-complete-summary',
                           'short-finish-btn', 'short-keep-picking-btn'):
            self.assertIn('id="%s"' % element_id, html)

    def test_both_overlays_start_hidden(self):
        html = self.scan_page()
        for element_id in ('short-pick-overlay', 'short-complete-overlay'):
            tag = re.search(r'<div id="%s"[^>]*>' % element_id, html).group(0)
            self.assertIn('scan-overlay hidden', tag)

    def test_reason_buttons_are_not_in_the_template(self):
        """They are built by shortPick.js from shortReasons.js, which also
        labels the short rows — one source, so a reason cannot read one way on
        the button and another way on the row it produces."""
        html = self.scan_page()
        grid = re.search(r'<div id="short-reason-grid"[^>]*></div>', html)
        self.assertIsNotNone(grid, 'the reason grid must be rendered empty')

    def test_action_column_header_is_present_in_both_view_modes(self):
        """Individual and grouped views share one <table> with two header
        rows; a column rendered into the body but missing from one header
        would shear that view's columns apart."""
        html = self.scan_page()
        thead = re.search(r'<thead>.*?</thead>', html, re.S).group(0)
        self.assertEqual(thead.count('class="th-action"'), 2)

    def test_action_column_starts_hidden_and_is_revealed_only_by_the_setting(self):
        """domUpdater gates the row cells on the identical strict check, so a
        warehouse without the feature stays consistently three columns wide."""
        html = self.scan_page()
        for header in re.findall(r'<th class="th-action"[^>]*>', html):
            self.assertIn('style="display: none;"', header)
        self.assertIn("window.SETTINGS.short_pick_enabled === true", html)

    def test_setting_reaches_the_client_settings_blob(self):
        self.assertIn('"short_pick_enabled": false', self.scan_page())
        self.set_setting('short_pick_enabled', 'true')
        self.assertIn('"short_pick_enabled": true', self.scan_page())

    def test_module_tag_is_unhashed(self):
        """Manifest storage hashes a {% static %} tag URL but not the relative
        import specifiers inside the module, so a hashed tag loads a second
        shadow copy of the whole graph (pick day 2026-10-11)."""
        html = self.scan_page()
        self.assertIn(
            '<script src="/static/orderpiqrApp/js/shortPick.js" type="module"></script>',
            html)
        self.assertNotRegex(html, r'shortPick\.[0-9a-f]{8,}\.js')

    def test_no_product_code_dataset_on_the_short_subtree(self):
        """manualOverride.js reads event.target.dataset.productCode straight
        off the click target: a flag button carrying the code would turn three
        impatient taps into three override picks of the line being reported
        missing."""
        html = self.scan_page()
        start = html.index('<div id="short-pick-overlay"')
        end = html.index('<div id="short-complete-overlay"')
        self.assertNotIn('data-product-code', html[start:end])
