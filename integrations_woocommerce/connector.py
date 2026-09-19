"""WooCommerce connector: translates between WooCommerce payloads/APIs and
the integrations core's canonical representations."""

import logging
from datetime import timezone as datetime_timezone

from django.utils import timezone

from integrations.canonical import ExternalLine, ExternalOrder, ExternalVariant
from integrations.connector_base import BaseConnector
from integrations.models import ProductLink, WebhookInbox
from integrations.registry import register_connector
from integrations_woocommerce.client import WooCommerceAPIError, WooCommerceClient
from integrations_woocommerce.services import strip_order_payload

logger = logging.getLogger(__name__)

ORDER_TOPICS = {'order.created', 'order.updated', 'order.deleted', 'poll/order'}

# WooCommerce order status -> canonical status. completed maps to
# fulfilled_elsewhere: the order was (or is being) handled outside OrderPiqr —
# including by our own fulfill_order write-back, whose order.updated echo must
# be a no-op on the already-completed local order.
STATUS_MAP = {
    'pending': 'open',
    'on-hold': 'open',
    'processing': 'open',
    'cancelled': 'cancelled',
    'refunded': 'cancelled',
    'failed': 'cancelled',
    'trash': 'cancelled',
    'completed': 'fulfilled_elsewhere',
}


def _identifiers(sku, barcode):
    """Identifier dict without empty values, so the identifier chain never
    matches on ''."""
    identifiers = {}
    if barcode:
        identifiers['barcode'] = str(barcode)
    if sku:
        identifiers['sku'] = str(sku)
    return identifiers


def _variation_title(product_name, variation):
    options = ' / '.join(
        str(attr.get('option'))
        for attr in variation.get('attributes') or [] if attr.get('option')
    )
    return f"{product_name} – {options}" if options else product_name


@register_connector
class WooCommerceConnector(BaseConnector):
    platform = 'woocommerce'
    poll_interval = 900  # webhook delivery on shared WP hosting is flaky

    config_defaults = {
        # Status our fulfill_order write-back sets on the WooCommerce order.
        'fulfill_status': 'completed',
    }

    @property
    def store(self):
        return self.connection.woocommerce_store

    def client(self):
        return WooCommerceClient.for_store(self.store)

    # --------------------------------------------------------------- inbound

    def parse_order_event(self, inbox_row):
        topic = inbox_row.topic
        payload = inbox_row.payload or {}

        if topic not in ORDER_TOPICS:
            return None

        external_order_id = str(payload.get('id') or '')
        if not external_order_id:
            return None
        order_number = str(payload.get('number') or '')

        if topic == 'order.deleted':
            return ExternalOrder(
                external_order_id=external_order_id,
                order_number=order_number,
                status='cancelled',
            )

        status = STATUS_MAP.get(payload.get('status'), 'open')
        lines = []
        for item in payload.get('line_items') or []:
            product_id = str(item.get('product_id') or '')
            variation_id = str(item.get('variation_id') or '') or product_id
            lines.append(ExternalLine(
                external_variant_id=variation_id,
                external_product_id=product_id,
                quantity=int(item.get('quantity') or 0),
                title=item.get('name') or '',
                identifiers=_identifiers(item.get('sku'),
                                         item.get('global_unique_id')),
            ))

        return ExternalOrder(
            external_order_id=external_order_id,
            order_number=order_number,
            note=payload.get('customer_note') or '',
            status=status,
            lines=lines,
        )

    def handle_event(self, inbox_row):
        topic = inbox_row.topic
        payload = inbox_row.payload or {}

        if topic == 'product.updated':
            self._sync_product_payload(payload)
            return True

        if topic == 'product.deleted':
            product_id = str(payload.get('id') or '')
            if product_id:
                ProductLink.objects.filter(
                    connection=self.connection,
                    external_product_id=product_id,
                    locked=False,
                ).delete()
            return True

        return False

    def _sync_product_payload(self, payload):
        """Refresh ProductLinks from a product.updated event. The webhook
        payload of a variable product only lists variation ids, so those are
        fetched from the REST API."""
        product_id = payload.get('id')
        if not product_id:
            return
        if payload.get('type') == 'variable' or payload.get('variations'):
            client = self.client()
            for variation in client.iter_variations(product_id):
                self._sync_variant(self._variation_to_variant(payload, variation))
        else:
            self._sync_variant(self._product_to_variant(payload))

    def _sync_variant(self, variant):
        from integrations.services.intake import _auto_create_product, resolve_line
        if ProductLink.objects.filter(
            connection=self.connection,
            external_variant_id=variant.external_variant_id,
            locked=True,
        ).exists():
            return
        line = ExternalLine(
            external_variant_id=variant.external_variant_id,
            external_product_id=variant.external_product_id,
            quantity=0,
            title=variant.title,
            identifiers=variant.identifiers,
        )
        product = resolve_line(self.connection, line, self.config)
        if (product is None
                and self.config.get('unknown_product_policy') == 'auto_create'
                and any(str(v).strip() for v in line.identifiers.values())):
            _auto_create_product(self.connection, line, self.config)

    # --------------------------------------------------------------- catalog

    @staticmethod
    def _product_to_variant(product):
        return ExternalVariant(
            external_variant_id=str(product.get('id') or ''),
            external_product_id=str(product.get('id') or ''),
            title=product.get('name') or '',
            identifiers=_identifiers(product.get('sku'),
                                     product.get('global_unique_id')),
            inventory_quantity=(product.get('stock_quantity')
                                if product.get('manage_stock') else None),
        )

    @staticmethod
    def _variation_to_variant(product, variation):
        return ExternalVariant(
            external_variant_id=str(variation.get('id') or ''),
            external_product_id=str(product.get('id') or ''),
            title=_variation_title(product.get('name') or '', variation),
            identifiers=_identifiers(variation.get('sku'),
                                     variation.get('global_unique_id')),
            inventory_quantity=(variation.get('stock_quantity')
                                if variation.get('manage_stock') else None),
        )

    def fetch_variants(self):
        """Yield the full catalog: each variation of a variable product, and
        every other product as its own variant."""
        client = self.client()
        for product in client.iter_products():
            if product.get('type') == 'variable' or product.get('variations'):
                for variation in client.iter_variations(product['id']):
                    yield self._variation_to_variant(product, variation)
            else:
                yield self._product_to_variant(product)

    def count_variants(self):
        # Product count from the X-WP-Total header; variable products add
        # their variations on top, so this is a cheap lower bound.
        return self.client().count_products()

    # ------------------------------------------------------------------ poll

    def needs_immediate_poll(self):
        return self.store.last_poll_at is None

    def poll(self):
        """Reconciliation backstop: insert events for orders modified since
        the last poll that webhooks may have missed."""
        store = self.store
        since = store.last_poll_at or (timezone.now() - timezone.timedelta(days=7))
        modified_after = since.astimezone(datetime_timezone.utc).strftime(
            '%Y-%m-%dT%H:%M:%S')
        poll_started = timezone.now()

        for order in self.client().iter_orders(modified_after=modified_after):
            payload = strip_order_payload(order)
            event_id = f"poll:{payload.get('id')}:{payload.get('date_modified') or ''}"
            WebhookInbox.objects.get_or_create(
                connection=self.connection,
                external_event_id=event_id[:255],
                defaults={'topic': 'poll/order', 'payload': payload},
            )

        store.last_poll_at = poll_started
        store.save(update_fields=['last_poll_at'])

    # -------------------------------------------------------------- outbound

    def execute(self, outbox_row):
        if outbox_row.action == 'fulfill_order':
            self._fulfill_order(outbox_row)
        elif outbox_row.action == 'archive_order':
            pass  # WooCommerce has no archive concept
        elif outbox_row.action == 'push_inventory':
            self._push_inventory(outbox_row)
        else:
            raise NotImplementedError(f"Unsupported action {outbox_row.action}")

    def _fulfill_order(self, outbox_row):
        payload = outbox_row.payload or {}
        order_id = payload['external_order_id']
        fulfill_status = self.config.get('fulfill_status') or 'completed'
        client = self.client()

        try:
            order = client.get_order(order_id)
        except WooCommerceAPIError as exc:
            if exc.status_code == 404:
                logger.warning("Order %s no longer exists in WooCommerce", order_id)
                return
            raise
        if order.get('status') == fulfill_status:
            return  # already there (possibly set by us on a retry)

        client.update_order(order_id, {'status': fulfill_status})
        client.create_order_note(order_id, 'Picked & completed via OrderPiqr')

    def _push_inventory(self, outbox_row):
        payload = outbox_row.payload or {}
        variant_id = str(payload['external_variant_id'])
        product_id = str(payload.get('external_product_id') or variant_id)
        quantity = int(payload['quantity'])
        client = self.client()
        if variant_id != product_id:
            client.update_variation(product_id, variant_id,
                                    {'stock_quantity': quantity})
        else:
            client.update_product(product_id, {'stock_quantity': quantity})
