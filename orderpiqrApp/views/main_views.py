from django.shortcuts import render, redirect
from django.utils.safestring import mark_safe
from django.urls import reverse

from orderpiqrApp.models import Product, SettingDefinition, CustomerSettingValue, Order
from orderpiqrApp.utils.build_id import get_build_id
from orderpiqrApp.utils.devices import pin_device_cookie, resolve_device
from orderpiqrApp.utils.scan_events import log_auth_bounce
import json

def index(request):
    device = resolve_device(request, touch=False)
    if not device:
        # The picker is being sent off the scan page — to name entry, and from
        # there to login if the session is gone. This is what "it kicked me
        # out" means, and it used to leave no trace at all. Attribute it to
        # whatever the fingerprint alone can resolve; some bounces are
        # genuinely unattributable, which is itself worth knowing.
        log_auth_bounce(request)
        # Redirect to name_entry with next parameter to return here after
        return redirect(f"{reverse('name_entry')}?next={request.get_full_path()}")

    customer = request.user.userprofile.customer
    product_data = list(Product.objects.filter(active=True, customer=customer)
                        .values('product_id', 'code', 'description', 'location'))
    # Barcode aliases ride along so the client can match any code in physical
    # circulation (e.g. a superseded EAN) to the same product.
    aliases = {}
    for product_id, alias_code in Product.objects.filter(
            customer=customer, active=True, barcodes__isnull=False
    ).values_list('product_id', 'barcodes__code'):
        aliases.setdefault(product_id, []).append(alias_code)
    for product in product_data:
        product['barcodes'] = aliases.get(product['product_id'], [])
    settings = get_customer_settings(customer)
    # The build id this page was rendered with; the client polls
    # /orderpiqr/client-version and reloads itself when it changes.
    settings['build_id'] = get_build_id()

    # Check if there's an order to load from the queue
    claimed_order_data = None
    order_code = request.GET.get('order')
    if order_code:
        order = Order.objects.filter(
            order_code=order_code,
            customer=customer,
            status='in_progress'
        ).first()
        if order:
            # Build picklist from order lines
            picklist = []
            for line in order.lines.select_related('product').all():
                for _ in range(line.quantity):
                    picklist.append(line.product.code)
            claimed_order_data = {
                'order_code': order.order_code,
                'picklist': picklist
            }

    context = {
        # Raw list: the template serialises it with |json_script (XSS-safe)
        'product_data': list(product_data),
        'username': device.name,
        'settings': mark_safe(json.dumps(settings)),
        'claimed_order': mark_safe(json.dumps(claimed_order_data)) if claimed_order_data else None,
    }
    # Re-issue the durable device cookie on every app open: it rolls the
    # lifetime forward for a phone in daily use, and gives a device that only
    # ever had localStorage the copy that survives storage eviction.
    return pin_device_cookie(
        render(request, 'index.html', context), device.device_fingerprint)


def get_customer_settings(customer):
    """Return a dictionary of all setting values for this customer, with fallback to defaults."""
    definitions = {d.key: d for d in SettingDefinition.objects.all()}
    values = CustomerSettingValue.objects.filter(customer=customer).select_related('definition')

    settings = {}
    for key, definition in definitions.items():
        # Check for customer override
        customer_value = next((v for v in values if v.definition_id == definition.id), None)
        raw_value = customer_value.value if customer_value else definition.default_value
        settings[key] = definition.cast_value(raw_value)
    return settings
