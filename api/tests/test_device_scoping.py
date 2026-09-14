"""Device endpoints are scoped to the caller's customer.

A fingerprint identifies hardware and may be registered for several customers,
so neither registration nor claiming may reach across a tenant boundary.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from orderpiqrApp.models import Customer, Device, Order, OrderLine, Product, UserProfile

FINGERPRINT = 'shared-fingerprint-abc123'


class DeviceScopingTestCase(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Warehouse A')
        self.user = User.objects.create_user(username='picker-a', password='x')
        UserProfile.objects.create(user=self.user, customer=self.customer)

        self.other_customer = Customer.objects.create(name='Warehouse B')
        self.other_user = User.objects.create_user(username='picker-b', password='x')
        UserProfile.objects.create(user=self.other_user, customer=self.other_customer)

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _make_device(self, customer, user):
        return Device.objects.create(
            user=user,
            device_fingerprint=FINGERPRINT,
            name='Shared tablet',
            description='',
            customer=customer,
            last_login=timezone.now(),
            lists_picked=0,
        )

    def _make_queued_order(self, customer):
        order = Order.objects.create(
            customer=customer, order_code='A-20260915', status='queued', queue_position=1)
        product = Product.objects.create(
            customer=customer, code='8710400011', description='Yoghurt', location='A1')
        OrderLine.objects.create(order=order, product=product, quantity=1)
        return order

    def test_register_creates_own_row_when_fingerprint_exists_elsewhere(self):
        foreign = self._make_device(self.other_customer, self.other_user)

        response = self.client.post(
            '/api/devices/register/', {'device_fingerprint': FINGERPRINT, 'name': 'My phone'}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['created'])
        self.assertNotEqual(response.data['device_id'], foreign.device_id)

        foreign.refresh_from_db()
        self.assertEqual(foreign.customer_id, self.other_customer.pk)
        self.assertEqual(foreign.user_id, self.other_user.pk)

    def test_register_is_idempotent_within_a_customer(self):
        first = self.client.post(
            '/api/devices/register/', {'device_fingerprint': FINGERPRINT}, format='json')
        second = self.client.post(
            '/api/devices/register/', {'device_fingerprint': FINGERPRINT}, format='json')

        self.assertTrue(first.data['created'])
        self.assertFalse(second.data['created'])
        self.assertEqual(first.data['device_id'], second.data['device_id'])

    def test_claim_rejects_another_customers_device(self):
        self._make_device(self.other_customer, self.other_user)
        order = self._make_queued_order(self.customer)

        response = self.client.post(
            f'/api/queue/claim/{order.order_id}/', {'deviceFingerprint': FINGERPRINT}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('Device not found', response.data['detail'])
        order.refresh_from_db()
        self.assertEqual(order.status, 'queued')

    def test_claim_accepts_own_device_with_the_same_fingerprint(self):
        self._make_device(self.other_customer, self.other_user)
        self._make_device(self.customer, self.user)
        order = self._make_queued_order(self.customer)

        response = self.client.post(
            f'/api/queue/claim/{order.order_id}/', {'deviceFingerprint': FINGERPRINT}, format='json')

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, 'in_progress')

    def test_create_rejects_duplicate_fingerprint_within_customer(self):
        self._make_device(self.customer, self.user)

        response = self.client.post(
            '/api/devices/', {'name': 'Second', 'description': '', 'device_fingerprint': FINGERPRINT},
            format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('device_fingerprint', response.data)
