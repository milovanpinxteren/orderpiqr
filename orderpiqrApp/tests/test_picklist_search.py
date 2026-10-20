"""Search-and-claim: finding an order by code when its QR will not scan.

Phones that cannot read a dense picklist QR need a way in that does not
involve the camera. ``picklist_search_enabled`` opens one: the picker types
part of the order code, picks the order from a short list and claims it
through the queue's existing claim endpoint. The tests below pin the two
things that make that safe — the search only ever shows recent, claimable
orders belonging to this customer, and the claim gate opens for either
feature instead of for the queue alone.
"""
import json
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import activate

from orderpiqrApp.models import (
    Customer, CustomerSettingValue, Device, Order, OrderLine, PickList,
    Product, SettingDefinition, UserProfile,
)
from orderpiqrApp.utils.inventory import is_picklist_search_enabled

FINGERPRINT = 'picklist-search-fp'


class PicklistSearchTestCase(TestCase):
    def setUp(self):
        activate('en')
        self.customer = Customer.objects.create(name='Search Warehouse')
        self.other_customer = Customer.objects.create(name='Someone Else')
        picker_group, _ = Group.objects.get_or_create(name='orderpicker')
        self.picker = User.objects.create_user(username='picker1', password='pw12345678')
        self.picker.groups.add(picker_group)
        UserProfile.objects.create(user=self.picker, customer=self.customer)
        self.device = Device.objects.create(
            user=self.picker, customer=self.customer, device_fingerprint=FINGERPRINT,
            name='Test phone', description='', last_login=timezone.now(), lists_picked=0)
        self.product = Product.objects.create(
            code='P-1', description='Widget', location='A1', customer=self.customer)
        self.client.login(username='picker1', password='pw12345678')

    def set_setting(self, key, value):
        CustomerSettingValue.objects.update_or_create(
            customer=self.customer,
            definition=SettingDefinition.objects.get(key=key),
            defaults={'value': value})

    def enable_search(self):
        self.set_setting('picklist_search_enabled', 'true')

    def make_order(self, code='SO-1', status='queued', customer=None, days_ago=0,
                   lines=()):
        order = Order.objects.create(
            customer=customer or self.customer, order_code=code, status=status)
        for product, quantity in lines:
            OrderLine.objects.create(order=order, product=product, quantity=quantity)
        if days_ago:
            # created_at is auto_now_add, so backdating has to bypass save().
            Order.objects.filter(pk=order.pk).update(
                created_at=timezone.now() - timedelta(days=days_ago))
            order.refresh_from_db()
        return order

    def search(self, q=None):
        return self.client.get(reverse('picklist_search'), data={} if q is None else {'q': q})

    def codes(self, response):
        return [row['order_code'] for row in response.json()['results']]


class PicklistSearchToggleTests(PicklistSearchTestCase):
    def test_default_is_disabled(self):
        self.assertFalse(is_picklist_search_enabled(self.customer))

    def test_disabled_returns_403(self):
        self.make_order()
        response = self.search()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['status'], 'error')

    def test_enabled_returns_results(self):
        self.enable_search()
        self.make_order(lines=[(self.product, 3)])
        response = self.search()
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(len(payload['results']), 1)
        row = payload['results'][0]
        self.assertEqual(row['order_code'], 'SO-1')
        self.assertEqual(row['status'], 'queued')
        self.assertEqual(row['line_count'], 1)
        self.assertEqual(row['item_count'], 3)
        self.assertIsNone(row['picked_by'])
        self.assertTrue(row['created_at'])


class PicklistSearchResultTests(PicklistSearchTestCase):
    def setUp(self):
        super().setUp()
        self.enable_search()

    def test_q_filters_by_substring(self):
        self.make_order(code='ORD-1001')
        self.make_order(code='ORD-2002')
        self.assertEqual(self.codes(self.search('1001')), ['ORD-1001'])
        self.assertEqual(sorted(self.codes(self.search('ORD'))), ['ORD-1001', 'ORD-2002'])
        self.assertEqual(self.codes(self.search('nothing-like-this')), [])

    def test_blank_q_lists_everything_claimable(self):
        self.make_order(code='ORD-1001')
        self.make_order(code='ORD-2002')
        self.assertEqual(sorted(self.codes(self.search('   '))), ['ORD-1001', 'ORD-2002'])

    def test_other_customers_orders_are_invisible(self):
        self.make_order(code='MINE-1')
        self.make_order(code='THEIRS-1', customer=self.other_customer)
        self.assertEqual(self.codes(self.search()), ['MINE-1'])

    def test_unclaimable_statuses_are_excluded(self):
        self.make_order(code='QUEUED-1', status='queued')
        self.make_order(code='PROGRESS-1', status='in_progress')
        self.make_order(code='DRAFT-1', status='draft')
        self.make_order(code='DONE-1', status='completed')
        self.make_order(code='GONE-1', status='cancelled')
        self.assertEqual(sorted(self.codes(self.search())), ['PROGRESS-1', 'QUEUED-1'])

    def test_stale_orders_are_excluded(self):
        self.make_order(code='FRESH-1', days_ago=1)
        self.make_order(code='STALE-1', days_ago=5)
        self.assertEqual(self.codes(self.search()), ['FRESH-1'])

    def test_stale_orders_stay_excluded_when_searched_by_code(self):
        """Prod holds hundreds of weeks-old queued orders; typing the code of
        one must not be a way around the window."""
        self.make_order(code='STALE-1', days_ago=5)
        self.assertEqual(self.codes(self.search('STALE-1')), [])

    def test_picked_by_names_the_holding_device(self):
        order = self.make_order(code='HELD-1', status='in_progress')
        PickList.objects.create(
            customer=self.customer, order=order, picklist_code='HELD-1',
            device=self.device, pick_started=True)
        row = self.search().json()['results'][0]
        self.assertEqual(row['order_code'], 'HELD-1')
        self.assertEqual(row['picked_by'], 'Test phone')


class PicklistSearchClaimGateTests(PicklistSearchTestCase):
    """Claiming is shared with the queue, so its gate must open for either
    feature — a searchable order that cannot be claimed is a dead end."""

    def claim(self, order):
        return self.client.post(
            reverse('queue_claim_order', args=[order.order_id]),
            data=json.dumps({'deviceFingerprint': FINGERPRINT}),
            content_type='application/json')

    def test_claim_allowed_with_queue_off_and_search_on(self):
        self.set_setting('queue_enabled', 'false')
        self.enable_search()
        order = self.make_order(lines=[(self.product, 2)])
        response = self.claim(order)
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, 'in_progress')
        self.assertTrue(PickList.objects.filter(
            customer=self.customer, picklist_code='SO-1', device=self.device).exists())

    def test_claim_refused_when_both_features_are_off(self):
        self.set_setting('queue_enabled', 'false')
        order = self.make_order()
        response = self.claim(order)
        self.assertEqual(response.status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, 'queued')
        self.assertFalse(PickList.objects.filter(customer=self.customer).exists())
