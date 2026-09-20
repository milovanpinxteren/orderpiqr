"""Tests for the WooCommerce connector: order-event parsing and status
mapping (incl. the fulfill echo-guard), product events, catalog iteration
with pagination, polling and outbound execution. All HTTP is mocked."""
import json
from unittest.mock import call, patch

from django.test import TestCase
from django.utils import timezone

from integrations.models import (
    Connection, ExternalOrderLink, ProductLink, SyncOutbox, WebhookInbox,
)
from integrations.services import events, intake
from integrations_woocommerce.client import WooCommerceClient
from integrations_woocommerce.models import WooCommerceStore
from integrations_woocommerce.services import strip_order_payload
from orderpiqrApp.models import Customer, Order, Product


def make_store(customer=None, **connection_kwargs):
    customer = customer or Customer.objects.create(name='Example Company')
    connection = Connection.objects.create(
        customer=customer, platform='woocommerce', status='active',
        **connection_kwargs)
    store = WooCommerceStore.objects.create(
        connection=connection, store_url='https://shop.example.com',
        webhook_secret='a' * 64)
    return store


def order_payload(**overrides):
    """A stripped order payload, as the webhook receiver stores it."""
    payload = {
        'id': 727,
        'number': '727',
        'status': 'processing',
        'customer_note': 'Ring the bell',
        'date_modified': '2026-09-18T10:00:00',
        'line_items': [{
            'id': 315, 'name': 'Woo Single #1', 'product_id': 93,
            'variation_id': 0, 'quantity': 2, 'sku': 'WS-1',
            'global_unique_id': '8719326391234',
        }],
    }
    payload.update(overrides)
    return payload


class FakeResponse:
    def __init__(self, body, headers=None, status_code=200):
        self.body = body
        self.headers = headers or {}
        self.status_code = status_code
        self.text = json.dumps(body)

    def json(self):
        return self.body


class ParseOrderEventTests(TestCase):
    def setUp(self):
        self.store = make_store()
        self.connection = self.store.connection
        self.connector = self.connection.get_connector()
        self.product = Product.objects.create(
            customer=self.connection.customer, code='8719326391234',
            description='Woo Single', active=True)

    def parse(self, topic, payload):
        row = WebhookInbox(connection=self.connection, topic=topic, payload=payload)
        return self.connector.parse_order_event(row)

    def test_order_created_maps_to_canonical(self):
        ext = self.parse('order.created', order_payload())
        self.assertEqual(ext.external_order_id, '727')
        self.assertEqual(ext.order_number, '727')
        self.assertEqual(ext.status, 'open')
        self.assertEqual(ext.note, 'Ring the bell')
        line = ext.lines[0]
        self.assertEqual(line.external_variant_id, '93')  # no variation -> product
        self.assertEqual(line.external_product_id, '93')
        self.assertEqual(line.quantity, 2)
        self.assertEqual(line.title, 'Woo Single #1')
        self.assertEqual(line.identifiers,
                         {'barcode': '8719326391234', 'sku': 'WS-1'})

    def test_variation_line_uses_variation_id(self):
        payload = order_payload()
        payload['line_items'][0]['variation_id'] = 941
        ext = self.parse('order.created', payload)
        self.assertEqual(ext.lines[0].external_variant_id, '941')
        self.assertEqual(ext.lines[0].external_product_id, '93')

    def test_empty_identifiers_are_omitted(self):
        payload = order_payload()
        payload['line_items'][0]['sku'] = ''
        del payload['line_items'][0]['global_unique_id']
        ext = self.parse('order.created', payload)
        self.assertEqual(ext.lines[0].identifiers, {})

    def test_status_mapping(self):
        for wc_status in ('pending', 'on-hold', 'processing'):
            ext = self.parse('order.updated', order_payload(status=wc_status))
            self.assertEqual(ext.status, 'open', wc_status)
        for wc_status in ('cancelled', 'refunded', 'failed', 'trash'):
            ext = self.parse('order.updated', order_payload(status=wc_status))
            self.assertEqual(ext.status, 'cancelled', wc_status)
        ext = self.parse('order.updated', order_payload(status='completed'))
        self.assertEqual(ext.status, 'fulfilled_elsewhere')
        # Unknown/custom statuses import as open rather than being lost
        ext = self.parse('order.updated', order_payload(status='custom-shipped'))
        self.assertEqual(ext.status, 'open')

    def test_order_deleted_topic_cancels(self):
        ext = self.parse('order.deleted', {'id': 727})
        self.assertEqual(ext.status, 'cancelled')
        self.assertEqual(ext.external_order_id, '727')

    def test_non_order_topics_are_ignored(self):
        self.assertIsNone(self.parse('product.updated', {'id': 93}))

    def test_payload_without_id_is_skipped(self):
        self.assertIsNone(self.parse('order.created', {}))

    def test_import_end_to_end(self):
        ext = self.parse('order.created', order_payload())
        order, created = intake.import_external_order(self.connection, ext)
        self.assertTrue(created)
        self.assertEqual(order.order_code, '727')
        self.assertEqual(order.lines.get().product, self.product)

    def test_completed_echo_is_a_noop_on_completed_order(self):
        """Our fulfill write-back sets the WooCommerce order to completed,
        which fires order.updated back at us. That echo maps to
        fulfilled_elsewhere and must leave the completed local order alone."""
        ext = self.parse('order.created', order_payload())
        order, _ = intake.import_external_order(self.connection, ext)
        order.status = 'completed'
        order.save(update_fields=['status'])
        notes_before = order.notes

        echo = self.parse('order.updated', order_payload(status='completed'))
        self.assertEqual(echo.status, 'fulfilled_elsewhere')
        intake.cancel_external_order(self.connection, echo.external_order_id,
                                     reason=echo.status)
        order.refresh_from_db()
        self.assertEqual(order.status, 'completed')
        self.assertEqual(order.notes, notes_before)

    def test_completed_event_cancels_open_order(self):
        """An order completed in WooCommerce by someone else while still
        queued here must be cancelled locally."""
        ext = self.parse('order.created', order_payload())
        order, _ = intake.import_external_order(self.connection, ext)
        self.assertEqual(order.status, 'queued')

        echo = self.parse('order.updated', order_payload(status='completed'))
        intake.cancel_external_order(self.connection, echo.external_order_id,
                                     reason=echo.status)
        order.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')


class ProductEventTests(TestCase):
    def setUp(self):
        self.store = make_store()
        self.connection = self.store.connection
        self.connector = self.connection.get_connector()

    def handle(self, topic, payload):
        row = WebhookInbox(connection=self.connection, topic=topic, payload=payload)
        return self.connector.handle_event(row)

    def test_product_updated_auto_creates_product(self):
        handled = self.handle('product.updated', {
            'id': 93, 'name': 'Woo Single #1', 'type': 'simple',
            'sku': 'WS-1', 'global_unique_id': '8719326391234',
            'variations': [],
        })
        self.assertTrue(handled)
        link = ProductLink.objects.get(
            connection=self.connection, external_variant_id='93')
        self.assertEqual(link.product.code, '8719326391234')

    def test_product_updated_links_existing_product(self):
        product = Product.objects.create(
            customer=self.connection.customer, code='WS-1',
            description='Woo Single', active=True)
        self.handle('product.updated', {
            'id': 93, 'name': 'Woo Single #1', 'type': 'simple',
            'sku': 'WS-1', 'variations': [],
        })
        link = ProductLink.objects.get(
            connection=self.connection, external_variant_id='93')
        self.assertEqual(link.product, product)
        self.assertEqual(link.match_method, 'sku')

    def test_variable_product_updated_fetches_variations(self):
        variations = [
            {'id': 941, 'sku': 'HOODIE-S', 'global_unique_id': '',
             'attributes': [{'name': 'Size', 'option': 'S'}]},
            {'id': 942, 'sku': 'HOODIE-M', 'global_unique_id': '',
             'attributes': [{'name': 'Size', 'option': 'M'}]},
        ]
        with patch.object(WooCommerceClient, 'iter_variations',
                          return_value=iter(variations)):
            self.handle('product.updated', {
                'id': 90, 'name': 'Hoodie', 'type': 'variable',
                'sku': '', 'variations': [941, 942],
            })
        links = ProductLink.objects.filter(connection=self.connection)
        self.assertEqual(links.count(), 2)
        self.assertEqual(links.get(external_variant_id='941').product.code,
                         'HOODIE-S')

    def test_locked_links_survive_product_update(self):
        product = Product.objects.create(
            customer=self.connection.customer, code='MANUAL',
            description='Manually mapped', active=True)
        ProductLink.objects.create(
            connection=self.connection, external_variant_id='93',
            external_product_id='93', product=product, locked=True,
            match_method='manual')
        self.handle('product.updated', {
            'id': 93, 'name': 'Woo Single #1', 'type': 'simple',
            'sku': 'WS-1', 'variations': [],
        })
        link = ProductLink.objects.get(
            connection=self.connection, external_variant_id='93')
        self.assertEqual(link.product, product)

    def test_product_deleted_unlinks(self):
        product = Product.objects.create(
            customer=self.connection.customer, code='WS-1',
            description='Woo Single', active=True)
        ProductLink.objects.create(
            connection=self.connection, external_variant_id='93',
            external_product_id='93', product=product)
        locked = ProductLink.objects.create(
            connection=self.connection, external_variant_id='941',
            external_product_id='93', product=product, locked=True)
        self.handle('product.deleted', {'id': 93})
        self.assertFalse(ProductLink.objects.filter(
            external_variant_id='93').exists())
        self.assertTrue(ProductLink.objects.filter(pk=locked.pk).exists())
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())


class FetchVariantsTests(TestCase):
    def setUp(self):
        self.store = make_store()
        self.connector = self.store.connection.get_connector()

    def test_fetch_variants_paginates_and_expands_variations(self):
        page1 = [
            {'id': 93, 'name': 'Woo Single #1', 'type': 'simple', 'sku': 'WS-1',
             'global_unique_id': '87193', 'manage_stock': True,
             'stock_quantity': 5, 'variations': []},
        ]
        page2 = [
            {'id': 90, 'name': 'Hoodie', 'type': 'variable', 'sku': '',
             'variations': [941]},
        ]
        variations = [
            {'id': 941, 'sku': 'HOODIE-S', 'global_unique_id': '',
             'manage_stock': False, 'stock_quantity': None,
             'attributes': [{'name': 'Size', 'option': 'S'}]},
        ]

        def fake_request(method, url, params=None, json=None, auth=None, timeout=None):
            if url.endswith('/products/90/variations'):
                return FakeResponse(variations, {'X-WP-TotalPages': '1'})
            self.assertTrue(url.endswith('/products'))
            page = params['page']
            body = page1 if page == 1 else page2
            return FakeResponse(body, {'X-WP-TotalPages': '2',
                                       'X-WP-Total': '2'})

        with patch('integrations_woocommerce.client.requests.request',
                   side_effect=fake_request):
            variants = list(self.connector.fetch_variants())

        self.assertEqual(len(variants), 2)
        simple, variation = variants
        self.assertEqual(simple.external_variant_id, '93')
        self.assertEqual(simple.identifiers, {'barcode': '87193', 'sku': 'WS-1'})
        self.assertEqual(simple.inventory_quantity, 5)
        self.assertEqual(variation.external_variant_id, '941')
        self.assertEqual(variation.external_product_id, '90')
        self.assertEqual(variation.title, 'Hoodie – S')
        self.assertIsNone(variation.inventory_quantity)  # manage_stock off

    def test_count_variants_uses_total_header(self):
        with patch('integrations_woocommerce.client.requests.request',
                   return_value=FakeResponse([], {'X-WP-Total': '37'})):
            self.assertEqual(self.connector.count_variants(), 37)


class PollTests(TestCase):
    def setUp(self):
        self.store = make_store()
        self.connection = self.store.connection
        self.connector = self.connection.get_connector()

    def orders_response(self, orders):
        return FakeResponse(orders, {'X-WP-TotalPages': '1'})

    def test_first_poll_needs_immediate_and_looks_back_7_days(self):
        self.assertTrue(self.connector.needs_immediate_poll())
        captured = {}

        def fake_request(method, url, params=None, json=None, auth=None, timeout=None):
            captured.update(params)
            return self.orders_response([])

        with patch('integrations_woocommerce.client.requests.request',
                   side_effect=fake_request):
            self.connector.poll()
        self.assertIn('modified_after', captured)
        self.assertEqual(captured['dates_are_gmt'], 'true')
        self.store.refresh_from_db()
        self.assertIsNotNone(self.store.last_poll_at)
        self.assertFalse(self.connector.needs_immediate_poll())

    def test_poll_inserts_stripped_events_idempotently(self):
        from integrations_woocommerce.tests.test_webhooks import wc_order_payload
        raw_order = wc_order_payload()
        with patch('integrations_woocommerce.client.requests.request',
                   return_value=self.orders_response([raw_order])):
            self.connector.poll()
            self.connector.poll()  # same order again

        rows = WebhookInbox.objects.filter(connection=self.connection)
        self.assertEqual(rows.count(), 1)
        row = rows.get()
        self.assertEqual(row.topic, 'poll/order')
        self.assertEqual(row.external_event_id,
                         'poll:727:2026-09-18T10:00:00')
        self.assertNotIn('billing', row.payload)
        self.assertNotIn('shipping', row.payload)
        # The stored payload parses like a webhook payload
        ext = self.connector.parse_order_event(row)
        self.assertEqual(ext.external_order_id, '727')
        self.assertEqual(ext.lines[0].identifiers['sku'], 'WS-1')

    def test_poll_strip_matches_webhook_strip(self):
        from integrations_woocommerce.tests.test_webhooks import wc_order_payload
        stripped = strip_order_payload(wc_order_payload())
        self.assertEqual(set(stripped.keys()),
                         {'id', 'number', 'status', 'customer_note',
                          'date_modified', 'line_items'})


class ExecuteTests(TestCase):
    def setUp(self):
        self.store = make_store()
        self.connection = self.store.connection
        self.connector = self.connection.get_connector()

    def outbox(self, action, payload):
        return SyncOutbox(connection=self.connection, action=action,
                          payload=payload)

    def test_fulfill_order_updates_status_and_notes(self):
        with patch.object(WooCommerceClient, 'get_order',
                          return_value={'id': 727, 'status': 'processing'}), \
             patch.object(WooCommerceClient, 'update_order',
                          return_value={}) as update_order, \
             patch.object(WooCommerceClient, 'create_order_note',
                          return_value={}) as create_note:
            self.connector.execute(self.outbox('fulfill_order', {
                'external_order_id': '727', 'notify_customer': True}))
        update_order.assert_called_once_with('727', {'status': 'completed'})
        create_note.assert_called_once_with(
            '727', 'Picked & completed via OrderPiqr')

    def test_fulfill_order_respects_configured_status(self):
        self.connection.config = {'fulfill_status': 'custom-shipped'}
        self.connection.save(update_fields=['config'])
        connector = self.connection.get_connector()
        with patch.object(WooCommerceClient, 'get_order',
                          return_value={'id': 727, 'status': 'processing'}), \
             patch.object(WooCommerceClient, 'update_order',
                          return_value={}) as update_order, \
             patch.object(WooCommerceClient, 'create_order_note',
                          return_value={}):
            connector.execute(self.outbox('fulfill_order', {
                'external_order_id': '727'}))
        update_order.assert_called_once_with('727', {'status': 'custom-shipped'})

    def test_fulfill_order_skips_when_already_completed(self):
        """Retry after a partial failure (or a manual completion) must not
        re-update or double-note the order."""
        with patch.object(WooCommerceClient, 'get_order',
                          return_value={'id': 727, 'status': 'completed'}), \
             patch.object(WooCommerceClient, 'update_order') as update_order, \
             patch.object(WooCommerceClient, 'create_order_note') as create_note:
            self.connector.execute(self.outbox('fulfill_order', {
                'external_order_id': '727'}))
        update_order.assert_not_called()
        create_note.assert_not_called()

    def test_archive_order_is_a_noop(self):
        self.connector.execute(self.outbox('archive_order', {
            'external_order_id': '727'}))  # must not raise or call the API

    def test_push_inventory_variation(self):
        with patch.object(WooCommerceClient, 'update_variation',
                          return_value={}) as update_variation:
            self.connector.execute(self.outbox('push_inventory', {
                'external_variant_id': '941', 'external_product_id': '90',
                'quantity': 7}))
        update_variation.assert_called_once_with('90', '941',
                                                 {'stock_quantity': 7})

    def test_push_inventory_simple_product(self):
        with patch.object(WooCommerceClient, 'update_product',
                          return_value={}) as update_product:
            self.connector.execute(self.outbox('push_inventory', {
                'external_variant_id': '93', 'external_product_id': '93',
                'quantity': 3}))
        update_product.assert_called_once_with('93', {'stock_quantity': 3})

    def test_order_completed_hook_queues_fulfill_neutrally(self):
        """The platform-neutral completion hook must enqueue fulfill_order
        for WooCommerce connections too."""
        order = Order.objects.create(
            customer=self.connection.customer, order_code='727',
            status='completed')
        ExternalOrderLink.objects.create(
            connection=self.connection, order=order, external_order_id='727')
        events.order_completed(order)
        row = SyncOutbox.objects.get(connection=self.connection)
        self.assertEqual(row.action, 'fulfill_order')
        self.assertEqual(row.payload['external_order_id'], '727')
