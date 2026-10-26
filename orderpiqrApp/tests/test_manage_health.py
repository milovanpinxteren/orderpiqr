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
    Customer, Device, PickList, Product, ProductBarcode, ProductPick, ScanEvent,
    UserProfile,
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

    def test_date_filter_drives_stats_and_breakdowns(self):
        device = self.make_device(name='Phone A')
        self.make_event('unknown_product', scanned_code='DAY-1', days_ago=3)
        self.make_event('manual_override', scanned_code='DAY-1',
                        device=device, days_ago=3)
        self.make_event('unknown_product', scanned_code='TODAY-1')
        self.make_event('manual_override', scanned_code='TODAY-1', device=device)

        day = (timezone.now() - timedelta(days=3)).date().isoformat()
        response = self.client.get(self.url, {'date_from': day, 'date_to': day})

        self.assertEqual(response.context['preset'], 'custom')
        self.assertEqual(response.context['tiles']['scanning'], 1)
        self.assertEqual(response.context['tiles']['overrides'], 1)
        self.assertEqual(
            [r['code'] for r in response.context['problem_codes']], ['DAY-1'])

    def test_date_filter_reaches_beyond_the_default_window(self):
        # Without dates the page shows the last 24 hours; a date window must
        # surface older pick days too.
        self.make_event('manual_override', scanned_code='OLD-1', days_ago=10)

        day = (timezone.now() - timedelta(days=10)).date().isoformat()
        response = self.client.get(self.url, {'date_from': day, 'date_to': day})
        self.assertEqual(response.context['tiles']['overrides'], 1)
        self.assertEqual(
            [r['code'] for r in response.context['problem_codes']], ['OLD-1'])

    def test_invalid_date_falls_back_to_the_default_window(self):
        self.make_event('unknown_product', scanned_code='NEW-1')
        response = self.client.get(self.url, {'date_from': 'not-a-date'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['preset'], '24h')
        self.assertEqual(
            [e.scanned_code for e in response.context['events']], ['NEW-1'])

    def test_excludes_other_customers_events(self):
        self.make_event('unknown_product', customer=self.other_customer,
                        scanned_code='FOREIGN-1')
        response = self.client.get(self.url)
        self.assertEqual(len(response.context['events']), 0)
        self.assertNotContains(response, 'FOREIGN-1')

    def test_problem_codes_name_the_cause_not_just_a_count(self):
        # The old card summed every event type into one number and printed
        # "Known product" where an action belonged, so it could not tell a
        # missing catalogue entry from a label that will not scan.
        Product.objects.create(customer=self.customer, code='KNOWN-1',
                               description='A known product')
        for _ in range(3):
            self.make_event('unknown_product', scanned_code='GHOST-1')
        self.make_event('wrong_product', scanned_code='KNOWN-1')
        # Outside the default window: must not appear at all.
        self.make_event('unknown_product', scanned_code='ANCIENT-1', days_ago=8)

        response = self.client.get(self.url)
        rows = response.context['problem_codes']
        by_code = {r['code']: r for r in rows}

        self.assertNotIn('ANCIENT-1', by_code)
        self.assertEqual(by_code['GHOST-1']['total'], 3)
        self.assertEqual(by_code['GHOST-1']['not_found'], 3)
        self.assertIsNone(by_code['GHOST-1']['product'])
        self.assertEqual(by_code['GHOST-1']['diagnosis'], 'unknown_code')
        self.assertEqual(by_code['KNOWN-1']['diagnosis'], 'unreadable')
        # Ordered by total, most frequent first.
        self.assertEqual(rows[0]['code'], 'GHOST-1')
        # The "Add as product" prefill only for genuinely unknown codes.
        self.assertContains(response, '?code=GHOST-1')
        self.assertNotContains(response, '?code=KNOWN-1')

    def test_overrides_on_a_known_product_read_as_a_barcode_problem(self):
        # Pickers confirming a line by hand are telling us the label does not
        # scan; the fix is an extra barcode, so the row must say so and link to
        # the product rather than offer "add as product".
        product = Product.objects.create(customer=self.customer, code='SMOOTHIE-1',
                                         description='Smoothie orange')
        for _ in range(5):
            self.make_event('manual_override', scanned_code='SMOOTHIE-1')
        self.make_event('unknown_product', scanned_code='SMOOTHIE-1')

        response = self.client.get(self.url)
        row = {r['code']: r for r in response.context['problem_codes']}['SMOOTHIE-1']

        self.assertEqual(row['diagnosis'], 'not_scanning')
        self.assertEqual(row['overrides'], 5)
        self.assertEqual(row['not_found'], 1)
        self.assertEqual(row['product'], product)
        self.assertContains(
            response, reverse('manage_product_edit', args=[product.product_id]))

    def test_known_product_reported_unknown_reads_as_scanned_outside_its_order(self):
        Product.objects.create(customer=self.customer, code='WRAP-1',
                               description='Wrap salmon')
        for _ in range(4):
            self.make_event('unknown_product', scanned_code='WRAP-1')
        self.make_event('manual_override', scanned_code='WRAP-1')

        response = self.client.get(self.url)
        row = {r['code']: r for r in response.context['problem_codes']}['WRAP-1']

        self.assertEqual(row['diagnosis'], 'not_in_order')

    def test_an_alias_code_is_not_offered_as_a_new_product(self):
        product = Product.objects.create(customer=self.customer, code='PRIMARY-1',
                                         description='Rotated EAN product')
        ProductBarcode.objects.create(customer=self.customer, product=product,
                                      code='OLD-EAN-1')
        self.make_event('unknown_product', scanned_code='OLD-EAN-1')

        response = self.client.get(self.url)
        row = {r['code']: r for r in response.context['problem_codes']}['OLD-EAN-1']

        self.assertEqual(row['product'], product)
        self.assertTrue(row['is_alias'])
        self.assertNotEqual(row['diagnosis'], 'unknown_code')
        self.assertNotContains(response, '?code=OLD-EAN-1')

    def test_override_breakdown_by_product_and_device(self):
        Product.objects.create(customer=self.customer, code='BAR-1',
                               description='Chocolate bar')
        device_a = self.make_device(name='Phone A')
        device_b = self.make_device(name='Phone B')
        for _ in range(3):
            self.make_event('manual_override', scanned_code='BAR-1', device=device_a)
        self.make_event('manual_override', scanned_code='NO-PRODUCT', device=device_b)
        # Outside the default window and other tenants must not count.
        self.make_event('manual_override', scanned_code='BAR-1', days_ago=8)
        self.make_event('manual_override', customer=self.other_customer,
                        scanned_code='BAR-1')
        # Not an override: must not leak into the override stats.
        self.make_event('unknown_product', scanned_code='BAR-1', device=device_a)

        response = self.client.get(self.url)

        self.assertEqual(response.context['tiles']['overrides'], 4)
        self.assertEqual(response.context['tiles']['scanning'], 1)

        # Overrides per code are one named cause in the codes table now, rather
        # than a separate card that could not say what to do about them.
        by_code = {r['code']: r for r in response.context['problem_codes']}
        self.assertEqual(by_code['BAR-1']['overrides'], 3)
        self.assertEqual(by_code['BAR-1']['diagnosis'], 'not_scanning')
        self.assertIsNone(by_code['NO-PRODUCT']['product'])
        self.assertEqual(by_code['NO-PRODUCT']['diagnosis'], 'unknown_code')

        # Per-device override counts live in the device breakdown, next to
        # errors, logouts and restarts, so one bad phone is visible at a glance.
        by_device = {row['name']: row for row in response.context['device_rows']}
        self.assertEqual(by_device['Phone A']['overrides'], 3)
        self.assertEqual(by_device['Phone B']['overrides'], 1)
        self.assertContains(response, 'Chocolate bar')

    def test_stale_picklists_listed_with_detail_link(self):
        device = self.make_device()
        stale = self.make_picklist(device, hours_ago=6, code='PL-STUCK')
        response = self.client.get(self.url)
        self.assertContains(response, 'PL-STUCK')
        self.assertContains(
            response, reverse('manage_picklist_detail', args=[stale.picklist_id]))

    def test_stale_picklists_show_trapped_work_and_restarts(self):
        # How much is stuck inside a dead lock, and whether the picker had to
        # keep restarting it, were both already stored and never shown.
        device = self.make_device()
        stale = self.make_picklist(device, hours_ago=6, code='PL-STUCK')
        product = Product.objects.create(customer=self.customer, code='P-1',
                                         description='Thing')
        ProductPick.objects.create(product=product, picklist=stale, quantity=1)
        ProductPick.objects.create(product=product, picklist=stale, quantity=1,
                                   outcome='picked')
        PickList.objects.filter(pk=stale.pk).update(
            notes='Restarted by device Scanner 1 at x\nRestarted by device Scanner 1 at y')

        response = self.client.get(self.url)

        listed = response.context['stale_picklists'][0]
        self.assertEqual(listed.pending_lines, 1)
        self.assertEqual(listed.restart_count, 2)
        self.assertEqual(response.context['stale_pending_lines'], 1)


class HealthTileTests(ManageHealthTestCase):
    """Problems grouped by kind, every count obeying the one date window."""

    def setUp(self):
        super().setUp()
        self.url = reverse('manage_health')

    def test_the_silences_are_counted(self):
        # None of these existed as events before: crashes, logouts, reloads and
        # lock handovers produced nothing at all.
        device = self.make_device()
        self.make_event('auth_bounce', device=device)
        self.make_event('client_error', device=device, reason='uncaught_error')
        self.make_event('camera_error', device=device, reason='permission_denied')
        self.make_event('app_lifecycle', device=device, reason='self_update_reload')
        self.make_event('lock_takeover', device=device)

        tiles = self.client.get(self.url).context['tiles']

        self.assertEqual(tiles['blocking'], 1)                     # auth_bounce
        self.assertEqual(tiles['app'], 4)   # client + camera + lifecycle + takeover

    def test_every_count_obeys_the_window(self):
        # The old page had a one-hour strip above a filtered body, so one screen
        # described two different periods.
        self.make_event('auth_bounce', days_ago=30)
        day = (timezone.now() - timedelta(days=30)).date().isoformat()

        inside = self.client.get(self.url, {'date_from': day, 'date_to': day})
        self.assertEqual(inside.context['tiles']['blocking'], 1)

        outside = self.client.get(self.url)
        self.assertEqual(outside.context['tiles']['blocking'], 0)

    def test_tiles_group_by_kind_of_problem(self):
        self.make_event('picklist_rejected')
        self.make_event('auth_bounce')
        self.make_event('unknown_product', scanned_code='X')
        self.make_event('manual_override', scanned_code='Y')
        self.make_event('client_error', reason='uncaught_error')

        tiles = self.client.get(self.url).context['tiles']

        self.assertEqual(tiles['blocking'], 2)   # rejected + bounce
        self.assertEqual(tiles['scanning'], 1)
        self.assertEqual(tiles['overrides'], 1)
        self.assertEqual(tiles['app'], 1)

    def test_tile_link_filters_the_event_list(self):
        self.make_event('picklist_rejected', scanned_code='BLOCKED-1')
        self.make_event('unknown_product', scanned_code='SCANNED-1')

        response = self.client.get(self.url, {'tile': 'blocking'})
        codes = [e.scanned_code for e in response.context['events']]
        self.assertEqual(codes, ['BLOCKED-1'])

    def test_severity_filter(self):
        self.make_event('manual_override', scanned_code='INFO-1', severity='info')
        self.make_event('sync_error', scanned_code='ERR-1', severity='error')

        response = self.client.get(self.url, {'severity': 'error'})
        self.assertEqual([e.scanned_code for e in response.context['events']], ['ERR-1'])

    def test_device_filter(self):
        device = self.make_device(name='Phone A')
        other = self.make_device(name='Phone B')
        self.make_event('sync_error', scanned_code='A-1', device=device)
        self.make_event('sync_error', scanned_code='B-1', device=other)

        response = self.client.get(self.url, {'device': device.device_id})
        self.assertEqual([e.scanned_code for e in response.context['events']], ['A-1'])


class HealthOutcomeTests(ManageHealthTestCase):
    """Picks the picker made that the server never recorded — the metric that
    measures real harm, and the one the page never showed."""

    def setUp(self):
        super().setUp()
        self.url = reverse('manage_health')
        self.device = self.make_device()
        self.product = Product.objects.create(customer=self.customer, code='P-1',
                                              description='Thing')

    def _list(self, code, successful, picked, pending, short=0):
        picklist = PickList.objects.create(
            customer=self.customer, device=self.device, picklist_code=code,
            pick_started=True, successful=successful)
        for _ in range(picked):
            ProductPick.objects.create(product=self.product, picklist=picklist,
                                       quantity=1, outcome='picked')
        for _ in range(short):
            ProductPick.objects.create(product=self.product, picklist=picklist,
                                       quantity=1, outcome='short', short_reason='other')
        for _ in range(pending):
            ProductPick.objects.create(product=self.product, picklist=picklist,
                                       quantity=1)
        return picklist

    def test_lines_left_pending_on_a_completed_list_count_as_lost(self):
        self._list('PL-OK', successful=True, picked=8, pending=2)

        outcomes = self.client.get(self.url).context['outcomes']

        self.assertEqual(outcomes['lists_completed'], 1)
        self.assertEqual(outcomes['lines_total'], 10)
        self.assertEqual(outcomes['lines_lost'], 2)
        self.assertEqual(outcomes['lines_lost_pct'], 20.0)

    def test_resolved_lost_lines_count_without_a_completed_parent(self):
        # Lost is a recorded outcome in its own right (the completion hooks
        # write it); it must count even when the parent list looks open.
        picklist = self._list('PL-LOST', successful=None, picked=1, pending=1)
        ProductPick.objects.filter(picklist=picklist, outcome='pending').update(
            outcome='lost')

        outcomes = self.client.get(self.url).context['outcomes']

        self.assertEqual(outcomes['lines_lost'], 1)

    def test_short_lines_are_counted_separately(self):
        # Declared shorts are recorded work, not lost picks.
        self._list('PL-SHORT', successful=True, picked=3, pending=0, short=2)

        outcomes = self.client.get(self.url).context['outcomes']

        self.assertEqual(outcomes['lines_short'], 2)
        self.assertEqual(outcomes['lines_lost'], 0)

    def test_pending_lines_on_an_open_list_are_not_lost(self):
        # Still being picked is not the same as silently dropped.
        self._list('PL-OPEN', successful=None, picked=1, pending=4)

        outcomes = self.client.get(self.url).context['outcomes']

        self.assertEqual(outcomes['lists_open'], 1)
        self.assertEqual(outcomes['lines_lost'], 0)

    def test_restarted_lists_are_counted(self):
        picklist = self._list('PL-R', successful=True, picked=1, pending=0)
        PickList.objects.filter(pk=picklist.pk).update(
            notes='Restarted by device Scanner 1 at 2026-10-13 21:04')

        self.assertEqual(self.client.get(self.url).context['outcomes']['lists_restarted'], 1)


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
