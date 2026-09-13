import base64
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.db import IntegrityError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from integrations.canonical import ExternalLine, ExternalOrder
from integrations.models import ExternalOrderLink, ProductLink, WebhookInbox
from integrations.services import intake
from integrations_shopify import services
from integrations_shopify.client import ShopifyAuthError, exchange_session_token
from integrations_shopify.models import ShopifyShop
from integrations_shopify.session_tokens import (
    InvalidSessionToken, get_session_token_from_request, verify_session_token,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------- webhooks --

@csrf_exempt
@require_POST
def webhook(request):
    """Receiver for all Shopify webhook topics (incl. mandatory GDPR ones).
    Verifies HMAC, stores the event in the inbox, returns 200 fast — all
    processing happens in the worker."""
    hmac_header = request.headers.get('X-Shopify-Hmac-Sha256', '')
    digest = base64.b64encode(
        hmac.new(settings.SHOPIFY_API_SECRET.encode(), request.body, hashlib.sha256).digest()
    ).decode()
    if not hmac_header or not hmac.compare_digest(digest, hmac_header):
        return HttpResponse(status=401)

    topic = request.headers.get('X-Shopify-Topic', '')
    shop_domain = request.headers.get('X-Shopify-Shop-Domain', '')
    event_id = request.headers.get('X-Shopify-Webhook-Id', '')

    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        payload = {}

    shop = (ShopifyShop.objects
            .filter(shop_domain=shop_domain)
            .select_related('connection')
            .first())
    if shop is None:
        # Unknown shop (e.g. GDPR webhook after full deletion): acknowledge.
        logger.info("Webhook %s for unknown shop %s acknowledged", topic, shop_domain)
        return HttpResponse(status=200)

    try:
        WebhookInbox.objects.create(
            connection=shop.connection,
            topic=topic,
            external_event_id=event_id,
            payload=payload,
        )
    except IntegrityError:
        pass  # duplicate delivery

    return HttpResponse(status=200)


# ----------------------------------------------------------- embedded app --

def _frame_headers(response, shop_domain):
    response['Content-Security-Policy'] = (
        f"frame-ancestors https://{shop_domain} https://admin.shopify.com"
    )
    response.xframe_options_exempt = True
    return response


def app_entry(request):
    """Embedded app entry point (iframe inside Shopify admin).

    First load carries ?shop=...&id_token=...; we verify the session token,
    provision/activate the shop via token exchange, and render the console
    shell. Subsequent API calls from the page carry the session token as a
    Bearer header."""
    shop_domain = request.GET.get('shop', '')
    token = get_session_token_from_request(request)

    if token:
        try:
            _, token_shop = verify_session_token(token)
            shop_domain = token_shop
        except InvalidSessionToken as exc:
            logger.warning("Invalid session token on app entry: %s", exc)
            return HttpResponse("Invalid session token", status=401)

        shop, created = services.provision_shop(shop_domain)
        try:
            exchange_session_token(shop, token)
            newly_active = shop.connection.status != 'active'
            services.activate_shop(shop)
            if created or newly_active:
                # Catalog sync runs in the worker (it can take minutes for
                # large shops); the console shows its progress. The worker
                # also polls new connections for recent orders on its own.
                services.enqueue_product_sync(shop.connection)
        except ShopifyAuthError as exc:
            logger.warning("Token exchange failed for %s: %s", shop_domain, exc)
        except Exception:
            logger.exception("App entry bootstrap failed for %s", shop_domain)

    if not shop_domain:
        return HttpResponse("Missing shop parameter", status=400)

    response = render(request, 'shopify/app.html', {
        'api_key': settings.SHOPIFY_API_KEY,
        'shop_domain': shop_domain,
    })
    return _frame_headers(response, shop_domain)


# ------------------------------------------------- session-token JSON API --

def _authenticated_shop(request):
    """Resolve the ShopifyShop for an embedded API request, or None."""
    token = get_session_token_from_request(request)
    if not token:
        return None
    try:
        _, shop_domain = verify_session_token(token)
    except InvalidSessionToken:
        return None
    return (ShopifyShop.objects
            .filter(shop_domain=shop_domain)
            .select_related('connection', 'connection__customer')
            .first())


def api_status(request):
    """Console bootstrap data: connection status, counts, settings."""
    shop = _authenticated_shop(request)
    if shop is None:
        return JsonResponse({'error': 'unauthorized'}, status=401)

    connection = shop.connection
    customer = connection.customer
    from orderpiqrApp.models import Order

    unresolved = ProductLink.objects.filter(
        connection=connection, product__isnull=True).count()
    queued = Order.objects.filter(customer=customer, status='queued').count()

    from django.contrib.auth.models import User
    picker = (User.objects
              .filter(userprofile__customer=customer, groups__name='orderpicker')
              .order_by('pk')
              .first())

    services.check_subscription(shop)
    store_handle = shop.shop_domain.replace('.myshopify.com', '')
    app_handle = getattr(settings, 'SHOPIFY_APP_HANDLE', 'orderpiqr')

    return JsonResponse({
        'shop': shop.shop_domain,
        'shop_name': shop.shop_name,
        'status': connection.status,
        'subscription_status': shop.subscription_status or 'unknown',
        'subscription_plan': shop.subscription_plan,
        'pricing_url': (f"https://admin.shopify.com/store/{store_handle}"
                        f"/charges/{app_handle}/pricing_plans"),
        'config': connection.get_config(),
        'queued_orders': queued,
        'unresolved_products': unresolved,
        'picker_url': request.build_absolute_uri('/'),
        'picker_username': picker.username if picker else '',
        'auto_provisioned': connection.auto_provisioned,
        'customer_name': customer.name,
    })


@csrf_exempt
@require_POST
def api_update_config(request):
    """Persist sync settings from the console."""
    shop = _authenticated_shop(request)
    if shop is None:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    try:
        updates = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'invalid json'}, status=400)

    allowed = set(shop.connection.get_config().keys())
    config = dict(shop.connection.config or {})
    for key, value in updates.items():
        if key in allowed:
            config[key] = value
    shop.connection.config = config
    shop.connection.save(update_fields=['config', 'updated_at'])
    return JsonResponse({'ok': True, 'config': shop.connection.get_config()})


@csrf_exempt
@require_POST
def api_sync_products(request):
    """Queue a product re-sync; the worker executes it and the console
    follows progress via api_sync_status."""
    shop = _authenticated_shop(request)
    if shop is None:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    job = services.enqueue_product_sync(shop.connection)
    return JsonResponse({'ok': True, 'job': job.as_dict()})


def api_sync_status(request):
    """Progress of the most recent product sync job."""
    from integrations.models import SyncJob
    shop = _authenticated_shop(request)
    if shop is None:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    job = (SyncJob.objects
           .filter(connection=shop.connection, kind='product_sync')
           .order_by('-created_at')
           .first())
    return JsonResponse({'job': job.as_dict() if job else None})


# Server-side filter presets keep Shopify search-syntax assembly out of the
# client (and out of user hands).
ORDER_FILTERS = {
    'open_unfulfilled': 'status:open fulfillment_status:unfulfilled',
    'open_unfulfilled_paid': 'status:open fulfillment_status:unfulfilled financial_status:paid',
    'open': 'status:open',
    'any': '',
}

PUSH_BATCH_LIMIT = 50


def api_orders(request):
    """One page of the shop's orders for the console's order browser, each
    flagged with whether it is already imported into OrderPiqr."""
    shop = _authenticated_shop(request)
    if shop is None:
        return JsonResponse({'error': 'unauthorized'}, status=401)

    query = ORDER_FILTERS.get(request.GET.get('filter', ''),
                              ORDER_FILTERS['open_unfulfilled'])
    search = request.GET.get('q', '').strip().replace('"', '')
    if search:
        query = f"{query} {search}".strip()
    after = request.GET.get('after') or None

    connector = shop.connection.get_connector()
    try:
        orders, has_next, end_cursor = connector.browse_orders(
            query=query, first=25, after=after)
    except Exception:
        logger.exception("Order browse failed for %s", shop.shop_domain)
        return JsonResponse({'error': 'Could not load orders from Shopify'}, status=502)

    links = {
        link.external_order_id: link
        for link in (ExternalOrderLink.objects
                     .filter(connection=shop.connection,
                             external_order_id__in=[o['external_order_id'] for o in orders])
                     .select_related('order'))
    }
    for order in orders:
        link = links.get(order['external_order_id'])
        order['imported'] = link is not None
        order['local_status'] = link.order.status if link else ''
        order['local_code'] = link.order.order_code if link else ''

    return JsonResponse({
        'orders': orders,
        'has_next': has_next,
        'end_cursor': end_cursor,
    })


@csrf_exempt
@require_POST
def api_push_orders(request):
    """Import the selected Shopify orders into OrderPiqr right now.

    An explicit push bypasses the financial-status import filter — the
    merchant chose these orders. Capped per request; the console pushes
    large selections in batches."""
    shop = _authenticated_shop(request)
    if shop is None:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    try:
        data = json.loads(request.body or b'{}')
        order_ids = [str(i) for i in data['order_ids']][:PUSH_BATCH_LIMIT]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({'error': 'invalid request'}, status=400)
    if not order_ids:
        return JsonResponse({'error': 'no orders selected'}, status=400)

    connection = shop.connection
    connector = connection.get_connector()
    try:
        payloads = connector.fetch_orders(order_ids)
    except Exception:
        logger.exception("Order fetch failed for %s", shop.shop_domain)
        return JsonResponse({'error': 'Could not load orders from Shopify'}, status=502)

    imported = already = needs_mapping = skipped = 0
    orders = []
    for payload in payloads:
        if payload['status'] == 'cancelled':
            skipped += 1
            continue
        orders.append(ExternalOrder(
            external_order_id=payload['external_order_id'],
            order_number=payload['order_number'],
            note=payload['note'],
            status='open',
            lines=[ExternalLine(**line) for line in payload['lines']],
        ))
    # One identifier lookup for the whole batch (only variants without a
    # ProductLink are fetched), instead of one GraphQL call per order.
    connector._enrich_line_identifiers(
        [line for ext in orders for line in ext.lines])

    for ext in orders:
        try:
            order, created = intake.import_external_order(connection, ext)
        except intake.UnresolvedLinesError:
            needs_mapping += 1
            continue
        if created:
            imported += 1
        elif order is not None:
            already += 1
        else:
            skipped += 1  # every line skipped (unknown products, skip policy)

    return JsonResponse({
        'ok': True,
        'imported': imported,
        'already_imported': already,
        'needs_mapping': needs_mapping,
        'skipped': skipped,
    })


def api_unresolved(request):
    """List Shopify variants that could not be matched to a product."""
    shop = _authenticated_shop(request)
    if shop is None:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    links = (ProductLink.objects
             .filter(connection=shop.connection, product__isnull=True)
             .order_by('title')[:200])
    return JsonResponse({'unresolved': [
        {
            'id': link.pk,
            'title': link.title,
            'external_variant_id': link.external_variant_id,
        }
        for link in links
    ]})


@csrf_exempt
@require_POST
def api_map_product(request):
    """Manually map an unresolved variant to a product code."""
    shop = _authenticated_shop(request)
    if shop is None:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    try:
        data = json.loads(request.body or b'{}')
        link_id = int(data['link_id'])
        product_code = str(data['product_code']).strip()
    except (json.JSONDecodeError, KeyError, ValueError):
        return JsonResponse({'error': 'invalid request'}, status=400)

    from orderpiqrApp.models import Product
    link = ProductLink.objects.filter(
        connection=shop.connection, pk=link_id).first()
    if link is None:
        return JsonResponse({'error': 'link not found'}, status=404)
    product = Product.objects.filter(
        customer=shop.connection.customer, code=product_code).first()
    if product is None:
        return JsonResponse({'error': 'no product with that code'}, status=404)

    link.product = product
    link.identifier_value = product_code
    link.match_method = 'manual'
    link.locked = True
    link.save(update_fields=['product', 'identifier_value', 'match_method', 'locked', 'updated_at'])
    return JsonResponse({'ok': True})


@csrf_exempt
@require_POST
def api_link_account(request):
    """Link this shop to an existing orderpiqr.nl account. The merchant
    proves ownership with their companyadmin credentials; the connection
    moves to that customer and the catalog re-syncs against its products."""
    shop = _authenticated_shop(request)
    if shop is None:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    try:
        data = json.loads(request.body or b'{}')
        username = str(data['username']).strip()
        password = str(data['password'])
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({'error': 'invalid request'}, status=400)

    from django.contrib.auth import authenticate
    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({'error': 'Invalid username or password'}, status=403)
    if not user.groups.filter(name='companyadmin').exists():
        return JsonResponse(
            {'error': 'This account is not a company admin'}, status=403)
    profile = getattr(user, 'userprofile', None)
    if profile is None:
        return JsonResponse({'error': 'Account has no company'}, status=403)

    services.link_to_existing_account(shop, profile.customer)
    shop.refresh_from_db()
    # Catalog re-sync against the new customer's products runs in the worker;
    # the worker's next poll re-imports recent orders (last_synced_at was reset).
    job = services.enqueue_product_sync(shop.connection)

    return JsonResponse({
        'ok': True,
        'customer_name': shop.connection.customer.name,
        'sync_job': job.as_dict(),
    })


@csrf_exempt
@require_POST
def api_set_picker_password(request):
    """Set the password for this customer's orderpicker user so the merchant
    can hand devices to warehouse staff."""
    shop = _authenticated_shop(request)
    if shop is None:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    try:
        data = json.loads(request.body or b'{}')
        password = str(data['password'])
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({'error': 'invalid request'}, status=400)
    if len(password) < 8:
        return JsonResponse({'error': 'password too short (min 8 characters)'}, status=400)

    store_handle = shop.shop_domain.replace('.myshopify.com', '')
    user = services.ensure_picker_user(shop.connection.customer, store_handle)
    user.set_password(password)
    user.save(update_fields=['password'])
    return JsonResponse({'ok': True, 'username': user.username})
