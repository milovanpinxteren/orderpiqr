"""Hooks called from the picking flow. Cheap and failure-proof: they only
write SyncOutbox rows; the worker talks to the platforms."""

import logging

from integrations.models import SyncOutbox

logger = logging.getLogger(__name__)


def _queue_intent(connection, order, action, payload):
    """Create an outbox row unless an equivalent one is already pending or done."""
    exists = SyncOutbox.objects.filter(
        connection=connection,
        order=order,
        action=action,
        status__in=['pending', 'processing', 'done'],
    ).exists()
    if not exists:
        SyncOutbox.objects.create(
            connection=connection, order=order, action=action, payload=payload,
        )


def order_completed(order):
    """Queue outbound intents for every connection this order came from.
    Called after an Order transitions to 'completed'. Never raises."""
    try:
        links = order.external_links.select_related('connection').all()
        for link in links:
            connection = link.connection
            if connection.status != 'active':
                continue
            config = connection.get_config()
            if config['fulfill_on_complete']:
                _queue_intent(connection, order, 'fulfill_order', {
                    'external_order_id': link.external_order_id,
                    'notify_customer': bool(config['notify_customer']),
                })
            if config['archive_on_complete']:
                _queue_intent(connection, order, 'archive_order', {
                    'external_order_id': link.external_order_id,
                })
    except Exception:
        logger.exception("order_completed hook failed for order %s", order.pk)
