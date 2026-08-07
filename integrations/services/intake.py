"""Order intake: the single place where external orders become OrderPiqr
Orders, regardless of platform."""

import logging

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from orderpiqrApp.models import Order, OrderLine, Product
from integrations.models import ExternalOrderLink, ProductLink

logger = logging.getLogger(__name__)


class UnresolvedLinesError(Exception):
    """Raised under the 'hold' unknown-product policy when one or more lines
    cannot be resolved to a Product."""

    def __init__(self, lines):
        self.lines = lines
        idents = ', '.join(
            (line.identifiers.get('barcode') or line.identifiers.get('sku')
             or line.external_variant_id or '?')
            for line in lines
        )
        super().__init__(f"Unresolved product identifiers: {idents}")


def resolve_line(connection, line, config):
    """Resolve an ExternalLine to a Product via ProductLink, falling back to
    the connection's identifier chain. Writes a ProductLink on first match."""
    link = (ProductLink.objects
            .filter(connection=connection,
                    external_variant_id=line.external_variant_id,
                    product__isnull=False)
            .select_related('product')
            .first())
    if link:
        return link.product

    for id_type in config['identifier_chain']:
        value = (line.identifiers or {}).get(id_type) or ''
        value = str(value).strip()
        if not value:
            continue
        product = Product.objects.filter(customer=connection.customer, code=value).first()
        if product:
            ProductLink.objects.update_or_create(
                connection=connection,
                external_variant_id=line.external_variant_id,
                defaults={
                    'product': product,
                    'external_product_id': line.external_product_id,
                    'identifier_value': value,
                    'match_method': id_type,
                    'title': line.title or '',
                },
            )
            return product
    return None


def _auto_create_product(connection, line, config):
    """Create a Product for an unknown external variant (auto_create policy)."""
    code = ''
    for id_type in config['identifier_chain']:
        value = (line.identifiers or {}).get(id_type) or ''
        value = str(value).strip()
        if value:
            code = value
            break
    if not code:
        code = f"{connection.platform}-{line.external_variant_id}"

    product = Product.objects.filter(customer=connection.customer, code=code).first()
    if product is None:
        product = Product.objects.create(
            customer=connection.customer,
            code=code,
            description=line.title or code,
            location='',
            active=True,
        )
        logger.info("Auto-created product %s for connection %s", code, connection.pk)

    ProductLink.objects.update_or_create(
        connection=connection,
        external_variant_id=line.external_variant_id,
        defaults={
            'product': product,
            'external_product_id': line.external_product_id,
            'identifier_value': code,
            'match_method': 'auto_created',
            'title': line.title or '',
        },
    )
    return product


def next_queue_position(customer):
    max_pos = Order.objects.filter(
        customer=customer,
        status__in=['queued', 'in_progress'],
    ).aggregate(max_pos=Max('queue_position'))['max_pos']
    return (max_pos or 0) + 1


def _unique_order_code(customer, base_code):
    """Order codes are unique per customer; a manual order may already use
    this code, in which case we suffix."""
    code = base_code
    suffix = 2
    while Order.objects.filter(customer=customer, order_code=code).exists():
        code = f"{base_code}-{suffix}"
        suffix += 1
    return code


@transaction.atomic
def import_external_order(connection, ext_order):
    """Create an Order (+lines +ExternalOrderLink) from an ExternalOrder.

    Idempotent on (connection, external_order_id). Returns (order, created);
    order is None when every line was skipped. Raises UnresolvedLinesError
    under the 'hold' policy.
    """
    existing = (ExternalOrderLink.objects
                .filter(connection=connection, external_order_id=ext_order.external_order_id)
                .select_related('order')
                .first())
    if existing:
        return existing.order, False

    config = connection.get_config()
    customer = connection.customer

    resolved = []
    unresolved = []
    for line in ext_order.lines:
        if line.quantity < 1:
            continue
        product = resolve_line(connection, line, config)
        if product is None:
            policy = config['unknown_product_policy']
            if policy == 'auto_create':
                product = _auto_create_product(connection, line, config)
            elif policy == 'skip':
                logger.info("Skipping unresolved line %s on order %s",
                            line.external_variant_id, ext_order.external_order_id)
                continue
            else:  # hold
                unresolved.append(line)
                continue
        resolved.append((product, line.quantity))

    if unresolved:
        raise UnresolvedLinesError(unresolved)
    if not resolved:
        return None, False

    base_code = ext_order.order_number or ext_order.external_order_id
    order_code = _unique_order_code(customer, str(base_code))

    if config['auto_queue']:
        status, queue_position = 'queued', next_queue_position(customer)
    else:
        status, queue_position = 'draft', None

    order = Order.objects.create(
        customer=customer,
        order_code=order_code,
        notes=ext_order.note or '',
        status=status,
        queue_position=queue_position,
        source=connection.platform,
    )
    OrderLine.objects.bulk_create([
        OrderLine(order=order, product=product, quantity=quantity)
        for product, quantity in resolved
    ])
    ExternalOrderLink.objects.create(
        connection=connection,
        order=order,
        external_order_id=ext_order.external_order_id,
        external_order_number=str(ext_order.order_number or ''),
    )
    logger.info("Imported order %s (%s) for connection %s",
                order_code, ext_order.external_order_id, connection.pk)
    return order, True


@transaction.atomic
def cancel_external_order(connection, external_order_id, reason=''):
    """Cancel the local Order for an externally cancelled/fulfilled order.
    Completed orders are left alone. Returns the order or None."""
    link = (ExternalOrderLink.objects
            .filter(connection=connection, external_order_id=str(external_order_id))
            .select_related('order')
            .first())
    if not link:
        return None
    order = link.order
    if order.status in ('completed', 'cancelled'):
        return order

    order.status = 'cancelled'
    order.queue_position = None
    stamp = f"[{timezone.now():%Y-%m-%d %H:%M}] Cancelled via {connection.platform}"
    if reason:
        stamp += f": {reason}"
    order.notes = f"{order.notes}\n{stamp}" if order.notes else stamp
    order.save(update_fields=['status', 'queue_position', 'notes'])
    logger.info("Cancelled order %s from external event", order.order_code)
    return order
