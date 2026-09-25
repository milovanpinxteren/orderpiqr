"""Pick-flow health: the dashboard scan-health stats, the manage health page
(filters, tenant scoping, top problem codes) and the product-create prefill
used by its "Add as product" button."""
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import activate

from orderpiqrApp.models import (
    Customer, Device, PickList, Product, ScanEvent, UserProfile,
)


class ManageHealthTestCase(TestCase):
    def setUp(self):
        activate('en')
        self.customer = Customer.objects.create(name='House of Tests')
        admin_group, _ = Group.objects.get_or_create(name='companyadmin')
        self.admin = User.objects.create_user(username='boss', password='secret123')
        self.admin.groups.add(admin_group)
        UserProfile.objects.create(user=self.admin, customer=self.customer)
        self.client.login(username='boss', password='secret123')

        self.other_customer = Customer.objects.create(name='Other company')

    def make_event(self, event_type, customer=None, days_ago=0, **kwargs):
        event = ScanEvent.objects.create(
            customer=customer or self.customer,
            event_type=event_type,
            **kwargs
        )
        if days_ago:
            # created_at is auto_now_add, so backdate via a queryset update.
            ScanEvent.objects.filter(pk=event.pk).update(
                created_at=timezone.now() - timedelta(days=days_ago))
        return event

    def make_device(self, customer=None, name='Scanner 1'):
        return Device.objects.create(
            customer=customer or self.customer,
            name=name,
            description='test device',
            last_login=timezone.now(),
            lists_picked=0,
        )

    def make_picklist(self, device, hours_ago, code='PL-1', started=True):
        picklist = PickList.objects.create(
            customer=self.customer,
            device=device,
            picklist_code=code,
            pick_started=started,
            successful=None,
        )
        # pick_time is auto_now_add, so backdate via a queryset update.
        PickList.objects.filter(pk=picklist.pk).update(
            pick_time=timezone.now() - timedelta(hours=hours_ago))
        return picklist


class DashboardHealthStatsTests(ManageHealthTestCase):
    def test_dashboard_context_contains_health_keys(self):
        response = self.client.get(reverse('manage_dashboard'))
        self.assertEqual(response.status_code, 200)
        for key in ['scan_issues_7d', 'scan_issues_24h', 'manual_overrides_7d',
                    'recent_scan_events', 'stale_picklists', 'stale_picklists_count']:
            self.assertIn(key, response.context)

    def test_dashboard_counts_events_correctly(self):
        self.make_event('unknown_product', scanned_code='X1')      # today: 24h + 7d
        self.make_event('sync_error', days_ago=2)                  # 7d only
        self.make_event('manual_override', days_ago=1)             # override, not an issue
        self.make_event('wrong_product', days_ago=10)              # outside both windows
        self.make_event('unknown_product', customer=self.other_customer)  # other tenant

        response = self.client.get(reverse('manage_dashboard'))
        self.assertEqual(response.context['scan_issues_7d'], 2)
        self.assertEqual(response.context['scan_issues_24h'], 1)
        self.assertEqual(response.context['manual_overrides_7d'], 1)

        recent = list(response.context['recent_scan_events'])
        self.assertEqual(len(recent), 4)  # other tenant's event excluded
        for event in recent:
            self.assertEqual(event.customer_id, self.customer.pk)

    def test_dashboard_recent_events_limited_to_eight(self):
        for i in range(10):
            self.make_event('unknown_product', scanned_code=f'CODE-{i}')
        response = self.client.get(reverse('manage_dashboard'))
        self.assertEqual(len(response.context['recent_scan_events']), 8)

    def test_dashboard_flags_stale_picklists(self):
        device = self.make_device()
        stale = self.make_picklist(device, hours_ago=5, code='PL-STALE')
        self.make_picklist(device, hours_ago=1, code='PL-FRESH')

        response = self.client.get(reverse('manage_dashboard'))
        self.assertEqual(response.context['stale_picklists_count'], 1)
        self.assertEqual([p.pk for p in response.context['stale_picklists']],
                         [stale.pk])


class HealthListTests(ManageHealthTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('manage_health')

    def test_renders_events(self):
        self.make_event('unknown_product', scanned_code='GHOST-1',
                        picklist_code='PL-9')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'GHOST-1')
        self.assertContains(response, 'PL-9')

    def test_filters_by_event_type(self):
        self.make_event('unknown_product', scanned_code='UNK-1')
        self.make_event('sync_error', scanned_code='SYNC-1')

        response = self.client.get(self.url, {'event_type': 'sync_error'})
        events = list(response.context['events'])
        self.assertEqual([e.event_type for e in events], ['sync_error'])
        self.assertEqual([e.scanned_code for e in events], ['SYNC-1'])
        # Note: the "Top Problem Codes" card still shows UNK-1 — only the
        # events table is filtered — so we assert on the context, not the HTML.

    def test_filters_by_date(self):
        self.make_event('unknown_product', scanned_code='OLD-1', days_ago=10)
        self.make_event('unknown_product', scanned_code='NEW-1')

        cutoff = (timezone.now() - timedelta(days=7)).date().isoformat()
        response = self.client.get(self.url, {'date_from': cutoff})
        codes = [e.scanned_code for e in response.context['events']]
        self.assertEqual(codes, ['NEW-1'])

    def test_excludes_other_customers_events(self):
        self.make_event('unknown_product', customer=self.other_customer,
                        scanned_code='FOREIGN-1')
        response = self.client.get(self.url)
        self.assertEqual(len(response.context['events']), 0)
        self.assertNotContains(response, 'FOREIGN-1')

    def test_top_codes_flag_unknown_vs_existing_products(self):
        Product.objects.create(customer=self.customer, code='KNOWN-1',
                               description='A known product')
        for _ in range(3):
            self.make_event('unknown_product', scanned_code='GHOST-1')
        self.make_event('wrong_product', scanned_code='KNOWN-1')
        # Outside the 7-day window: must not appear at all.
        self.make_event('unknown_product', scanned_code='ANCIENT-1', days_ago=8)

        response = self.client.get(self.url)
        top_codes = response.context['top_codes']
        by_code = {entry['scanned_code']: entry for entry in top_codes}

        self.assertNotIn('ANCIENT-1', by_code)
        self.assertEqual(by_code['GHOST-1']['count'], 3)
        self.assertFalse(by_code['GHOST-1']['product_exists'])
        self.assertTrue(by_code['KNOWN-1']['product_exists'])
        # Ordered by count, most frequent first.
        self.assertEqual(top_codes[0]['scanned_code'], 'GHOST-1')
        # The "Add as product" prefill link only for genuinely unknown codes.
        self.assertContains(response, '?code=GHOST-1')
        self.assertNotContains(response, '?code=KNOWN-1')

    def test_stale_picklists_listed_with_detail_link(self):
        device = self.make_device()
        stale = self.make_picklist(device, hours_ago=6, code='PL-STUCK')
        response = self.client.get(self.url)
        self.assertContains(response, 'PL-STUCK')
        self.assertContains(
            response, reverse('manage_picklist_detail', args=[stale.picklist_id]))


class PicklistCloseTests(ManageHealthTestCase):
    """Admin cleanup of stale picklists: mark completed or archive.
    There is deliberately no cancel/delete — billing counts picklists."""

    def setUp(self):
        super().setUp()
        self.device = self.make_device()
        self.picklist = self.make_picklist(self.device, hours_ago=6, code='PL-STUCK')
        self.url = reverse('manage_picklist_close', args=[self.picklist.picklist_id])

    def test_get_does_not_modify(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.picklist.refresh_from_db()
        self.assertIsNone(self.picklist.successful)
        self.assertFalse(self.picklist.archived)

    def test_mark_completed(self):
        from orderpiqrApp.models import Order
        order = Order.objects.create(
            customer=self.customer, order_code='ORD-STUCK', status='in_progress')
        PickList.objects.filter(pk=self.picklist.pk).update(order=order)

        response = self.client.post(self.url, {'action': 'complete', 'next': 'health'})
        self.assertRedirects(response, reverse('manage_health'))

        self.picklist.refresh_from_db()
        self.assertTrue(self.picklist.successful)
        self.assertIsNotNone(self.picklist.time_taken)
        self.assertIn('Marked completed by boss', self.picklist.notes)
        order.refresh_from_db()
        self.assertEqual(order.status, 'completed')
        self.assertIsNotNone(order.completed_at)

    def test_archive_hides_from_health_and_dashboard(self):
        response = self.client.post(self.url, {'action': 'archive', 'next': 'health'})
        self.assertRedirects(response, reverse('manage_health'))

        self.picklist.refresh_from_db()
        self.assertTrue(self.picklist.archived)
        self.assertIsNone(self.picklist.successful)  # archive is not completion
        self.assertIn('Archived by boss', self.picklist.notes)

        health = self.client.get(reverse('manage_health'))
        self.assertEqual(len(health.context['stale_picklists']), 0)
        dashboard = self.client.get(reverse('manage_dashboard'))
        self.assertEqual(dashboard.context['stale_picklists_count'], 0)

    def test_complete_ignored_when_already_closed(self):
        PickList.objects.filter(pk=self.picklist.pk).update(successful=True)
        self.client.post(self.url, {'action': 'complete'})
        self.picklist.refresh_from_db()
        self.assertIsNone(self.picklist.notes)  # no admin note appended

    def test_other_customers_picklist_is_404(self):
        other_device = self.make_device(customer=self.other_customer, name='Foreign')
        foreign = PickList.objects.create(
            customer=self.other_customer, device=other_device,
            picklist_code='PL-FOREIGN', pick_started=True, successful=None)
        url = reverse('manage_picklist_close', args=[foreign.picklist_id])
        response = self.client.post(url, {'action': 'archive'})
        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertFalse(foreign.archived)

    def test_archived_filter_on_picklists_list(self):
        self.client.post(self.url, {'action': 'archive'})
        response = self.client.get(reverse('manage_picklists'), {'status': 'archived'})
        self.assertEqual([p.pk for p in response.context['picklists']],
                         [self.picklist.pk])
        in_progress = self.client.get(reverse('manage_picklists'), {'status': 'in_progress'})
        self.assertEqual(len(in_progress.context['picklists']), 0)


class ProductCreatePrefillTests(ManageHealthTestCase):
    def test_code_prefilled_from_query_param(self):
        response = self.client.get(
            reverse('manage_product_create'), {'code': 'GHOST-42'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="GHOST-42"')

    def test_no_prefill_without_query_param(self):
        response = self.client.get(reverse('manage_product_create'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'GHOST-42')
