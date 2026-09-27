"""Barcode aliases through the API: /api/products/ CRUD and the order upsert.

The invariants that keep supplier EAN rotations painless:
- an order line whose code matches an alias resolves to the existing product
  (no duplicate is created),
- changing a product's primary code keeps the old code scannable as an alias
  ("never forget a code"),
- no code — primary or alias — can be claimed twice within a customer.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from orderpiqrApp.models import Customer, Product, ProductBarcode, UserProfile

OLD_EAN = '8712345678906'
NEW_EAN = '8798765432109'


class ProductBarcodeAPITestCase(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Warehouse A')
        self.user = User.objects.create_user(username='hfportal', password='x')
        UserProfile.objects.create(user=self.user, customer=self.customer)

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)


class ProductEndpointBarcodeTests(ProductBarcodeAPITestCase):
    def test_create_with_barcodes(self):
        response = self.client.post('/api/products/', {
            'code': NEW_EAN,
            'description': 'Broodje',
            'location': '16',
            'barcodes': [OLD_EAN],
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['barcodes'], [OLD_EAN])
        product = Product.objects.get(customer=self.customer, code=NEW_EAN)
        self.assertEqual(list(product.barcodes.values_list('code', flat=True)), [OLD_EAN])

    def test_patch_code_change_keeps_old_code_as_alias(self):
        product = Product.objects.create(
            customer=self.customer, code=OLD_EAN, description='Broodje')

        response = self.client.patch(f'/api/products/{product.product_id}/', {
            'code': NEW_EAN,
        }, format='json')

        self.assertEqual(response.status_code, 200)
        product.refresh_from_db()
        self.assertEqual(product.code, NEW_EAN)
        self.assertEqual(list(product.barcodes.values_list('code', flat=True)), [OLD_EAN])
        self.assertEqual(response.data['barcodes'], [OLD_EAN])

    def test_patch_barcodes_replaces_the_set(self):
        product = Product.objects.create(
            customer=self.customer, code=NEW_EAN, description='Broodje')
        ProductBarcode.objects.create(product=product, code=OLD_EAN)

        response = self.client.patch(f'/api/products/{product.product_id}/', {
            'barcodes': ['111'],
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(product.barcodes.values_list('code', flat=True)), ['111'])

    def test_patch_without_barcodes_leaves_aliases_alone(self):
        product = Product.objects.create(
            customer=self.customer, code=NEW_EAN, description='Broodje')
        ProductBarcode.objects.create(product=product, code=OLD_EAN)

        self.client.patch(f'/api/products/{product.product_id}/', {
            'description': 'Broodje kaas',
        }, format='json')

        self.assertEqual(list(product.barcodes.values_list('code', flat=True)), [OLD_EAN])

    def test_barcode_taken_by_another_product_is_rejected(self):
        Product.objects.create(customer=self.customer, code=OLD_EAN, description='Other')

        response = self.client.post('/api/products/', {
            'code': NEW_EAN,
            'description': 'Broodje',
            'location': '16',
            'barcodes': [OLD_EAN],
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('barcodes', response.data)
        self.assertFalse(Product.objects.filter(customer=self.customer, code=NEW_EAN).exists())

    def test_code_taken_as_alias_elsewhere_is_rejected(self):
        other = Product.objects.create(
            customer=self.customer, code='SKU-1', description='Other')
        ProductBarcode.objects.create(product=other, code=OLD_EAN)

        response = self.client.post('/api/products/', {
            'code': OLD_EAN,
            'description': 'Impostor',
            'location': '1',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('code', response.data)

    def test_demote_collision_is_a_400_not_a_500(self):
        # Pre-existing bad state (primary equal to another product's alias,
        # possible via surfaces that predate the conflict checks): PATCHing the
        # code away demotes the old primary, which collides with the alias.
        product = Product.objects.create(
            customer=self.customer, code=OLD_EAN, description='Broodje')
        other = Product.objects.create(
            customer=self.customer, code='SKU-2', description='Wrap')
        ProductBarcode.objects.create(product=other, code=OLD_EAN)

        response = self.client.patch(f'/api/products/{product.product_id}/', {
            'code': NEW_EAN,
        }, format='json')

        self.assertEqual(response.status_code, 400)
        product.refresh_from_db()
        self.assertEqual(product.code, OLD_EAN)  # rolled back, nothing half-applied

    def test_same_code_across_customers_is_fine(self):
        other_customer = Customer.objects.create(name='Warehouse B')
        other_product = Product.objects.create(
            customer=other_customer, code='SKU-1', description='Foreign')
        ProductBarcode.objects.create(product=other_product, code=OLD_EAN)

        response = self.client.post('/api/products/', {
            'code': NEW_EAN,
            'description': 'Broodje',
            'location': '16',
            'barcodes': [OLD_EAN],
        }, format='json')

        self.assertEqual(response.status_code, 201)

    def test_lookup_resolves_alias(self):
        product = Product.objects.create(
            customer=self.customer, code=NEW_EAN, description='Broodje')
        ProductBarcode.objects.create(product=product, code=OLD_EAN)

        response = self.client.get(f'/api/products/lookup/?code={OLD_EAN}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['code'], NEW_EAN)


class UpsertAliasTests(ProductBarcodeAPITestCase):
    def post(self, payload):
        return self.client.post('/api/orders/upsert/', payload, format='json')

    def test_line_with_alias_code_resolves_to_existing_product(self):
        """An order pushed with the old EAN after the catalog moved to the new
        one must not spawn a duplicate product."""
        product = Product.objects.create(
            customer=self.customer, code=NEW_EAN, description='Broodje')
        ProductBarcode.objects.create(product=product, code=OLD_EAN)

        response = self.post({
            'orders': [{
                'order_code': 'AMS01-20260927',
                'lines': [{'code': OLD_EAN, 'quantity': 3}],
            }],
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['products_created'], 0)
        self.assertEqual(Product.objects.filter(customer=self.customer).count(), 1)
        order_line = product.orderline_set.get()
        self.assertEqual(order_line.quantity, 3)

    def test_unknown_code_still_creates_a_product(self):
        response = self.post({
            'orders': [{
                'order_code': 'AMS01-20260927',
                'lines': [{'code': 'BRAND-NEW', 'quantity': 1}],
            }],
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['products_created'], 1)
        self.assertTrue(Product.objects.filter(customer=self.customer, code='BRAND-NEW').exists())
