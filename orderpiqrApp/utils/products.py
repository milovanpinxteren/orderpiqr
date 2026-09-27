"""Product code resolution and barcode-alias management.

A product is scannable by its primary ``Product.code`` and by any number of
``ProductBarcode`` aliases. Every place that turns a scanned/synced code into a
Product must go through ``resolve_product`` so the two stay interchangeable —
suppliers rotate EANs, and during the transition both codes are in circulation.
"""
from django.db import transaction
from django.db.models import F, Q

from orderpiqrApp.models import InventoryLog, Product, ProductBarcode


def resolve_product(customer, code):
    """Resolve a scan/order-line code to a Product: primary code first, then
    barcode aliases. Returns None when nothing matches."""
    product = Product.objects.filter(customer=customer, code=code).first()
    if product is not None:
        return product
    alias = (ProductBarcode.objects
             .filter(customer=customer, code=code)
             .select_related('product')
             .first())
    return alias.product if alias else None


def code_conflict(customer, code, exclude_product=None):
    """True when ``code`` is already taken within this customer, as another
    product's primary code or as a barcode alias. ``exclude_product`` exempts
    that product's own codes (for edits)."""
    products = Product.objects.filter(customer=customer, code=code)
    aliases = ProductBarcode.objects.filter(customer=customer, code=code)
    if exclude_product is not None:
        products = products.exclude(pk=exclude_product.pk)
        aliases = aliases.exclude(product=exclude_product)
    return products.exists() or aliases.exists()


def set_primary_code(product, new_code):
    """Change a product's primary code, keeping the old primary as a barcode
    alias ("never forget a code" — old labels stay scannable). If the new code
    was one of the product's own aliases, the two simply swap. Saves nothing
    when the code is unchanged."""
    old_code = product.code
    if new_code == old_code:
        return
    with transaction.atomic():
        # Promoting an existing alias: remove it so alias never equals primary.
        ProductBarcode.objects.filter(product=product, code=new_code).delete()
        product.code = new_code
        product.save(update_fields=['code'])
        ProductBarcode.objects.get_or_create(
            product=product, customer=product.customer, code=old_code)


def set_alias_codes(product, codes):
    """Bring the product's alias set to exactly ``codes`` (desired state).
    The primary code is silently dropped from the list. Callers validate
    conflicts with other products first (``code_conflict``)."""
    wanted = {str(c).strip() for c in codes if str(c).strip()}
    wanted.discard(product.code)
    with transaction.atomic():
        product.barcodes.exclude(code__in=wanted).delete()
        existing = set(product.barcodes.values_list('code', flat=True))
        ProductBarcode.objects.bulk_create([
            ProductBarcode(product=product, customer=product.customer, code=code)
            for code in wanted - existing
        ])


def merge_products(target, source, user=None):
    """Merge ``source`` into ``target``: repoint order lines and picks, keep
    every code of ``source`` as an alias of ``target``, add inventory together,
    delete ``source``. Both products must belong to the same customer.
    ``user`` is recorded on the inventory-transfer log entry."""
    if source.pk == target.pk:
        raise ValueError("Cannot merge a product into itself")
    if source.customer_id != target.customer_id:
        raise ValueError("Cannot merge products of different customers")

    with transaction.atomic():
        source.orderline_set.update(product=target)
        source.productpick_set.update(product=target)
        source.inventory_logs.update(product=target)
        # Platform links (Shopify/WooCommerce variant mappings) would otherwise
        # cascade away with the source product.
        source.external_links.update(product=target)

        source_codes = [source.code, *source.barcodes.values_list('code', flat=True)]
        source.barcodes.all().delete()
        for code in source_codes:
            if code != target.code:
                ProductBarcode.objects.get_or_create(
                    product=target, customer=target.customer, code=code)

        if source.inventory_quantity:
            # F() so a concurrent pick decrementing the target is not overwritten.
            Product.objects.filter(pk=target.pk).update(
                inventory_quantity=F('inventory_quantity') + source.inventory_quantity)
            target.refresh_from_db(fields=['inventory_quantity'])
            # Same audit trail as every other quantity change (the log
            # old/new pair is best-effort under concurrency; the quantity
            # itself is race-free).
            InventoryLog.objects.create(
                product=target,
                user=user,
                old_quantity=target.inventory_quantity - source.inventory_quantity,
                new_quantity=target.inventory_quantity,
                change_type=InventoryLog.ChangeType.ADJUST,
                reason=InventoryLog.Reason.OTHER,
                notes=f"Merged product '{source.code}' into '{target.code}'",
            )
        source.delete()
