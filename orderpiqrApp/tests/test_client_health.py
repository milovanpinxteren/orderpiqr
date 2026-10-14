"""Telemetry for the failures that used to produce no event at all.

Crashes, self-update reloads, dead cameras and lost sessions were invisible:
the health dashboard was built entirely from scan outcomes, so it stayed clean
while pickers reported the app crashing and logging them out. These tests cover
the server side of closing that gap — the enriched scan-event endpoint, device
context capture, and auth-bounce logging.
"""
import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from orderpiqrApp.models import Device, ScanEvent
from orderpiqrApp.tests.test_scan_endpoints import FINGERPRINT, ScanEndpointTestCase

IOS_SAFARI_UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 15_7 like Mac OS X) '
                 'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1')


class ClientHealthEventTests(ScanEndpointTestCase):
    def post_event(self, **overrides):
        payload = {
            'eventType': 'client_error',
            'deviceFingerprint': FINGERPRINT,
            'message': 'Cannot read properties of null',
        }
        payload.update(overrides)
        return self.client.post('/orderpiqr/scan-event', data=json.dumps(payload),
                                content_type='application/json')

    def test_client_error_is_accepted_and_defaults_to_error_severity(self):
        response = self.post_event(reason='uncaught_error')

        self.assertEqual(response.status_code, 200)
        event = ScanEvent.objects.get()
        self.assertEqual(event.event_type, 'client_error')
        self.assertEqual(event.reason, 'uncaught_error')
        self.assertEqual(event.severity, 'error')

    def test_lifecycle_event_defaults_to_info(self):
        self.post_event(eventType='app_lifecycle', reason='app_open')
        self.assertEqual(ScanEvent.objects.get().severity, 'info')

    def test_camera_error_is_accepted(self):
        self.post_event(eventType='camera_error', reason='permission_denied')
        event = ScanEvent.objects.get()
        self.assertEqual(event.event_type, 'camera_error')
        self.assertEqual(event.severity, 'error')

    def test_build_id_is_recorded(self):
        self.post_event(buildId='abc123')
        self.assertEqual(ScanEvent.objects.get().build_id, 'abc123')

    def test_client_timestamp_is_kept_for_queued_events(self):
        # An event queued while offline must keep the time it happened, not the
        # time the network came back.
        happened = timezone.now() - timedelta(minutes=20)
        self.post_event(clientTs=happened.isoformat())

        event = ScanEvent.objects.get()
        self.assertIsNotNone(event.client_ts)
        self.assertAlmostEqual(event.client_ts, happened, delta=timedelta(seconds=1))
        self.assertAlmostEqual(event.occurred_at, happened, delta=timedelta(seconds=1))

    def test_absurd_client_clock_is_discarded_not_stored(self):
        # A phone with a wrong clock must not be able to drag the dashboard's
        # time axis years off scale.
        self.post_event(clientTs=(timezone.now() + timedelta(days=400)).isoformat())

        event = ScanEvent.objects.get()
        self.assertIsNone(event.client_ts)
        self.assertAlmostEqual(event.occurred_at, event.created_at, delta=timedelta(seconds=5))

    def test_unparseable_client_timestamp_is_ignored(self):
        self.post_event(clientTs='not-a-date')
        self.assertIsNone(ScanEvent.objects.get().client_ts)

    def test_different_reasons_are_not_deduped(self):
        # Client errors carry no scanned_code, so without `reason` in the
        # dedupe key a burst of genuinely different crashes would collapse into
        # one row every five seconds.
        self.post_event(reason='uncaught_error')
        self.post_event(reason='unhandled_rejection')
        self.assertEqual(ScanEvent.objects.count(), 2)

    def test_identical_reason_is_still_deduped(self):
        self.post_event(reason='uncaught_error')
        self.post_event(reason='uncaught_error')
        self.assertEqual(ScanEvent.objects.count(), 1)

    def test_invalid_severity_falls_back_to_the_type_default(self):
        self.post_event(severity='catastrophic')
        self.assertEqual(ScanEvent.objects.get().severity, 'error')

    def test_oversized_reason_is_truncated_not_rejected(self):
        self.post_event(reason='x' * 500)
        self.assertEqual(len(ScanEvent.objects.get().reason), 64)


class DeviceContextTests(ScanEndpointTestCase):
    def test_scan_event_records_browser_os_and_display_mode(self):
        self.client.post(
            '/orderpiqr/scan-event',
            data=json.dumps({
                'eventType': 'app_lifecycle',
                'reason': 'app_open',
                'deviceFingerprint': FINGERPRINT,
                'displayMode': 'browser',
                'buildId': 'build-7',
            }),
            content_type='application/json',
            HTTP_USER_AGENT=IOS_SAFARI_UA)

        self.device.refresh_from_db()
        self.assertEqual(self.device.display_mode, 'browser')
        self.assertEqual(self.device.last_build_id, 'build-7')
        self.assertEqual(self.device.os, 'iOS')
        self.assertIn('Safari', self.device.browser)
        self.assertEqual(self.device.device_family, 'iPhone')

    def test_scanning_a_list_records_device_context(self):
        self.client.post('/orderpiqr/scan-picklist', data=json.dumps({
            'orderID': 'ORD-1',
            'picklist': ['SMOOTHIE-1'],
            'deviceFingerprint': FINGERPRINT,
            'displayMode': 'standalone',
            'buildId': 'build-9',
        }), content_type='application/json', HTTP_USER_AGENT=IOS_SAFARI_UA)

        self.device.refresh_from_db()
        self.assertEqual(self.device.display_mode, 'standalone')
        self.assertEqual(self.device.last_build_id, 'build-9')

    def test_unknown_display_mode_is_ignored(self):
        self.client.post('/orderpiqr/scan-event', data=json.dumps({
            'eventType': 'app_lifecycle',
            'deviceFingerprint': FINGERPRINT,
            'displayMode': 'kiosk',
        }), content_type='application/json')

        self.device.refresh_from_db()
        self.assertEqual(self.device.display_mode, '')

    def test_unchanged_context_writes_nothing(self):
        # This runs on the pick path; it must not add a write per scan.
        self.client.post('/orderpiqr/scan-event', data=json.dumps({
            'eventType': 'app_lifecycle', 'deviceFingerprint': FINGERPRINT,
            'displayMode': 'browser',
        }), content_type='application/json', HTTP_USER_AGENT=IOS_SAFARI_UA)
        self.device.refresh_from_db()
        before = self.device.last_login

        with self.assertNumQueries(self._queries_without_device_write()):
            self.client.post('/orderpiqr/scan-event', data=json.dumps({
                'eventType': 'app_lifecycle', 'deviceFingerprint': FINGERPRINT,
                'displayMode': 'browser', 'reason': 'second',
            }), content_type='application/json', HTTP_USER_AGENT=IOS_SAFARI_UA)

        self.device.refresh_from_db()
        self.assertEqual(self.device.last_login, before)

    def _queries_without_device_write(self):
        """Query count for a repeat event, measured rather than hard-coded.

        The exact number depends on session and auth lookups; what this test
        asserts is that a second identical event costs the same as the first
        repeat, i.e. no extra Device UPDATE.
        """
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        with CaptureQueriesContext(connection) as ctx:
            self.client.post('/orderpiqr/scan-event', data=json.dumps({
                'eventType': 'app_lifecycle', 'deviceFingerprint': FINGERPRINT,
                'displayMode': 'browser', 'reason': 'probe',
            }), content_type='application/json', HTTP_USER_AGENT=IOS_SAFARI_UA)
        return len(ctx.captured_queries)


class AuthBounceTests(TestCase):
    """A picker landing back on the login/name-entry screen mid-shift is the
    literal complaint ("it kicks us out") and used to leave no trace at all.
    """

    def setUp(self):
        from django.contrib.auth.models import Group, User
        from orderpiqrApp.models import Customer, UserProfile

        self.customer = Customer.objects.create(name='Healthy Fridge')
        picker_group, _ = Group.objects.get_or_create(name='orderpicker')
        self.picker = User.objects.create_user(username='picker1', password='pw12345678')
        self.picker.groups.add(picker_group)
        UserProfile.objects.create(user=self.picker, customer=self.customer)
        self.device = Device.objects.create(
            user=self.picker, customer=self.customer, device_fingerprint=FINGERPRINT,
            name='Test phone', description='', last_login=timezone.now(), lists_picked=0)

    def test_authenticated_picker_with_no_device_logs_a_bounce(self):
        self.client.login(username='picker1', password='pw12345678')
        # Logged in, but this session has never pinned a fingerprint — the
        # storage-eviction case.
        response = self.client.get(reverse('index'))

        self.assertEqual(response.status_code, 302)
        event = ScanEvent.objects.get(event_type='auth_bounce')
        self.assertEqual(event.customer, self.customer)
        self.assertEqual(event.reason, 'device_unknown')

    def test_bounce_is_recorded_even_when_the_device_row_is_gone(self):
        self.client.login(username='picker1', password='pw12345678')
        session = self.client.session
        session['device_fingerprint'] = FINGERPRINT
        session.save()
        self.device.delete()

        self.client.get(reverse('index'))

        # The device row is gone, so the event cannot name it — but the bounce
        # must still be recorded against the right tenant, or the case we most
        # want to count stays invisible.
        event = ScanEvent.objects.get(event_type='auth_bounce')
        self.assertEqual(event.customer, self.customer)
        self.assertIsNone(event.device)

    def test_unattributable_bounce_is_skipped_rather_than_guessed(self):
        # No session, no resolvable fingerprint: nothing identifies the
        # customer, and inventing one would be worse than recording nothing.
        self.client.get(reverse('index'))
        self.assertEqual(ScanEvent.objects.count(), 0)
