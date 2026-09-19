"""Store pairing, webhook registration and payload sanitisation.

Privacy rule: OrderPiqr stores no customer PII. WooCommerce order payloads
carry full billing/shipping blocks, so everything that goes into the
WebhookInbox is first reduced to the whitelisted fields below."""

import logging

from django.conf import settings

from integrations.services.catalog import enqueue_product_sync  # noqa: F401
from integrations_woocommerce.client import WooCommerceAPIError, WooCommerceClient

logger = logging.getLogger(__name__)

WEBHOOK_TOPICS = [
    'order.created',
    'order.updated',
    'order.deleted',
    'product.updated',
    'product.deleted',
]

ORDER_FIELDS = ('id', 'number', 'status', 'customer_note', 'date_modified')
LINE_ITEM_FIELDS = ('id', 'product_id', 'variation_id', 'sku',
                    'global_unique_id', 'name', 'quantity')
PRODUCT_FIELDS = ('id', 'name', 'sku', 'global_unique_id', 'type', 'status',
                  'variations', 'manage_stock', 'stock_quantity', 'date_modified')


def _pick(payload, fields):
    return {key: payload[key] for key in fields if key in payload}


def strip_order_payload(payload):
    """Reduce a WooCommerce order payload to the PII-free fields we need."""
    stripped = _pick(payload or {}, ORDER_FIELDS)
    stripped['line_items'] = [
        _pick(item or {}, LINE_ITEM_FIELDS)
        for item in (payload or {}).get('line_items') or []
    ]
    return stripped


def strip_product_payload(payload):
    """Products carry no PII, but store only what the connector consumes."""
    return _pick(payload or {}, PRODUCT_FIELDS)


def strip_webhook_payload(topic, payload):
    if topic.startswith('order.'):
        return strip_order_payload(payload)
    if topic.startswith('product.'):
        return strip_product_payload(payload)
    return {}


def webhook_delivery_url(connection):
    return f"{settings.APP_BASE_URL}/woocommerce/webhooks?cid={connection.pk}"


def register_webhooks(store):
    """Create our webhooks in the store; returns the list of webhook ids.
    Raises WooCommerceAPIError when any registration fails."""
    client = WooCommerceClient.for_store(store)
    delivery_url = webhook_delivery_url(store.connection)
    webhook_ids = []
    for topic in WEBHOOK_TOPICS:
        created = client.create_webhook(topic, delivery_url, store.webhook_secret)
        webhook_ids.append(created.get('id'))
    return webhook_ids


def remove_webhooks(store):
    """Best-effort cleanup of our webhooks in the store (disconnect or
    replacement); the store may be unreachable, which is fine."""
    if not store.webhook_ids:
        return
    client = WooCommerceClient.for_store(store)
    for webhook_id in store.webhook_ids:
        try:
            client.delete_webhook(webhook_id)
        except WooCommerceAPIError:
            logger.info("Could not delete webhook %s on %s (already gone?)",
                        webhook_id, store.store_url)
    store.webhook_ids = []
    store.save(update_fields=['webhook_ids'])
