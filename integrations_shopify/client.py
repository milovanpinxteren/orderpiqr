"""Shopify GraphQL Admin API client (GraphQL-only; REST is legacy for new
apps) plus token exchange / refresh for expiring offline access tokens."""

import logging
import time

import httpx
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

TOKEN_EXCHANGE_GRANT = 'urn:ietf:params:oauth:grant-type:token-exchange'
ID_TOKEN_TYPE = 'urn:ietf:params:oauth:token-type:id_token'
OFFLINE_TOKEN_TYPE = 'urn:shopify:params:oauth:token-type:offline-access-token'


class ShopifyAPIError(Exception):
    def __init__(self, message, errors=None):
        super().__init__(message)
        self.errors = errors or []


class ShopifyAuthError(ShopifyAPIError):
    pass


def _store_token_response(shop, data):
    """Persist an access-token response (exchange or refresh) on ShopifyShop."""
    shop.access_token = data['access_token']
    shop.scopes = data.get('scope', shop.scopes)
    expires_in = data.get('expires_in')
    shop.token_expires_at = (
        timezone.now() + timezone.timedelta(seconds=int(expires_in))
        if expires_in else None
    )
    refresh = data.get('refresh_token')
    if refresh:
        shop.refresh_token = refresh
    shop.save(update_fields=[
        'encrypted_access_token', 'encrypted_refresh_token',
        'token_expires_at', 'scopes',
    ])


def exchange_session_token(shop, session_token):
    """Exchange an App Bridge session token for an offline access token
    (Shopify managed installation flow — no OAuth redirect needed)."""
    url = f"https://{shop.shop_domain}/admin/oauth/access_token"
    response = httpx.post(url, json={
        'client_id': settings.SHOPIFY_API_KEY,
        'client_secret': settings.SHOPIFY_API_SECRET,
        'grant_type': TOKEN_EXCHANGE_GRANT,
        'subject_token': session_token,
        'subject_token_type': ID_TOKEN_TYPE,
        'requested_token_type': OFFLINE_TOKEN_TYPE,
    }, timeout=15)
    if response.status_code != 200:
        raise ShopifyAuthError(
            f"Token exchange failed ({response.status_code}): {response.text[:500]}")
    _store_token_response(shop, response.json())
    return shop


def refresh_access_token(shop):
    """Refresh an expiring offline access token using its refresh token."""
    refresh_token = shop.refresh_token
    if not refresh_token:
        raise ShopifyAuthError("No refresh token stored; re-exchange required")
    url = f"https://{shop.shop_domain}/admin/oauth/access_token"
    response = httpx.post(url, json={
        'client_id': settings.SHOPIFY_API_KEY,
        'client_secret': settings.SHOPIFY_API_SECRET,
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
    }, timeout=15)
    if response.status_code != 200:
        raise ShopifyAuthError(
            f"Token refresh failed ({response.status_code}): {response.text[:500]}")
    _store_token_response(shop, response.json())
    return shop


class ShopifyClient:
    """Minimal GraphQL client with throttle retry and auto token refresh."""

    def __init__(self, shop):
        self.shop = shop
        self.endpoint = (
            f"https://{shop.shop_domain}/admin/api/"
            f"{settings.SHOPIFY_API_VERSION}/graphql.json"
        )

    def _ensure_token(self):
        if self.shop.token_expired:
            refresh_access_token(self.shop)
        token = self.shop.access_token
        if not token:
            raise ShopifyAuthError(f"No access token for {self.shop.shop_domain}")
        return token

    def graphql(self, query, variables=None, max_retries=3):
        """Run a GraphQL query/mutation, returning the `data` dict.
        Retries on throttling; refreshes the token once on 401."""
        attempt = 0
        refreshed = False
        while True:
            attempt += 1
            token = self._ensure_token()
            response = httpx.post(
                self.endpoint,
                json={'query': query, 'variables': variables or {}},
                headers={'X-Shopify-Access-Token': token},
                timeout=30,
            )

            if response.status_code == 401 and not refreshed:
                refreshed = True
                refresh_access_token(self.shop)
                continue
            if response.status_code == 429 and attempt <= max_retries:
                time.sleep(2 * attempt)
                continue
            if response.status_code != 200:
                raise ShopifyAPIError(
                    f"GraphQL HTTP {response.status_code}: {response.text[:500]}")

            body = response.json()
            errors = body.get('errors') or []
            if errors:
                throttled = any(
                    (e.get('extensions') or {}).get('code') == 'THROTTLED'
                    for e in errors
                )
                if throttled and attempt <= max_retries:
                    time.sleep(2 * attempt)
                    continue
                raise ShopifyAPIError(f"GraphQL errors: {errors}", errors=errors)
            return body['data']

    @staticmethod
    def check_user_errors(payload, key):
        """Raise if a mutation payload contains userErrors."""
        user_errors = (payload.get(key) or {}).get('userErrors') or []
        if user_errors:
            raise ShopifyAPIError(f"{key} userErrors: {user_errors}", errors=user_errors)
