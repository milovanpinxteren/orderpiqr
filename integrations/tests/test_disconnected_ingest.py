"""A closed connection must stop becoming orders.

NELA COLLECTIVE paired their store twice, we failed to remove the first
store's webhooks, and both kept delivering for five days after they had
deactivated the plugin — 35 of their 221 orders were duplicates of each other
and 31 of the 49 orders in their picking queue were junk. Nothing in the chain
checked whether the connection was still live: not the webhook receivers, not
the worker, and nothing cancelled the old copies when the store re-paired.
"""
from unittest.mock import patch

from django.test import TestCase

from integrations.canonical import ExternalLine, ExternalOrder
from integrations.models import Connection, ExternalOrderLink, WebhookInbox
from integrations.services import intake
from integrations.management.commands.run_integrations_worker import Command
from orderpiqrApp.models import Customer, Order, Product


class CancelOpenOrdersTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Example Company')
        self.connection = Connection.objects.create(
            customer=self.customer, platform='woocommerce', status='active')

    def make_order(self, code, status, external_id):
        order = Order.objects.create(
            customer=self.customer, order_code=code, status=status,
            queue_position=1 if status == 'queued' else None)
        ExternalOrderLink.objects.create(
            connection=self.connection, order=order,
            external_order_id=external_id, external_order_number=code)
        return order

    def test_only_open_orders_are_cancelled(self):
        queued = self.make_order('1001', 'queued', '1')
        draft = self.make_order('1002', 'draft', '2')
        in_progress = self.make_order('1003', 'in_progress', '3')
        completed = self.make_order('1004', 'completed', '4')

        count = intake.cancel_open_orders(self.connection, reason='plugin disconnected')

        self.assertEqual(count, 2)
        queued.refresh_from_db()
        draft.refresh_from_db()
        in_progress.refresh_from_db()
        completed.refresh_from_db()
        self.assertEqual(queued.status, 'cancelled')
        self.assertEqual(draft.status, 'cancelled')
        # Work a picker already started or finished is never thrown away.
        self.assertEqual(in_progress.status, 'in_progress')
        self.assertEqual(completed.status, 'completed')
        self.assertIsNone(queued.queue_position)
        self.assertIn('plugin disconnected', queued.notes)

    def test_other_connections_are_untouched(self):
        other = Connection.objects.create(
            customer=self.customer, platform='shopify', status='active')
        mine = self.make_order('2001', 'queued', '10')
        theirs = Order.objects.create(
            customer=self.customer, order_code='2002', status='queued')
        ExternalOrderLink.objects.create(
            connection=other, order=theirs, external_order_id='11')

        intake.cancel_open_orders(self.connection)

        mine.refresh_from_db()
        theirs.refresh_from_db()
        self.assertEqual(mine.status, 'cancelled')
        self.assertEqual(theirs.status, 'queued')


class WorkerSkipsDisconnectedTests(TestCase):
    """Rows already sitting in the inbox when a connection closes must not
    turn into orders either — the queue drains after the plugin is gone."""

    def setUp(self):
        self.customer = Customer.objects.create(name='Example Company')
        self.connection = Connection.objects.create(
            customer=self.customer, platform='woocommerce', status='disconnected')
        self.row = WebhookInbox.objects.create(
            connection=self.connection, topic='order.created',
            external_event_id='evt-1', payload={'id': 1, 'number': '1'})

    def test_order_event_on_disconnected_connection_is_skipped(self):
        with patch('integrations.services.intake.import_external_order') as import_order:
            Command().process_inbox_row(self.row)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'skipped')
        import_order.assert_not_called()
        self.assertFalse(Order.objects.exists())

    def test_order_event_on_active_connection_still_imports(self):
        self.connection.status = 'active'
        self.connection.save(update_fields=['status'])
        Product.objects.create(customer=self.customer, code='WS-1',
                               description='Woo Single', active=True)
        self.row.payload = {
            'id': 1, 'number': '1', 'status': 'processing',
            'line_items': [{'product_id': 93, 'quantity': 2, 'sku': 'WS-1'}],
        }
        self.row.save(update_fields=['payload'])

        Command().process_inbox_row(self.row)

        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'processed')
        self.assertEqual(Order.objects.count(), 1)


class NoDuplicateQueueOnRepairTests(TestCase):
    """The duplicate-order mechanism itself: re-importing a store's open
    orders onto a new connection while the old copies are still queued gives
    the merchant '7898' and '7898-2' side by side."""

    def setUp(self):
        self.customer = Customer.objects.create(name='Example Company')
        self.product = Product.objects.create(
            customer=self.customer, code='8719326391234',
            description='Woo Single', active=True)

    def import_order(self, connection, external_id='727', number='7898'):
        ext = ExternalOrder(
            external_order_id=external_id,
            order_number=number,
            lines=[ExternalLine(
                external_variant_id='93', external_product_id='93', quantity=1,
                title='Woo Single', identifiers={'barcode': '8719326391234'})],
        )
        return intake.import_external_order(connection, ext)[0]

    def test_cancelling_the_old_connection_keeps_the_code_free(self):
        old = Connection.objects.create(
            customer=self.customer, platform='woocommerce', status='active')
        first = self.import_order(old)
        self.assertEqual(first.order_code, '7898')
        self.assertEqual(first.status, 'queued')

        # Store re-paired: old connection closes, its open orders go with it.
        old.status = 'disconnected'
        old.save(update_fields=['status'])
        intake.cancel_open_orders(old, reason='store re-paired')

        new = Connection.objects.create(
            customer=self.customer, platform='woocommerce', status='active')
        second = self.import_order(new)

        # Still suffixed (codes are unique per customer and the cancelled row
        # is kept for history), but only one of the two is in the queue.
        queued = Order.objects.filter(customer=self.customer, status='queued')
        self.assertEqual([o.order_code for o in queued], [second.order_code])
        first.refresh_from_db()
        self.assertEqual(first.status, 'cancelled')
