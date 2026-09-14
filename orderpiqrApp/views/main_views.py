from django.shortcuts import render, redirect
from django.utils.safestring import mark_safe
from django.urls import reverse

from orderpiqrApp.models import Product, SettingDefinition, CustomerSettingValue, Order
from orderpiqrApp.utils.devices import resolve_device
import json

def index(request):
    device = resolve_device(request, touch=False)
    if not device:
        # Redirect to name_entry with next parameter to return here after
        return redirect(f"{reverse('name_entry')}?next={request.get_full_path()}")

    customer = request.user.userprofile.customer
    product_data = Product.objects.filter(active=True, customer=customer)
    product_data = product_data.values('product_id', 'code', 'description', 'location')
    settings = get_customer_settings(customer)

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
        'product_data': json.dumps(list(product_data)),
        'username': device.name,
        'settings': mark_safe(json.dumps(settings)),
        'claimed_order': mark_safe(json.dumps(claimed_order_data)) if claimed_order_data else None,
    }
    return render(request, 'index.html', context)


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
