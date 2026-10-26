"""The scan-picklist / complete-picklist endpoints behind the camera page.

The critical invariant: a picklist the server refuses must leave no trace — no
PickList row, and a queued order must stay queued (not locked in_progress) so
another picker can still claim it.
"""
import json
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone
from django.utils.translation import activate

from orderpiqrApp.models import (
    Customer, Device, Order, OrderLine, PickList, Product, ProductPick, ScanEvent,
    UserProfile,
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

    def test_rescan_by_same_device_restarts_instead_of_409(self):
        # Regression: a steady phone re-scans the picklist QR a second later;
        # the order was already in_progress from the first scan and the 409
        # made the client wipe the picker's list.
        order = Order.objects.create(
            customer=self.customer, order_code='ORD-1', status='queued', queue_position=1)
        OrderLine.objects.create(order=order, product=self.smoothie, quantity=1)

        self.scan(['SMOOTHIE-1'])
        response = self.scan(['SMOOTHIE-1'])

        self.assertEqual(response.status_code, 200)
        picklist = PickList.objects.get(picklist_code='ORD-1', customer=self.customer)
        self.assertEqual(ProductPick.objects.filter(picklist=picklist).count(), 1)

    def test_restart_preserves_recorded_picks(self):
        # A restart (same device re-scans its list, e.g. after the app
        # reloaded or a stop-the-line overlay) must not erase recorded work:
        # successful rows survive, only pending rows are rebuilt, and the
        # client is told what was kept so it can shorten the list on screen.
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1', 'SALAD-1'])
        self.client.post('/orderpiqr/product-pick', data=json.dumps({
            'orderID': 'ORD-1', 'productCode': 'SMOOTHIE-1',
            'deviceFingerprint': FINGERPRINT, 'timeTakenMs': 500,
        }), content_type='application/json')

        response = self.scan(['SMOOTHIE-1', 'SMOOTHIE-1', 'SALAD-1'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['already_picked'], {'SMOOTHIE-1': 1})
        picklist = PickList.objects.get(picklist_code='ORD-1', customer=self.customer)
        picks = ProductPick.objects.filter(picklist=picklist)
        self.assertEqual(picks.count(), 3)
        self.assertEqual(picks.filter(outcome='picked').count(), 1)
        self.assertEqual(picks.filter(outcome='pending').count(), 2)

    def test_restart_without_recorded_picks_keeps_nothing(self):
        self.scan(['SMOOTHIE-1'])
        response = self.scan(['SMOOTHIE-1'])
        self.assertEqual(response.json()['already_picked'], {})
        self.assertEqual(response.json()['already_short'], {})

    def test_restart_preserves_short_rows(self):
        # A declared short is recorded work exactly like a pick: it must
        # survive a restart and be reported separately so the client can
        # render it as short, not as picked.
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1', 'SALAD-1'])
        self.client.post('/orderpiqr/product-pick', data=json.dumps({
            'orderID': 'ORD-1', 'productCode': 'SMOOTHIE-1',
            'deviceFingerprint': FINGERPRINT, 'successful': False,
            'shortReason': 'not_found',
        }), content_type='application/json')

        response = self.scan(['SMOOTHIE-1', 'SMOOTHIE-1', 'SALAD-1'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['already_picked'], {})
        self.assertEqual(response.json()['already_short'], {'SMOOTHIE-1': 1})
        picklist = PickList.objects.get(picklist_code='ORD-1', customer=self.customer)
        picks = ProductPick.objects.filter(picklist=picklist)
        self.assertEqual(picks.count(), 3)
        short = picks.get(outcome='short')
        self.assertEqual(short.short_reason, 'not_found')
        self.assertEqual(picks.filter(outcome='pending').count(), 2)

    def test_scan_of_order_held_by_other_device_is_rejected(self):
        order = Order.objects.create(
            customer=self.customer, order_code='ORD-1', status='queued', queue_position=1)
        OrderLine.objects.create(order=order, product=self.smoothie, quantity=1)
        self.scan(['SMOOTHIE-1'])

        other_device = Device.objects.create(
            user=self.picker, customer=self.customer, device_fingerprint='other-fp',
            name='Other phone', description='', last_login=timezone.now(), lists_picked=0)
        response = self.client.post('/orderpiqr/scan-picklist', data=json.dumps({
            'orderID': 'ORD-1',
            'picklist': ['SMOOTHIE-1'],
            'deviceFingerprint': 'other-fp',
        }), content_type='application/json')

        self.assertEqual(response.status_code, 409)
        # The first device's picklist must survive the rejected takeover.
        picklist = PickList.objects.get(picklist_code='ORD-1', customer=self.customer)
        self.assertEqual(picklist.device, self.device)

    def _held_order(self, picklist=('SMOOTHIE-1',)):
        """Scan ORD-1 as self.device so the order is locked in_progress.

        The holder check only runs for order-backed picklists, so the Order row
        is what makes a lock exist at all.
        """
        order = Order.objects.create(
            customer=self.customer, order_code='ORD-1', status='queued', queue_position=1)
        OrderLine.objects.create(order=order, product=self.smoothie, quantity=1)
        self.scan(list(picklist))
        return order

    def _other_device(self, last_login):
        return Device.objects.create(
            user=self.picker, customer=self.customer, device_fingerprint='other-fp',
            name='Other phone', description='', last_login=last_login, lists_picked=0)

    def _scan_as_other(self, picklist=('SMOOTHIE-1',)):
        return self.client.post('/orderpiqr/scan-picklist', data=json.dumps({
            'orderID': 'ORD-1',
            'picklist': list(picklist),
            'deviceFingerprint': 'other-fp',
        }), content_type='application/json')

    def test_stale_lock_is_handed_over_to_the_rescanning_device(self):
        # A device identity is only a localStorage UUID, so a picker whose
        # storage was evicted returns as "another device" and was locked out of
        # their own list forever. Once the holder has gone quiet, hand it over.
        self._held_order(['SMOOTHIE-1', 'SALAD-1'])
        Device.objects.filter(pk=self.device.pk).update(
            last_login=timezone.now() - timedelta(minutes=45))
        self._other_device(last_login=timezone.now())

        response = self._scan_as_other(['SMOOTHIE-1', 'SALAD-1'])

        self.assertEqual(response.status_code, 200)
        picklist = PickList.objects.get(picklist_code='ORD-1', customer=self.customer)
        self.assertEqual(picklist.device.device_fingerprint, 'other-fp')

    def test_stale_lock_takeover_preserves_recorded_picks(self):
        self._held_order(['SMOOTHIE-1', 'SMOOTHIE-1', 'SALAD-1'])
        self.client.post('/orderpiqr/product-pick', data=json.dumps({
            'orderID': 'ORD-1', 'productCode': 'SMOOTHIE-1',
            'deviceFingerprint': FINGERPRINT, 'timeTakenMs': 500,
        }), content_type='application/json')
        Device.objects.filter(pk=self.device.pk).update(
            last_login=timezone.now() - timedelta(hours=2))
        self._other_device(last_login=timezone.now())

        response = self._scan_as_other(['SMOOTHIE-1', 'SMOOTHIE-1', 'SALAD-1'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['already_picked'], {'SMOOTHIE-1': 1})
        picklist = PickList.objects.get(picklist_code='ORD-1', customer=self.customer)
        self.assertEqual(
            ProductPick.objects.filter(picklist=picklist, outcome='picked').count(), 1)

    def test_stale_lock_takeover_is_logged(self):
        self._held_order()
        Device.objects.filter(pk=self.device.pk).update(
            last_login=timezone.now() - timedelta(minutes=30))
        self._other_device(last_login=timezone.now())

        self._scan_as_other()

        event = ScanEvent.objects.get(event_type='lock_takeover')
        self.assertEqual(event.picklist_code, 'ORD-1')
        self.assertIn('Test phone', event.message)

    def test_live_holder_still_blocks_and_is_logged_as_rejected(self):
        self._held_order()
        self._other_device(last_login=timezone.now())

        response = self._scan_as_other()

        self.assertEqual(response.status_code, 409)
        self.assertTrue(ScanEvent.objects.filter(event_type='picklist_rejected').exists())
        self.assertFalse(ScanEvent.objects.filter(event_type='lock_takeover').exists())

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
