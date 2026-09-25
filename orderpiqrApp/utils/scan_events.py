"""Best-effort recording of pick-flow health events (ScanEvent rows).

Health logging must NEVER break or slow down picking: every failure in here is
swallowed, and near-duplicate events (double-fired scanners, retrying clients)
are deduped server-side.
"""
from datetime import timedelta

from django.utils import timezone

from orderpiqrApp.models import ScanEvent

# Identical events inside this window are considered duplicates and skipped.
DEDUPE_WINDOW = timedelta(seconds=5)


def log_scan_event(customer, device, event_type, scanned_code='', picklist_code='', message=''):
    """Create a ScanEvent, best-effort.

    Returns the created ScanEvent, or None when the insert was skipped (an
    identical event — same customer, device, event_type and scanned_code —
    exists within the last 5 seconds) or when anything at all went wrong.
    """
    try:
        scanned_code = str(scanned_code or '')[:255]
        picklist_code = str(picklist_code or '')[:255]
        message = str(message or '')[:2000]

        cutoff = timezone.now() - DEDUPE_WINDOW
        duplicate = ScanEvent.objects.filter(
            customer=customer,
            device=device,
            event_type=event_type,
            scanned_code=scanned_code,
            created_at__gte=cutoff,
        ).exists()
        if duplicate:
            return None

        return ScanEvent.objects.create(
            customer=customer,
            device=device,
            event_type=event_type,
            scanned_code=scanned_code,
            picklist_code=picklist_code,
            message=message,
        )
    except Exception:
        # Never let health logging take down the pick flow.
        return None
