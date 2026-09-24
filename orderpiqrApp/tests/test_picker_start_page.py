"""Where a picker lands after logging in.

Covers both entry points together — QR scan and password login — because the
whole point of routing them through ``resolve_start_page`` is that they agree.
"""
from urllib.parse import quote

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import activate

from orderpiqrApp.models import (
    Customer, CustomerSettingValue, Device, PickerLoginToken, SettingDefinition, UserProfile)
from orderpiqrApp.utils.login_qr import issue_token
from orderpiqrApp.utils.start_page import QUEUE, SCAN, resolve_start_page


class StartPageTestCase(TestCase):
    def setUp(self):
        activate('en')
        self.customer = Customer.objects.create(name='House of Tests')
        admin_group, _ = Group.objects.get_or_create(name='companyadmin')
        picker_group, _ = Group.objects.get_or_create(name='orderpicker')

        self.admin = User.objects.create_user(username='boss', password='secret123')
        self.admin.groups.add(admin_group)
        UserProfile.objects.create(user=self.admin, customer=self.customer)

        self.picker = User.objects.create_user(username='picker1', password='pick-password')
        self.picker.groups.add(picker_group)
        UserProfile.objects.create(user=self.picker, customer=self.customer)

        self.scan_url = reverse('index')
        self.queue_url = reverse('queue_picker')

    def set_customer_setting(self, key, value):
        definition = SettingDefinition.objects.get(key=key)
        CustomerSettingValue.objects.update_or_create(
            customer=self.customer, definition=definition, defaults={'value': value})

    def register_phone(self, fingerprint='known-phone'):
        Device.objects.create(
            user=self.picker, customer=self.customer, device_fingerprint=fingerprint,
            name='Known phone', description='', last_login=timezone.now(), lists_picked=0)

    def scan(self, start_page='', fingerprint='known-phone'):
        """Redeem a fresh QR and return the response."""
        _token, raw = issue_token(
            self.picker, self.customer, created_by=self.admin, start_page=start_page)
        return self.client.post(
            reverse('qr_login', args=[raw]), {'device_fingerprint': fingerprint})


class ResolverTests(StartPageTestCase):
    def test_defaults_to_the_queue(self):
        """The behaviour before the setting existed, for every customer who
        never touches it."""
        self.assertEqual(resolve_start_page(self.customer), self.queue_url)

    def test_customer_setting_selects_the_scan_page(self):
        self.set_customer_setting('picker_start_page', SCAN)
        self.assertEqual(resolve_start_page(self.customer), self.scan_url)

    def test_token_override_beats_the_customer_setting(self):
        self.set_customer_setting('picker_start_page', SCAN)
        self.assertEqual(resolve_start_page(self.customer, QUEUE), self.queue_url)

    def test_blank_override_follows_the_customer_setting(self):
        self.set_customer_setting('picker_start_page', SCAN)
        self.assertEqual(resolve_start_page(self.customer, ''), self.scan_url)

    def test_choice_is_ignored_when_order_picking_is_off(self):
        """Otherwise switching the feature off would strand pickers on a page
        they can no longer use."""
        self.set_customer_setting('orderpicking_enabled', 'false')
        self.set_customer_setting('inventory_management_enabled', 'true')
        self.set_customer_setting('picker_start_page', SCAN)

        self.assertEqual(resolve_start_page(self.customer), reverse('inventory_picker'))
        self.assertEqual(resolve_start_page(self.customer, QUEUE), reverse('inventory_picker'))

    def test_both_features_on_still_offers_the_choice_screen(self):
        self.set_customer_setting('inventory_management_enabled', 'true')
        self.assertEqual(resolve_start_page(self.customer), reverse('picker_choice'))

    def test_unknown_stored_value_falls_back_instead_of_breaking(self):
        self.set_customer_setting('picker_start_page', 'nonsense')
        self.assertEqual(resolve_start_page(self.customer), self.queue_url)

    def test_no_customer_resolves_without_querying(self):
        self.assertEqual(resolve_start_page(None), reverse('index'))


class QRScanTests(StartPageTestCase):
    def test_scan_lands_on_the_queue_by_default(self):
        self.register_phone()
        self.assertRedirects(self.scan(), self.queue_url, fetch_redirect_response=False)

    def test_scan_lands_on_the_scan_page_when_the_company_says_so(self):
        self.register_phone()
        self.set_customer_setting('picker_start_page', SCAN)
        self.assertRedirects(self.scan(), self.scan_url, fetch_redirect_response=False)

    def test_per_qr_override_wins(self):
        self.register_phone()
        self.set_customer_setting('picker_start_page', SCAN)
        self.assertRedirects(
            self.scan(start_page=QUEUE), self.queue_url, fetch_redirect_response=False)

    def test_unregistered_phone_names_itself_then_continues_to_the_start_page(self):
        self.set_customer_setting('picker_start_page', SCAN)
        response = self.scan(fingerprint='brand-new-phone')
        self.assertRedirects(
            response, f"{reverse('name_entry')}?next={quote(self.scan_url)}",
            fetch_redirect_response=False)

    def test_start_page_survives_on_the_token(self):
        """Stored server-side, so it can be corrected without reprinting."""
        token, _raw = issue_token(
            self.picker, self.customer, created_by=self.admin, start_page=SCAN)
        token.refresh_from_db()
        self.assertEqual(token.start_page, SCAN)


class PasswordLoginTests(StartPageTestCase):
    """The setting is about how the warehouse works, so it must not depend on
    which way the picker happened to log in."""

    # reverse() rather than '/': the root is behind i18n_patterns, so '/' only
    # redirects to the language-prefixed root and never reaches root_redirect.
    def test_password_login_honours_the_same_setting(self):
        self.set_customer_setting('picker_start_page', SCAN)
        self.client.login(username='picker1', password='pick-password')
        self.assertRedirects(
            self.client.get(reverse('root_redirect')), self.scan_url,
            fetch_redirect_response=False)

    def test_password_login_defaults_to_the_queue(self):
        self.client.login(username='picker1', password='pick-password')
        self.assertRedirects(
            self.client.get(reverse('root_redirect')), self.queue_url,
            fetch_redirect_response=False)


class IssuingUITests(StartPageTestCase):
    def post_create(self, start_page):
        self.client.login(username='boss', password='secret123')
        self.client.post(reverse('manage_profile'), {
            'action': 'create_picker_qr',
            'picker_id': self.picker.pk,
            'start_page': start_page,
        })
        return PickerLoginToken.objects.filter(user=self.picker).latest('created')

    def test_admin_can_pick_the_scan_page(self):
        self.assertEqual(self.post_create(SCAN).start_page, SCAN)

    def test_blank_is_stored_as_follow_the_company(self):
        self.assertEqual(self.post_create('').start_page, '')

    def test_unrecognised_value_is_not_stored(self):
        """A hand-crafted POST must not pin a QR to an arbitrary string."""
        self.assertEqual(self.post_create('/evil').start_page, '')

    def test_the_form_offers_the_choice(self):
        self.client.login(username='boss', password='secret123')
        response = self.client.get(reverse('manage_profile'))
        self.assertContains(response, 'name="start_page"')
        self.assertContains(response, 'Scan an order')


class NameEntryRedirectTests(StartPageTestCase):
    def test_offsite_next_is_refused(self):
        """`next` is attacker-supplied; a freshly logged-in picker must not be
        bounced off-site."""
        self.register_phone()
        self.client.login(username='picker1', password='pick-password')
        response = self.client.post(reverse('name_entry'), {
            'name': 'Phone', 'device_fingerprint': 'known-phone',
            'next': 'https://evil.example/steal',
        })
        self.assertRedirects(response, '/', fetch_redirect_response=False)

    def test_local_next_is_followed(self):
        self.register_phone()
        self.client.login(username='picker1', password='pick-password')
        response = self.client.post(reverse('name_entry'), {
            'name': 'Phone', 'device_fingerprint': 'known-phone',
            'next': self.scan_url,
        })
        self.assertRedirects(response, self.scan_url, fetch_redirect_response=False)
