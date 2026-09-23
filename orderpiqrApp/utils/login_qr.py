"""Issuing and redeeming the scannable picker login QR.

One module so the manage UI (which issues tokens) and the public login view
(which redeems them) cannot drift on what "a valid token" means. Every check
that keeps a QR low-risk lives in :func:`resolve_token`.
"""
from datetime import timedelta

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from orderpiqrApp.models import PickerLoginToken
from orderpiqrApp.models.login_tokens import DEFAULT_VALIDITY_DAYS
from orderpiqrApp.utils.devices import get_customer


def is_qr_loginable(user):
    """Only active, low-privilege picker accounts may be reachable by QR.

    A printed code is a bearer credential, so an account that can reach the
    manage interface must never be behind one — not even if a token was somehow
    issued before the account was promoted.
    """
    return (
        user.is_active
        and not user.is_staff
        and not user.is_superuser
        and user.groups.filter(name='orderpicker').exists()
    )


def active_token(user):
    """The live token for this picker, or None."""
    return (PickerLoginToken.objects
            .filter(user=user, revoked_at__isnull=True, expires_at__gt=timezone.now())
            .order_by('-created')
            .first())


def issue_token(user, customer, created_by=None, days=DEFAULT_VALIDITY_DAYS):
    """Issue a fresh token, revoking any earlier one for this picker.

    Returns ``(token, raw_token)``. The raw token is returned once and is not
    recoverable afterwards — only its hash is stored, so it exists solely in
    the QR image rendered from this call.
    """
    PickerLoginToken.objects.filter(
        user=user, revoked_at__isnull=True).update(revoked_at=timezone.now())

    raw_token, key_hash = PickerLoginToken.generate_token()
    token = PickerLoginToken.objects.create(
        user=user,
        customer=customer,
        key_hash=key_hash,
        created_by=created_by,
        expires_at=timezone.now() + timedelta(days=days),
    )
    return token, raw_token


def resolve_token(raw_token):
    """The usable token behind a scanned code, or None.

    Re-checks the tenant binding on every scan, not just at issue time: a
    picker whose profile has moved to another customer can no longer be reached
    by a QR printed for the old one.
    """
    if not raw_token:
        return None

    token = (PickerLoginToken.objects
             .select_related('user', 'customer')
             .filter(key_hash=PickerLoginToken.hash_token(raw_token))
             .first())
    if token is None or not token.is_usable:
        return None
    if not is_qr_loginable(token.user):
        return None
    if get_customer(token.user) != token.customer:
        return None
    return token


def login_url(raw_token):
    """Absolute URL to embed in the QR image.

    Built from APP_BASE_URL rather than the current request: the code is
    printed once and scanned from phones that never saw the issuing host.
    """
    return f"{settings.APP_BASE_URL}{reverse('qr_login', args=[raw_token])}"
