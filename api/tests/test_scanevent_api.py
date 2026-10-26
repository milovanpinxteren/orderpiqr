"""`/api/scanevents/` — read-only pick-flow health events.

Tenant scoping, the hand-rolled filter params, and the occurred_at fallback
(client_ts when the device sent one, created_at otherwise) are the load-bearing
behaviours here; the health page itself is covered by test_manage_health.py.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from orderpiqrApp.models import Customer, Device, ScanEvent, UserProfile


class ScanEventAPITestCase(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Warehouse A')
        self.user = User.objects.create_user(username='picker-a', password='x')
        UserProfile.objects.create(user=self.user, customer=self.customer)

        self.other_customer = Customer.objects.create(name='Warehouse B')
        self.other_user = User.objects.create_user(username='picker-b', password='x')
        UserProfile.objects.create(user=self.other_user, customer=self.other_customer)

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def make_event(self, customer=None, days_ago=0, **kwargs):
        event = ScanEvent.objects.create(
            customer=customer or self.customer,
            event_type=kwargs.pop('event_type', 'unknown_product'),
            **kwargs
        )
        if days_ago:
            # created_at is auto_now_add, so backdate via a queryset update,
            # same recipe test_manage_health.py uses.
            ScanEvent.objects.filter(pk=event.pk).update(
                created_at=timezone.now() - timedelta(days=days_ago))
        return event

    def make_device(self, customer=None, name='Scanner 1'):
        return Device.objects.create(
            customer=customer or self.customer,
            name=name,
            description='',
            last_login=timezone.now(),
            lists_picked=0,
        )


class ScopingTests(ScanEventAPITestCase):
    def test_list_excludes_other_customers_events(self):
        mine = self.make_event(scanned_code='MINE-1')
        self.make_event(customer=self.other_customer, scanned_code='THEIRS-1')

        response = self.client.get('/api/scanevents/')
        codes = [row['scanned_code'] for row in response.data['results']]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(codes, ['MINE-1'])
        self.assertEqual(response.data['results'][0]['id'], mine.id)

    def test_retrieve_another_customers_event_is_404(self):
        foreign = self.make_event(customer=self.other_customer, scanned_code='THEIRS-1')
        response = self.client.get(f'/api/scanevents/{foreign.id}/')
        self.assertEqual(response.status_code, 404)


class FilterTests(ScanEventAPITestCase):
    def test_filter_by_event_type(self):
        self.make_event(event_type='unknown_product', scanned_code='UNK-1')
        self.make_event(event_type='sync_error', scanned_code='SYNC-1')

        response = self.client.get('/api/scanevents/', {'event_type': 'sync_error'})
        codes = [row['scanned_code'] for row in response.data['results']]
        self.assertEqual(codes, ['SYNC-1'])

    def test_filter_by_severity(self):
        self.make_event(scanned_code='WARN-1', severity='warning')
        self.make_event(scanned_code='ERR-1', severity='error')

        response = self.client.get('/api/scanevents/', {'severity': 'error'})
        codes = [row['scanned_code'] for row in response.data['results']]
        self.assertEqual(codes, ['ERR-1'])

    def test_filter_by_picklist_code(self):
        self.make_event(scanned_code='A-1', picklist_code='PL-1')
        self.make_event(scanned_code='B-1', picklist_code='PL-2')

        response = self.client.get('/api/scanevents/', {'picklist_code': 'PL-1'})
        codes = [row['scanned_code'] for row in response.data['results']]
        self.assertEqual(codes, ['A-1'])

    def test_filter_by_device(self):
        device_a = self.make_device(name='Phone A')
        device_b = self.make_device(name='Phone B')
        self.make_event(scanned_code='A-1', device=device_a)
        self.make_event(scanned_code='B-1', device=device_b)

        response = self.client.get('/api/scanevents/', {'device': device_a.device_id})
        codes = [row['scanned_code'] for row in response.data['results']]
        self.assertEqual(codes, ['A-1'])

    def test_search_matches_scanned_code_picklist_code_reason_and_message(self):
        self.make_event(scanned_code='FINDME-1')
        self.make_event(picklist_code='FINDME-2')
        self.make_event(reason='findme-3')
        self.make_event(message='contains findme-4 inline')
        self.make_event(scanned_code='OTHER')

        for term in ['FINDME-1', 'FINDME-2', 'findme-3', 'findme-4']:
            response = self.client.get('/api/scanevents/', {'search': term})
            self.assertEqual(response.data['count'], 1, msg=f'search={term!r}')

    def test_date_range_filter_includes_a_backdated_event_inside_the_window(self):
        inside = self.make_event(scanned_code='INSIDE-1', days_ago=5)
        self.make_event(scanned_code='OUTSIDE-1', days_ago=20)
        self.make_event(scanned_code='OUTSIDE-2', days_ago=0)

        gte = (timezone.now() - timedelta(days=10)).isoformat()
        lte = (timezone.now() - timedelta(days=1)).isoformat()
        response = self.client.get(
            '/api/scanevents/', {'created_at__gte': gte, 'created_at__lte': lte})

        codes = [row['scanned_code'] for row in response.data['results']]
        self.assertEqual(codes, ['INSIDE-1'])
        self.assertEqual(response.data['results'][0]['id'], inside.id)


class OccurredAtTests(ScanEventAPITestCase):
    def test_occurred_at_uses_client_ts_when_present(self):
        client_ts = timezone.now() - timedelta(minutes=45)
        event = self.make_event(scanned_code='X-1', client_ts=client_ts)

        response = self.client.get(f'/api/scanevents/{event.id}/')
        # Compare instants, not string formatting: DRF renders datetimes in
        # the project's local timezone (Europe/Amsterdam), not UTC 'Z'.
        self.assertEqual(parse_datetime(response.data['occurred_at']), client_ts)
        self.assertNotEqual(response.data['occurred_at'], response.data['created_at'])

    def test_occurred_at_falls_back_to_created_at_without_client_ts(self):
        event = self.make_event(scanned_code='X-2')
        event.refresh_from_db()

        response = self.client.get(f'/api/scanevents/{event.id}/')
        self.assertEqual(response.data['occurred_at'], response.data['created_at'])


class WriteMethodsRejectedTests(ScanEventAPITestCase):
    """Events are written exclusively by the scan flow; the API is read-only."""

    def test_post_not_allowed(self):
        response = self.client.post('/api/scanevents/', {
            'event_type': 'unknown_product', 'scanned_code': 'X',
        }, format='json')
        self.assertEqual(response.status_code, 405)

    def test_put_not_allowed(self):
        event = self.make_event(scanned_code='X-1')
        response = self.client.put(f'/api/scanevents/{event.id}/', {
            'event_type': 'sync_error',
        }, format='json')
        self.assertEqual(response.status_code, 405)

    def test_patch_not_allowed(self):
        event = self.make_event(scanned_code='X-1')
        response = self.client.patch(f'/api/scanevents/{event.id}/', {
            'severity': 'error',
        }, format='json')
        self.assertEqual(response.status_code, 405)

    def test_delete_not_allowed(self):
        event = self.make_event(scanned_code='X-1')
        response = self.client.delete(f'/api/scanevents/{event.id}/')
        self.assertEqual(response.status_code, 405)


class OrderingTests(ScanEventAPITestCase):
    def test_default_ordering_is_newest_first(self):
        self.make_event(scanned_code='OLD-1', days_ago=2)
        self.make_event(scanned_code='NEW-1', days_ago=0)

        response = self.client.get('/api/scanevents/')
        codes = [row['scanned_code'] for row in response.data['results']]
        self.assertEqual(codes, ['NEW-1', 'OLD-1'])
