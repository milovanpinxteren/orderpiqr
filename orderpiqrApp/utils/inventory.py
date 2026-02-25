from django.db import transaction
from django.utils.translation import gettext as _

from orderpiqrApp.models import Product, SettingDefinition, CustomerSettingValue, InventoryLog


def is_inventory_enabled(customer):
    """
    Check if inventory management is enabled for this customer.

    Args:
        customer: Customer instance

    Returns:
        bool: True if inventory management is enabled
    """
    if not customer:
        return False

    try:
        definition = SettingDefinition.objects.get(key='inventory_management_enabled')
        customer_value = CustomerSettingValue.objects.filter(
            customer=customer,
            definition=definition
        ).first()

        raw_value = customer_value.value if customer_value else definition.default_value
        return definition.cast_value(raw_value) if raw_value else False
    except SettingDefinition.DoesNotExist:
        return False


@transaction.atomic
def modify_inventory(
    product,
    user,
    change_type,
    reason,
    value,
    device=None,
    notes=None,
    source_picklist=None
):
    """
    Modify inventory for a product with full logging.

    Args:
        product: Product instance
        user: User making the change
        change_type: 'set' for absolute or 'adjust' for relative
        reason: Reason code from InventoryLog.Reason
        value: The quantity value (new quantity for 'set', delta for 'adjust')
        device: Optional Device instance
        notes: Optional notes string
        source_picklist: Optional PickList reference for Phase 2 integration

    Returns:
        InventoryLog instance
    """
    old_quantity = product.inventory_quantity

    if change_type == InventoryLog.ChangeType.SET:
        new_quantity = value
    else:  # ADJUST
        new_quantity = old_quantity + value

    # Ensure non-negative
    new_quantity = max(0, new_quantity)

    # Update product
    product.inventory_quantity = new_quantity
    product.save(update_fields=['inventory_quantity'])

    # Create log entry
    log = InventoryLog.objects.create(
        product=product,
        user=user,
        device=device,
        old_quantity=old_quantity,
        new_quantity=new_quantity,
        change_type=change_type,
        reason=reason,
        notes=notes,
        source_picklist=source_picklist
    )

    return log


def decrement_inventory_for_picklist(picklist, user):
    """
    Phase 2 hook: Decrement inventory for all products in a completed picklist.

    This function should be called when a picklist is marked as successful.
    Currently not called - prepared for Phase 2 integration.

    Args:
        picklist: PickList instance
        user: User who completed the picklist

    Returns:
        list: List of InventoryLog entries created
    """
    from orderpiqrApp.models import ProductPick

    if not picklist.order or not picklist.order.customer:
        return []

    if not is_inventory_enabled(picklist.order.customer):
        return []

    logs = []
    product_picks = ProductPick.objects.filter(
        picklist=picklist,
        successful=True
    ).select_related('product')

    # Aggregate quantities by product
    from collections import defaultdict
    quantities = defaultdict(int)
    for pick in product_picks:
        quantities[pick.product_id] += pick.quantity

    for product_id, quantity in quantities.items():
        product = Product.objects.get(product_id=product_id)
        log = modify_inventory(
            product=product,
            user=user,
            change_type=InventoryLog.ChangeType.ADJUST,
            reason=InventoryLog.Reason.ORDER_PICKED,
            value=-quantity,
            device=picklist.device,
            notes=_("Auto-decremented from order %(order_code)s") % {
                "order_code": picklist.order.order_code
            },
            source_picklist=picklist
        )
        logs.append(log)

    return logs
