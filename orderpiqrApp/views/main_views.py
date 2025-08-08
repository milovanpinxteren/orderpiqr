from django.shortcuts import render
from django.utils.safestring import mark_safe

from orderpiqr.views import name_entry
from orderpiqrApp.models import Product, Device, SettingDefinition, CustomerSettingValue
import json

def index(request):
    device_fingerprint = request.session.get('device_fingerprint')
    device = Device.objects.filter(user=request.user, device_fingerprint=device_fingerprint).first()
    if not device:
        return name_entry(request)

    customer = request.user.userprofile.customer
    product_data = Product.objects.filter(active=True, customer=customer)
    product_data = product_data.values('product_id', 'code', 'description', 'location')
    settings = get_customer_settings(customer)

    context = {'product_data': str(list(product_data)).replace("'", '"'), 'username': device.name,
               'settings': mark_safe(json.dumps(settings)),
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
