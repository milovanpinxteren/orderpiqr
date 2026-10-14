"""Single source of truth for resolving the Device behind a request.

A fingerprint identifies hardware, not a tenant: the same phone or shared tablet
may be registered for several customers. Every lookup therefore scopes on
``(device_fingerprint, customer)``. Scoping on ``user`` is wrong — a device is
shared between the pickers of one customer — and scoping on the fingerprint
alone crosses tenant boundaries.
"""
from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from orderpiqrApp.models import Device

SESSION_KEY = 'device_fingerprint'

# A JS-readable cookie mirroring the client's localStorage device id. It exists
# because localStorage alone was not durable enough: iOS Safari evicts
# script-writable storage after 7 days for sites that are not installed to the
# home screen, and a phone that loses its id is refused its own picklist as
# "another device". A cookie set by the server (Set-Cookie, as opposed to
# document.cookie) is not subject to that cap, so it is the copy most likely to
# survive. Deliberately NOT httpOnly — fingerprint.js has to read it to
# recover. It identifies a device, never a person.
COOKIE_KEY = 'orderpiqr_device_id'
COOKIE_MAX_AGE = 60 * 60 * 24 * 730  # 2 years


def get_customer(user):
    """Customer of an authenticated user, or None when there is no profile."""
    if not getattr(user, 'is_authenticated', False):
        return None
    return getattr(getattr(user, 'userprofile', None), 'customer', None)


def get_fingerprint(request, payload=None):
    """Fingerprint for this request, most to least authoritative.

    ``payload`` is any mapping carrying the fingerprint — a parsed JSON body
    (``deviceFingerprint``) or ``request.POST`` (``device_fingerprint``).

    The cookie is the last resort and the reason this function has three
    sources: a plain GET carries no payload, and if the session has also been
    lost there was previously nothing left to identify the device by, so the
    picker was sent to name entry and registered all over again.
    """
    if payload:
        for key in ('deviceFingerprint', 'device_fingerprint'):
            value = str(payload.get(key) or '').strip()
            if value:
                return value
    from_session = str(request.session.get(SESSION_KEY) or '').strip()
    if from_session:
        return from_session
    return str(request.COOKIES.get(COOKIE_KEY) or '').strip()


def remember_fingerprint(request, fingerprint):
    """Pin the fingerprint to the session so later requests resolve without a body."""
    if fingerprint:
        request.session[SESSION_KEY] = fingerprint


def pin_device_cookie(response, fingerprint):
    """Re-issue the long-lived device cookie on a response.

    Called on page loads so the cookie's lifetime keeps rolling forward for a
    device in daily use, and so a device that only ever had localStorage gains
    the sturdier copy on its next visit.
    """
    if not fingerprint:
        return response
    try:
        response.set_cookie(
            COOKIE_KEY, fingerprint,
            max_age=COOKIE_MAX_AGE,
            httponly=False,   # fingerprint.js must be able to read it
            samesite='Lax',
            secure=not settings.DEBUG,
        )
    except Exception:
        # Never fail a page render over a diagnostic cookie.
        pass
    return response


def auto_device_name(user, fingerprint):
    """Fallback name for a device registered without the picker naming it."""
    return f"{getattr(user, 'username', '') or 'picker'} ({(fingerprint or 'unknown')[:8]})"


def _ua_fields(request):
    """Browser/OS/device parsed from the user agent, or {} when unavailable."""
    ua = getattr(request, 'user_agent', None)
    if ua is None:
        return {}
    return {
        'browser': (getattr(ua.browser, 'family', '') or '')[:64],
        'browser_version': (getattr(ua.browser, 'version_string', '') or '')[:32],
        'os': (getattr(ua.os, 'family', '') or '')[:64],
        'os_version': (getattr(ua.os, 'version_string', '') or '')[:32],
        'device_family': (getattr(ua.device, 'family', '') or '')[:64],
    }


def stamp_device_context(device, request, payload=None):
    """Record what this device is, best-effort and only when it changed.

    Called from the hot pick endpoints, so it must not add a write per pick:
    these values are near-constant, and an unchanged device is left alone.
    """
    if device is None:
        return device
    try:
        values = _ua_fields(request)
        if payload:
            mode = str(payload.get('displayMode') or '').strip()
            if mode in dict(Device.DISPLAY_MODES):
                values['display_mode'] = mode
            build = str(payload.get('buildId') or '').strip()[:64]
            if build:
                values['last_build_id'] = build

        changed = [f for f, v in values.items() if v and getattr(device, f) != v]
        if not changed:
            return device
        for field in changed:
            setattr(device, field, values[field])
        device.save(update_fields=changed)
    except Exception:
        # Diagnostics must never break a pick.
        pass
    return device


def resolve_device(request, payload=None, customer=None, touch=True):
    """Return the Device for this request, scoped to the user's customer.

    None when the user has no customer profile, no fingerprint is available, or
    the device is not registered for this customer. Resolving refreshes the
    session pin and (unless ``touch=False``) stamps ``last_login``.
    """
    customer = customer or get_customer(request.user)
    if customer is None:
        return None

    fingerprint = get_fingerprint(request, payload)
    if not fingerprint:
        return None

    device = Device.objects.filter(device_fingerprint=fingerprint, customer=customer).first()
    if device is None:
        return None

    remember_fingerprint(request, fingerprint)
    if touch:
        device.last_login = timezone.now()
        device.save(update_fields=['last_login'])
    return device


def register_device(request, name=None, payload=None, customer=None, fingerprint=None):
    """Create or refresh the device for (fingerprint, customer).

    Returns (device, created); (None, False) when the customer or fingerprint is
    unknown. Idempotent — re-registering an existing device rebinds it to the
    current user rather than stealing another customer's row.
    """
    customer = customer or get_customer(request.user)
    fingerprint = fingerprint or get_fingerprint(request, payload)
    if customer is None or not fingerprint:
        return None, False

    now = timezone.now()
    try:
        device, created = Device.objects.get_or_create(
            device_fingerprint=fingerprint,
            customer=customer,
            defaults={
                'user': request.user,
                'name': name or auto_device_name(request.user, fingerprint),
                'description': '',
                'last_login': now,
                'lists_picked': 0,
            },
        )
    except IntegrityError:
        # A concurrent registration of the same device won the race.
        device, created = Device.objects.get(device_fingerprint=fingerprint, customer=customer), False

    if not created:
        device.user = request.user
        device.last_login = now
        if name:
            device.name = name
        device.save(update_fields=['user', 'name', 'last_login'])

    remember_fingerprint(request, fingerprint)
    return device, created


def resolve_device_unauthenticated(fingerprint):
    """Resolve a device by fingerprint alone, for endpoints without a session.

    Returns (device, ambiguous). A fingerprint registered for more than one
    customer cannot be resolved without knowing the tenant, so it yields
    (None, True) rather than an arbitrary pick.
    """
    if not fingerprint:
        return None, False
    devices = list(Device.objects.filter(device_fingerprint=fingerprint)[:2])
    if len(devices) == 1:
        return devices[0], False
    return None, len(devices) > 1
