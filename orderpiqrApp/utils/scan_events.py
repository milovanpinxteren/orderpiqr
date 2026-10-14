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


def log_scan_event(customer, device, event_type, scanned_code='', picklist_code='',
                   message='', reason='', severity=None, build_id='', client_ts=None):
    """Create a ScanEvent, best-effort.

    Returns the created ScanEvent, or None when the insert was skipped as a
    near-duplicate, or when anything at all went wrong.
    """
    try:
        scanned_code = str(scanned_code or '')[:255]
        picklist_code = str(picklist_code or '')[:255]
        message = str(message or '')[:2000]
        reason = str(reason or '')[:64]
        build_id = str(build_id or '')[:64]
        if severity not in dict(ScanEvent.SEVERITIES):
            severity = ScanEvent.DEFAULT_SEVERITY.get(event_type, 'warning')

        cutoff = timezone.now() - DEDUPE_WINDOW
        # `reason` is part of the key: the lifecycle and error types carry no
        # scanned_code, so without it a burst of genuinely different client
        # errors would collapse into a single row every 5 seconds.
        duplicate = ScanEvent.objects.filter(
            customer=customer,
            device=device,
            event_type=event_type,
            scanned_code=scanned_code,
            reason=reason,
            created_at__gte=cutoff,
        ).exists()
        if duplicate:
            return None

        return ScanEvent.objects.create(
            customer=customer,
            device=device,
            event_type=event_type,
            severity=severity,
            reason=reason,
            scanned_code=scanned_code,
            picklist_code=picklist_code,
            message=message,
            build_id=build_id,
            client_ts=client_ts,
        )
    except Exception:
        # Never let health logging take down the pick flow.
        return None


def log_auth_bounce(request, reason=None, message=''):
    """Record a picker being sent back to the name-entry or login screen.

    Best-effort by nature: at the moment of a bounce there is often no session
    and no resolvable device — that is what the bounce *is*. We attribute it
    from whatever remains (the authenticated user's customer, or a fingerprint
    registered to exactly one tenant) and skip it when nothing identifies the
    customer, rather than guessing.
    """
    try:
        # Imported here: utils.devices has no dependency on this module and
        # should not grow one.
        from orderpiqrApp.utils.devices import (
            get_customer, get_fingerprint, resolve_device_unauthenticated,
        )

        authenticated = getattr(request.user, 'is_authenticated', False)
        device = None
        customer = get_customer(request.user) if authenticated else None

        fingerprint = get_fingerprint(request)
        if fingerprint:
            resolved, ambiguous = resolve_device_unauthenticated(fingerprint)
            if resolved is not None and not ambiguous:
                device = resolved
                customer = customer or resolved.customer

        if customer is None:
            return None

        if reason is None:
            # An authenticated picker with no device row lost their local
            # identity (storage eviction); an unauthenticated one lost the
            # session itself. Very different fixes, so keep them apart.
            reason = 'device_unknown' if authenticated else 'session_lost'

        return log_scan_event(
            customer, device, 'auth_bounce', reason=reason,
            message=message or ('Device no longer recognised — picker sent to name entry'
                                if reason == 'device_unknown'
                                else 'No session — picker sent back to login'),
        )
    except Exception:
        return None
