"""Verification of Shopify App Bridge session tokens (JWT, HS256).

Used for every request from the embedded admin console — session cookies do
not work inside the Shopify admin iframe."""

import jwt
from django.conf import settings


class InvalidSessionToken(Exception):
    pass


def verify_session_token(token):
    """Verify an App Bridge session token. Returns (payload, shop_domain).

    Raises InvalidSessionToken on any problem.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SHOPIFY_API_SECRET,
            algorithms=['HS256'],
            audience=settings.SHOPIFY_API_KEY,
            leeway=10,
            options={'require': ['exp', 'nbf', 'iss', 'dest', 'aud']},
        )
    except jwt.PyJWTError as exc:
        raise InvalidSessionToken(str(exc)) from exc

    dest = payload.get('dest', '')
    iss = payload.get('iss', '')
    shop_domain = dest.replace('https://', '').strip('/')
    if not shop_domain.endswith('.myshopify.com'):
        raise InvalidSessionToken(f"Unexpected dest: {dest}")
    if not iss.startswith(dest):
        raise InvalidSessionToken("iss does not match dest")
    return payload, shop_domain


def get_session_token_from_request(request):
    """Extract the bearer session token from an embedded-app request."""
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        return auth[len('Bearer '):]
    # First page load: App Bridge appends id_token to the URL.
    return request.GET.get('id_token', '')
