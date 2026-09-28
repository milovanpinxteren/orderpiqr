"""Barcode aliases: one product, several scannable codes.

Suppliers rotate EANs, so during the transition old and new barcodes are both
in physical circulation. Every scan surface must resolve either code to the
same product, and merging accidental duplicates must keep every code working.
"""
import json

from django.contrib.auth.models import Group, User
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import activate

from orderpiqrApp.models import (
    Customer, Device, Order, OrderLine, PickList, Product, ProductBarcode,
    ProductPick, UserProfile,
)
from orderpiqrApp.utils.products import (
    code_conflict, merge_products, resolve_product, set_alias_codes, set_primary_code,
)

FINGERPRINT = 'barcode-test-fp'

OLD_EAN = '8712345678906'
NEW_EAN = '8798765432109'


class ProductBarcodeTestCase(TestCase):
    def setUp(self):
        activate('en')
        self.customer = Customer.objects.create(name='Healthy Fridge')
        picker_group, _ = Group.objects.get_or_create(name='orderpicker')

        self.picker = User.objects.create_user(username='picker1', password='pw12345678')
        self.picker.groups.add(picker_group)
        UserProfile.objects.create(user=self.picker, customer=self.customer)

        self.device = Device.objects.create(
            user=self.picker, customer=self.customer, device_fingerprint=FINGERPRINT,
            name='Test phone', description='', last_login=timezone.now(), lists_picked=0)

        # Product whose EAN was rotated: NEW_EAN is primary, OLD_EAN an alias.
        self.smoothie = Product.objects.create(
            customer=self.customer, code=NEW_EAN, description='Green smoothie')
        ProductBarcode.objects.create(product=self.smoothie, code=OLD_EAN)

        self.client.login(username='picker1', password='pw12345678')

    def scan(self, picklist, order_id='ORD-1'):
        return self.client.post('/orderpiqr/scan-picklist', data=json.dumps({
            'orderID': order_id,
            'picklist': picklist,
            'deviceFingerprint': FINGERPRINT,
        }), content_type='application/json')

    def pick(self, product_code, order_id='ORD-1'):
        return self.client.post('/orderpiqr/product-pick', data=json.dumps({
            'orderID': order_id,
            'productCode': product_code,
            'deviceFingerprint': FINGERPRINT,
            'successful': True,
            'timeTakenMs': 1200,
        }), content_type='application/json')


class ResolveProductTests(ProductBarcodeTestCase):
    def test_resolves_primary_code(self):
        self.assertEqual(resolve_product(self.customer, NEW_EAN), self.smoothie)

    def test_resolves_alias_code(self):
        self.assertEqual(resolve_product(self.customer, OLD_EAN), self.smoothie)

    def test_alias_of_other_customer_does_not_resolve(self):
        other = Customer.objects.create(name='Other Warehouse')
        self.assertIsNone(resolve_product(other, OLD_EAN))

    def test_unknown_code_returns_none(self):
        self.assertIsNone(resolve_product(self.customer, 'NO-SUCH-CODE'))

    def test_alias_unique_per_customer(self):
        other_product = Product.objects.create(
            customer=self.customer, code='SALAD-1', description='Caesar salad')
        with self.assertRaises(IntegrityError):
            ProductBarcode.objects.create(product=other_product, code=OLD_EAN)

    def test_code_conflict_sees_primary_and_alias(self):
        self.assertTrue(code_conflict(self.customer, NEW_EAN))
        self.assertTrue(code_conflict(self.customer, OLD_EAN))
        self.assertFalse(code_conflict(self.customer, 'FREE-CODE'))
        # A product's own codes don't conflict with itself.
        self.assertFalse(code_conflict(self.customer, OLD_EAN, exclude_product=self.smoothie))


class ResolveGs1Tests(ProductBarcodeTestCase):
    """2D supplier labels (GS1 DataMatrix) carry the EAN inside AI 01 as a
    zero-padded GTIN-14, prefixed by FNC1 (the GS control character) and
    followed by further AIs such as expiry (17) and batch (10). The catalog
    stores the plain EAN-13/UPC-A, so resolution must extract the GTIN."""

    GS1_NEW_EAN = f"\x1d010{NEW_EAN}17261005"

    def test_gs1_with_fnc1_resolves_primary(self):
        self.assertEqual(resolve_product(self.customer, self.GS1_NEW_EAN), self.smoothie)

    def test_gs1_without_fnc1_resolves(self):
        self.assertEqual(resolve_product(self.customer, f"010{NEW_EAN}17261005"),
                         self.smoothie)

    def test_gs1_resolves_alias(self):
        self.assertEqual(resolve_product(self.customer, f"\x1d010{OLD_EAN}10BATCH42"),
                         self.smoothie)

    def test_gs1_unknown_gtin_returns_none(self):
        self.assertIsNone(resolve_product(self.customer, "\x1d010999999999999917261005"))

    def test_gs1_upc_a_needs_two_zeroes_stripped(self):
        upc_product = Product.objects.create(
            customer=self.customer, code='687456927435', description='Made Good bar')
        self.assertEqual(resolve_product(self.customer, "\x1d010068745692743517261005"),
                         upc_product)

    def test_gs1_gtin14_stored_as_is_resolves(self):
        gtin_product = Product.objects.create(
            customer=self.customer, code='18712345678903', description='Case of smoothies')
        self.assertEqual(resolve_product(self.customer, "\x1d011871234567890317261005"),
                         gtin_product)

    def test_pick_with_gs1_code_registers(self):
        """The picker client posts the raw scanned code; a GS1 label on the
        physical item must still tick off the picklist line."""
        self.scan([NEW_EAN])

        response = self.pick(self.GS1_NEW_EAN)

        self.assertEqual(response.status_code, 200)
        picklist = PickList.objects.get(picklist_code='ORD-1', customer=self.customer)
        pick = ProductPick.objects.get(picklist=picklist, product=self.smoothie)
        self.assertTrue(pick.successful)


class ScanWithAliasTests(ProductBarcodeTestCase):
    def test_picklist_qr_with_old_ean_resolves(self):
        """A paper picklist printed before the EAN change keeps working."""
        response = self.scan([OLD_EAN, OLD_EAN])

        self.assertEqual(response.status_code, 200)
        picklist = PickList.objects.get(picklist_code='ORD-1', customer=self.customer)
        picks = ProductPick.objects.filter(picklist=picklist)
        self.assertEqual(picks.count(), 2)
        self.assertEqual({p.product for p in picks}, {self.smoothie})

    def test_pick_scanning_other_generation_barcode_registers(self):
        """Picklist listed the old EAN; the physical item carries the new one
        (or vice versa) — the pick must still tick off."""
        self.scan([OLD_EAN])

        response = self.pick(NEW_EAN)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        pick = ProductPick.objects.get(product=self.smoothie)
        self.assertTrue(pick.successful)

    def test_pick_scanning_old_barcode_registers(self):
        self.scan([NEW_EAN])

        response = self.pick(OLD_EAN)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')


class SetPrimaryCodeTests(ProductBarcodeTestCase):
    def test_old_primary_is_kept_as_alias(self):
        product = Product.objects.create(
            customer=self.customer, code='SKU-1', description='Wrap')

        set_primary_code(product, 'SKU-2')

        product.refresh_from_db()
        self.assertEqual(product.code, 'SKU-2')
        self.assertEqual(list(product.barcodes.values_list('code', flat=True)), ['SKU-1'])

    def test_promoting_an_alias_swaps_it_with_the_primary(self):
        set_primary_code(self.smoothie, OLD_EAN)

        self.smoothie.refresh_from_db()
        self.assertEqual(self.smoothie.code, OLD_EAN)
        self.assertEqual(
            list(self.smoothie.barcodes.values_list('code', flat=True)), [NEW_EAN])

    def test_unchanged_code_is_a_noop(self):
        set_primary_code(self.smoothie, NEW_EAN)
        self.assertEqual(
            list(self.smoothie.barcodes.values_list('code', flat=True)), [OLD_EAN])


class SetAliasCodesTests(ProductBarcodeTestCase):
    def test_replaces_alias_set(self):
        set_alias_codes(self.smoothie, ['111', '222'])
        self.assertEqual(
            sorted(self.smoothie.barcodes.values_list('code', flat=True)), ['111', '222'])

    def test_primary_code_is_dropped_from_aliases(self):
        set_alias_codes(self.smoothie, [NEW_EAN, '111'])
        self.assertEqual(
            list(self.smoothie.barcodes.values_list('code', flat=True)), ['111'])


class MergeProductsTests(ProductBarcodeTestCase):
    def setUp(self):
        super().setUp()
        # Orphan created by a sync that didn't know about the EAN change.
        self.orphan = Product.objects.create(
            customer=self.customer, code='ORPHAN-EAN', description='Green smoothie (dup)',
            inventory_quantity=7)
        self.smoothie.inventory_quantity = 3
        self.smoothie.save(update_fields=['inventory_quantity'])

    def test_merge_moves_lines_picks_codes_and_inventory(self):
        order = Order.objects.create(
            customer=self.customer, order_code='ORD-9', status='queued', queue_position=1)
        line = OrderLine.objects.create(order=order, product=self.orphan, quantity=2)
        picklist = PickList.objects.create(
            picklist_code='ORD-9', customer=self.customer, device=self.device,
            updated_at=timezone.now(), pick_started=True, order=order)
        pick = ProductPick.objects.create(product=self.orphan, picklist=picklist, quantity=1)

        merge_products(self.smoothie, self.orphan)

        line.refresh_from_db()
        pick.refresh_from_db()
        self.smoothie.refresh_from_db()
        self.assertEqual(line.product, self.smoothie)
        self.assertEqual(pick.product, self.smoothie)
        self.assertEqual(self.smoothie.inventory_quantity, 10)
        self.assertFalse(Product.objects.filter(pk=self.orphan.pk).exists())
        # Every code stays scannable and lands on the surviving product.
        self.assertEqual(resolve_product(self.customer, 'ORPHAN-EAN'), self.smoothie)
        self.assertEqual(resolve_product(self.customer, OLD_EAN), self.smoothie)

    def test_merge_into_itself_is_rejected(self):
        with self.assertRaises(ValueError):
            merge_products(self.smoothie, self.smoothie)

    def test_merge_across_customers_is_rejected(self):
        other = Customer.objects.create(name='Other Warehouse')
        foreign = Product.objects.create(customer=other, code='X', description='X')
        with self.assertRaises(ValueError):
            merge_products(self.smoothie, foreign)


class ManageMergeActionTests(ProductBarcodeTestCase):
    def setUp(self):
        super().setUp()
        admin_group, _ = Group.objects.get_or_create(name='companyadmin')
        self.admin = User.objects.create_user(username='admin1', password='pw12345678')
        self.admin.groups.add(admin_group)
        UserProfile.objects.create(user=self.admin, customer=self.customer)
        self.client.login(username='admin1', password='pw12345678')

        self.orphan = Product.objects.create(
            customer=self.customer, code='ORPHAN-EAN', description='Green smoothie (dup)')

    def bulk(self, payload):
        return self.client.post(reverse('manage_products_bulk_action'),
                                data=json.dumps(payload),
                                content_type='application/json')

    def test_merge_action_merges_into_target_code(self):
        response = self.bulk({
            'action': 'merge',
            'product_ids': [self.orphan.product_id],
            'value': NEW_EAN,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        self.assertFalse(Product.objects.filter(pk=self.orphan.pk).exists())
        self.assertEqual(resolve_product(self.customer, 'ORPHAN-EAN'), self.smoothie)

    def test_merge_target_may_be_among_the_selection(self):
        response = self.bulk({
            'action': 'merge',
            'product_ids': [self.orphan.product_id, self.smoothie.product_id],
            'value': NEW_EAN,
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Product.objects.filter(pk=self.smoothie.pk).exists())
        self.assertFalse(Product.objects.filter(pk=self.orphan.pk).exists())

    def test_merge_with_unknown_target_is_rejected(self):
        response = self.bulk({
            'action': 'merge',
            'product_ids': [self.orphan.product_id],
            'value': 'NO-SUCH-CODE',
        })
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Product.objects.filter(pk=self.orphan.pk).exists())


class ManageProductFormTests(ProductBarcodeTestCase):
    def setUp(self):
        super().setUp()
        admin_group, _ = Group.objects.get_or_create(name='companyadmin')
        self.admin = User.objects.create_user(username='admin1', password='pw12345678')
        self.admin.groups.add(admin_group)
        UserProfile.objects.create(user=self.admin, customer=self.customer)
        self.client.login(username='admin1', password='pw12345678')

    def test_create_with_barcodes(self):
        response = self.client.post(reverse('manage_product_create'), {
            'code': 'SKU-9',
            'description': 'Juice',
            'location': '',
            'barcodes': '111\n222',
        })

        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(customer=self.customer, code='SKU-9')
        self.assertEqual(sorted(product.barcodes.values_list('code', flat=True)), ['111', '222'])

    def test_create_rejects_code_taken_as_alias_elsewhere(self):
        response = self.client.post(reverse('manage_product_create'), {
            'code': OLD_EAN,  # alias of smoothie
            'description': 'Impostor',
            'barcodes': '',
        })
        self.assertEqual(response.status_code, 200)  # re-rendered with errors
        self.assertFalse(Product.objects.filter(customer=self.customer, code=OLD_EAN).exists())

    def test_edit_rejects_barcode_taken_by_other_product(self):
        product = Product.objects.create(
            customer=self.customer, code='SKU-9', description='Juice')
        response = self.client.post(
            reverse('manage_product_edit', args=[product.product_id]), {
            'code': 'SKU-9',
            'description': 'Juice',
            'barcodes': OLD_EAN,  # already smoothie's alias
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(product.barcodes.count(), 0)

    def test_edit_replaces_barcodes(self):
        response = self.client.post(
            reverse('manage_product_edit', args=[self.smoothie.product_id]), {
            'code': NEW_EAN,
            'description': 'Green smoothie',
            'barcodes': '333',
            'active': 'on',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            list(self.smoothie.barcodes.values_list('code', flat=True)), ['333'])


class InventoryLookupTests(ProductBarcodeTestCase):
    def setUp(self):
        super().setUp()
        from orderpiqrApp.models import CustomerSettingValue, SettingDefinition
        definition, _created = SettingDefinition.objects.get_or_create(
            key='inventory_management_enabled',
            defaults={'label': 'Inventory management', 'setting_type': 'bool',
                      'default_value': 'false'},
        )
        CustomerSettingValue.objects.update_or_create(
            customer=self.customer, definition=definition, defaults={'value': 'true'})

    def test_lookup_by_alias_returns_the_product(self):
        response = self.client.get(reverse('inventory_lookup', args=[OLD_EAN]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['product']['code'], NEW_EAN)

    def test_lookup_of_inactive_product_stays_404(self):
        self.smoothie.active = False
        self.smoothie.save(update_fields=['active'])

        response = self.client.get(reverse('inventory_lookup', args=[OLD_EAN]))
        self.assertEqual(response.status_code, 404)


class CustomerReassignmentTests(ProductBarcodeTestCase):
    """The denormalised ProductBarcode.customer must follow its product."""

    def test_moving_a_product_updates_its_barcode_tenant(self):
        other = Customer.objects.create(name='Other Warehouse')

        self.smoothie.customer = other
        self.smoothie.save()

        barcode = self.smoothie.barcodes.get()
        self.assertEqual(barcode.customer, other)
        # The old tenant no longer resolves the alias; the new one does.
        self.assertIsNone(resolve_product(self.customer, OLD_EAN))
        self.assertEqual(resolve_product(other, OLD_EAN), self.smoothie)

    def test_save_without_customer_change_leaves_barcodes_alone(self):
        self.smoothie.description = 'Greener smoothie'
        self.smoothie.save()
        self.assertEqual(self.smoothie.barcodes.get().customer, self.customer)


class ProductBarcodeCleanTests(ProductBarcodeTestCase):
    """Form-level validation: collisions become field errors, not 500s."""

    def _clean_error(self, barcode):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError) as ctx:
            barcode.full_clean()
        return ctx.exception

    def test_duplicate_alias_is_a_validation_error(self):
        other_product = Product.objects.create(
            customer=self.customer, code='SALAD-1', description='Caesar salad')
        exc = self._clean_error(ProductBarcode(product=other_product, code=OLD_EAN))
        self.assertIn('code', exc.error_dict)

    def test_alias_equal_to_another_products_primary_is_rejected(self):
        other_product = Product.objects.create(
            customer=self.customer, code='SALAD-1', description='Caesar salad')
        exc = self._clean_error(ProductBarcode(product=other_product, code=NEW_EAN))
        self.assertIn('code', exc.error_dict)

    def test_alias_equal_to_own_primary_is_rejected(self):
        exc = self._clean_error(ProductBarcode(product=self.smoothie, code=NEW_EAN))
        self.assertIn('code', exc.error_dict)

    def test_same_code_for_another_customer_is_fine(self):
        other = Customer.objects.create(name='Other Warehouse')
        foreign = Product.objects.create(customer=other, code='X-1', description='X')
        ProductBarcode(product=foreign, code=OLD_EAN).full_clean()  # must not raise


class MergeInventoryLogTests(ProductBarcodeTestCase):
    def test_merge_writes_an_inventory_log_entry(self):
        from orderpiqrApp.models import InventoryLog
        orphan = Product.objects.create(
            customer=self.customer, code='ORPHAN-EAN', description='Dup',
            inventory_quantity=7)
        self.smoothie.inventory_quantity = 3
        self.smoothie.save(update_fields=['inventory_quantity'])

        merge_products(self.smoothie, orphan, user=self.picker)

        self.smoothie.refresh_from_db()
        self.assertEqual(self.smoothie.inventory_quantity, 10)
        log = InventoryLog.objects.get(product=self.smoothie, reason=InventoryLog.Reason.OTHER)
        self.assertEqual((log.old_quantity, log.new_quantity), (3, 10))
        self.assertEqual(log.user, self.picker)

    def test_merge_of_zero_inventory_writes_no_log(self):
        from orderpiqrApp.models import InventoryLog
        orphan = Product.objects.create(
            customer=self.customer, code='ORPHAN-EAN', description='Dup')
        merge_products(self.smoothie, orphan)
        self.assertFalse(InventoryLog.objects.exists())


class CompanyAdminTestCase(ProductBarcodeTestCase):
    """Base for manage-portal tests: logs in as a companyadmin (no own tests)."""

    def setUp(self):
        super().setUp()
        admin_group, _ = Group.objects.get_or_create(name='companyadmin')
        self.admin = User.objects.create_user(username='admin1', password='pw12345678')
        self.admin.groups.add(admin_group)
        UserProfile.objects.create(user=self.admin, customer=self.customer)
        self.client.login(username='admin1', password='pw12345678')


class ManageMergeByAliasTests(CompanyAdminTestCase):
    def test_merge_target_identified_by_alias_code(self):
        orphan = Product.objects.create(
            customer=self.customer, code='ORPHAN-EAN', description='Green smoothie (dup)')
        response = self.client.post(reverse('manage_products_bulk_action'),
                                    data=json.dumps({
                                        'action': 'merge',
                                        'product_ids': [orphan.product_id],
                                        'value': OLD_EAN,  # an alias of the intended target
                                    }),
                                    content_type='application/json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        self.assertFalse(Product.objects.filter(pk=orphan.pk).exists())
        self.assertEqual(resolve_product(self.customer, 'ORPHAN-EAN'), self.smoothie)


class InlineCodeEditTests(CompanyAdminTestCase):
    def test_inline_code_change_keeps_old_primary_as_barcode(self):
        response = self.client.post(
            reverse('manage_product_inline_edit', args=[self.smoothie.product_id]),
            data=json.dumps({'field': 'code', 'value': 'BRAND-NEW'}),
            content_type='application/json')

        self.assertEqual(response.status_code, 200)
        self.smoothie.refresh_from_db()
        self.assertEqual(self.smoothie.code, 'BRAND-NEW')
        # Both previous codes still resolve ("never forget a code").
        self.assertEqual(resolve_product(self.customer, NEW_EAN), self.smoothie)
        self.assertEqual(resolve_product(self.customer, OLD_EAN), self.smoothie)

    def test_inline_code_conflict_is_rejected(self):
        other_product = Product.objects.create(
            customer=self.customer, code='SALAD-1', description='Caesar salad')
        response = self.client.post(
            reverse('manage_product_inline_edit', args=[other_product.product_id]),
            data=json.dumps({'field': 'code', 'value': OLD_EAN}),
            content_type='application/json')
        self.assertEqual(response.status_code, 400)


class HealthPageAliasTests(CompanyAdminTestCase):
    def test_alias_codes_are_not_offered_as_new_products(self):
        from orderpiqrApp.models import ScanEvent
        ScanEvent.objects.create(customer=self.customer, event_type='unknown_product',
                                 scanned_code=OLD_EAN)
        ScanEvent.objects.create(customer=self.customer, event_type='unknown_product',
                                 scanned_code='REALLY-UNKNOWN')

        response = self.client.get(reverse('manage_health'))

        self.assertEqual(response.status_code, 200)
        by_code = {entry['scanned_code']: entry for entry in response.context['top_codes']}
        self.assertTrue(by_code[OLD_EAN]['product_exists'])
        self.assertFalse(by_code['REALLY-UNKNOWN']['product_exists'])


class AdminSaveModelTests(ProductBarcodeTestCase):
    def test_django_admin_rejects_code_taken_as_alias(self):
        from django.contrib import admin as django_admin
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.forms import modelform_factory
        from django.test import RequestFactory

        from orderpiqrApp.admin.product_admin import ProductAdmin

        admin_group, _ = Group.objects.get_or_create(name='companyadmin')
        staff = User.objects.create_user(username='staffadmin', password='pw12345678',
                                         is_staff=True)
        staff.groups.add(admin_group)
        UserProfile.objects.create(user=staff, customer=self.customer)

        form_class = modelform_factory(Product, fields=['code', 'description', 'location'])
        form = form_class(data={'code': OLD_EAN, 'description': 'Impostor', 'location': 'X'})
        self.assertTrue(form.is_valid())

        request = RequestFactory().post('/admin/orderpiqrApp/product/add/')
        request.user = staff
        request.session = self.client.session
        request._messages = FallbackStorage(request)

        model_admin = ProductAdmin(Product, django_admin.site)
        model_admin.save_model(request, form.save(commit=False), form, change=False)

        # OLD_EAN is the smoothie's alias: the save must be refused.
        self.assertFalse(Product.objects.filter(customer=self.customer, code=OLD_EAN).exists())


class ScanPageXssTests(ProductBarcodeTestCase):
    def test_product_description_cannot_break_out_of_the_json_block(self):
        from orderpiqrApp.utils.devices import SESSION_KEY
        self.smoothie.description = '</script><script>alert(1)</script>'
        self.smoothie.save(update_fields=['description'])

        # Pin the device fingerprint to the session so the scan page resolves.
        session = self.client.session
        session[SESSION_KEY] = FINGERPRINT
        session.save()
        response = self.client.get(reverse('index'))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn('</script><script>alert(1)</script>', content)
        # json_script keeps the data readable for the page's own JS.
        self.assertIn('\\u003C/script\\u003E', content)
