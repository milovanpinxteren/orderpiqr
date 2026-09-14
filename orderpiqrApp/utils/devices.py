"""Single source of truth for resolving the Device behind a request.

A fingerprint identifies hardware, not a tenant: the same phone or shared tablet
may be registered for several customers. Every lookup therefore scopes on
``(device_fingerprint, customer)``. Scoping on ``user`` is wrong — a device is
shared between the pickers of one customer — and scoping on the fingerprint
alone crosses tenant boundaries.
"""
from django.db import IntegrityError
from django.utils import timezone

from orderpiqrApp.models import Device

SESSION_KEY = 'device_fingerprint'


def get_customer(user):
    """Customer of an authenticated user, or None when there is no profile."""
    if not getattr(user, 'is_authenticated', False):
        return None
    return getattr(getattr(user, 'userprofile', None), 'customer', None)


def get_fingerprint(request, payload=None):
    """Fingerprint for this request: the payload first, the session as fallback.

    ``payload`` is any mapping carrying the fingerprint — a parsed JSON body
    (``deviceFingerprint``) or ``request.POST`` (``device_fingerprint``).
    """
    if payload:
        for key in ('deviceFingerprint', 'device_fingerprint'):
            value = str(payload.get(key) or '').strip()
            if value:
                return value
    return str(request.session.get(SESSION_KEY) or '').strip()


def remember_fingerprint(request, fingerprint):
    """Pin the fingerprint to the session so later requests resolve without a body."""
    if fingerprint:
        request.session[SESSION_KEY] = fingerprint


def auto_device_name(user, fingerprint):
    """Fallback name for a device registered without the picker naming it."""
    return f"{getattr(user, 'username', '') or 'picker'} ({(fingerprint or 'unknown')[:8]})"


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
