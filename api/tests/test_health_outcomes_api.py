"""`/api/health/outcomes/` (R6) — the same counters as the manage health page's
outcome tiles, tenant-scoped, as an API aggregate. Scenarios mirror
orderpiqrApp/tests/test_manage_health.py's HealthOutcomeTests so the two
surfaces can never silently disagree.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from orderpiqrApp.models import Customer, Device, PickList, Product, ProductPick, UserProfile


class HealthOutcomesAPITestCase(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Warehouse A')
        self.user = User.objects.create_user(username='picker-a', password='x')
        UserProfile.objects.create(user=self.user, customer=self.customer)

        self.other_customer = Customer.objects.create(name='Warehouse B')

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.device = Device.objects.create(
            customer=self.customer, name='Scanner 1', description='',
            last_login=timezone.now(), lists_picked=0,
        )
        self.product = Product.objects.create(
            customer=self.customer, code='P-1', description='Thing', location='A1')

    def _list(self, code, successful, picked, pending, short=0, customer=None, device=None):
        picklist = PickList.objects.create(
            customer=customer or self.customer, device=device or self.device,
            picklist_code=code, pick_started=True, successful=successful)
        for _ in range(picked):
            ProductPick.objects.create(product=self.product, picklist=picklist,
                                       quantity=1, outcome='picked')
        for _ in range(short):
            ProductPick.objects.create(product=self.product, picklist=picklist,
                                       quantity=1, outcome='short', short_reason='other')
        for _ in range(pending):
            ProductPick.objects.create(product=self.product, picklist=picklist,
                                       quantity=1)
        return picklist

    def get(self, **params):
        return self.client.get('/api/health/outcomes/', params)


class OutcomeCounterTests(HealthOutcomesAPITestCase):
    def test_lines_left_pending_on_a_completed_list_count_as_lost(self):
        self._list('PL-OK', successful=True, picked=8, pending=2)

        outcomes = self.get().data['outcomes']

        self.assertEqual(outcomes['lists_completed'], 1)
        self.assertEqual(outcomes['lines_total'], 10)
        self.assertEqual(outcomes['lines_lost'], 2)
        self.assertEqual(outcomes['lines_lost_pct'], 20.0)

    def test_resolved_lost_lines_count_without_a_completed_parent(self):
        # Lost is a recorded outcome in its own right; it counts even when the
        # parent list still looks open (the union is the robustness check).
        picklist = self._list('PL-LOST', successful=None, picked=1, pending=1)
        ProductPick.objects.filter(picklist=picklist, outcome='pending').update(outcome='lost')

        outcomes = self.get().data['outcomes']
        self.assertEqual(outcomes['lines_lost'], 1)

    def test_short_lines_counted_separately_from_lost(self):
        self._list('PL-SHORT', successful=True, picked=3, pending=0, short=2)

        outcomes = self.get().data['outcomes']
        self.assertEqual(outcomes['lines_short'], 2)
        self.assertEqual(outcomes['lines_lost'], 0)

    def test_pending_lines_on_an_open_list_are_not_lost(self):
        self._list('PL-OPEN', successful=None, picked=1, pending=4)

        outcomes = self.get().data['outcomes']
        self.assertEqual(outcomes['lists_open'], 1)
        self.assertEqual(outcomes['lines_lost'], 0)

    def test_restarted_lists_counted(self):
        picklist = self._list('PL-R', successful=True, picked=1, pending=0)
        PickList.objects.filter(pk=picklist.pk).update(
            notes='Restarted by device Scanner 1 at 2026-10-13 21:04')

        self.assertEqual(self.get().data['outcomes']['lists_restarted'], 1)

    def test_devices_on_old_build_counted(self):
        current = self.device  # last_build_id defaults to '' -> excluded
        old_build_device = Device.objects.create(
            customer=self.customer, name='Old Phone', description='',
            last_login=timezone.now(), lists_picked=0, last_build_id='stale-build')
        self._list('PL-OLD', successful=True, picked=1, pending=0, device=old_build_device)

        response = self.get()
        self.assertIn('current_build', response.data)
        self.assertEqual(response.data['outcomes']['devices_on_old_build'], 1)


class WindowTests(HealthOutcomesAPITestCase):
    def test_default_window_is_last_24_hours(self):
        response = self.get()
        self.assertEqual(response.data['window']['preset'], '24h')

    def test_out_of_window_picks_excluded_via_backdated_pick_time(self):
        old_picklist = self._list('PL-OLD-WINDOW', successful=True, picked=1, pending=0)
        PickList.objects.filter(pk=old_picklist.pk).update(
            pick_time=timezone.now() - timedelta(days=10))
        self._list('PL-RECENT', successful=True, picked=2, pending=0)

        response = self.get()
        self.assertEqual(response.data['outcomes']['lists_total'], 1)
        self.assertEqual(response.data['outcomes']['lines_total'], 2)

    def test_date_from_date_to_reach_beyond_the_default_window(self):
        old_picklist = self._list('PL-OLD-WINDOW', successful=True, picked=1, pending=0)
        PickList.objects.filter(pk=old_picklist.pk).update(
            pick_time=timezone.now() - timedelta(days=10))

        day = (timezone.now() - timedelta(days=10)).date().isoformat()
        response = self.get(date_from=day, date_to=day)

        self.assertEqual(response.data['window']['preset'], 'custom')
        self.assertEqual(response.data['outcomes']['lists_total'], 1)

    def test_preset_param_is_honoured(self):
        response = self.get(preset='7d')
        self.assertEqual(response.data['window']['preset'], '7d')


class ScopingTests(HealthOutcomesAPITestCase):
    def test_counters_exclude_other_customers_picklists(self):
        foreign_device = Device.objects.create(
            customer=self.other_customer, name='Foreign Scanner', description='',
            last_login=timezone.now(), lists_picked=0)
        self._list('PL-FOREIGN', successful=True, picked=5, pending=0,
                   customer=self.other_customer, device=foreign_device)
        self._list('PL-MINE', successful=True, picked=1, pending=0)

        outcomes = self.get().data['outcomes']
        self.assertEqual(outcomes['lists_total'], 1)
        self.assertEqual(outcomes['lines_total'], 1)


class AuthTests(HealthOutcomesAPITestCase):
    def test_unauthenticated_request_is_rejected(self):
        anonymous_client = APIClient()
        response = anonymous_client.get('/api/health/outcomes/')
        self.assertIn(response.status_code, (401, 403))
