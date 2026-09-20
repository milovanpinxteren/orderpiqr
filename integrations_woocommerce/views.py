"""Machine-to-machine JSON endpoints for the WordPress plugin. All views are
CSRF-exempt; auth is the pairing key (connect), the webhook HMAC signature
(webhooks) or the plugin token (status/disconnect)."""

import base64
import hashlib
import hmac
import json
import logging
import secrets

from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from integrations.models import (
    Connection, ExternalOrderLink, ProductLink, WebhookInbox,
)
from integrations_woocommerce import services
from integrations_woocommerce.client import WooCommerceAPIError, WooCommerceClient, normalize_store_url
from integrations_woocommerce.models import PairingToken, WooCommerceStore

logger = logging.getLogger(__name__)


def _clip(value, limit):
    return str(value or '')[:limit]


def _error(code, message, status=400):
    return JsonResponse({'error': code, 'message': message}, status=status)


def _json_body(request):
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------- connect --

@csrf_exempt
@require_POST
def connect(request):
    """Pair a store with a customer: validate the pairing key, verify the
    REST credentials, create the connection, register webhooks, queue the
    catalog sync and hand the plugin its API token."""
    data = _json_body(request)
    if data is None:
        return _error('invalid_request', 'Request body must be a JSON object.')

    token = PairingToken.find(data.get('pairing_key'))
    if token is None or token.is_used:
        return _error('invalid_pairing_key',
                      'This pairing key is not valid. Generate a new one in '
                      'the OrderPiqr portal.')
    if token.is_expired:
        return _error('expired_pairing_key',
                      'This pairing key has expired. Generate a new one in '
                      'the OrderPiqr portal.')

    try:
        store_url = normalize_store_url(data.get('store_url'))
    except ValueError as exc:
        return _error('store_unreachable', str(exc))
    consumer_key = str(data.get('consumer_key') or '')
    consumer_secret = str(data.get('consumer_secret') or '')

    client = WooCommerceClient(store_url, consumer_key, consumer_secret)
    try:
        client.get_system_status()
    except WooCommerceAPIError as exc:
        logger.info("Connect check failed for %s: %s", store_url, exc)
        return _error('store_unreachable',
                      'Could not reach the store with these API credentials. '
                      'Check the store URL and REST API key.')

    customer = token.customer
    store_name = _clip(data.get('store_name'), 255) or store_url.split('//', 1)[-1]

    # Reconnect: replace any previous connection of this store for this
    # customer (fresh credentials, fresh webhooks, history stays on the old
    # connection rows until then).
    for old_store in WooCommerceStore.objects.filter(
            connection__customer=customer, store_url=store_url
    ).exclude(connection__status='disconnected').select_related('connection'):
        try:
            services.remove_webhooks(old_store)
        except WooCommerceAPIError:
            logger.info("Webhook cleanup failed for %s", old_store.store_url)
        old_store.connection.status = 'disconnected'
        old_store.connection.save(update_fields=['status'])

    plugin_token, plugin_token_hash = WooCommerceStore.generate_plugin_token()
    with transaction.atomic():
        connection = Connection.objects.create(
            customer=customer,
            platform='woocommerce',
            name=store_name,
            status='active',
        )
        store = WooCommerceStore.objects.create(
            connection=connection,
            store_url=_clip(store_url, 255),
            store_name=store_name,
            webhook_secret=secrets.token_hex(32),
            plugin_token_hash=plugin_token_hash,
            wordpress_version=_clip(data.get('wordpress_version'), 32),
            woocommerce_version=_clip(data.get('woocommerce_version'), 32),
            plugin_version=_clip(data.get('plugin_version'), 32),
        )
        store.consumer_key = consumer_key
        store.consumer_secret = consumer_secret
        store.save(update_fields=['encrypted_consumer_key', 'encrypted_consumer_secret'])

    try:
        store.webhook_ids = services.register_webhooks(store)
        store.save(update_fields=['webhook_ids'])
    except WooCommerceAPIError as exc:
        logger.warning("Webhook registration failed for %s: %s", store_url, exc)
        connection.delete()  # cascades the store
        return _error('webhook_registration_failed',
                      'The store accepted the credentials but webhook '
                      'registration failed. Check that the REST API key has '
                      'Read/Write permissions.')

    services.enqueue_product_sync(connection)
    token.mark_used()
    logger.info("Connected WooCommerce store %s to customer %s (connection %s)",
                store_url, customer.pk, connection.pk)

    return JsonResponse({
        'status': 'connected',
        'connection_id': connection.pk,
        'plugin_token': plugin_token,
        'customer_name': customer.name,
    })


# --------------------------------------------------------------- webhooks --

@csrf_exempt
@require_POST
def webhook(request):
    """Receiver for WooCommerce webhook deliveries. Verifies the HMAC
    signature, strips the payload down to PII-free fields and stores it in
    the inbox — processing happens in the worker."""
    signature = request.headers.get('X-WC-Webhook-Signature', '')
    topic = request.headers.get('X-WC-Webhook-Topic', '')
    if not signature or not topic:
        # Activation ping ('webhook_id=N', unsigned): acknowledge, no inbox row.
        return HttpResponse(status=200)

    cid = request.GET.get('cid', '')
    store = None
    if cid.isdigit():
        store = (WooCommerceStore.objects
                 .filter(connection_id=int(cid))
                 .select_related('connection')
                 .first())
    if store is None:
        return HttpResponse(status=400)

    digest = base64.b64encode(
        hmac.new(store.webhook_secret.encode(), request.body, hashlib.sha256).digest()
    ).decode()
    if not hmac.compare_digest(digest, signature):
        return HttpResponse(status=401)

    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict) or not payload.get('id'):
        return HttpResponse(status=200)  # ping-shaped or empty body

    event_id = request.headers.get('X-WC-Webhook-Delivery-ID', '')
    if not event_id:
        # Redeliveries of the same event share this fingerprint;
        # date_modified keeps distinct updates of one resource apart.
        fingerprint = ':'.join([
            request.headers.get('X-WC-Webhook-ID', ''),
            request.headers.get('X-WC-Webhook-Resource-ID', str(payload.get('id'))),
            topic,
            str(payload.get('date_modified') or ''),
        ])
        event_id = hashlib.sha256(fingerprint.encode()).hexdigest()

    try:
        with transaction.atomic():
            WebhookInbox.objects.create(
                connection=store.connection,
                topic=_clip(topic, 64),
                external_event_id=_clip(event_id, 255),
                payload=services.strip_webhook_payload(topic, payload),
            )
    except IntegrityError:
        pass  # duplicate delivery

    return HttpResponse(status=200)


# ------------------------------------------------------ plugin token auth --

def _store_for_plugin(connection_id, plugin_token):
    """Resolve the store for a plugin-authenticated request, or None."""
    if not str(connection_id or '').isdigit():
        return None
    store = (WooCommerceStore.objects
             .filter(connection_id=int(connection_id))
             .select_related('connection')
             .first())
    if store is None or not store.check_plugin_token(plugin_token):
        return None
    return store


@csrf_exempt
@require_POST
def disconnect(request):
    """Called when the plugin is disconnected/deactivated. Idempotent."""
    data = _json_body(request)
    if data is None:
        return _error('invalid_request', 'Request body must be a JSON object.')

    connection_id = data.get('connection_id')
    if not str(connection_id or '').isdigit():
        return _error('invalid_request', 'connection_id is required.')
    store = (WooCommerceStore.objects
             .filter(connection_id=int(connection_id))
             .select_related('connection')
             .first())
    if store is None:
        return JsonResponse({'status': 'disconnected'})  # already gone
    if not store.check_plugin_token(str(data.get('plugin_token') or '')):
        return _error('unauthorized', 'Invalid plugin token.', status=403)

    if store.connection.status != 'disconnected':
        store.connection.status = 'disconnected'
        store.connection.save(update_fields=['status'])
        try:
            services.remove_webhooks(store)
        except WooCommerceAPIError:
            logger.info("Webhook cleanup on disconnect failed for %s",
                        store.store_url)
    return JsonResponse({'status': 'disconnected'})


@require_GET
def status(request):
    """Connection health for the plugin's settings screen."""
    store = _store_for_plugin(
        request.GET.get('connection_id'),
        request.headers.get('X-OrderPiqr-Plugin-Token', ''),
    )
    if store is None:
        return _error('unauthorized', 'Invalid connection or plugin token.',
                      status=401)

    connection = store.connection
    last_event = (WebhookInbox.objects
                  .filter(connection=connection)
                  .order_by('-received_at')
                  .values_list('received_at', flat=True)
                  .first())
    return JsonResponse({
        'status': connection.status,
        'store_name': store.store_name,
        'orders_synced': ExternalOrderLink.objects.filter(
            connection=connection).count(),
        'products_linked': ProductLink.objects.filter(
            connection=connection, product__isnull=False).count(),
        'last_event_at': last_event.isoformat() if last_event else None,
    })
