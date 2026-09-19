"""Tests for the plugin-facing connect/disconnect/status endpoints."""
import json
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from integrations.models import Connection, ExternalOrderLink, SyncJob
from integrations_woocommerce.client import WooCommerceAPIError, WooCommerceClient
from integrations_woocommerce.models import PairingToken, WooCommerceStore
from orderpiqrApp.models import Customer, Order


def connect_body(pairing_key, **overrides):
    body = {
        'pairing_key': pairing_key,
        'store_url': 'https://shop.example.com',
        'store_name': 'Example Shop',
        'consumer_key': 'ck_test',
        'consumer_secret': 'cs_test',
        'wordpress_version': '6.7',
        'woocommerce_version': '9.5.1',
        'plugin_version': '1.0.0',
    }
    body.update(overrides)
    return body


class ConnectTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Example Company')
        self.raw_key, self.token = PairingToken.issue(self.customer)

    def post_connect(self, body, path='/woocommerce/connect'):
        return self.client.post(path, json.dumps(body),
                                content_type='application/json')

    def connect_ok(self, body=None, path='/woocommerce/connect'):
        webhook_ids = iter(range(11, 20))
        with patch.object(WooCommerceClient, 'get_system_status',
                          return_value={'environment': {}}), \
             patch.object(WooCommerceClient, 'create_webhook',
                          side_effect=lambda *a, **kw: {'id': next(webhook_ids)}), \
             patch.object(WooCommerceClient, 'delete_webhook', return_value={}):
            return self.post_connect(body or connect_body(self.raw_key), path)

    def test_connect_happy_path(self):
        response = self.connect_ok()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'connected')
        self.assertEqual(data['customer_name'], 'Example Company')
        self.assertTrue(data['plugin_token'].startswith('opqpt_'))
        self.assertEqual(len(data['plugin_token']), len('opqpt_') + 64)

        connection = Connection.objects.get(pk=data['connection_id'])
        self.assertEqual(connection.platform, 'woocommerce')
        self.assertEqual(connection.status, 'active')
        self.assertEqual(connection.name, 'Example Shop')
        store = connection.woocommerce_store
        self.assertEqual(store.store_url, 'https://shop.example.com')
        self.assertEqual(store.consumer_key, 'ck_test')
        self.assertEqual(store.consumer_secret, 'cs_test')
        self.assertNotIn('ck_test', store.encrypted_consumer_key)
        self.assertEqual(len(store.webhook_ids), 5)
        self.assertTrue(store.check_plugin_token(data['plugin_token']))
        # Catalog sync queued for the worker
        self.assertTrue(SyncJob.objects.filter(
            connection=connection, kind='product_sync').exists())
        # Pairing key consumed
        self.token.refresh_from_db()
        self.assertTrue(self.token.is_used)

    def test_connect_works_without_trailing_slash_and_with(self):
        response = self.connect_ok(path='/woocommerce/connect')
        self.assertEqual(response.status_code, 200)
        raw_key2, _ = PairingToken.issue(self.customer)
        response = self.connect_ok(connect_body(raw_key2), path='/woocommerce/connect/')
        self.assertEqual(response.status_code, 200)

    def test_unknown_pairing_key(self):
        response = self.post_connect(connect_body('opqpk_deadbeef'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'invalid_pairing_key')

    def test_used_pairing_key_is_rejected(self):
        self.connect_ok()
        response = self.post_connect(connect_body(self.raw_key))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'invalid_pairing_key')

    def test_expired_pairing_key(self):
        self.token.expires_at = timezone.now() - timezone.timedelta(minutes=1)
        self.token.save(update_fields=['expires_at'])
        response = self.post_connect(connect_body(self.raw_key))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'expired_pairing_key')

    def test_store_unreachable(self):
        with patch.object(WooCommerceClient, 'get_system_status',
                          side_effect=WooCommerceAPIError('401', status_code=401)):
            response = self.post_connect(connect_body(self.raw_key))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'store_unreachable')
        self.assertFalse(Connection.objects.exists())

    def test_http_store_url_rejected_outside_debug(self):
        response = self.post_connect(
            connect_body(self.raw_key, store_url='http://shop.example.com'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'store_unreachable')

    def test_webhook_registration_failure_rolls_back(self):
        with patch.object(WooCommerceClient, 'get_system_status',
                          return_value={}), \
             patch.object(WooCommerceClient, 'create_webhook',
                          side_effect=WooCommerceAPIError('boom', status_code=500)):
            response = self.post_connect(connect_body(self.raw_key))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'webhook_registration_failed')
        self.assertFalse(Connection.objects.exists())
        self.token.refresh_from_db()
        self.assertFalse(self.token.is_used)  # merchant can retry with same key

    def test_reconnect_replaces_old_connection(self):
        first = self.connect_ok().json()
        raw_key2, _ = PairingToken.issue(self.customer)
        second = self.connect_ok(connect_body(raw_key2)).json()

        old = Connection.objects.get(pk=first['connection_id'])
        new = Connection.objects.get(pk=second['connection_id'])
        self.assertEqual(old.status, 'disconnected')
        self.assertEqual(new.status, 'active')
        self.assertNotEqual(old.pk, new.pk)

    def test_overlong_external_values_are_clipped(self):
        response = self.connect_ok(connect_body(
            self.raw_key,
            store_name='S' * 400,
            woocommerce_version='9' * 60,
        ))
        self.assertEqual(response.status_code, 200)
        store = WooCommerceStore.objects.get()
        self.assertEqual(len(store.store_name), 255)
        self.assertEqual(len(store.woocommerce_version), 32)


class DisconnectAndStatusTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Example Company')
        self.connection = Connection.objects.create(
            customer=self.customer, platform='woocommerce', status='active',
            name='Example Shop')
        raw, token_hash = WooCommerceStore.generate_plugin_token()
        self.plugin_token = raw
        self.store = WooCommerceStore.objects.create(
            connection=self.connection, store_url='https://shop.example.com',
            store_name='Example Shop', plugin_token_hash=token_hash,
            webhook_ids=[1, 2])

    def post_disconnect(self, body):
        return self.client.post('/woocommerce/disconnect', json.dumps(body),
                                content_type='application/json')

    def test_disconnect(self):
        with patch.object(WooCommerceClient, 'delete_webhook', return_value={}):
            response = self.post_disconnect({
                'connection_id': self.connection.pk,
                'plugin_token': self.plugin_token,
            })
        self.assertEqual(response.status_code, 200)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, 'disconnected')

    def test_disconnect_is_idempotent(self):
        with patch.object(WooCommerceClient, 'delete_webhook', return_value={}):
            for _ in range(2):
                response = self.post_disconnect({
                    'connection_id': self.connection.pk,
                    'plugin_token': self.plugin_token,
                })
                self.assertEqual(response.status_code, 200)
        # Unknown connection is also a 200 (already gone)
        response = self.post_disconnect({
            'connection_id': 999999, 'plugin_token': self.plugin_token})
        self.assertEqual(response.status_code, 200)

    def test_disconnect_rejects_bad_token(self):
        response = self.post_disconnect({
            'connection_id': self.connection.pk, 'plugin_token': 'opqpt_wrong'})
        self.assertEqual(response.status_code, 403)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, 'active')

    def test_status_endpoint(self):
        order = Order.objects.create(
            customer=self.customer, order_code='1001', status='queued')
        ExternalOrderLink.objects.create(
            connection=self.connection, order=order, external_order_id='1001')
        response = self.client.get(
            f'/woocommerce/status?connection_id={self.connection.pk}',
            headers={'X-OrderPiqr-Plugin-Token': self.plugin_token})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'active')
        self.assertEqual(data['store_name'], 'Example Shop')
        self.assertEqual(data['orders_synced'], 1)
        self.assertEqual(data['products_linked'], 0)

    def test_status_requires_valid_token(self):
        response = self.client.get(
            f'/woocommerce/status?connection_id={self.connection.pk}',
            headers={'X-OrderPiqr-Plugin-Token': 'opqpt_wrong'})
        self.assertEqual(response.status_code, 401)
