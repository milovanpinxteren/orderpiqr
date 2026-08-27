"""Tests for order-event intake from Shopify webhooks.

These cover the pay-later flow that can break App Store review: an order
created in the admin as unpaid is filtered out on orders/create, so the
later orders/paid (or orders/updated) event must import it.
"""
from django.test import TestCase

from integrations.models import Connection, ExternalOrderLink, WebhookInbox
from integrations.services.intake import import_external_order
from orderpiqrApp.models import Customer, Order, Product


def order_payload(**overrides):
    payload = {
        'id': 5678001122,
        'name': '#1010',
        'note': '',
        'financial_status': 'paid',
        'fulfillment_status': None,
        'cancelled_at': None,
        'line_items': [{
            'variant_id': 111,
            'product_id': 222,
            'quantity': 1,
            'title': 'Framed Metal (Gloss Metal)',
            'sku': '2195',
        }],
    }
    payload.update(overrides)
    return payload


class OrderEventTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Test shop')
        self.connection = Connection.objects.create(
            customer=self.customer,
            platform='shopify',
            status='active',
            # sku-only chain: no barcode/metafield GraphQL enrichment needed
            config={'identifier_chain': ['sku']},
        )
        self.product = Product.objects.create(
            customer=self.customer, code='2195',
            description='Framed Metal', active=True,
        )
        self.connector = self.connection.get_connector()

    def parse(self, topic, payload):
        row = WebhookInbox(connection=self.connection, topic=topic, payload=payload)
        return self.connector.parse_order_event(row)

    def test_create_unpaid_is_filtered(self):
        ext = self.parse('orders/create', order_payload(financial_status='pending'))
        self.assertIsNone(ext)

    def test_create_paid_imports(self):
        ext = self.parse('orders/create', order_payload())
        self.assertIsNotNone(ext)
        order, created = import_external_order(self.connection, ext)
        self.assertTrue(created)
        self.assertEqual(order.order_code, '#1010')
        self.assertEqual(order.lines.get().product, self.product)

    def test_paid_event_imports_order_missed_on_create(self):
        # orders/create arrived unpaid and was skipped...
        self.assertIsNone(
            self.parse('orders/create', order_payload(financial_status='pending')))
        # ...orders/paid must pick it up.
        ext = self.parse('orders/paid', order_payload())
        self.assertIsNotNone(ext)
        order, created = import_external_order(self.connection, ext)
        self.assertTrue(created)
        self.assertEqual(ExternalOrderLink.objects.filter(
            connection=self.connection, external_order_id='5678001122').count(), 1)

    def test_updated_event_imports_when_now_eligible(self):
        ext = self.parse('orders/updated', order_payload())
        self.assertIsNotNone(ext)
        self.assertEqual(ext.status, 'open')

    def test_updated_event_still_reports_cancellation(self):
        ext = self.parse('orders/updated',
                         order_payload(cancelled_at='2026-08-22T01:00:00Z'))
        self.assertEqual(ext.status, 'cancelled')

    def test_fulfilled_orders_are_not_imported(self):
        ext = self.parse('orders/paid', order_payload(fulfillment_status='fulfilled'))
        self.assertIsNone(ext)

    def test_duplicate_events_import_once(self):
        for topic in ('orders/create', 'orders/paid', 'orders/updated'):
            ext = self.parse(topic, order_payload())
            import_external_order(self.connection, ext)
        self.assertEqual(Order.objects.filter(customer=self.customer).count(), 1)
