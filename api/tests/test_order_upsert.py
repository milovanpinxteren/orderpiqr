"""Tests for POST /api/orders/upsert/ — the desired-state bulk sync endpoint
used by external portals (e.g. the HF Portal picklist push).
"""
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from drf_hashed_token.models import HashedToken
from orderpiqrApp.models import Customer, Order, OrderLine, Product, UserProfile

UPSERT_URL = '/api/orders/upsert/'


class OrderUpsertTestCase(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Warehouse A')
        self.user = User.objects.create_user(username='hfportal', password='x')
        UserProfile.objects.create(user=self.user, customer=self.customer)

        self.other_customer = Customer.objects.create(name='Warehouse B')
        other_user = User.objects.create_user(username='other', password='x')
        UserProfile.objects.create(user=other_user, customer=self.other_customer)

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def post(self, payload):
        return self.client.post(UPSERT_URL, payload, format='json')

    @staticmethod
    def order_payload(order_code, lines, **extra):
        return {'order_code': order_code, 'lines': lines, **extra}

    def test_creates_orders_and_products(self):
        response = self.post({
            'source': 'hfportal',
            'orders': [
                self.order_payload('AMS01-20260915', [
                    {'code': '8712345678906', 'quantity': 12, 'description': 'Broodje', 'location': '16'},
                    {'code': '101', 'quantity': 3, 'description': 'Muffin', 'location': '2'},
                ]),
            ],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['created'], ['AMS01-20260915'])
        self.assertEqual(response.data['products_created'], 2)

        order = Order.objects.get(customer=self.customer, order_code='AMS01-20260915')
        self.assertEqual(order.status, 'draft')
        self.assertEqual(order.source, 'hfportal')
        self.assertIsNone(order.queue_position)
        self.assertEqual(order.lines.count(), 2)

        product = Product.objects.get(customer=self.customer, code='8712345678906')
        self.assertEqual(product.description, 'Broodje')
        self.assertEqual(product.location, '16')

    def test_updates_existing_draft_replacing_lines(self):
        old_product = Product.objects.create(
            customer=self.customer, code='OLD', description='Old', location='1')
        order = Order.objects.create(
            customer=self.customer, order_code='AMS01-20260915', status='draft')
        OrderLine.objects.create(order=order, product=old_product, quantity=5)

        response = self.post({
            'orders': [
                self.order_payload('AMS01-20260915', [
                    {'code': 'NEW', 'quantity': 7, 'description': 'New', 'location': '3'},
                ]),
            ],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['updated'], ['AMS01-20260915'])

        order.refresh_from_db()
        self.assertEqual(order.lines.count(), 1)
        line = order.lines.get()
        self.assertEqual(line.product.code, 'NEW')
        self.assertEqual(line.quantity, 7)

    def test_updates_product_description_and_location(self):
        Product.objects.create(
            customer=self.customer, code='101', description='Old name', location='99')

        self.post({
            'orders': [
                self.order_payload('X-1', [
                    {'code': '101', 'quantity': 1, 'description': 'New name', 'location': '4'},
                ]),
            ],
        })
        product = Product.objects.get(customer=self.customer, code='101')
        self.assertEqual(product.description, 'New name')
        self.assertEqual(product.location, '4')
        self.assertEqual(Product.objects.filter(customer=self.customer, code='101').count(), 1)

    def test_promotes_to_queued_with_positions(self):
        self.post({
            'orders': [
                self.order_payload('A-1', [{'code': 'P1', 'quantity': 1}]),
            ],
        })
        response = self.post({
            'orders': [
                self.order_payload('A-1', [{'code': 'P1', 'quantity': 1}],
                                   status='queued', queue_position=2),
                self.order_payload('A-2', [{'code': 'P1', 'quantity': 4}],
                                   status='queued', queue_position=1),
            ],
        })
        self.assertEqual(response.status_code, 200)
        order_1 = Order.objects.get(customer=self.customer, order_code='A-1')
        order_2 = Order.objects.get(customer=self.customer, order_code='A-2')
        self.assertEqual((order_1.status, order_1.queue_position), ('queued', 2))
        self.assertEqual((order_2.status, order_2.queue_position), ('queued', 1))

    def test_queued_without_position_appends_to_queue(self):
        Order.objects.create(customer=self.customer, order_code='EXISTING',
                             status='queued', queue_position=5)
        self.post({
            'orders': [
                self.order_payload('A-1', [{'code': 'P1', 'quantity': 1}], status='queued'),
            ],
        })
        order = Order.objects.get(customer=self.customer, order_code='A-1')
        self.assertEqual(order.queue_position, 6)

    def test_in_progress_and_completed_are_skipped(self):
        product = Product.objects.create(
            customer=self.customer, code='P1', description='P1', location='1')
        for code, order_status in [('BUSY-1', 'in_progress'), ('DONE-1', 'completed')]:
            order = Order.objects.create(
                customer=self.customer, order_code=code, status=order_status)
            OrderLine.objects.create(order=order, product=product, quantity=9)

        response = self.post({
            'orders': [
                self.order_payload('BUSY-1', [{'code': 'P1', 'quantity': 1}]),
                self.order_payload('DONE-1', [{'code': 'P1', 'quantity': 1}]),
            ],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['skipped'], [
            {'order_code': 'BUSY-1', 'status': 'in_progress'},
            {'order_code': 'DONE-1', 'status': 'completed'},
        ])
        for code in ['BUSY-1', 'DONE-1']:
            order = Order.objects.get(customer=self.customer, order_code=code)
            self.assertEqual(order.lines.get().quantity, 9)

    def test_empty_lines_cancels_order(self):
        Order.objects.create(customer=self.customer, order_code='GONE-1',
                             status='queued', queue_position=1)
        response = self.post({
            'orders': [self.order_payload('GONE-1', [])],
        })
        self.assertEqual(response.data['cancelled'], ['GONE-1'])
        order = Order.objects.get(customer=self.customer, order_code='GONE-1')
        self.assertEqual(order.status, 'cancelled')
        self.assertIsNone(order.queue_position)

    def test_cancelled_order_is_resurrected(self):
        Order.objects.create(customer=self.customer, order_code='BACK-1', status='cancelled')
        response = self.post({
            'orders': [
                self.order_payload('BACK-1', [{'code': 'P1', 'quantity': 2}], status='queued'),
            ],
        })
        self.assertEqual(response.data['updated'], ['BACK-1'])
        order = Order.objects.get(customer=self.customer, order_code='BACK-1')
        self.assertEqual(order.status, 'queued')

    def test_prune_cancels_stale_same_source_orders_only(self):
        for code in ['KEEP-20260915', 'STALE-20260915']:
            Order.objects.create(customer=self.customer, order_code=code,
                                 status='queued', queue_position=1, source='hfportal')
        # Different source and different suffix must both survive.
        Order.objects.create(customer=self.customer, order_code='MANUAL-20260915',
                             status='draft', source='manual')
        Order.objects.create(customer=self.customer, order_code='STALE-20260916',
                             status='draft', source='hfportal')
        # Started orders are never pruned.
        Order.objects.create(customer=self.customer, order_code='BUSY-20260915',
                             status='in_progress', source='hfportal')

        response = self.post({
            'source': 'hfportal',
            'orders': [
                self.order_payload('KEEP-20260915', [{'code': 'P1', 'quantity': 1}],
                                   status='queued', queue_position=1),
            ],
            'prune': {'order_code_suffix': '-20260915'},
        })
        self.assertEqual(response.data['cancelled'], ['STALE-20260915'])
        self.assertEqual(
            Order.objects.get(customer=self.customer, order_code='STALE-20260915').status,
            'cancelled')
        for code, expected in [('KEEP-20260915', 'queued'), ('MANUAL-20260915', 'draft'),
                               ('STALE-20260916', 'draft'), ('BUSY-20260915', 'in_progress')]:
            self.assertEqual(
                Order.objects.get(customer=self.customer, order_code=code).status, expected)

    def test_tenant_isolation(self):
        Order.objects.create(customer=self.other_customer, order_code='SHARED-1',
                             status='draft', source='hfportal')
        Product.objects.create(customer=self.other_customer, code='P1',
                               description='Other tenant product', location='9')

        self.post({
            'orders': [
                self.order_payload('SHARED-1', [{'code': 'P1', 'quantity': 1, 'description': 'Mine'}]),
            ],
        })
        # Both tenants now have their own SHARED-1 order and P1 product.
        self.assertEqual(Order.objects.filter(order_code='SHARED-1').count(), 2)
        other_product = Product.objects.get(customer=self.other_customer, code='P1')
        self.assertEqual(other_product.description, 'Other tenant product')

    def test_idempotent_repost(self):
        payload = {
            'orders': [
                self.order_payload('A-1', [
                    {'code': 'P1', 'quantity': 3, 'description': 'P1', 'location': '1'},
                ]),
            ],
        }
        self.post(payload)
        response = self.post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['updated'], ['A-1'])
        self.assertEqual(response.data['products_created'], 0)
        self.assertEqual(response.data['products_updated'], 0)
        self.assertEqual(Product.objects.filter(customer=self.customer, code='P1').count(), 1)
        self.assertEqual(OrderLine.objects.filter(order__order_code='A-1').count(), 1)

    def test_bad_order_reported_others_applied(self):
        response = self.post({
            'orders': [
                self.order_payload('OK-1', [{'code': 'P1', 'quantity': 1}]),
                self.order_payload('BAD-1', [{'quantity': 1}]),  # missing product code
            ],
        })
        self.assertEqual(response.status_code, 207)
        self.assertEqual(response.data['created'], ['OK-1'])
        self.assertEqual(len(response.data['errors']), 1)
        self.assertEqual(response.data['errors'][0]['order_code'], 'BAD-1')
        self.assertFalse(
            Order.objects.filter(customer=self.customer, order_code='BAD-1').exists())

    def test_no_orders_is_bad_request(self):
        response = self.post({'orders': []})
        self.assertEqual(response.status_code, 400)


class HashedTokenAuthTestCase(TestCase):
    """The upsert endpoint must be reachable with a hashed API token (no JWT dance)."""

    def setUp(self):
        self.customer = Customer.objects.create(name='Warehouse A')
        self.user = User.objects.create_user(username='hfportal', password='x')
        UserProfile.objects.create(user=self.user, customer=self.customer)

        raw_token, key_hash = HashedToken.generate_token()
        HashedToken.objects.create(user=self.user, key_hash=key_hash,
                                   stage=HashedToken.TokenStage.LIVE)
        self.auth_header = f'Token LIVE_{raw_token}'

    def test_upsert_with_token(self):
        client = APIClient()
        response = client.post(
            UPSERT_URL,
            {'orders': [{'order_code': 'T-1', 'lines': [{'code': 'P1', 'quantity': 1}]}]},
            format='json',
            HTTP_AUTHORIZATION=self.auth_header,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Order.objects.filter(customer=self.customer, order_code='T-1').exists())

    def test_wrong_stage_token_rejected(self):
        raw_token, key_hash = HashedToken.generate_token()
        test_user = User.objects.create_user(username='tester', password='x')
        UserProfile.objects.create(user=test_user, customer=self.customer)
        HashedToken.objects.create(user=test_user, key_hash=key_hash,
                                   stage=HashedToken.TokenStage.TEST)

        client = APIClient()
        response = client.post(
            UPSERT_URL,
            {'orders': [{'order_code': 'T-2', 'lines': [{'code': 'P1', 'quantity': 1}]}]},
            format='json',
            HTTP_AUTHORIZATION=f'Token TEST_{raw_token}',
        )
        self.assertEqual(response.status_code, 401)

    def test_missing_auth_rejected(self):
        client = APIClient()
        response = client.post(
            UPSERT_URL,
            {'orders': [{'order_code': 'T-3', 'lines': [{'code': 'P1', 'quantity': 1}]}]},
            format='json',
        )
        self.assertEqual(response.status_code, 401)
