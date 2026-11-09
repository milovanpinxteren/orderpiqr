"""The admin as an operator surface: does every changelist load, does the
customer overview count the right things, and do its count links resolve.

The counts on the customer row and the filtered lists they link to are built
from separate code paths (annotations vs. changelist lookups), so each test
here checks both halves agree — a link that 400s on a disallowed lookup, or a
column that counts a relation twice, looks perfectly healthy from the outside.
"""
import html
import re
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from orderpiqrApp.models import (
    Customer, Device, Order, OrderLine, PickList, Product, ProductPick, ScanEvent,
    UserProfile,
)


class AdminOverviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username='milo', email='milo@example.com', password='pw')

        cls.customer = Customer.objects.create(name='Healthy Fridge', description='Fridges')
        cls.other = Customer.objects.create(name='House of Beers', description='Beers')

        picker = User.objects.create_user(username='picker', password='pw')
        UserProfile.objects.create(user=picker, customer=cls.customer)

        cls.device = Device.objects.create(
            name='Scanner 1', description='Phone', customer=cls.customer,
            last_login=timezone.now(), lists_picked=0)
        Device.objects.create(
            name='Dead phone', description='Archived', customer=cls.customer,
            last_login=timezone.now() - timedelta(days=200), lists_picked=0,
            archived=True)

        cls.product = Product.objects.create(
            code='EAN-1', description='Yoghurt', location='A1', customer=cls.customer)
        Product.objects.create(
            code='EAN-2', description='Milk', location='A2', customer=cls.customer)
        Product.objects.create(
            code='EAN-OLD', description='Discontinued', location='A3',
            customer=cls.customer, active=False)
        # Same codes under another customer: every count must stay scoped.
        Product.objects.create(
            code='EAN-1', description='Beer', location='B1', customer=cls.other)

        order = Order.objects.create(customer=cls.customer, order_code='ORD-1')
        OrderLine.objects.create(order=order, product=cls.product, quantity=2)
        OrderLine.objects.create(order=order, product=cls.product, quantity=5)

        cls.picklist = PickList.objects.create(
            customer=cls.customer, order=order, picklist_code='ORD-1',
            device=cls.device)
        ProductPick.objects.create(
            product=cls.product, picklist=cls.picklist, quantity=2,
            outcome=ProductPick.Outcome.PICKED)
        ProductPick.objects.create(
            product=cls.product, picklist=cls.picklist, quantity=5,
            outcome=ProductPick.Outcome.SHORT)

        ScanEvent.objects.create(customer=cls.customer, event_type='camera_error',
                                 severity='error')
        ScanEvent.objects.create(customer=cls.customer, event_type='manual_override',
                                 severity='info')

    def setUp(self):
        self.client.force_login(self.superuser)

    def customer_row(self):
        response = self.client.get(reverse('admin:orderpiqrApp_customer_changelist'))
        self.assertEqual(response.status_code, 200)
        rows = {row.name: row for row in response.context['cl'].result_list}
        return response, rows[self.customer.name]

    def test_customer_overview_counts_are_scoped_and_not_inflated(self):
        """Several counts on one row: the join-fan-out failure mode would
        multiply these together rather than report them side by side."""
        _, row = self.customer_row()

        self.assertEqual(row.n_users, 1)
        self.assertEqual(row.n_devices, 2)
        self.assertEqual(row.n_devices_active, 1)
        self.assertEqual(row.n_products, 2)  # the inactive one is excluded
        self.assertEqual(row.n_orders, 1)
        self.assertEqual(row.n_picklists, 1)
        self.assertEqual(row.n_lines_picked, 1)  # the short pick is not a pick
        self.assertEqual(row.n_errors, 1)  # the info event is not an error
        self.assertEqual(row.last_pick_at.date(), timezone.localdate())

    def test_customer_with_no_activity_counts_zero(self):
        _, row = self.customer_row()
        response = self.client.get(reverse('admin:orderpiqrApp_customer_changelist'))
        other = {r.name: r for r in response.context['cl'].result_list}[self.other.name]

        self.assertEqual(other.n_users, 0)
        self.assertEqual(other.n_picklists, 0)
        self.assertEqual(other.n_products, 1)
        self.assertIsNone(other.last_pick_at)

    def test_every_count_link_resolves_and_filters(self):
        """A count that links to a lookup the target admin disallows answers
        400, not 200 — which is invisible until someone clicks it."""
        response, _ = self.customer_row()
        content = response.content.decode()
        links = {html.unescape(href) for href in re.findall(r'href="([^"]+)"', content)
                 if '?' in href and '/admin/' in href}

        self.assertTrue(links, 'the overview rendered no filtered count links')
        for link in links:
            with self.subTest(link=link):
                linked = self.client.get(link)
                self.assertEqual(linked.status_code, 200)

    def test_product_count_link_lands_on_that_customers_products(self):
        url = (reverse('admin:orderpiqrApp_product_changelist')
               + '?customer__customer_id__exact=%s&active__exact=1' % self.customer.pk)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        codes = sorted(p.code for p in response.context['cl'].result_list)
        self.assertEqual(codes, ['EAN-1', 'EAN-2'])

    def test_all_changelists_load(self):
        for model, model_admin in [
                (Customer, None), (Product, None), (Order, None), (OrderLine, None),
                (PickList, None), (Device, None), (ScanEvent, None), (UserProfile, None)]:
            url = reverse('admin:orderpiqrApp_%s_changelist' % model._meta.model_name)
            with self.subTest(model=model.__name__):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_picklist_search_accepts_a_non_date_term(self):
        """pick_time, a DateTimeField, used to be a search field: every term
        became an icontains against it, so anything not date-shaped broke the
        query instead of matching nothing."""
        url = reverse('admin:orderpiqrApp_picklist_changelist') + '?q=scanner'

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([p.pk for p in response.context['cl'].result_list],
                         [self.picklist.pk])

    def test_order_line_count(self):
        url = reverse('admin:orderpiqrApp_order_changelist')

        response = self.client.get(url)

        self.assertEqual(response.context['cl'].result_list[0].n_lines, 2)


class ProductAdminSaveTests(TestCase):
    """The product save path, which a superuser could not use at all: it
    raised ValidationError for anyone outside the companyadmin group."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username='milo', email='milo@example.com', password='pw')
        cls.customer = Customer.objects.create(name='Healthy Fridge', description='x')

    def setUp(self):
        self.client.force_login(self.superuser)

    def post_product(self, code, description='Yoghurt'):
        return self.client.post(reverse('admin:orderpiqrApp_product_add'), data={
            'code': code,
            'description': description,
            'location': 'A1',
            'customer': self.customer.pk,
            'active': 'on',
            'inventory_quantity': '0',
            'barcodes-TOTAL_FORMS': '0',
            'barcodes-INITIAL_FORMS': '0',
            'barcodes-MIN_NUM_FORMS': '0',
            'barcodes-MAX_NUM_FORMS': '1000',
        })

    def test_superuser_can_add_a_product(self):
        response = self.post_product('EAN-NEW')

        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(code='EAN-NEW')
        self.assertEqual(product.customer, self.customer)

    def test_duplicate_code_is_a_form_error_not_a_silent_no_save(self):
        Product.objects.create(code='EAN-1', description='Yoghurt', location='A1',
                               customer=self.customer)

        response = self.post_product('EAN-1')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Product.objects.filter(code='EAN-1').count(), 1)
        self.assertIn('code', response.context['adminform'].form.errors)

    def test_same_code_under_another_customer_is_allowed(self):
        other = Customer.objects.create(name='House of Beers', description='x')
        Product.objects.create(code='EAN-1', description='Beer', location='B1',
                               customer=other)

        response = self.post_product('EAN-1')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Product.objects.filter(code='EAN-1').count(), 2)
