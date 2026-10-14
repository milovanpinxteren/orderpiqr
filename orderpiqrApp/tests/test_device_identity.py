"""Durability of the device identity, and the paths that can destroy work.

The identity is not cosmetic: a picklist lock is scoped to
(fingerprint, customer), so a phone that comes back with a new id is refused
its own list. It used to live in localStorage alone, which iOS Safari evicts
after 7 days for sites that are not installed to the home screen.
"""
import json

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from orderpiqrApp.models import (
    Customer, Device, Order, OrderLine, PickList, Product, ProductPick, ScanEvent,
    UserProfile,
)
from orderpiqrApp.utils.devices import COOKIE_KEY, get_fingerprint

FINGERPRINT = 'durable-fp'


class DeviceCookieTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Healthy Fridge')
        picker_group, _ = Group.objects.get_or_create(name='orderpicker')
        self.picker = User.objects.create_user(username='picker1', password='pw12345678')
        self.picker.groups.add(picker_group)
        UserProfile.objects.create(user=self.picker, customer=self.customer)
        self.device = Device.objects.create(
            user=self.picker, customer=self.customer, device_fingerprint=FINGERPRINT,
            name='Test phone', description='', last_login=timezone.now(), lists_picked=0)
        self.client.login(username='picker1', password='pw12345678')

    def _pin_session(self):
        session = self.client.session
        session['device_fingerprint'] = FINGERPRINT
        session.save()

    def test_scan_page_issues_the_durable_cookie(self):
        self._pin_session()
        response = self.client.get(reverse('index'))

        self.assertEqual(response.status_code, 200)
        cookie = response.cookies[COOKIE_KEY]
        self.assertEqual(cookie.value, FINGERPRINT)
        # Must stay readable by fingerprint.js, which is the whole point.
        self.assertFalse(cookie['httponly'])
        self.assertGreater(int(cookie['max-age']), 60 * 60 * 24 * 365)

    def test_cookie_rescues_a_device_whose_session_and_storage_are_gone(self):
        # The eviction case: no session fingerprint, no payload. Before the
        # cookie this fell through to name entry and registered a duplicate.
        self.client.cookies[COOKIE_KEY] = FINGERPRINT

        response = self.client.get(reverse('index'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ScanEvent.objects.filter(event_type='auth_bounce').exists())

    def test_without_the_cookie_the_picker_is_still_bounced(self):
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('name-entry', response.url)

    def test_get_fingerprint_prefers_payload_then_session_then_cookie(self):
        request = self.client.get(reverse('index')).wsgi_request

        request.session['device_fingerprint'] = 'from-session'
        request.COOKIES[COOKIE_KEY] = 'from-cookie'
        self.assertEqual(
            get_fingerprint(request, {'deviceFingerprint': 'from-payload'}),
            'from-payload')
        self.assertEqual(get_fingerprint(request), 'from-session')

        del request.session['device_fingerprint']
        self.assertEqual(get_fingerprint(request), 'from-cookie')

    def test_naming_a_device_pins_the_cookie(self):
        Device.objects.all().delete()
        response = self.client.post(reverse('name_entry'), {
            'name': 'Nonna', 'device_fingerprint': 'brand-new-fp', 'next': '/',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.cookies[COOKIE_KEY].value, 'brand-new-fp')


class ForceReclaimTests(TestCase):
    """Force-reclaiming a queued order used to delete the previous picker's
    ProductPick rows outright — the same mistake the restart path made until
    v124, on a path nobody was watching. Recorded picks are real physical work.
    """

    def setUp(self):
        self.customer = Customer.objects.create(name='Healthy Fridge')
        picker_group, _ = Group.objects.get_or_create(name='orderpicker')
        self.picker = User.objects.create_user(username='picker1', password='pw12345678')
        self.picker.groups.add(picker_group)
        UserProfile.objects.create(user=self.picker, customer=self.customer)

        self.holder = Device.objects.create(
            user=self.picker, customer=self.customer, device_fingerprint='holder-fp',
            name='Holder phone', description='', last_login=timezone.now(), lists_picked=0)
        self.claimer = Device.objects.create(
            user=self.picker, customer=self.customer, device_fingerprint='claimer-fp',
            name='Claimer phone', description='', last_login=timezone.now(), lists_picked=0)

        self.product = Product.objects.create(
            customer=self.customer, code='P-1', description='Thing')
        self.order = Order.objects.create(
            customer=self.customer, order_code='ORD-1', status='in_progress',
            queue_position=1)
        OrderLine.objects.create(order=self.order, product=self.product, quantity=3)

        self.picklist = PickList.objects.create(
            customer=self.customer, device=self.holder, picklist_code='ORD-1',
            order=self.order, pick_started=True, successful=None)
        self.done = ProductPick.objects.create(
            product=self.product, picklist=self.picklist, quantity=1, successful=True)
        self.pending = ProductPick.objects.create(
            product=self.product, picklist=self.picklist, quantity=1)

        self.client.login(username='picker1', password='pw12345678')

    def _claim(self, force):
        return self.client.post(
            reverse('queue_claim_order', args=[self.order.order_id]),
            data=json.dumps({
                'deviceFingerprint': 'claimer-fp',
                'force': force,
            }), content_type='application/json')

    def test_force_reclaim_preserves_recorded_picks(self):
        self._claim(force=True)

        self.assertTrue(ProductPick.objects.filter(pk=self.done.pk).exists())
        self.assertFalse(ProductPick.objects.filter(pk=self.pending.pk).exists())

    def test_force_reclaim_keeps_the_picklist_for_the_restart_path(self):
        # Deleting the row would lose the preserved picks with it; scan_picklist
        # adopts it instead and tells the new picker what is already done.
        self._claim(force=True)
        self.assertTrue(PickList.objects.filter(pk=self.picklist.pk).exists())

    def test_force_reclaim_is_logged_against_the_losing_device(self):
        self._claim(force=True)

        event = ScanEvent.objects.get(reason='force_reclaimed')
        self.assertEqual(event.device, self.holder)
        self.assertEqual(event.picklist_code, 'ORD-1')
        self.assertIn('Claimer phone', event.message)
        self.assertIn('1 recorded pick', event.message)

    def test_claim_rebuilds_only_the_pending_units(self):
        # The order has 3 units; one was already picked. The picker's screen
        # must show the 2 that are left, not all 3 — and the recorded one must
        # survive, which is the bug: the claim path deleted every pick row.
        response = self._claim(force=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['picklist']), 2)
        picks = ProductPick.objects.filter(picklist=self.picklist)
        self.assertEqual(picks.filter(successful=True).count(), 1)
        self.assertEqual(picks.filter(successful__isnull=True).count(), 2)

    def test_claiming_a_queued_order_is_unaffected(self):
        # No prior work: the claim must still build the full list.
        PickList.objects.all().delete()
        Order.objects.filter(pk=self.order.pk).update(status='queued')

        response = self._claim(force=False)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['picklist']), 3)

    def test_reclaim_without_force_changes_nothing(self):
        response = self._claim(force=False)

        self.assertEqual(response.status_code, 409)
        self.assertTrue(ProductPick.objects.filter(pk=self.done.pk).exists())
        self.assertTrue(ProductPick.objects.filter(pk=self.pending.pk).exists())
        self.assertFalse(ScanEvent.objects.filter(reason='force_reclaimed').exists())
