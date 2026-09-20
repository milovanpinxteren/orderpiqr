"""Tests for the webhook receiver: signature verification, PII stripping,
idempotency and the activation ping."""
import base64
import hashlib
import hmac
import json

from django.test import TestCase

from integrations.models import Connection, WebhookInbox
from integrations_woocommerce.models import WooCommerceStore
from orderpiqrApp.models import Customer

WEBHOOK_SECRET = 'a' * 64


def wc_order_payload(**overrides):
    """A realistic WooCommerce order payload, full of PII that must never
    reach the inbox."""
    payload = {
        'id': 727,
        'number': '727',
        'status': 'processing',
        'currency': 'EUR',
        'customer_note': 'Ring the bell',
        'date_modified': '2026-09-18T10:00:00',
        'billing': {
            'first_name': 'John', 'last_name': 'Doe',
            'address_1': 'Main Street 1', 'city': 'Amsterdam',
            'email': 'john.doe@example.com', 'phone': '+3161234567',
        },
        'shipping': {
            'first_name': 'John', 'last_name': 'Doe',
            'address_1': 'Main Street 1', 'city': 'Amsterdam',
        },
        'customer_id': 42,
        'customer_ip_address': '203.0.113.9',
        'payment_method_title': 'iDEAL',
        'line_items': [{
            'id': 315,
            'name': 'Woo Single #1',
            'product_id': 93,
            'variation_id': 0,
            'quantity': 2,
            'sku': 'WS-1',
            'global_unique_id': '8719326391234',
            'price': 21.99,
            'taxes': [],
            'meta_data': [{'key': '_secret', 'value': 'internal'}],
        }],
    }
    payload.update(overrides)
    return payload


class WebhookTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Example Company')
        self.connection = Connection.objects.create(
            customer=self.customer, platform='woocommerce', status='active')
        self.store = WooCommerceStore.objects.create(
            connection=self.connection, store_url='https://shop.example.com',
            webhook_secret=WEBHOOK_SECRET)

    def sign(self, body, secret=WEBHOOK_SECRET):
        return base64.b64encode(
            hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()

    def deliver(self, payload, topic='order.created', cid=None, secret=WEBHOOK_SECRET,
                signature=None, delivery_id='delivery-1', path='/woocommerce/webhooks'):
        body = json.dumps(payload).encode()
        cid = self.connection.pk if cid is None else cid
        headers = {
            'X-WC-Webhook-Topic': topic,
            'X-WC-Webhook-Signature': signature or self.sign(body, secret),
            'X-WC-Webhook-Delivery-ID': delivery_id,
            'X-WC-Webhook-ID': '5',
            'X-WC-Webhook-Resource-ID': str(payload.get('id', '')),
        }
        return self.client.post(f'{path}?cid={cid}', body,
                                content_type='application/json', headers=headers)

    def test_valid_webhook_is_stored(self):
        response = self.deliver(wc_order_payload())
        self.assertEqual(response.status_code, 200)
        row = WebhookInbox.objects.get()
        self.assertEqual(row.connection, self.connection)
        self.assertEqual(row.topic, 'order.created')
        self.assertEqual(row.external_event_id, 'delivery-1')
        self.assertEqual(row.status, 'pending')

    def test_no_trailing_slash_post_works(self):
        for path in ('/woocommerce/webhooks', '/woocommerce/webhooks/'):
            response = self.deliver(wc_order_payload(), path=path,
                                    delivery_id=f'd-{path}')
            self.assertEqual(response.status_code, 200)
        self.assertEqual(WebhookInbox.objects.count(), 2)

    def test_pii_is_stripped_before_storage(self):
        self.deliver(wc_order_payload())
        payload = WebhookInbox.objects.get().payload

        forbidden = {'billing', 'shipping', 'customer_id', 'customer_ip_address',
                     'payment_method_title', 'currency'}
        self.assertFalse(forbidden & set(payload.keys()),
                         f"PII keys leaked into inbox: {forbidden & set(payload.keys())}")
        self.assertEqual(set(payload.keys()) - {'line_items'},
                         {'id', 'number', 'status', 'customer_note', 'date_modified'})
        line = payload['line_items'][0]
        self.assertNotIn('price', line)
        self.assertNotIn('meta_data', line)
        self.assertEqual(line['sku'], 'WS-1')
        self.assertEqual(line['global_unique_id'], '8719326391234')
        self.assertEqual(line['quantity'], 2)

    def test_invalid_signature_is_rejected(self):
        response = self.deliver(wc_order_payload(), secret='b' * 64)
        self.assertEqual(response.status_code, 401)
        self.assertFalse(WebhookInbox.objects.exists())

    def test_missing_cid_is_rejected(self):
        body = json.dumps(wc_order_payload()).encode()
        response = self.client.post(
            '/woocommerce/webhooks', body, content_type='application/json',
            headers={'X-WC-Webhook-Topic': 'order.created',
                     'X-WC-Webhook-Signature': self.sign(body)})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(WebhookInbox.objects.exists())

    def test_unknown_cid_is_rejected(self):
        response = self.deliver(wc_order_payload(), cid=999999)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(WebhookInbox.objects.exists())

    def test_activation_ping_returns_200_without_inbox_row(self):
        # WooCommerce pings the delivery URL on activation: form-encoded body,
        # no signature/topic headers.
        response = self.client.post(
            f'/woocommerce/webhooks?cid={self.connection.pk}',
            'webhook_id=12', content_type='application/x-www-form-urlencoded')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(WebhookInbox.objects.exists())

    def test_duplicate_delivery_is_ignored(self):
        self.deliver(wc_order_payload(), delivery_id='dup-1')
        response = self.deliver(wc_order_payload(), delivery_id='dup-1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WebhookInbox.objects.count(), 1)

    def test_fallback_event_id_when_no_delivery_header(self):
        body = json.dumps(wc_order_payload()).encode()
        headers = {
            'X-WC-Webhook-Topic': 'order.updated',
            'X-WC-Webhook-Signature': self.sign(body),
            'X-WC-Webhook-ID': '5',
            'X-WC-Webhook-Resource-ID': '727',
        }
        url = f'/woocommerce/webhooks?cid={self.connection.pk}'
        self.client.post(url, body, content_type='application/json', headers=headers)
        self.client.post(url, body, content_type='application/json', headers=headers)
        # Identical redelivery dedupes...
        self.assertEqual(WebhookInbox.objects.count(), 1)
        # ...but a later update of the same order (new date_modified) does not.
        body2 = json.dumps(wc_order_payload(
            date_modified='2026-09-18T11:00:00', status='completed')).encode()
        headers['X-WC-Webhook-Signature'] = self.sign(body2)
        self.client.post(url, body2, content_type='application/json', headers=headers)
        self.assertEqual(WebhookInbox.objects.count(), 2)

    def test_product_webhook_stores_stripped_payload(self):
        payload = {
            'id': 93, 'name': 'Woo Single #1', 'type': 'simple',
            'status': 'publish', 'sku': 'WS-1', 'global_unique_id': '87193',
            'manage_stock': True, 'stock_quantity': 12,
            'date_modified': '2026-09-18T10:00:00',
            'description': '<p>huge html blob</p>', 'images': [{'src': 'x'}],
            'variations': [],
        }
        self.deliver(payload, topic='product.updated', delivery_id='p-1')
        row = WebhookInbox.objects.get()
        self.assertNotIn('description', row.payload)
        self.assertNotIn('images', row.payload)
        self.assertEqual(row.payload['sku'], 'WS-1')
