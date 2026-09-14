"""Device identity is per-customer, not global.

The same phone or shared tablet may be registered for several customers, so a
fingerprint is unique per customer and every lookup scopes on it. These tests
pin the behaviour that used to strand a device on whichever customer registered
it first.
"""
import json

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import activate

from orderpiqrApp.models import Customer, Device, Order, OrderLine, Product, UserProfile

FINGERPRINT = 'shared-fingerprint-abc123'


class DeviceResolutionTests(TestCase):
    def setUp(self):
        activate('en')
        self.picker_group, _ = Group.objects.get_or_create(name='orderpicker')

        self.customer = Customer.objects.create(name='Healthy Fridge')
        self.other_customer = Customer.objects.create(name='Other Company')

        self.picker = User.objects.create_user(username='picker1', password='secret123')
        self.picker.groups.add(self.picker_group)
        UserProfile.objects.create(user=self.picker, customer=self.customer)

        self.other_picker = User.objects.create_user(username='picker2', password='secret123')
        self.other_picker.groups.add(self.picker_group)
        UserProfile.objects.create(user=self.other_picker, customer=self.other_customer)

    def _make_device(self, customer, user, fingerprint=FINGERPRINT, name='Test phone'):
        return Device.objects.create(
            user=user,
            device_fingerprint=fingerprint,
            name=name,
            description='',
            customer=customer,
            last_login=timezone.now(),
            lists_picked=0,
        )

    def _make_queued_order(self, customer, order_code='HF01-20260915'):
        order = Order.objects.create(
            customer=customer,
            order_code=order_code,
            status='queued',
            queue_position=1,
        )
        product = Product.objects.create(
            customer=customer, code='8710400011', description='Yoghurt', location='A1')
        OrderLine.objects.create(order=order, product=product, quantity=2)
        return order

    def _claim(self, order, fingerprint=FINGERPRINT):
        return self.client.post(
            reverse('queue_claim_order', args=[order.order_id]),
            data=json.dumps({'deviceFingerprint': fingerprint}),
            content_type='application/json',
        )

    # --- the model ------------------------------------------------------

    def test_same_fingerprint_can_be_registered_for_two_customers(self):
        first = self._make_device(self.other_customer, self.other_picker)
        second = self._make_device(self.customer, self.picker)

        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(Device.objects.filter(device_fingerprint=FINGERPRINT).count(), 2)

    # --- the reported bug ------------------------------------------------

    def test_picker_can_claim_when_fingerprint_belongs_to_another_customer(self):
        """The device row of another customer must not block registration here."""
        stranded = self._make_device(self.other_customer, self.other_picker, name='Other phone')
        order = self._make_queued_order(self.customer)

        self.client.login(username='picker1', password='secret123')
        self.client.post(reverse('name_entry'), {
            'name': 'Milo',
            'device_fingerprint': FINGERPRINT,
            'next': '/',
        })

        response = self._claim(order)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')

        order.refresh_from_db()
        self.assertEqual(order.status, 'in_progress')

        # The other customer's device was left completely alone.
        stranded.refresh_from_db()
        self.assertEqual(stranded.customer_id, self.other_customer.pk)
        self.assertEqual(stranded.user_id, self.other_picker.pk)
        self.assertEqual(stranded.name, 'Other phone')

    def test_name_entry_registers_device_for_the_pickers_own_customer(self):
        self._make_device(self.other_customer, self.other_picker)

        self.client.login(username='picker1', password='secret123')
        self.client.post(reverse('name_entry'), {
            'name': 'Milo',
            'device_fingerprint': FINGERPRINT,
            'next': '/',
        })

        device = Device.objects.get(device_fingerprint=FINGERPRINT, customer=self.customer)
        self.assertEqual(device.name, 'Milo')
        self.assertEqual(device.user_id, self.picker.pk)
        self.assertEqual(self.client.session['device_fingerprint'], FINGERPRINT)

    # --- follow-ons ------------------------------------------------------

    def test_login_pins_fingerprint_even_without_a_registered_device(self):
        """Without this the session fallback is dead on a first login."""
        response = self.client.post(reverse('login'), {
            'username': 'picker1',
            'password': 'secret123',
            'device_fingerprint': FINGERPRINT,
        })

        self.assertRedirects(response, reverse('name_entry'), fetch_redirect_response=False)
        self.assertEqual(self.client.session['device_fingerprint'], FINGERPRINT)

    def test_claim_self_heals_when_no_device_is_registered_yet(self):
        order = self._make_queued_order(self.customer)
        self.client.login(username='picker1', password='secret123')

        response = self._claim(order)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        self.assertTrue(
            Device.objects.filter(device_fingerprint=FINGERPRINT, customer=self.customer).exists())

    def test_claim_without_any_fingerprint_points_at_name_entry(self):
        order = self._make_queued_order(self.customer)
        self.client.login(username='picker1', password='secret123')

        response = self.client.post(
            reverse('queue_claim_order', args=[order.order_id]),
            data=json.dumps({}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(reverse('name_entry'), response.json()['redirect_url'])

    def test_claim_does_not_use_another_customers_device(self):
        """Self-heal must register a new device, never adopt the foreign row."""
        foreign = self._make_device(self.other_customer, self.other_picker)
        order = self._make_queued_order(self.customer)

        self.client.login(username='picker1', password='secret123')
        response = self._claim(order)

        self.assertEqual(response.status_code, 200)
        picklist = order.picklist_set.get()
        self.assertNotEqual(picklist.device_id, foreign.pk)
        self.assertEqual(picklist.device.customer_id, self.customer.pk)

    def test_name_entry_requires_login(self):
        response = self.client.get(reverse('name_entry'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_queue_picker_sends_unregistered_device_to_name_entry(self):
        self.client.login(username='picker1', password='secret123')
        response = self.client.get(reverse('queue_picker'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('name_entry'), response.url)
