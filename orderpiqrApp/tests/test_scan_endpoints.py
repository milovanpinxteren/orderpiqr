"""The scan-picklist / complete-picklist endpoints behind the camera page.

The critical invariant: a picklist the server refuses must leave no trace — no
PickList row, and a queued order must stay queued (not locked in_progress) so
another picker can still claim it.
"""
import json

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone
from django.utils.translation import activate

from orderpiqrApp.models import (
    Customer, Device, Order, OrderLine, PickList, Product, ProductPick, UserProfile,
)

FINGERPRINT = 'test-device-fp'


class ScanEndpointTestCase(TestCase):
    def setUp(self):
        activate('en')
        self.customer = Customer.objects.create(name='Healthy Fridge')
        picker_group, _ = Group.objects.get_or_create(name='orderpicker')

        self.picker = User.objects.create_user(username='picker1', password='pw12345678')
        self.picker.groups.add(picker_group)
        UserProfile.objects.create(user=self.picker, customer=self.customer)

        self.device = Device.objects.create(
            user=self.picker, customer=self.customer, device_fingerprint=FINGERPRINT,
            name='Test phone', description='', last_login=timezone.now(), lists_picked=0)

        self.smoothie = Product.objects.create(
            customer=self.customer, code='SMOOTHIE-1', description='Green smoothie')
        self.salad = Product.objects.create(
            customer=self.customer, code='SALAD-1', description='Caesar salad')

        self.client.login(username='picker1', password='pw12345678')

    def scan(self, picklist, order_id='ORD-1'):
        return self.client.post('/orderpiqr/scan-picklist', data=json.dumps({
            'orderID': order_id,
            'picklist': picklist,
            'deviceFingerprint': FINGERPRINT,
        }), content_type='application/json')

    def complete(self, order_id='ORD-1'):
        return self.client.post('/orderpiqr/complete-picklist', data=json.dumps({
            'orderID': order_id,
            'deviceFingerprint': FINGERPRINT,
        }), content_type='application/json')


class ScanPicklistTests(ScanEndpointTestCase):
    def test_valid_scan_creates_picklist_with_picks(self):
        response = self.scan(['SMOOTHIE-1', 'SMOOTHIE-1', 'SALAD-1'])

        self.assertEqual(response.status_code, 200)
        picklist = PickList.objects.get(picklist_code='ORD-1', customer=self.customer)
        self.assertEqual(ProductPick.objects.filter(picklist=picklist).count(), 3)

    def test_unknown_product_names_the_code(self):
        response = self.scan(['SMOOTHIE-1', 'NO-SUCH-CODE'])

        self.assertEqual(response.status_code, 404)
        self.assertIn('NO-SUCH-CODE', response.json()['message'])

    def test_unknown_product_leaves_no_picklist_behind(self):
        self.scan(['SMOOTHIE-1', 'NO-SUCH-CODE'])
        self.assertFalse(PickList.objects.filter(picklist_code='ORD-1').exists())

    def test_unknown_product_does_not_lock_the_queued_order(self):
        order = Order.objects.create(
            customer=self.customer, order_code='ORD-1', status='queued', queue_position=1)
        OrderLine.objects.create(order=order, product=self.smoothie, quantity=1)

        response = self.scan(['SMOOTHIE-1', 'NO-SUCH-CODE'])

        self.assertEqual(response.status_code, 404)
        order.refresh_from_db()
        # The rejected scan must roll back the in_progress lock, or the order
        # becomes unclaimable by anyone.
        self.assertEqual(order.status, 'queued')

    def test_unknown_product_from_another_customer_is_still_unknown(self):
        other = Customer.objects.create(name='Other company')
        Product.objects.create(customer=other, code='OTHER-1', description='Not ours')

        response = self.scan(['OTHER-1'])
        self.assertEqual(response.status_code, 404)


class CompletePicklistTests(ScanEndpointTestCase):
    def test_completing_without_a_picklist_is_an_error(self):
        # Regression: this used to return 200 "ok", so a picker whose scan was
        # rejected finished a whole list believing it was recorded.
        response = self.complete('ORD-NEVER-SCANNED')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['status'], 'error')

    def test_scan_then_complete_marks_picklist_successful(self):
        self.scan(['SMOOTHIE-1'])
        response = self.complete()

        self.assertEqual(response.status_code, 200)
        picklist = PickList.objects.get(picklist_code='ORD-1', customer=self.customer)
        self.assertTrue(picklist.successful)

    def test_scan_then_complete_finishes_the_linked_order(self):
        order = Order.objects.create(
            customer=self.customer, order_code='ORD-1', status='queued', queue_position=1)
        OrderLine.objects.create(order=order, product=self.smoothie, quantity=1)

        self.scan(['SMOOTHIE-1'])
        order.refresh_from_db()
        self.assertEqual(order.status, 'in_progress')

        self.complete()
        order.refresh_from_db()
        self.assertEqual(order.status, 'completed')
