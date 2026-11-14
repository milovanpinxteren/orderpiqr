"""An imported product should be scannable by every code it carries.

A variant usually has both an EAN and a SKU, but an auto-created product takes
only the first identifier in the chain as its primary code. The warehouse label
is whichever the merchant happens to print — so a picker scanning the SKU of a
barcode-coded product got "unknown product" on a catalog we imported ourselves,
which looks exactly like a broken scanner to the person holding the phone.
"""
from django.test import TestCase

from integrations.canonical import ExternalLine, ExternalOrder
from integrations.models import Connection
from integrations.services import intake
from orderpiqrApp.models import Customer, Product
from orderpiqrApp.utils.products import resolve_product


class AutoCreateAliasTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Example Company')
        self.connection = Connection.objects.create(
            customer=self.customer, platform='shopify', status='active',
            config={'identifier_chain': ['barcode', 'sku']})

    def import_line(self, identifiers, order_id='1', title='Corset Shorts'):
        ext = ExternalOrder(
            external_order_id=order_id,
            order_number=order_id,
            lines=[ExternalLine(
                external_variant_id=f'v{order_id}',
                external_product_id=f'p{order_id}',
                quantity=1, title=title, identifiers=identifiers)],
        )
        intake.import_external_order(self.connection, ext)
        return Product.objects.get(customer=self.customer,
                                   description=title)

    def test_both_barcode_and_sku_resolve(self):
        product = self.import_line(
            {'barcode': '7640228381081', 'sku': 'CS-BLACK-M'})

        self.assertEqual(product.code, '7640228381081')
        self.assertEqual(resolve_product(self.customer, '7640228381081'), product)
        # The whole point: the SKU on the shelf label scans too.
        self.assertEqual(resolve_product(self.customer, 'CS-BLACK-M'), product)

    def test_internal_platform_ids_are_not_registered(self):
        """Only identifier types the connection matches on — a variant_id is
        not printed on a box and must never occupy a scannable code."""
        product = self.import_line(
            {'barcode': '7640228381098', 'sku': 'CS-BLACK-L',
             'variant_id': '4711'}, order_id='2')

        self.assertIsNone(resolve_product(self.customer, '4711'))
        self.assertEqual(
            set(product.barcodes.values_list('code', flat=True)), {'CS-BLACK-L'})

    def test_an_existing_product_is_reused_not_duplicated_or_rewritten(self):
        """A code already in the catalog wins over creating anything new, and
        the merchant's own product keeps the codes they gave it: we only hand
        extra aliases to products we created ourselves."""
        owner = Product.objects.create(
            customer=self.customer, code='CS-BLACK-M',
            description='Hand-made entry', active=True)

        ext = ExternalOrder(
            external_order_id='3', order_number='3',
            lines=[ExternalLine(
                external_variant_id='v3', external_product_id='p3', quantity=1,
                title='Corset Shorts',
                identifiers={'barcode': '7640228381081', 'sku': 'CS-BLACK-M'})],
        )
        intake.import_external_order(self.connection, ext)

        # Matched on the SKU — no second product for the same thing.
        self.assertEqual(Product.objects.filter(customer=self.customer).count(), 1)
        self.assertEqual(resolve_product(self.customer, 'CS-BLACK-M'), owner)
        owner.refresh_from_db()
        self.assertFalse(owner.barcodes.exists())

    def test_single_identifier_variant_gets_no_aliases(self):
        product = self.import_line({'sku': 'ONLY-SKU'}, order_id='4')
        self.assertEqual(product.code, 'ONLY-SKU')
        self.assertFalse(product.barcodes.exists())
