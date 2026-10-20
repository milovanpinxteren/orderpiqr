"""Bulk actions on the manage orders/products lists, including the
"select all matching filters" mode."""
import json
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import activate

from orderpiqrApp.models import Customer, Order, OrderLine, Product, UserProfile, PickList, Device


class BulkActionTestCase(TestCase):
    def setUp(self):
        activate('en')
        self.customer = Customer.objects.create(name='House of Tests')
        admin_group, _ = Group.objects.get_or_create(name='companyadmin')
        self.admin = User.objects.create_user(username='boss', password='secret123')
        self.admin.groups.add(admin_group)
        UserProfile.objects.create(user=self.admin, customer=self.customer)
        self.client.login(username='boss', password='secret123')

        self.other_customer = Customer.objects.create(name='Other company')

    def post_json(self, url, payload):
        return self.client.post(url, json.dumps(payload),
                                content_type='application/json')


class OrdersBulkActionTests(BulkActionTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('manage_orders_bulk_action')

    def make_order(self, code, status='draft', source='manual', **kwargs):
        return Order.objects.create(customer=self.customer, order_code=code,
                                    status=status, source=source, **kwargs)

    def test_delete_by_ids_skips_in_progress(self):
        draft = self.make_order('D1')
        picking = self.make_order('P1', status='in_progress', queue_position=1)
        response = self.post_json(self.url, {
            'action': 'delete',
            'order_ids': [draft.order_id, picking.order_id],
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Order.objects.filter(pk=draft.pk).exists())
        self.assertTrue(Order.objects.filter(pk=picking.pk).exists())
        self.assertIn('skipped', response.json()['message'])

    def test_delete_ignores_other_customers_orders(self):
        foreign = Order.objects.create(customer=self.other_customer, order_code='F1')
        self.post_json(self.url, {'action': 'delete', 'order_ids': [foreign.order_id]})
        self.assertTrue(Order.objects.filter(pk=foreign.pk).exists())

    def test_select_all_applies_filters(self):
        old = self.make_order('OLD')
        Order.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=30))
        recent = self.make_order('NEW')
        shopify = self.make_order('SHOP', source='shopify')

        cutoff = (timezone.now() - timedelta(days=7)).date().isoformat()
        response = self.post_json(self.url, {
            'action': 'delete',
            'select_all': True,
            'filters': {'status': 'draft', 'source': 'manual', 'date_from': cutoff},
        })
        self.assertEqual(response.status_code, 200)
        # Only the recent manual draft matches: old is outside the date range,
        # shopify has a different source.
        self.assertFalse(Order.objects.filter(pk=recent.pk).exists())
        self.assertTrue(Order.objects.filter(pk=old.pk).exists())
        self.assertTrue(Order.objects.filter(pk=shopify.pk).exists())

    def test_select_all_date_to_filter(self):
        old = self.make_order('OLD')
        Order.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=30))
        recent = self.make_order('NEW')

        cutoff = (timezone.now() - timedelta(days=7)).date().isoformat()
        self.post_json(self.url, {
            'action': 'delete',
            'select_all': True,
            'filters': {'date_to': cutoff},
        })
        self.assertFalse(Order.objects.filter(pk=old.pk).exists())
        self.assertTrue(Order.objects.filter(pk=recent.pk).exists())

    def test_add_to_queue_appends_after_existing_queue(self):
        self.make_order('Q1', status='queued', queue_position=5)
        first = self.make_order('D1')
        second = self.make_order('D2')
        completed = self.make_order('C1', status='completed')

        response = self.post_json(self.url, {
            'action': 'add_to_queue',
            'order_ids': [first.order_id, second.order_id, completed.order_id],
        })
        self.assertEqual(response.status_code, 200)
        first.refresh_from_db()
        second.refresh_from_db()
        completed.refresh_from_db()
        self.assertEqual(first.status, 'queued')
        self.assertEqual(first.queue_position, 6)
        self.assertEqual(second.queue_position, 7)
        self.assertEqual(completed.status, 'completed')
        self.assertIn('skipped', response.json()['message'])

    def test_remove_from_queue_only_touches_queued(self):
        queued = self.make_order('Q1', status='queued', queue_position=1)
        picking = self.make_order('P1', status='in_progress', queue_position=2)

        response = self.post_json(self.url, {
            'action': 'remove_from_queue',
            'order_ids': [queued.order_id, picking.order_id],
        })
        self.assertEqual(response.status_code, 200)
        queued.refresh_from_db()
        picking.refresh_from_db()
        self.assertEqual(queued.status, 'draft')
        self.assertIsNone(queued.queue_position)
        self.assertEqual(picking.status, 'in_progress')

    def test_reset_to_draft_unclaims_in_progress_and_deletes_active_picklist(self):
        from orderpiqrApp.models import Device, PickList
        picking = self.make_order('P1', status='in_progress', queue_position=1)
        queued = self.make_order('Q1', status='queued', queue_position=2)
        completed = self.make_order('C1', status='completed')
        device = Device.objects.create(
            user=self.admin, customer=self.customer, device_fingerprint='fp-1',
            name='Phone', description='', last_login=timezone.now(), lists_picked=0)
        active = PickList.objects.create(
            picklist_code='P1', customer=self.customer, device=device,
            order=picking, pick_started=True)

        response = self.post_json(self.url, {
            'action': 'reset_to_draft',
            'order_ids': [picking.order_id, queued.order_id, completed.order_id],
        })
        self.assertEqual(response.status_code, 200)
        picking.refresh_from_db()
        queued.refresh_from_db()
        completed.refresh_from_db()
        self.assertEqual(picking.status, 'draft')
        self.assertIsNone(picking.queue_position)
        self.assertEqual(queued.status, 'draft')
        self.assertEqual(completed.status, 'completed')
        self.assertFalse(PickList.objects.filter(pk=active.pk).exists())
        self.assertIn('skipped', response.json()['message'])

    def test_reset_to_draft_then_delete_removes_stuck_order(self):
        picking = self.make_order('P1', status='in_progress', queue_position=1)
        self.post_json(self.url, {'action': 'reset_to_draft', 'order_ids': [picking.order_id]})
        self.post_json(self.url, {'action': 'delete', 'order_ids': [picking.order_id]})
        self.assertFalse(Order.objects.filter(pk=picking.pk).exists())

    def test_reset_to_draft_spares_completed_picklists(self):
        # Only the ACTIVE picklist is discarded; a finished one is history.
        from orderpiqrApp.models import Device, PickList
        picking = self.make_order('P1', status='in_progress')
        device = Device.objects.create(
            user=self.admin, customer=self.customer, device_fingerprint='fp-1',
            name='Phone', description='', last_login=timezone.now(), lists_picked=0)
        done = PickList.objects.create(
            picklist_code='P1', customer=self.customer, device=device,
            order=picking, pick_started=True, successful=True)

        self.post_json(self.url, {'action': 'reset_to_draft', 'order_ids': [picking.order_id]})
        self.assertTrue(PickList.objects.filter(pk=done.pk).exists())

    def test_empty_selection_rejected(self):
        response = self.post_json(self.url, {'action': 'delete', 'order_ids': []})
        self.assertEqual(response.status_code, 400)

    def test_select_all_is_scoped_to_own_customer(self):
        foreign = Order.objects.create(customer=self.other_customer, order_code='F1')
        self.post_json(self.url, {'action': 'delete', 'select_all': True, 'filters': {}})
        self.assertTrue(Order.objects.filter(pk=foreign.pk).exists())

    def test_unknown_action_rejected(self):
        self.make_order('D1')
        response = self.post_json(self.url, {'action': 'explode', 'select_all': True})
        self.assertEqual(response.status_code, 400)


class ListPageRenderTests(BulkActionTestCase):
    """The list templates wire up ListTools; make sure they still render,
    including the new filter controls."""

    def test_orders_list_renders_with_filters(self):
        Order.objects.create(customer=self.customer, order_code='O1', source='manual')
        Order.objects.create(customer=self.customer, order_code='O2', source='shopify')
        response = self.client.get(reverse('manage_orders'), {
            'status': 'draft', 'source': 'manual',
            'date_from': '2026-01-01', 'date_to': '2026-12-31',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'O1')
        self.assertNotContains(response, 'O2')
        self.assertContains(response, 'date-from-filter')
        self.assertContains(response, 'bulk-banner')

    def test_products_list_renders(self):
        Product.objects.create(customer=self.customer, code='P1', description='P1')
        response = self.client.get(reverse('manage_products'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'bulk-banner')

    def test_picklists_list_renders_with_filters(self):
        from orderpiqrApp.models import Device, PickList
        device = Device.objects.create(
            user=self.admin, customer=self.customer, device_fingerprint='fp-1',
            name='Phone', description='', last_login=timezone.now(), lists_picked=0)
        p1 = PickList.objects.create(
            picklist_code='LIST-001', customer=self.customer, device=device)
        p2 = PickList.objects.create(
            picklist_code='OTHER-001', customer=self.customer, device=device)
        response = self.client.get(reverse('manage_picklists'), {
            'q': 'LIST',
            'status': 'pending',
            'device': str(device.device_id),
            'date_from': '2026-01-01',
            'date_to': '2026-12-31',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'LIST-001')
        self.assertNotContains(response, 'OTHER-001')
        self.assertContains(response, 'date-from-filter')
        self.assertContains(response, 'bulk-banner')

    def test_picklists_device_filter_is_a_searchable_select(self):
        # The combobox enhances the native select, which must survive intact:
        # currentFilters() and its onchange read it directly.
        def make_device(fingerprint, name):
            return Device.objects.create(
                user=self.admin, customer=self.customer,
                device_fingerprint=fingerprint, name=name, description='',
                last_login=timezone.now(), lists_picked=0)

        make_device('fp-1', 'Freezer Phone')
        make_device('fp-2', 'Dock Tablet')

        response = self.client.get(reverse('manage_picklists'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'manage/searchableSelect')
        self.assertContains(response, "SearchableSelect.init('device-filter')")
        self.assertContains(response, 'id="device-filter"')
        self.assertContains(response, 'onchange="applyFilters()"')
        self.assertContains(response, 'Freezer Phone')
        self.assertContains(response, 'Dock Tablet')


class ProductsBulkActionTests(BulkActionTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('manage_products_bulk_action')

    def make_product(self, code, **kwargs):
        kwargs.setdefault('description', code)
        return Product.objects.create(customer=self.customer, code=code, **kwargs)

    def test_select_all_applies_filters(self):
        aisle_a = self.make_product('A1', location='A')
        aisle_b = self.make_product('B1', location='B')
        response = self.post_json(self.url, {
            'action': 'deactivate',
            'select_all': True,
            'filters': {'location': 'A'},
        })
        self.assertEqual(response.status_code, 200)
        aisle_a.refresh_from_db()
        aisle_b.refresh_from_db()
        self.assertFalse(aisle_a.active)
        self.assertTrue(aisle_b.active)

    def test_delete_skips_products_used_in_orders(self):
        used = self.make_product('USED')
        unused = self.make_product('UNUSED')
        order = Order.objects.create(customer=self.customer, order_code='O1')
        OrderLine.objects.create(order=order, product=used, quantity=1)

        response = self.post_json(self.url, {
            'action': 'delete',
            'product_ids': [used.product_id, unused.product_id],
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Product.objects.filter(pk=used.pk).exists())
        self.assertFalse(Product.objects.filter(pk=unused.pk).exists())
        self.assertIn('skipped', response.json()['message'])

    def test_ids_mode_still_works(self):
        product = self.make_product('P1')
        response = self.post_json(self.url, {
            'action': 'set_location',
            'product_ids': [product.product_id],
            'value': 'C-3',
        })
        self.assertEqual(response.status_code, 200)
        product.refresh_from_db()
        self.assertEqual(product.location, 'C-3')

    def test_select_all_is_scoped_to_own_customer(self):
        foreign = Product.objects.create(customer=self.other_customer,
                                         code='F1', description='F1')
        self.post_json(self.url, {'action': 'delete', 'select_all': True, 'filters': {}})
        foreign.refresh_from_db()  # still exists
        self.assertTrue(Product.objects.filter(pk=foreign.pk).exists())

    def test_empty_selection_rejected(self):
        response = self.post_json(self.url, {'action': 'delete', 'product_ids': []})
        self.assertEqual(response.status_code, 400)


class PicklistsBulkActionTests(BulkActionTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('manage_picklists_bulk_action')
        from orderpiqrApp.models import Device
        self.device = Device.objects.create(
            user=self.admin, customer=self.customer, device_fingerprint='fp-1',
            name='Phone', description='', last_login=timezone.now(), lists_picked=0)

    def make_picklist(self, code, device=None, order=None, **kwargs):
        from orderpiqrApp.models import PickList
        if device is None:
            device = self.device
        return PickList.objects.create(
            picklist_code=code, customer=self.customer, device=device,
            order=order, **kwargs)

    def test_complete_marks_successful_and_closes_order(self):
        order = Order.objects.create(customer=self.customer, order_code='O1', status='in_progress')
        picklist = self.make_picklist('P1', order=order, pick_started=True)
        response = self.post_json(self.url, {
            'action': 'complete',
            'picklist_ids': [picklist.picklist_id],
        })
        self.assertEqual(response.status_code, 200)
        picklist.refresh_from_db()
        order.refresh_from_db()
        self.assertTrue(picklist.successful)
        self.assertEqual(order.status, 'completed')
        self.assertIsNotNone(order.completed_at)
        self.assertIn('marked as completed', response.json()['message'])

    def test_complete_skips_already_marked_picklists(self):
        completed = self.make_picklist('P1', successful=True)
        failed = self.make_picklist('P2', successful=False)
        response = self.post_json(self.url, {
            'action': 'complete',
            'picklist_ids': [completed.picklist_id, failed.picklist_id],
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('skipped', response.json()['message'])

    def test_archive_marks_archived(self):
        picklist = self.make_picklist('P1')
        response = self.post_json(self.url, {
            'action': 'archive',
            'picklist_ids': [picklist.picklist_id],
        })
        self.assertEqual(response.status_code, 200)
        picklist.refresh_from_db()
        self.assertTrue(picklist.archived)
        self.assertIn('archived', response.json()['message'])

    def test_archive_skips_already_archived(self):
        archived = self.make_picklist('P1', archived=True)
        response = self.post_json(self.url, {
            'action': 'archive',
            'picklist_ids': [archived.picklist_id],
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('skipped', response.json()['message'])

    def test_ignores_other_customers_picklists(self):
        foreign_device = Device.objects.create(
            customer=self.other_customer, device_fingerprint='fp-2',
            name='Other Phone', description='', last_login=timezone.now(), lists_picked=0)
        foreign = PickList.objects.create(
            picklist_code='F1', customer=self.other_customer, device=foreign_device)
        # If this wasn't scoped to the customer, we'd try to complete a foreign picklist
        response = self.post_json(self.url, {
            'action': 'complete',
            'picklist_ids': [foreign.picklist_id],
        })
        self.assertEqual(response.status_code, 400)
        foreign.refresh_from_db()
        self.assertIsNone(foreign.successful)

    def test_select_all_applies_filters(self):
        # Create picklists with different statuses
        pending = self.make_picklist('P1', pick_started=None)
        in_progress = self.make_picklist('P2', pick_started=True)
        completed = self.make_picklist('P3', successful=True)

        # Complete all pending picklists
        response = self.post_json(self.url, {
            'action': 'complete',
            'select_all': True,
            'filters': {'status': 'pending'},
        })
        self.assertEqual(response.status_code, 200)
        pending.refresh_from_db()
        in_progress.refresh_from_db()
        completed.refresh_from_db()
        self.assertTrue(pending.successful)
        self.assertIsNone(in_progress.successful)
        self.assertTrue(completed.successful)

    def test_select_all_filters_by_device(self):
        other_device = Device.objects.create(
            customer=self.customer, device_fingerprint='fp-2',
            name='Tablet', description='', last_login=timezone.now(), lists_picked=0)
        phone_list = self.make_picklist('P1')
        tablet_list = self.make_picklist('P2', device=other_device)

        response = self.post_json(self.url, {
            'action': 'archive',
            'select_all': True,
            'filters': {'device': str(self.device.device_id)},
        })
        self.assertEqual(response.status_code, 200)
        phone_list.refresh_from_db()
        tablet_list.refresh_from_db()
        self.assertTrue(phone_list.archived)
        self.assertFalse(tablet_list.archived)

    def test_select_all_filters_by_code(self):
        match = self.make_picklist('MATCH-001')
        nomatch = self.make_picklist('OTHER-001')

        response = self.post_json(self.url, {
            'action': 'archive',
            'select_all': True,
            'filters': {'q': 'MATCH'},
        })
        self.assertEqual(response.status_code, 200)
        match.refresh_from_db()
        nomatch.refresh_from_db()
        self.assertTrue(match.archived)
        self.assertFalse(nomatch.archived)

    def test_select_all_filters_by_date_range(self):
        old = self.make_picklist('P1')
        PickList.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=30))
        recent = self.make_picklist('P2')

        cutoff = (timezone.now() - timedelta(days=7)).date().isoformat()
        response = self.post_json(self.url, {
            'action': 'archive',
            'select_all': True,
            'filters': {'date_from': cutoff},
        })
        self.assertEqual(response.status_code, 200)
        old.refresh_from_db()
        recent.refresh_from_db()
        self.assertFalse(old.archived)
        self.assertTrue(recent.archived)

    def test_empty_selection_rejected(self):
        response = self.post_json(self.url, {'action': 'complete', 'picklist_ids': []})
        self.assertEqual(response.status_code, 400)

    def test_unknown_action_rejected(self):
        self.make_picklist('P1')
        response = self.post_json(self.url, {'action': 'delete', 'select_all': True})
        self.assertEqual(response.status_code, 400)

    def test_complete_adds_admin_stamp_to_notes(self):
        picklist = self.make_picklist('P1')
        response = self.post_json(self.url, {
            'action': 'complete',
            'picklist_ids': [picklist.picklist_id],
        })
        picklist.refresh_from_db()
        self.assertIn('Marked completed by boss', picklist.notes)
