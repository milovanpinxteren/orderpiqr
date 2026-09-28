"""The queue_enabled customer setting and the stop-the-line contract.

Warehouses that only scan printed picklist QRs can switch the shared queue
off: the queue pages redirect away, claims are refused, and the start page
never lands on the queue. Independently, endpoints that discover a missing
picklist return ``error_code: picklist_not_found`` so the picker client can
block further scanning instead of losing pick after pick.
"""
import json

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import activate

from orderpiqrApp.models import (
    Customer, CustomerSettingValue, Device, Order, PickList,
    SettingDefinition, UserProfile,
)
from orderpiqrApp.utils.inventory import is_queue_enabled
from orderpiqrApp.utils.start_page import QUEUE, SETTING_KEY, resolve_start_page

FINGERPRINT = 'queue-toggle-fp'


class QueueToggleTestCase(TestCase):
    def setUp(self):
        activate('en')
        self.customer = Customer.objects.create(name='Scan-only Warehouse')
        picker_group, _ = Group.objects.get_or_create(name='orderpicker')
        self.picker = User.objects.create_user(username='picker1', password='pw12345678')
        self.picker.groups.add(picker_group)
        UserProfile.objects.create(user=self.picker, customer=self.customer)
        self.device = Device.objects.create(
            user=self.picker, customer=self.customer, device_fingerprint=FINGERPRINT,
            name='Test phone', description='', last_login=timezone.now(), lists_picked=0)
        self.client.login(username='picker1', password='pw12345678')

    def set_setting(self, key, value):
        CustomerSettingValue.objects.update_or_create(
            customer=self.customer,
            definition=SettingDefinition.objects.get(key=key),
            defaults={'value': value})

    def disable_queue(self):
        self.set_setting('queue_enabled', 'false')

    def make_order(self, code='Q-1'):
        return Order.objects.create(
            customer=self.customer, order_code=code, status='queued')


class QueueEnabledSettingTests(QueueToggleTestCase):
    def test_default_is_enabled(self):
        self.assertTrue(is_queue_enabled(self.customer))
        response = self.client.get(reverse('queue_display'))
        self.assertEqual(response.status_code, 200)

    def test_disabled_redirects_picker_page_to_scan(self):
        self.disable_queue()
        self.assertFalse(is_queue_enabled(self.customer))
        response = self.client.get(reverse('queue_picker'))
        # The scan page may itself redirect (device registration), so only
        # the immediate target matters here.
        self.assertRedirects(response, reverse('index'), fetch_redirect_response=False)

    def test_disabled_redirects_display_page(self):
        self.disable_queue()
        response = self.client.get(reverse('queue_display'))
        self.assertRedirects(response, reverse('index'), fetch_redirect_response=False)

    def test_disabled_blocks_claim(self):
        """Even with a direct POST (stale tab, old bookmark) the claim must be
        refused — this is the mistake that stranded a whole picked list."""
        self.disable_queue()
        order = self.make_order()
        response = self.client.post(
            reverse('queue_claim_order', args=[order.order_id]),
            data=json.dumps({'deviceFingerprint': FINGERPRINT}),
            content_type='application/json')
        self.assertEqual(response.status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, 'queued')
        self.assertFalse(PickList.objects.filter(customer=self.customer).exists())

    def test_enabled_claim_still_works(self):
        order = self.make_order()
        response = self.client.post(
            reverse('queue_claim_order', args=[order.order_id]),
            data=json.dumps({'deviceFingerprint': FINGERPRINT}),
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, 'in_progress')
        self.assertTrue(PickList.objects.filter(
            customer=self.customer, picklist_code='Q-1', device=self.device).exists())

    def test_start_page_queue_choice_falls_back_to_scan(self):
        self.set_setting(SETTING_KEY, QUEUE)
        self.assertEqual(resolve_start_page(self.customer), reverse('queue_picker'))
        self.disable_queue()
        self.assertEqual(resolve_start_page(self.customer), reverse('index'))


class StopTheLineContractTests(QueueToggleTestCase):
    """product-pick / bulk-product-pick / complete-picklist must name a
    missing picklist explicitly — the client blocks scanning on this code."""

    def test_product_pick_flags_missing_picklist(self):
        response = self.client.post('/orderpiqr/product-pick', data=json.dumps({
            'orderID': 'GONE-1',
            'productCode': 'ANY',
            'deviceFingerprint': FINGERPRINT,
            'successful': True,
            'timeTakenMs': 1000,
        }), content_type='application/json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get('error_code'), 'picklist_not_found')

    def test_bulk_product_pick_flags_missing_picklist(self):
        response = self.client.post('/orderpiqr/bulk-product-pick', data=json.dumps({
            'orderID': 'GONE-1',
            'productCode': 'ANY',
            'deviceFingerprint': FINGERPRINT,
            'quantity': 2,
            'timeTakenMs': 1000,
        }), content_type='application/json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get('error_code'), 'picklist_not_found')

    def test_complete_picklist_flags_missing_picklist(self):
        response = self.client.post('/orderpiqr/complete-picklist', data=json.dumps({
            'orderID': 'GONE-1',
            'deviceFingerprint': FINGERPRINT,
        }), content_type='application/json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get('error_code'), 'picklist_not_found')
