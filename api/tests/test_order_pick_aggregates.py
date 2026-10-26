"""R4 — per-line pick aggregates on `/api/orders/`: requested/picked/short/lost
quantities per (order, product), computed once per request from
`build_pick_aggregates`, never per line.
"""
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from orderpiqrApp.models import (
    Customer, Device, Order, OrderLine, PickList, Product, ProductPick, UserProfile,
)


class OrderPickAggregatesTestCase(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Warehouse A')
        self.user = User.objects.create_user(username='picker-a', password='x')
        UserProfile.objects.create(user=self.user, customer=self.customer)

        self.other_customer = Customer.objects.create(name='Warehouse B')
        self.other_user = User.objects.create_user(username='picker-b', password='x')
        UserProfile.objects.create(user=self.other_user, customer=self.other_customer)

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.device = self._make_device()

    def _make_device(self, customer=None):
        return Device.objects.create(
            customer=customer or self.customer, name='Scanner 1', description='',
            last_login=timezone.now(), lists_picked=0,
        )

    def _make_product(self, code, customer=None):
        return Product.objects.create(
            customer=customer or self.customer, code=code, description=code, location='A1')

    def _make_order(self, order_code, customer=None):
        return Order.objects.create(
            customer=customer or self.customer, order_code=order_code, status='completed')

    def _make_picklist(self, order, archived=False, device=None, customer=None):
        return PickList.objects.create(
            customer=customer or self.customer, device=device or self.device,
            order=order, picklist_code=f'PL-{order.order_code}',
            pick_started=True, archived=archived)

    def _make_pick(self, product, picklist, quantity=1, outcome='pending', **kwargs):
        return ProductPick.objects.create(
            product=product, picklist=picklist, quantity=quantity, outcome=outcome, **kwargs)


class OutcomeMixTests(OrderPickAggregatesTestCase):
    def setUp(self):
        super().setUp()
        self.product = self._make_product('P-1')
        self.order = self._make_order('ORD-MIX')
        OrderLine.objects.create(order=self.order, product=self.product, quantity=6)
        self.picklist = self._make_picklist(self.order)
        self._make_pick(self.product, self.picklist, quantity=1, outcome='picked')
        self._make_pick(self.product, self.picklist, quantity=1, outcome='picked')
        self._make_pick(self.product, self.picklist, quantity=1, outcome='picked')
        self._make_pick(self.product, self.picklist, quantity=1, outcome='picked')
        self._make_pick(self.product, self.picklist, quantity=1, outcome='short', short_reason='other')
        self._make_pick(self.product, self.picklist, quantity=1, outcome='short', short_reason='other')

    def _line_data(self, line_data):
        return {
            'requested_quantity': line_data['requested_quantity'],
            'picked_quantity': line_data['picked_quantity'],
            'short_quantity': line_data['short_quantity'],
            'lost_quantity': line_data['lost_quantity'],
        }

    def test_list_shows_aggregates(self):
        response = self.client.get('/api/orders/')
        order_row = next(r for r in response.data['results'] if r['order_code'] == 'ORD-MIX')
        line = order_row['lines'][0]

        self.assertEqual(self._line_data(line),
                          {'requested_quantity': 6, 'picked_quantity': 4,
                           'short_quantity': 2, 'lost_quantity': 0})

    def test_detail_shows_aggregates(self):
        response = self.client.get(f'/api/orders/{self.order.order_id}/')
        line = response.data['lines'][0]

        self.assertEqual(self._line_data(line),
                          {'requested_quantity': 6, 'picked_quantity': 4,
                           'short_quantity': 2, 'lost_quantity': 0})

    def test_lookup_action_shows_aggregates(self):
        response = self.client.get('/api/orders/lookup/', {'code': 'ORD-MIX'})
        line = response.data['lines'][0]

        self.assertEqual(self._line_data(line),
                          {'requested_quantity': 6, 'picked_quantity': 4,
                           'short_quantity': 2, 'lost_quantity': 0})

    def test_lost_quantity_counted(self):
        self._make_pick(self.product, self.picklist, quantity=1, outcome='lost')
        response = self.client.get(f'/api/orders/{self.order.order_id}/')
        self.assertEqual(response.data['lines'][0]['lost_quantity'], 1)


class DuplicateLineTests(OrderPickAggregatesTestCase):
    def test_duplicate_same_product_lines_repeat_the_aggregate(self):
        # Two order lines for the same product on the same order must both
        # report the aggregate for that (order, product) pair — it describes
        # the product's units across the order, not the line, so it is not
        # summed across the duplicate lines.
        product = self._make_product('P-DUP')
        order = self._make_order('ORD-DUP')
        OrderLine.objects.create(order=order, product=product, quantity=2)
        OrderLine.objects.create(order=order, product=product, quantity=3)
        picklist = self._make_picklist(order)
        self._make_pick(product, picklist, quantity=1, outcome='picked')
        self._make_pick(product, picklist, quantity=1, outcome='picked')

        response = self.client.get(f'/api/orders/{order.order_id}/')
        picked_values = [line['picked_quantity'] for line in response.data['lines']]

        self.assertEqual(picked_values, [2, 2])


class ArchivedPicklistTests(OrderPickAggregatesTestCase):
    def test_archived_picklists_excluded_from_aggregates(self):
        product = self._make_product('P-ARCH')
        order = self._make_order('ORD-ARCH')
        OrderLine.objects.create(order=order, product=product, quantity=1)
        archived_picklist = self._make_picklist(order, archived=True)
        self._make_pick(product, archived_picklist, quantity=1, outcome='picked')

        response = self.client.get(f'/api/orders/{order.order_id}/')
        line = response.data['lines'][0]

        self.assertEqual(line['picked_quantity'], 0)
        self.assertEqual(line['short_quantity'], 0)
        self.assertEqual(line['lost_quantity'], 0)


class NoPicklistTests(OrderPickAggregatesTestCase):
    def test_order_without_a_picklist_shows_zero_not_null(self):
        product = self._make_product('P-NOPICK')
        order = self._make_order('ORD-NOPICK')
        OrderLine.objects.create(order=order, product=product, quantity=4)

        response = self.client.get(f'/api/orders/{order.order_id}/')
        line = response.data['lines'][0]

        self.assertEqual(line['requested_quantity'], 4)
        self.assertEqual(line['picked_quantity'], 0)
        self.assertEqual(line['short_quantity'], 0)
        self.assertEqual(line['lost_quantity'], 0)


class ScopingTests(OrderPickAggregatesTestCase):
    def test_list_excludes_other_customers_orders_and_aggregates(self):
        other_device = self._make_device(customer=self.other_customer)
        other_product = self._make_product('P-FOREIGN', customer=self.other_customer)
        foreign_order = self._make_order('ORD-FOREIGN', customer=self.other_customer)
        OrderLine.objects.create(order=foreign_order, product=other_product, quantity=1)
        foreign_picklist = self._make_picklist(
            foreign_order, device=other_device, customer=self.other_customer)
        self._make_pick(other_product, foreign_picklist, quantity=1, outcome='picked')

        mine = self._make_order('ORD-MINE')

        response = self.client.get('/api/orders/')
        codes = [row['order_code'] for row in response.data['results']]

        self.assertEqual(codes, ['ORD-MINE'])

    def test_detail_on_another_customers_order_is_404(self):
        foreign_order = self._make_order('ORD-FOREIGN', customer=self.other_customer)
        response = self.client.get(f'/api/orders/{foreign_order.order_id}/')
        self.assertEqual(response.status_code, 404)


class QueryCountTests(OrderPickAggregatesTestCase):
    """Aggregates are one grouped query per request, not one per line."""

    def _capture_list_query_count(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get('/api/orders/')
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries)

    def test_query_count_does_not_grow_with_line_count(self):
        # Deliberately a single order throughout: OrderSerializer.get_item_count
        # already does one query per *order* (pre-existing, unrelated to this
        # change), so adding more orders would confound the comparison. Adding
        # more *lines* to the same order must not move the query count at all.
        order = self._make_order('ORD-GROWING')
        product = self._make_product('P-FEW')
        OrderLine.objects.create(order=order, product=product, quantity=1)
        picklist = self._make_picklist(order)
        self._make_pick(product, picklist, quantity=1, outcome='picked')

        baseline = self._capture_list_query_count()

        # Pile on many more lines across several products (plus a duplicate
        # line per product) and matching picks — if aggregates were computed
        # per line this would grow the query count; the envelope must not move.
        for i in range(8):
            product_i = self._make_product(f'P-MANY-{i}')
            OrderLine.objects.create(order=order, product=product_i, quantity=2)
            OrderLine.objects.create(order=order, product=product_i, quantity=1)  # duplicate line
            self._make_pick(product_i, picklist, quantity=1, outcome='picked')
            self._make_pick(product_i, picklist, quantity=1, outcome='short', short_reason='other')

        grown = self._capture_list_query_count()

        self.assertEqual(grown, baseline)
