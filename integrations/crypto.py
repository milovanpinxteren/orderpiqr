"""Symmetric encryption for credentials at rest, keyed from SECRET_KEY.

Note: rotating SECRET_KEY invalidates stored tokens; platform connections
then need to re-authenticate (for Shopify: automatic via token exchange on
next embedded app load)."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet():
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt(value):
    if not value:
        return ''
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value):
    if not value:
        return ''
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return ''
