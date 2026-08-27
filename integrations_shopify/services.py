"""Shop provisioning and connect-time product sync."""

import logging
import secrets

from django.contrib.auth.models import Group, User
from django.db import transaction
from django.utils import timezone

from integrations.models import Connection
from integrations.services.intake import resolve_line
from integrations.canonical import ExternalLine
from integrations_shopify.client import ShopifyClient
from integrations_shopify.models import ShopifyShop
from orderpiqrApp.models import Customer, UserProfile

logger = logging.getLogger(__name__)

SHOP_INFO_QUERY = """
{ shop { name email myshopifyDomain } }
"""

SUBSCRIPTION_QUERY = """
{ currentAppInstallation { activeSubscriptions { name status currentPeriodEnd } } }
"""

SUBSCRIPTION_CHECK_INTERVAL = timezone.timedelta(hours=1)


def check_subscription(shop, force=False):
    """Refresh the cached Managed Pricing subscription state (throttled).

    Returns True when an active subscription exists (trials are ACTIVE in
    Shopify's model). On API failure the last known state is kept — billing
    checks must never take the console or sync down."""
    fresh = (shop.subscription_checked_at is not None
             and timezone.now() - shop.subscription_checked_at < SUBSCRIPTION_CHECK_INTERVAL)
    if fresh and not force:
        return shop.subscription_status == 'active'

    client = ShopifyClient(shop)
    try:
        subs = (client.graphql(SUBSCRIPTION_QUERY)
                ['currentAppInstallation']['activeSubscriptions'])
    except Exception:
        logger.exception("Subscription check failed for %s", shop.shop_domain)
        return shop.subscription_status == 'active'

    if subs:
        shop.subscription_status = 'active'
        shop.subscription_plan = subs[0].get('name') or ''
    else:
        shop.subscription_status = 'none'
        shop.subscription_plan = ''
    shop.subscription_checked_at = timezone.now()
    shop.save(update_fields=[
        'subscription_status', 'subscription_plan', 'subscription_checked_at'])
    return shop.subscription_status == 'active'


@transaction.atomic
def provision_shop(shop_domain):
    """Get or create the Customer + Connection + ShopifyShop for a shop.

    Called on first embedded-app load after installation. Also (re)activates
    a previously uninstalled shop."""
    shop = (ShopifyShop.objects
            .filter(shop_domain=shop_domain)
            .select_related('connection', 'connection__customer')
            .first())
    if shop:
        if shop.uninstalled_at:
            shop.uninstalled_at = None
            shop.save(update_fields=['uninstalled_at'])
            shop.connection.status = 'active'
            shop.connection.save(update_fields=['status'])
        return shop, False

    store_name = shop_domain.replace('.myshopify.com', '')
    customer = Customer.objects.create(
        name=store_name,
        description=f"Created via Shopify install ({shop_domain})",
    )
    connection = Connection.objects.create(
        customer=customer,
        platform='shopify',
        name=store_name,
        status='pending',  # active once token exchange succeeds
        auto_provisioned=True,
    )
    shop = ShopifyShop.objects.create(connection=connection, shop_domain=shop_domain)

    _provision_users(customer, store_name)
    logger.info("Provisioned new customer %s for shop %s", customer.pk, shop_domain)
    return shop, True


def _provision_users(customer, store_name):
    """Create the companyadmin and orderpicker users, mirroring signup.
    Passwords are random; the merchant sets real ones from the console."""
    admin_group, _ = Group.objects.get_or_create(name='companyadmin')
    picker_group, _ = Group.objects.get_or_create(name='orderpicker')

    for base, group in ((f"{store_name}_admin", admin_group),
                        (f"{store_name}_picker", picker_group)):
        username = base
        suffix = 2
        while User.objects.filter(username=username).exists():
            username = f"{base}{suffix}"
            suffix += 1
        user = User.objects.create_user(
            username=username, password=secrets.token_urlsafe(16))
        user.groups.add(group)
        UserProfile.objects.create(user=user, customer=customer)


def activate_shop(shop):
    """Mark the connection active and store shop metadata (post token
    exchange), then make sure the catalog is linked."""
    client = ShopifyClient(shop)
    try:
        info = client.graphql(SHOP_INFO_QUERY)['shop']
        shop.shop_name = info.get('name') or ''
        shop.shop_email = info.get('email') or ''
        shop.save(update_fields=['shop_name', 'shop_email'])
    except Exception:
        logger.exception("Could not fetch shop info for %s", shop.shop_domain)

    connection = shop.connection
    if connection.status != 'active':
        connection.status = 'active'
        connection.save(update_fields=['status'])

    check_subscription(shop, force=True)


@transaction.atomic
def link_to_existing_account(shop, target_customer):
    """Re-attach a connection to an existing OrderPiqr customer.

    Used when a merchant who already has an orderpiqr.nl account installed
    the app (which auto-provisioned a throwaway Customer). Imported artifacts
    tied to the old customer are discarded; the catalog is re-synced against
    the target customer's products afterwards (by the caller).
    """
    from orderpiqrApp.models import Order

    connection = shop.connection
    old_customer = connection.customer
    if old_customer.pk == target_customer.pk:
        return connection

    # Discard imported orders that were never picked, plus all links —
    # they reference the old customer's products.
    order_ids = list(connection.order_links.values_list('order_id', flat=True))
    connection.order_links.all().delete()
    Order.objects.filter(
        order_id__in=order_ids, status__in=['draft', 'queued', 'cancelled'],
    ).delete()
    connection.product_links.all().delete()

    was_auto = connection.auto_provisioned
    connection.customer = target_customer
    connection.auto_provisioned = False
    connection.save(update_fields=['customer', 'auto_provisioned', 'updated_at'])

    if was_auto and not old_customer.picklist_set.exists():
        # Throwaway account was never used: remove it and its auto users.
        for profile in UserProfile.objects.filter(customer=old_customer).select_related('user'):
            profile.user.delete()
        old_customer.delete()
        logger.info("Removed auto-provisioned customer %s after linking shop %s",
                    old_customer.pk, shop.shop_domain)

    logger.info("Linked shop %s to existing customer %s",
                shop.shop_domain, target_customer.pk)
    return connection


def sync_products(connection):
    """Walk the Shopify catalog and resolve every variant against the
    customer's products using the connection's identifier chain. Under the
    auto_create policy, unmatched variants become new products (this is how
    a fresh install imports the catalog). Returns (linked, unresolved)."""
    from integrations.services.intake import _auto_create_product

    connector = connection.get_connector()
    config = connection.get_config()
    auto_create = config['unknown_product_policy'] == 'auto_create'
    linked = 0
    unresolved = 0
    from integrations.models import ProductLink

    for variant in connector.fetch_variants():
        if ProductLink.objects.filter(
            connection=connection,
            external_variant_id=variant.external_variant_id,
            locked=True,
        ).exists():
            linked += 1
            continue
        line = ExternalLine(
            external_variant_id=variant.external_variant_id,
            external_product_id=variant.external_product_id,
            quantity=0,
            title=variant.title,
            identifiers=variant.identifiers,
            location=variant.location,
        )
        product = resolve_line(connection, line, config)
        if product is None and auto_create and any(
                str(v).strip() for v in (variant.identifiers or {}).values()):
            product = _auto_create_product(connection, line, config)
        if product is not None:
            if variant.location and product.location != variant.location:
                # Location metafield configured -> Shopify is source of truth
                product.location = variant.location
                product.save(update_fields=['location'])
            linked += 1
        else:
            unresolved += 1
            # Record the unresolved variant so the console can list it.
            ProductLink.objects.update_or_create(
                connection=connection,
                external_variant_id=variant.external_variant_id,
                defaults={
                    'product': None,
                    'external_product_id': variant.external_product_id,
                    'identifier_value': '',
                    'match_method': '',
                    'title': variant.title,
                },
            )
    logger.info("Product sync for connection %s: %s linked, %s unresolved",
                connection.pk, linked, unresolved)
    return linked, unresolved
