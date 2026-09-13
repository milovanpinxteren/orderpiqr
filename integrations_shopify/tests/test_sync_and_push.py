"""Tests for background product sync (SyncJob), the console order browser /
push endpoints, and the poll dedupe healing that re-imports orders discarded
when a shop is linked to an existing account."""
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from integrations.canonical import ExternalVariant
from integrations.models import (
    Connection, ExternalOrderLink, SyncJob, WebhookInbox,
)
from integrations.services.catalog import enqueue_product_sync
from integrations.management.commands.run_integrations_worker import Command
from integrations_shopify.models import ShopifyShop
from integrations_shopify.services import link_to_existing_account
from orderpiqrApp.models import Customer, Order, Product


def make_shop(customer=None, domain='test.myshopify.com', **connection_kwargs):
    customer = customer or Customer.objects.create(name='Test shop')
    connection_kwargs.setdefault('config', {'identifier_chain': ['sku']})
    connection = Connection.objects.create(
        customer=customer, platform='shopify', status='active',
        **connection_kwargs)
    shop = ShopifyShop.objects.create(connection=connection, shop_domain=domain)
    return shop


def poll_node(order_id, name='#1001', sku='2195', quantity=1):
    return {
        'id': f'gid://shopify/Order/{order_id}',
        'name': name,
        'note': '',
        'cancelledAt': None,
        'lineItems': {'nodes': [{
            'quantity': quantity,
            'sku': sku,
            'title': 'Beer crate',
            'variant': {'id': 'gid://shopify/ProductVariant/111',
                        'product': {'id': 'gid://shopify/Product/222'}},
        }]},
    }


class SyncJobTests(TestCase):
    def setUp(self):
        self.shop = make_shop()
        self.connection = self.shop.connection

    def test_enqueue_dedupes_active_jobs(self):
        job1 = enqueue_product_sync(self.connection)
        job2 = enqueue_product_sync(self.connection)
        self.assertEqual(job1.pk, job2.pk)

        job1.status = 'done'
        job1.save(update_fields=['status'])
        job3 = enqueue_product_sync(self.connection)
        self.assertNotEqual(job1.pk, job3.pk)

    def test_worker_runs_product_sync_job(self):
        Product.objects.create(
            customer=self.connection.customer, code='2195',
            description='Beer crate', active=True)
        job = enqueue_product_sync(self.connection)

        variants = [
            ExternalVariant(external_variant_id='111', external_product_id='222',
                            title='Beer crate', identifiers={'sku': '2195'}),
            ExternalVariant(external_variant_id='112', external_product_id='222',
                            title='No identifiers at all', identifiers={'sku': ''}),
        ]
        with patch('integrations_shopify.connector.ShopifyConnector.fetch_variants',
                   return_value=iter(variants)), \
             patch('integrations_shopify.connector.ShopifyConnector.count_variants',
                   return_value=2):
            Command().process_sync_jobs()

        job.refresh_from_db()
        self.assertEqual(job.status, 'done')
        self.assertEqual(job.total, 2)
        self.assertEqual(job.processed, 2)
        self.assertEqual(job.linked, 1)
        self.assertEqual(job.unresolved, 1)

    def test_sync_clips_overlong_external_values(self):
        # Real House of Beers regression: a variant title > 255 chars made
        # PostgreSQL reject the ProductLink row and killed the whole sync.
        long_title = 'Extremely long product title ' * 20
        variants = [
            ExternalVariant(external_variant_id='113', external_product_id='222',
                            title=long_title, identifiers={'sku': 'LONG-1'}),
        ]
        job = enqueue_product_sync(self.connection)
        with patch('integrations_shopify.connector.ShopifyConnector.fetch_variants',
                   return_value=iter(variants)), \
             patch('integrations_shopify.connector.ShopifyConnector.count_variants',
                   return_value=1):
            Command().process_sync_jobs()

        job.refresh_from_db()
        self.assertEqual(job.status, 'done')
        from integrations.models import ProductLink
        link = ProductLink.objects.get(
            connection=self.connection, external_variant_id='113')
        self.assertEqual(len(link.title), 255)
        self.assertIsNotNone(link.product)

    def test_worker_marks_failed_job(self):
        job = enqueue_product_sync(self.connection)
        with patch('integrations_shopify.connector.ShopifyConnector.fetch_variants',
                   side_effect=RuntimeError('boom')), \
             patch('integrations_shopify.connector.ShopifyConnector.count_variants',
                   return_value=None):
            Command().process_sync_jobs()
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertIn('boom', job.error)


class PushOrdersTests(TestCase):
    def setUp(self):
        self.shop = make_shop()
        self.connection = self.shop.connection
        self.product = Product.objects.create(
            customer=self.connection.customer, code='2195',
            description='Beer crate', active=True)

    def push(self, order_ids, payloads):
        with patch('integrations_shopify.views._authenticated_shop',
                   return_value=self.shop), \
             patch('integrations_shopify.connector.ShopifyConnector.fetch_orders',
                   return_value=payloads):
            return self.client.post(
                '/shopify/api/push-orders/', {'order_ids': order_ids},
                content_type='application/json')

    def canonical(self, order_id, status='open'):
        return {
            'external_order_id': str(order_id),
            'order_number': f'#{order_id}',
            'note': '',
            'status': status,
            'lines': [{
                'external_variant_id': '111',
                'external_product_id': '222',
                'quantity': 2,
                'title': 'Beer crate',
                'identifiers': {'sku': '2195', 'variant_id': '111'},
            }],
        }

    def test_push_imports_selected_orders(self):
        response = self.push(['1001'], [self.canonical(1001)])
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['imported'], 1)
        order = Order.objects.get(customer=self.connection.customer)
        self.assertEqual(order.order_code, '#1001')
        self.assertEqual(order.lines.get().product, self.product)

    def test_push_is_idempotent(self):
        self.push(['1001'], [self.canonical(1001)])
        response = self.push(['1001'], [self.canonical(1001)])
        data = response.json()
        self.assertEqual(data['imported'], 0)
        self.assertEqual(data['already_imported'], 1)
        self.assertEqual(
            Order.objects.filter(customer=self.connection.customer).count(), 1)

    def test_push_skips_cancelled(self):
        response = self.push(['1002'], [self.canonical(1002, status='cancelled')])
        self.assertEqual(response.json()['skipped'], 1)
        self.assertFalse(Order.objects.exists())

    def test_orders_list_flags_imported(self):
        self.push(['1001'], [self.canonical(1001)])
        browsed = [
            {'external_order_id': '1001', 'name': '#1001', 'created_at': '',
             'cancelled': False, 'fulfillment_status': 'UNFULFILLED',
             'financial_status': 'PAID', 'item_count': 2},
            {'external_order_id': '1002', 'name': '#1002', 'created_at': '',
             'cancelled': False, 'fulfillment_status': 'UNFULFILLED',
             'financial_status': 'PAID', 'item_count': 1},
        ]
        with patch('integrations_shopify.views._authenticated_shop',
                   return_value=self.shop), \
             patch('integrations_shopify.connector.ShopifyConnector.browse_orders',
                   return_value=(browsed, False, None)):
            response = self.client.get('/shopify/api/orders/')
        orders = {o['name']: o for o in response.json()['orders']}
        self.assertTrue(orders['#1001']['imported'])
        self.assertEqual(orders['#1001']['local_status'], 'queued')
        self.assertFalse(orders['#1002']['imported'])


class PollHealTests(TestCase):
    """A processed poll-order dedupe row whose local order is gone must be
    reset so the order can be imported again (e.g. after account linking)."""

    def setUp(self):
        self.shop = make_shop()
        self.connection = self.shop.connection
        self.connector = self.connection.get_connector()

    def test_orphaned_dedupe_row_is_reset(self):
        row = WebhookInbox.objects.create(
            connection=self.connection, topic='poll/order',
            external_event_id='poll-order-1001', status='processed',
            payload={})
        self.connector._inbox_from_poll_node(poll_node(1001))
        row.refresh_from_db()
        self.assertEqual(row.status, 'pending')
        self.assertEqual(row.payload['external_order_id'], '1001')

    def test_imported_order_row_is_left_alone(self):
        order = Order.objects.create(
            customer=self.connection.customer, order_code='#1001', status='queued')
        ExternalOrderLink.objects.create(
            connection=self.connection, order=order, external_order_id='1001')
        row = WebhookInbox.objects.create(
            connection=self.connection, topic='poll/order',
            external_event_id='poll-order-1001', status='processed',
            payload={})
        self.connector._inbox_from_poll_node(poll_node(1001))
        row.refresh_from_db()
        self.assertEqual(row.status, 'processed')


class LinkAccountResetTests(TestCase):
    def test_link_clears_inbox_and_poll_cursor(self):
        shop = make_shop()
        connection = shop.connection
        shop.last_synced_at = timezone.now()
        shop.save(update_fields=['last_synced_at'])
        WebhookInbox.objects.create(
            connection=connection, topic='poll/order',
            external_event_id='poll-order-1001', status='processed', payload={})
        target = Customer.objects.create(name='Existing company')

        link_to_existing_account(shop, target)

        shop.refresh_from_db()
        self.assertIsNone(shop.last_synced_at)
        self.assertFalse(WebhookInbox.objects.filter(connection=connection).exists())
        self.assertEqual(shop.connection.customer, target)
