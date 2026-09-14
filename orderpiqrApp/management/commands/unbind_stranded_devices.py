"""Repair devices whose user belongs to a different customer than the device.

Before device fingerprints became unique per customer (migration 0026), the
name-entry view reassigned an existing device's ``user`` when a picker from
another company logged in on the same hardware — without moving the device's
``customer``. That left rows bound to a user who cannot legitimately use them,
and it silently broke picking for the customer that owned the device.

This command finds those rows and unbinds them (``user = None``), which is the
same state a freshly imported device has. It does not guess a replacement
owner: the device simply gets picked up by whoever next registers it.

    python manage.py unbind_stranded_devices            # report only
    python manage.py unbind_stranded_devices --apply    # actually unbind
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from orderpiqrApp.models import Device

# Description stamped by the old name-entry branch; cleared when we repair a row.
LEGACY_MARKER = 'Fingerprint used for multiple users'


class Command(BaseCommand):
    help = "Unbind devices whose assigned user belongs to a different customer."

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Persist the changes. Without it the command only reports.')

    def handle(self, *args, **options):
        apply_changes = options['apply']

        stranded = [
            device for device in (
                Device.objects
                .exclude(user__isnull=True)
                .select_related('customer', 'user__userprofile__customer')
            )
            if self._user_customer_id(device) not in (None, device.customer_id)
        ]

        if not stranded:
            self.stdout.write(self.style.SUCCESS('No stranded devices found.'))
            return

        self.stdout.write(f'Found {len(stranded)} stranded device(s):')
        for device in stranded:
            user_customer = getattr(getattr(device.user, 'userprofile', None), 'customer', None)
            self.stdout.write(
                f'  #{device.device_id} "{device.name}" '
                f'(fingerprint {(device.device_fingerprint or "-")[:12]}…) '
                f'belongs to "{device.customer}" but is bound to user '
                f'"{device.user}" of "{user_customer}"'
            )

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                'Dry run — nothing changed. Re-run with --apply to unbind these devices.'))
            return

        with transaction.atomic():
            for device in stranded:
                device.user = None
                if device.description == LEGACY_MARKER:
                    device.description = ''
                device.save(update_fields=['user', 'description'])

        self.stdout.write(self.style.SUCCESS(f'Unbound {len(stranded)} device(s).'))

    @staticmethod
    def _user_customer_id(device):
        """Customer of the device's assigned user, or None when it has no profile."""
        profile = getattr(device.user, 'userprofile', None)
        return getattr(profile, 'customer_id', None)
