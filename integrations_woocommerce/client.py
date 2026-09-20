"""Thin wrapper over the WooCommerce REST API v3.

Auth is HTTP Basic with the consumer key/secret, which is only safe over
HTTPS; plain HTTP is allowed exclusively in DEBUG for local test stores."""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT = 20  # seconds
PER_PAGE = 100


class WooCommerceAPIError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def normalize_store_url(store_url):
    """'https://shop.example.com/' -> 'https://shop.example.com'.
    Raises ValueError for schemes we refuse to send credentials over."""
    url = str(store_url or '').strip().rstrip('/')
    if url.startswith('http://'):
        if not settings.DEBUG:
            raise ValueError('Plain http store URLs are only allowed in DEBUG')
    elif not url.startswith('https://'):
        raise ValueError('Store URL must start with https://')
    return url


class WooCommerceClient:

    def __init__(self, store_url, consumer_key, consumer_secret):
        self.base_url = f"{normalize_store_url(store_url)}/wp-json/wc/v3"
        self.auth = (consumer_key, consumer_secret)

    @classmethod
    def for_store(cls, store):
        return cls(store.store_url, store.consumer_key, store.consumer_secret)

    def _request(self, method, path, params=None, json=None):
        try:
            response = requests.request(
                method, f"{self.base_url}/{path.lstrip('/')}",
                params=params, json=json, auth=self.auth, timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            raise WooCommerceAPIError(f"WooCommerce request failed: {exc}") from exc
        if not 200 <= response.status_code < 300:
            raise WooCommerceAPIError(
                f"WooCommerce API {method} /{path} -> {response.status_code}: "
                f"{response.text[:500]}",
                status_code=response.status_code,
            )
        return response

    def get(self, path, params=None):
        return self._request('GET', path, params=params)

    def _iterate(self, path, params=None):
        """Yield items from a paginated collection endpoint."""
        page = 1
        while True:
            response = self.get(path, params={
                **(params or {}), 'per_page': PER_PAGE, 'page': page,
            })
            items = response.json()
            yield from items
            total_pages = int(response.headers.get('X-WP-TotalPages') or 1)
            if page >= total_pages or not items:
                break
            page += 1

    def _count(self, path, params=None):
        """Collection size via the X-WP-Total header (no body paging)."""
        response = self.get(path, params={**(params or {}), 'per_page': 1})
        total = response.headers.get('X-WP-Total')
        return int(total) if total is not None else None

    # ---- store ---------------------------------------------------------

    def get_system_status(self):
        return self.get('system_status').json()

    # ---- webhooks ------------------------------------------------------

    def list_webhooks(self):
        return list(self._iterate('webhooks'))

    def create_webhook(self, topic, delivery_url, secret):
        return self._request('POST', 'webhooks', json={
            'name': f"OrderPiqr {topic}",
            'topic': topic,
            'delivery_url': delivery_url,
            'secret': secret,
            'status': 'active',
        }).json()

    def delete_webhook(self, webhook_id):
        return self._request('DELETE', f"webhooks/{webhook_id}",
                             params={'force': 'true'}).json()

    # ---- catalog -------------------------------------------------------

    def iter_products(self):
        return self._iterate('products')

    def count_products(self):
        return self._count('products')

    def iter_variations(self, product_id):
        return self._iterate(f"products/{product_id}/variations")

    def update_product(self, product_id, data):
        return self._request('PUT', f"products/{product_id}", json=data).json()

    def update_variation(self, product_id, variation_id, data):
        return self._request(
            'PUT', f"products/{product_id}/variations/{variation_id}",
            json=data).json()

    # ---- orders --------------------------------------------------------

    def iter_orders(self, modified_after=None, **params):
        if modified_after:
            params['modified_after'] = modified_after
            # modified_after is ignored unless dates_are_gmt matches the input
            params.setdefault('dates_are_gmt', 'true')
        return self._iterate('orders', params=params)

    def get_order(self, order_id):
        return self.get(f"orders/{order_id}").json()

    def update_order(self, order_id, data):
        return self._request('PUT', f"orders/{order_id}", json=data).json()

    def create_order_note(self, order_id, note, customer_note=False):
        return self._request('POST', f"orders/{order_id}/notes", json={
            'note': note, 'customer_note': customer_note,
        }).json()
