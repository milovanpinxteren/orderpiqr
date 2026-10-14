"""The Devices page.

It used to show a name, an online dot and a lifetime list count — nothing that
could answer "is it an old phone, is it running in a browser tab, is it the one
producing all the errors". These tests cover what it shows now.
"""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from orderpiqrApp.models import Device, PickList
from orderpiqrApp.tests.test_manage_health import ManageHealthTestCase


class DevicesListTests(ManageHealthTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('manage_devices')

    def _device(self, name, **kwargs):
        defaults = {
            'customer': self.customer,
            'name': name,
            'description': '',
            'last_login': timezone.now(),
            'lists_picked': 0,
        }
        defaults.update(kwargs)
        return Device.objects.create(**defaults)

    def test_shows_phone_and_app_details(self):
        self._device('Phone A', os='iOS', os_version='15.7', browser='Mobile Safari',
                     browser_version='15.6', display_mode='browser')

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'iOS')
        self.assertContains(response, 'Mobile Safari')
        self.assertContains(response, 'Browser tab')

    def test_counts_errors_logouts_and_overrides_from_the_last_day(self):
        device = self._device('Phone A')
        self.make_event('client_error', device=device, reason='uncaught_error')
        self.make_event('sync_error', device=device, scanned_code='X')
        self.make_event('auth_bounce', device=device)
        self.make_event('manual_override', device=device, scanned_code='Y')
        self.make_event('app_lifecycle', device=device, reason='self_update_reload')
        # Older than the window: must not count.
        self.make_event('client_error', device=device, reason='old', days_ago=3)

        listed = self.client.get(self.url).context['devices'][0]

        self.assertEqual(listed.errors_today, 2)      # client_error + sync_error
        self.assertEqual(listed.bounces_today, 1)
        self.assertEqual(listed.overrides_today, 1)
        self.assertEqual(listed.restarts_today, 1)

    def test_problem_devices_sort_first(self):
        quiet = self._device('Quiet phone')
        noisy = self._device('Noisy phone')
        self.make_event('auth_bounce', device=noisy)
        self.make_event('client_error', device=noisy, reason='uncaught_error')

        devices = self.client.get(self.url).context['devices']

        self.assertEqual(devices[0].name, noisy.name)
        self.assertEqual(devices[1].name, quiet.name)

    def test_duplicate_names_are_flagged(self):
        # Several rows for one human is the fingerprint-churn signature: the
        # picker's storage was evicted and they came back as a new device, which
        # is what then gets them refused their own picklist.
        self._device('Nonna', device_fingerprint='fp-1')
        self._device('Nonna', device_fingerprint='fp-2')
        self._device('Beata', device_fingerprint='fp-3')

        response = self.client.get(self.url)

        self.assertEqual(response.context['duplicate_count'], 2)
        flagged = {d.name: d.possible_duplicate for d in response.context['devices']}
        self.assertTrue(flagged['Nonna'])
        self.assertFalse(flagged['Beata'])

    def test_auto_created_devices_are_flagged_as_never_named(self):
        self._device('Auto-created device (2026-10-13 20:31)')
        listed = self.client.get(self.url).context['devices'][0]
        self.assertTrue(listed.unnamed)

    def test_browser_tab_and_unknown_mode_are_summarised(self):
        self._device('A', device_fingerprint='fp-a', display_mode='browser')
        self._device('B', device_fingerprint='fp-b', display_mode='standalone')
        self._device('C', device_fingerprint='fp-c')

        response = self.client.get(self.url)

        self.assertEqual(response.context['browser_tab_count'], 1)
        self.assertEqual(response.context['unknown_mode_count'], 1)

    def test_old_build_flagged_only_for_recently_seen_devices(self):
        self._device('Recent', device_fingerprint='fp-r',
                     last_build_id='ancient-build')
        self._device('Long gone', device_fingerprint='fp-g',
                     last_build_id='ancient-build',
                     last_login=timezone.now() - timedelta(days=30))

        devices = {d.name: d for d in self.client.get(self.url).context['devices']}

        self.assertTrue(devices['Recent'].build_outdated)
        # A phone last seen a month ago is simply gone, not "outdated".
        self.assertFalse(devices['Long gone'].build_outdated)

    def test_lists_counted_over_the_last_week(self):
        device = self._device('Phone A')
        PickList.objects.create(customer=self.customer, device=device,
                                picklist_code='PL-1', pick_started=True)
        old = PickList.objects.create(customer=self.customer, device=device,
                                      picklist_code='PL-OLD', pick_started=True)
        PickList.objects.filter(pk=old.pk).update(
            pick_time=timezone.now() - timedelta(days=30))

        listed = self.client.get(self.url).context['devices'][0]
        self.assertEqual(listed.lists_week, 1)

    def test_other_customers_devices_are_not_listed(self):
        self._device('Ours', device_fingerprint='fp-ours')
        Device.objects.create(customer=self.other_customer, name='Theirs',
                              description='', last_login=timezone.now(),
                              lists_picked=0, device_fingerprint='fp-theirs')

        response = self.client.get(self.url)

        names = [d.name for d in response.context['devices']]
        self.assertEqual(names, ['Ours'])
        self.assertNotContains(response, 'Theirs')
