"""Shopify connector: translates between Shopify payloads/APIs and the
integrations core's canonical representations."""

import logging

from django.utils import timezone

from integrations.canonical import ExternalLine, ExternalOrder, ExternalVariant
from integrations.connector_base import BaseConnector
from integrations.models import ExternalOrderLink, ProductLink, WebhookInbox
from integrations.registry import register_connector
from integrations_shopify.client import ShopifyClient

logger = logging.getLogger(__name__)

ORDER_TOPICS = {'orders/create', 'orders/paid', 'orders/updated', 'orders/cancelled',
                'poll/order'}


def order_gid(numeric_id):
    return f"gid://shopify/Order/{numeric_id}"


def gid_tail(gid):
    """'gid://shopify/ProductVariant/123' -> '123'"""
    return str(gid).rsplit('/', 1)[-1]


VARIANTS_QUERY = """
query Variants($first: Int!, $after: String, $withMetafield: Boolean!,
               $mfNamespace: String!, $mfKey: String!,
               $withLocationMetafield: Boolean!,
               $locNamespace: String!, $locKey: String!) {
  productVariants(first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      sku
      barcode
      title
      product { id title }
      metafield(namespace: $mfNamespace, key: $mfKey) @include(if: $withMetafield) { value }
      locationMetafield: metafield(namespace: $locNamespace, key: $locKey)
        @include(if: $withLocationMetafield) { value }
    }
  }
}
"""

VARIANT_NODES_QUERY = """
query VariantNodes($ids: [ID!]!, $withMetafield: Boolean!,
                   $mfNamespace: String!, $mfKey: String!,
                   $withLocationMetafield: Boolean!,
                   $locNamespace: String!, $locKey: String!) {
  nodes(ids: $ids) {
    ... on ProductVariant {
      id
      sku
      barcode
      product { id title }
      metafield(namespace: $mfNamespace, key: $mfKey) @include(if: $withMetafield) { value }
      locationMetafield: metafield(namespace: $locNamespace, key: $locKey)
        @include(if: $withLocationMetafield) { value }
    }
  }
}
"""

ORDERS_POLL_QUERY = """
query PollOrders($first: Int!, $after: String, $query: String!) {
  orders(first: $first, after: $after, query: $query, sortKey: UPDATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      name
      note
      cancelledAt
      displayFulfillmentStatus
      displayFinancialStatus
      lineItems(first: 100) {
        nodes {
          quantity
          sku
          title
          variant { id product { id } }
        }
      }
    }
  }
}
"""

ORDERS_BROWSE_QUERY = """
query BrowseOrders($first: Int!, $after: String, $query: String) {
  orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      name
      createdAt
      cancelledAt
      displayFulfillmentStatus
      displayFinancialStatus
      currentSubtotalLineItemsQuantity
    }
  }
}
"""

ORDER_NODES_QUERY = """
query OrderNodes($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on Order {
      id
      name
      note
      cancelledAt
      displayFulfillmentStatus
      displayFinancialStatus
      lineItems(first: 100) {
        nodes {
          quantity
          sku
          title
          variant { id product { id } }
        }
      }
    }
  }
}
"""

FULFILLMENT_ORDERS_QUERY = """
query FulfillmentOrders($id: ID!) {
  order(id: $id) {
    id
    displayFulfillmentStatus
    fulfillmentOrders(first: 20) {
      nodes {
        id
        status
        supportedActions { action }
      }
    }
  }
}
"""

FULFILLMENT_CREATE_MUTATION = """
mutation FulfillmentCreate($fulfillment: FulfillmentInput!) {
  fulfillmentCreate(fulfillment: $fulfillment) {
    fulfillment { id status }
    userErrors { field message }
  }
}
"""

ORDER_CLOSE_MUTATION = """
mutation OrderClose($input: OrderCloseInput!) {
  orderClose(input: $input) {
    order { id closed }
    userErrors { field message }
  }
}
"""


@register_connector
class ShopifyConnector(BaseConnector):
    platform = 'shopify'
    poll_interval = 3600  # webhooks are primary; poll is the backstop

    config_defaults = {
        # Metafield identifier support (identifier_chain entry 'metafield').
        'metafield_namespace': '',
        'metafield_key': '',
        # Optional metafield that carries the warehouse location; when set,
        # Shopify is the source of truth for Product.location on synced items.
        'location_metafield_namespace': '',
        'location_metafield_key': '',
        # Only import orders that are paid (any|paid).
        'financial_status': 'paid',
    }

    # ------------------------------------------------------------------ shop

    @property
    def shop(self):
        return self.connection.shopify_shop

    def client(self):
        return ShopifyClient(self.shop)

    def _metafield_vars(self):
        ns = self.config.get('metafield_namespace') or ''
        key = self.config.get('metafield_key') or ''
        loc_ns = self.config.get('location_metafield_namespace') or ''
        loc_key = self.config.get('location_metafield_key') or ''
        return {
            'withMetafield': bool(ns and key),
            'mfNamespace': ns or '_',
            'mfKey': key or '_',
            'withLocationMetafield': bool(loc_ns and loc_key),
            'locNamespace': loc_ns or '_',
            'locKey': loc_key or '_',
        }

    # --------------------------------------------------------------- inbound

    def parse_order_event(self, inbox_row):
        topic = inbox_row.topic
        payload = inbox_row.payload or {}

        if topic not in ORDER_TOPICS:
            return None

        if topic == 'poll/order':
            # Canonical payload written by poll().
            return ExternalOrder(
                external_order_id=str(payload['external_order_id']),
                order_number=payload.get('order_number', ''),
                note=payload.get('note') or '',
                status=payload.get('status', 'open'),
                lines=[ExternalLine(**line) for line in payload.get('lines', [])],
            )

        # Webhook payloads (REST-shaped JSON from Shopify webhooks).
        external_order_id = str(payload.get('id', ''))
        if not external_order_id:
            return None

        if topic == 'orders/cancelled' or payload.get('cancelled_at'):
            return ExternalOrder(
                external_order_id=external_order_id,
                order_number=payload.get('name', ''),
                status='cancelled',
            )

        # orders/create, orders/paid and orders/updated all funnel into the
        # same import path: an order that only becomes eligible after creation
        # (e.g. created unpaid, marked as paid later) is imported the moment
        # an event shows it passing the filter. Import is idempotent on
        # external_order_id, so repeated events are harmless.
        if not self._passes_import_filter(payload):
            return None

        lines = []
        for item in payload.get('line_items', []):
            variant_id = str(item.get('variant_id') or '')
            lines.append(ExternalLine(
                external_variant_id=variant_id,
                external_product_id=str(item.get('product_id') or ''),
                quantity=int(item.get('quantity') or 0),
                title=item.get('title') or '',
                identifiers={'sku': item.get('sku') or '', 'variant_id': variant_id},
            ))

        self._enrich_line_identifiers(lines)

        return ExternalOrder(
            external_order_id=external_order_id,
            order_number=payload.get('name', ''),
            note=payload.get('note') or '',
            status='open',
            lines=lines,
        )

    def _passes_import_filter(self, payload):
        if self.config.get('financial_status', 'paid') == 'paid':
            if payload.get('financial_status') not in ('paid', 'partially_refunded'):
                return False
        if payload.get('fulfillment_status') == 'fulfilled':
            return False
        return True

    def _enrich_line_identifiers(self, lines):
        """Webhook order payloads carry SKU but not barcode/metafield. For
        lines without an existing ProductLink, fetch those identifiers via
        GraphQL when the identifier chain needs them."""
        chain = self.config.get('identifier_chain', [])
        needs_lookup = any(t in chain for t in ('barcode', 'metafield'))
        if not needs_lookup:
            return

        variant_ids = [l.external_variant_id for l in lines if l.external_variant_id]
        if not variant_ids:
            return
        linked = set(
            ProductLink.objects
            .filter(connection=self.connection,
                    external_variant_id__in=variant_ids,
                    product__isnull=False)
            .values_list('external_variant_id', flat=True)
        )
        missing = [v for v in variant_ids if v not in linked]
        if not missing:
            return

        gids = [f"gid://shopify/ProductVariant/{v}" for v in missing]
        try:
            data = self.client().graphql(
                VARIANT_NODES_QUERY,
                {'ids': gids, **self._metafield_vars()},
            )
        except Exception:
            logger.exception("Variant identifier lookup failed for connection %s",
                             self.connection.pk)
            return

        by_id = {}
        for node in data.get('nodes') or []:
            if node and node.get('id'):
                by_id[gid_tail(node['id'])] = node

        for line in lines:
            node = by_id.get(line.external_variant_id)
            if not node:
                continue
            line.identifiers.setdefault('sku', node.get('sku') or '')
            line.identifiers['barcode'] = node.get('barcode') or ''
            metafield = node.get('metafield') or {}
            line.identifiers['metafield'] = metafield.get('value') or ''

    def handle_event(self, inbox_row):
        topic = inbox_row.topic
        payload = inbox_row.payload or {}

        if topic in ('products/create', 'products/update'):
            self._sync_product_payload(payload)
            return True

        if topic == 'products/delete':
            ProductLink.objects.filter(
                connection=self.connection,
                external_product_id=str(payload.get('id') or ''),
                locked=False,
            ).delete()
            return True

        if topic == 'app/uninstalled':
            shop = self.shop
            shop.uninstalled_at = timezone.now()
            shop.access_token = ''
            shop.refresh_token = ''
            shop.save(update_fields=[
                'uninstalled_at', 'encrypted_access_token', 'encrypted_refresh_token'])
            self.connection.status = 'disconnected'
            self.connection.save(update_fields=['status'])
            return True

        if topic in ('customers/data_request', 'customers/redact'):
            # We deliberately store no customer PII; nothing to export/delete.
            logger.info("GDPR topic %s acknowledged for %s (no PII stored)",
                        topic, self.shop.shop_domain)
            return True

        if topic == 'shop/redact':
            # 48h+ after uninstall: delete everything for this shop.
            logger.info("shop/redact: deleting connection %s data", self.connection.pk)
            self.connection.delete()  # cascades shop, links, inbox, outbox
            return True

        if topic == 'fulfillments/create':
            # Order fulfilled outside OrderPiqr -> cancel local pick if open.
            from integrations.services.intake import cancel_external_order
            ext_id = str(payload.get('order_id') or '')
            if ext_id:
                cancel_external_order(self.connection, ext_id,
                                      reason='fulfilled in Shopify')
            return True

        return False

    def _sync_product_payload(self, payload):
        """Refresh ProductLinks from a products/create|update webhook payload.
        Under the auto_create policy, brand-new variants become OrderPiqr
        products immediately (same behaviour as the full catalog sync)."""
        from integrations.services.intake import _auto_create_product, resolve_line
        auto_create = self.config.get('unknown_product_policy') == 'auto_create'
        product_id = str(payload.get('id') or '')

        # Webhook payloads don't include metafields; fetch them when the
        # identifier chain or location source needs one.
        mf_vars = self._metafield_vars()
        needs_lookup = (
            (mf_vars['withMetafield'] and 'metafield' in self.config.get('identifier_chain', []))
            or mf_vars['withLocationMetafield']
        )
        enriched = {}
        if needs_lookup:
            variant_ids = [str(v.get('id')) for v in payload.get('variants', []) if v.get('id')]
            if variant_ids:
                try:
                    data = self.client().graphql(VARIANT_NODES_QUERY, {
                        'ids': [f"gid://shopify/ProductVariant/{v}" for v in variant_ids],
                        **mf_vars,
                    })
                    for node in data.get('nodes') or []:
                        if node and node.get('id'):
                            enriched[gid_tail(node['id'])] = node
                except Exception:
                    logger.exception("Metafield lookup failed for product %s", product_id)

        for variant in payload.get('variants', []):
            variant_id = str(variant.get('id') or '')
            if not variant_id:
                continue
            if ProductLink.objects.filter(
                connection=self.connection, external_variant_id=variant_id, locked=True,
            ).exists():
                continue
            node = enriched.get(variant_id) or {}
            line = ExternalLine(
                external_variant_id=variant_id,
                external_product_id=product_id,
                quantity=0,
                title=' - '.join(filter(None, [
                    payload.get('title') or '', variant.get('title') or ''])),
                identifiers={
                    'sku': variant.get('sku') or '',
                    'barcode': variant.get('barcode') or '',
                    'metafield': (node.get('metafield') or {}).get('value') or '',
                    'variant_id': variant_id,
                },
                location=(node.get('locationMetafield') or {}).get('value') or '',
            )
            product = resolve_line(self.connection, line, self.config)
            if product is None and auto_create and any(
                    str(v).strip() for v in line.identifiers.values()):
                product = _auto_create_product(self.connection, line, self.config)
            location = (line.location or '')[:50]
            if product is not None and location and product.location != location:
                # Location metafield configured -> Shopify is source of truth
                product.location = location
                product.save(update_fields=['location'])

    def fetch_variants(self):
        """Yield every product variant in the shop (product sync)."""
        client = self.client()
        after = None
        while True:
            data = client.graphql(VARIANTS_QUERY, {
                'first': 100, 'after': after, **self._metafield_vars(),
            })
            page = data['productVariants']
            for node in page['nodes']:
                metafield = node.get('metafield') or {}
                location_metafield = node.get('locationMetafield') or {}
                product = node.get('product') or {}
                yield ExternalVariant(
                    external_variant_id=gid_tail(node['id']),
                    external_product_id=gid_tail(product.get('id', '')),
                    title=' - '.join(filter(None, [
                        product.get('title') or '', node.get('title') or ''])),
                    identifiers={
                        'sku': node.get('sku') or '',
                        'barcode': node.get('barcode') or '',
                        'metafield': metafield.get('value') or '',
                        'variant_id': gid_tail(node['id']),
                    },
                    location=location_metafield.get('value') or '',
                )
            if not page['pageInfo']['hasNextPage']:
                break
            after = page['pageInfo']['endCursor']

    def count_variants(self):
        data = self.client().graphql("{ productVariantsCount { count } }")
        return (data.get('productVariantsCount') or {}).get('count')

    def needs_immediate_poll(self):
        return self.shop.last_synced_at is None

    def poll(self):
        """Reconciliation backstop: import open, unfulfilled orders updated
        since the last poll that webhooks may have missed."""
        shop = self.shop
        since = shop.last_synced_at or (timezone.now() - timezone.timedelta(days=7))
        query = (
            f"updated_at:>'{since.isoformat()}' status:open fulfillment_status:unfulfilled"
        )
        if self.config.get('financial_status', 'paid') == 'paid':
            query += " financial_status:paid"

        client = self.client()
        after = None
        poll_started = timezone.now()
        while True:
            data = client.graphql(ORDERS_POLL_QUERY,
                                  {'first': 50, 'after': after, 'query': query})
            page = data['orders']
            for node in page['nodes']:
                self._inbox_from_poll_node(node)
            if not page['pageInfo']['hasNextPage']:
                break
            after = page['pageInfo']['endCursor']

        shop.last_synced_at = poll_started
        shop.save(update_fields=['last_synced_at'])

    @staticmethod
    def _canonical_order_payload(node):
        """GraphQL order node (with lineItems) -> canonical poll/order payload."""
        external_order_id = gid_tail(node['id'])
        lines = []
        for item in (node.get('lineItems') or {}).get('nodes', []):
            variant = item.get('variant') or {}
            variant_id = gid_tail(variant.get('id', '')) if variant.get('id') else ''
            lines.append({
                'external_variant_id': variant_id,
                'external_product_id': gid_tail((variant.get('product') or {}).get('id', ''))
                if variant.get('product') else '',
                'quantity': int(item.get('quantity') or 0),
                'title': item.get('title') or '',
                'identifiers': {'sku': item.get('sku') or '', 'variant_id': variant_id},
            })
        return {
            'external_order_id': external_order_id,
            'order_number': node.get('name') or '',
            'note': node.get('note') or '',
            'status': 'cancelled' if node.get('cancelledAt') else 'open',
            'lines': lines,
        }

    def _inbox_from_poll_node(self, node):
        payload = self._canonical_order_payload(node)
        external_order_id = payload['external_order_id']
        row, created = WebhookInbox.objects.get_or_create(
            connection=self.connection,
            external_event_id=f"poll-order-{external_order_id}",
            defaults={'topic': 'poll/order', 'payload': payload},
        )
        if (not created and row.status in ('processed', 'skipped', 'failed')
                and payload['status'] == 'open'
                and not ExternalOrderLink.objects.filter(
                    connection=self.connection,
                    external_order_id=external_order_id).exists()):
            # Dedupe row exists but the local order is gone (e.g. discarded
            # when the shop was linked to another account): re-import.
            row.topic = 'poll/order'
            row.payload = payload
            row.status = 'pending'
            row.error = ''
            row.save(update_fields=['topic', 'payload', 'status', 'error'])

    # ---------------------------------------------------------- order browse

    def browse_orders(self, query='', first=25, after=None):
        """One page of orders for the console's order browser. Returns
        (orders, has_next, end_cursor); orders are plain display dicts."""
        data = self.client().graphql(ORDERS_BROWSE_QUERY, {
            'first': first, 'after': after, 'query': query or None,
        })
        page = data['orders']
        orders = []
        for node in page['nodes']:
            orders.append({
                'external_order_id': gid_tail(node['id']),
                'name': node.get('name') or '',
                'created_at': node.get('createdAt') or '',
                'cancelled': bool(node.get('cancelledAt')),
                'fulfillment_status': node.get('displayFulfillmentStatus') or '',
                'financial_status': node.get('displayFinancialStatus') or '',
                'item_count': node.get('currentSubtotalLineItemsQuantity') or 0,
            })
        info = page['pageInfo']
        return orders, info['hasNextPage'], info['endCursor']

    def fetch_orders(self, external_order_ids):
        """Full canonical payloads (with lines) for the given order ids."""
        payloads = []
        ids = [order_gid(i) for i in external_order_ids]
        data = self.client().graphql(ORDER_NODES_QUERY, {'ids': ids})
        for node in data.get('nodes') or []:
            if node and node.get('id'):
                payloads.append(self._canonical_order_payload(node))
        return payloads

    # -------------------------------------------------------------- outbound

    def execute(self, outbox_row):
        if outbox_row.action == 'fulfill_order':
            self._fulfill_order(outbox_row)
        elif outbox_row.action == 'archive_order':
            self._archive_order(outbox_row)
        else:
            raise NotImplementedError(f"Unsupported action {outbox_row.action}")

    def _fulfill_order(self, outbox_row):
        payload = outbox_row.payload or {}
        gid = order_gid(payload['external_order_id'])
        client = self.client()

        data = client.graphql(FULFILLMENT_ORDERS_QUERY, {'id': gid})
        order = data.get('order')
        if order is None:
            logger.warning("Order %s no longer exists in Shopify", gid)
            return
        if order.get('displayFulfillmentStatus') == 'FULFILLED':
            return  # already fulfilled (possibly by us on a retry)

        all_fos = (order.get('fulfillmentOrders') or {}).get('nodes', [])
        open_fos = []
        for fo in all_fos:
            if fo.get('status') not in ('OPEN', 'IN_PROGRESS'):
                continue
            actions = {a.get('action') for a in fo.get('supportedActions') or []}
            if 'CREATE_FULFILLMENT' in actions:
                open_fos.append(fo)
            else:
                # e.g. assigned to a third-party fulfillment service; only
                # that service's app may fulfill it.
                logger.warning("Skipping fulfillment order %s on %s: not fulfillable "
                               "by this app (actions=%s)", fo.get('id'), gid, actions)
        if not open_fos:
            logger.info("No fulfillable open fulfillment orders for %s", gid)
            return

        for fo in open_fos:
            result = client.graphql(FULFILLMENT_CREATE_MUTATION, {
                'fulfillment': {
                    'lineItemsByFulfillmentOrder': [
                        {'fulfillmentOrderId': fo['id']},
                    ],
                    'notifyCustomer': bool(payload.get('notify_customer', True)),
                },
            })
            ShopifyClient.check_user_errors(result, 'fulfillmentCreate')

    def _archive_order(self, outbox_row):
        payload = outbox_row.payload or {}
        gid = order_gid(payload['external_order_id'])
        client = self.client()
        result = client.graphql(ORDER_CLOSE_MUTATION, {'input': {'id': gid}})
        ShopifyClient.check_user_errors(result, 'orderClose')

    # ------------------------------------------------------------------ auth

    def refresh_auth(self):
        from integrations_shopify.client import refresh_access_token
        shop = self.shop
        if shop.token_expired and shop.refresh_token:
            refresh_access_token(shop)
