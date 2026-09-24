"""Scannable picker login: issuing from manage/profile and redeeming at /q/."""
import re
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import activate

from orderpiqrApp.models import Customer, Device, PickerLoginToken, UserProfile
from orderpiqrApp.utils.login_qr import active_token, issue_token, login_url, resolve_token


class PickerLoginQRTestCase(TestCase):
    def setUp(self):
        activate('en')
        self.customer = Customer.objects.create(name='House of Tests')
        admin_group, _ = Group.objects.get_or_create(name='companyadmin')
        self.picker_group, _ = Group.objects.get_or_create(name='orderpicker')

        self.admin = User.objects.create_user(username='boss', password='secret123')
        self.admin.groups.add(admin_group)
        UserProfile.objects.create(user=self.admin, customer=self.customer)

        self.picker = User.objects.create_user(username='picker1', password='pick-password')
        self.picker.groups.add(self.picker_group)
        UserProfile.objects.create(user=self.picker, customer=self.customer)

        self.profile_url = reverse('manage_profile')

    def issue(self, user=None):
        return issue_token(user or self.picker, self.customer, created_by=self.admin)


class IssuingTests(PickerLoginQRTestCase):
    def test_admin_creates_qr_for_own_picker(self):
        self.client.login(username='boss', password='secret123')
        response = self.client.post(self.profile_url, {
            'action': 'create_picker_qr',
            'picker_id': self.picker.pk,
        })
        # Rendered, not redirected: the raw token is only shown once.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PickerLoginToken.objects.filter(user=self.picker).count(), 1)
        self.assertContains(response, 'data:image/png;base64,')

    def test_qr_defaults_to_90_days(self):
        token, _raw = self.issue()
        self.assertEqual(token.days_remaining, 90)

    def test_days_remaining_bottoms_out_at_zero(self):
        token, _raw = self.issue()
        token.expires_at = timezone.now() - timedelta(days=3)
        self.assertEqual(token.days_remaining, 0)

    def test_issuing_again_revokes_the_previous_token(self):
        _first, first_raw = self.issue()
        _second, second_raw = self.issue()

        self.assertIsNone(resolve_token(first_raw))
        self.assertIsNotNone(resolve_token(second_raw))

    def test_revoke_kills_printed_copies(self):
        _token, raw = self.issue()
        self.client.login(username='boss', password='secret123')
        response = self.client.post(self.profile_url, {
            'action': 'revoke_picker_qr',
            'picker_id': self.picker.pk,
        })
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(resolve_token(raw))
        self.assertIsNone(active_token(self.picker))

    def test_cannot_issue_for_another_customers_picker(self):
        other_customer = Customer.objects.create(name='Other company')
        outsider = User.objects.create_user(username='outsider', password='pw')
        outsider.groups.add(self.picker_group)
        UserProfile.objects.create(user=outsider, customer=other_customer)

        self.client.login(username='boss', password='secret123')
        self.client.post(self.profile_url, {
            'action': 'create_picker_qr',
            'picker_id': outsider.pk,
        })
        self.assertFalse(PickerLoginToken.objects.filter(user=outsider).exists())

    def test_cannot_issue_for_an_admin_account(self):
        # _picker_users filters on the orderpicker group, so a companyadmin id
        # must find nothing even though it belongs to this customer.
        self.client.login(username='boss', password='secret123')
        self.client.post(self.profile_url, {
            'action': 'create_picker_qr',
            'picker_id': self.admin.pk,
        })
        self.assertFalse(PickerLoginToken.objects.filter(user=self.admin).exists())

    def test_login_url_is_absolute_and_short(self):
        _token, raw = self.issue()
        url = login_url(raw)
        self.assertTrue(url.startswith('http'))
        self.assertIn('/q/', url)
        self.assertLess(len(url), 120)


class RedeemingTests(PickerLoginQRTestCase):
    def test_get_shows_confirmation_without_logging_in(self):
        _token, raw = self.issue()
        response = self.client.get(reverse('qr_login', args=[raw]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'picker1')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_post_logs_in_and_asks_for_a_device_name(self):
        _token, raw = self.issue()
        response = self.client.post(reverse('qr_login', args=[raw]), {
            'device_fingerprint': 'brand-new-phone',
        })

        self.assertRedirects(response, reverse('name_entry'), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.picker.pk)

    def test_post_from_a_known_device_goes_straight_to_the_app(self):
        Device.objects.create(
            user=self.picker, customer=self.customer, device_fingerprint='known-phone',
            name='Known phone', description='', last_login=timezone.now(), lists_picked=0)
        _token, raw = self.issue()

        response = self.client.post(reverse('qr_login', args=[raw]), {
            'device_fingerprint': 'known-phone',
        })
        self.assertRedirects(response, '/', fetch_redirect_response=False)

    def test_redeeming_stamps_usage(self):
        token, raw = self.issue()
        self.client.post(reverse('qr_login', args=[raw]), {'device_fingerprint': 'phone'})

        token.refresh_from_db()
        self.assertEqual(token.use_count, 1)
        self.assertIsNotNone(token.last_used_at)

    def test_qr_stays_valid_for_repeat_scans(self):
        _token, raw = self.issue()
        self.client.post(reverse('qr_login', args=[raw]), {'device_fingerprint': 'phone'})
        self.client.logout()

        response = self.client.post(reverse('qr_login', args=[raw]), {'device_fingerprint': 'phone'})
        self.assertEqual(int(self.client.session['_auth_user_id']), self.picker.pk)
        self.assertEqual(response.status_code, 302)

    def test_unknown_token_is_rejected(self):
        response = self.client.get(reverse('qr_login', args=['not-a-real-token']))
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_expired_token_is_rejected(self):
        token, raw = self.issue()
        token.expires_at = timezone.now() - timedelta(seconds=1)
        token.save(update_fields=['expires_at'])

        response = self.client.post(reverse('qr_login', args=[raw]), {})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_revoked_token_is_rejected(self):
        token, raw = self.issue()
        token.revoke()

        response = self.client.post(reverse('qr_login', args=[raw]), {})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_token_dies_when_the_picker_is_promoted(self):
        # A QR must never reach an account that can open the manage interface,
        # even if the token was issued while it was still a plain picker.
        _token, raw = self.issue()
        self.picker.is_staff = True
        self.picker.save(update_fields=['is_staff'])

        response = self.client.post(reverse('qr_login', args=[raw]), {})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_token_dies_when_the_picker_is_deactivated(self):
        _token, raw = self.issue()
        self.picker.is_active = False
        self.picker.save(update_fields=['is_active'])

        response = self.client.post(reverse('qr_login', args=[raw]), {})
        self.assertEqual(response.status_code, 403)

    def test_token_dies_when_the_picker_moves_to_another_customer(self):
        _token, raw = self.issue()
        profile = self.picker.userprofile
        profile.customer = Customer.objects.create(name='Other company')
        profile.save(update_fields=['customer'])

        response = self.client.post(reverse('qr_login', args=[raw]), {})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_response_keeps_the_token_off_other_hosts(self):
        _token, raw = self.issue()
        response = self.client.get(reverse('qr_login', args=[raw]))
        # Not 'no-referrer' — see CsrfTests.browser_headers for why that breaks
        # the page's own POST.
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_invalid_page_keeps_the_token_off_other_hosts(self):
        response = self.client.get(reverse('qr_login', args=['not-a-real-token']))
        self.assertEqual(response['Referrer-Policy'], 'same-origin')


class CsrfTests(PickerLoginQRTestCase):
    """The Continue button has to survive CsrfViewMiddleware for real.

    Every other test here uses the default test client, which disables CSRF
    enforcement and sends no Origin header — so they all pass even when a real
    phone gets a 403 on the very same POST.
    """

    HOST = 'app.orderpiqr.nl'
    ORIGIN = 'https://app.orderpiqr.nl'

    def setUp(self):
        super().setUp()
        self.client = Client(enforce_csrf_checks=True)

    @classmethod
    def browser_headers(cls, referrer_policy, url):
        """The Origin/Referer a browser puts on this page's own form POST.

        Per Fetch, "append a request Origin header": for a non-CORS request
        whose method is not GET/HEAD, a document referrer policy of
        ``no-referrer`` replaces the serialized origin with ``null`` (and of
        course suppresses Referer). Django's ``_origin_verified`` then matches
        ``null`` against neither ``request.get_host()`` nor
        ``CSRF_TRUSTED_ORIGINS`` and rejects the POST. ``same-origin`` still
        withholds both headers from every other host, but leaves our own POST
        alone.
        """
        if referrer_policy == 'no-referrer':
            return {'HTTP_ORIGIN': 'null'}
        return {'HTTP_ORIGIN': cls.ORIGIN, 'HTTP_REFERER': f'{cls.ORIGIN}{url}'}

    def get_confirmation(self, raw):
        url = reverse('qr_login', args=[raw])
        page = self.client.get(url, secure=True, HTTP_HOST=self.HOST)
        self.assertEqual(page.status_code, 200)
        return url, page

    def test_continue_button_is_accepted_by_csrf_middleware(self):
        """Scan, press Continue, get logged in — not a 403."""
        _token, raw = self.issue()
        url, page = self.get_confirmation(raw)

        match = re.search(
            r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', page.content.decode())
        self.assertIsNotNone(match, 'confirmation form is missing {% csrf_token %}')
        self.assertIn('csrftoken', self.client.cookies,
                      'GET did not set the CSRF cookie the POST needs')

        response = self.client.post(
            url,
            {'csrfmiddlewaretoken': match.group(1), 'device_fingerprint': 'brand-new-phone'},
            secure=True,
            HTTP_HOST=self.HOST,
            **self.browser_headers(page['Referrer-Policy'], url),
        )

        self.assertNotEqual(response.status_code, 403, 'CSRF verification failed')
        self.assertRedirects(response, reverse('name_entry'), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.picker.pk)

    def test_confirmation_page_is_never_cached(self):
        # A cached page would hand every scanner the same stale CSRF token.
        _token, raw = self.issue()
        _url, page = self.get_confirmation(raw)
        self.assertIn('no-store', page['Cache-Control'])

    def test_post_without_a_csrf_token_is_still_rejected(self):
        # The fix must not have loosened protection on this endpoint.
        _token, raw = self.issue()
        url, _page = self.get_confirmation(raw)

        response = self.client.post(
            url, {'device_fingerprint': 'phone'}, secure=True, HTTP_HOST=self.HOST,
            HTTP_ORIGIN=self.ORIGIN, HTTP_REFERER=f'{self.ORIGIN}{url}')

        self.assertEqual(response.status_code, 403)
        self.assertNotIn('_auth_user_id', self.client.session)
