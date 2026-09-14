"""The unbind_stranded_devices repair command."""
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from orderpiqrApp.management.commands.unbind_stranded_devices import LEGACY_MARKER
from orderpiqrApp.models import Customer, Device, UserProfile


class UnbindStrandedDevicesTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Owning Company')
        self.other_customer = Customer.objects.create(name='Other Company')

        self.owner = User.objects.create_user(username='owner', password='x')
        UserProfile.objects.create(user=self.owner, customer=self.customer)

        self.outsider = User.objects.create_user(username='outsider', password='x')
        UserProfile.objects.create(user=self.outsider, customer=self.other_customer)

    def _make_device(self, user, description='', fingerprint='fp-1'):
        return Device.objects.create(
            user=user,
            device_fingerprint=fingerprint,
            name='Tablet',
            description=description,
            customer=self.customer,
            last_login=timezone.now(),
            lists_picked=0,
        )

    def _run(self, *args):
        out = StringIO()
        call_command('unbind_stranded_devices', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_reports_without_changing(self):
        device = self._make_device(self.outsider, description=LEGACY_MARKER)

        output = self._run()

        self.assertIn('Found 1 stranded device(s)', output)
        self.assertIn('Dry run', output)
        device.refresh_from_db()
        self.assertEqual(device.user_id, self.outsider.pk)

    def test_apply_unbinds_and_clears_the_legacy_marker(self):
        device = self._make_device(self.outsider, description=LEGACY_MARKER)

        output = self._run('--apply')

        self.assertIn('Unbound 1 device(s)', output)
        device.refresh_from_db()
        self.assertIsNone(device.user_id)
        self.assertEqual(device.description, '')

    def test_leaves_correctly_bound_devices_alone(self):
        device = self._make_device(self.owner, description='My tablet')

        output = self._run('--apply')

        self.assertIn('No stranded devices found', output)
        device.refresh_from_db()
        self.assertEqual(device.user_id, self.owner.pk)
        self.assertEqual(device.description, 'My tablet')

    def test_ignores_unassigned_devices_and_users_without_a_profile(self):
        unassigned = self._make_device(None, fingerprint='fp-2')
        profileless = User.objects.create_user(username='noprofile', password='x')
        no_profile_device = self._make_device(profileless, fingerprint='fp-3')

        output = self._run('--apply')

        self.assertIn('No stranded devices found', output)
        unassigned.refresh_from_db()
        no_profile_device.refresh_from_db()
        self.assertIsNone(unassigned.user_id)
        self.assertEqual(no_profile_device.user_id, profileless.pk)

    def test_keeps_a_non_legacy_description(self):
        device = self._make_device(self.outsider, description='Warehouse scanner 3')

        self._run('--apply')

        device.refresh_from_db()
        self.assertIsNone(device.user_id)
        self.assertEqual(device.description, 'Warehouse scanner 3')
