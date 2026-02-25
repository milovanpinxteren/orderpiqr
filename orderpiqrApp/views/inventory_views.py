import json

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from orderpiqrApp.models import Product, Device, InventoryLog
from orderpiqrApp.utils.inventory import is_inventory_enabled, modify_inventory


def get_device_from_request(request):
    """Get device for the current session."""
    device_fingerprint = request.session.get('device_fingerprint')
    if device_fingerprint:
        device = Device.objects.filter(
            user=request.user,
            device_fingerprint=device_fingerprint
        ).first()
        if device:
            # Update last_login on activity
            device.last_login = timezone.now()
            device.save(update_fields=['last_login'])
        return device
    return None


@login_required
def inventory_picker(request):
    """
    Mobile-friendly inventory management view for order pickers.
    """
    try:
        customer = request.user.userprofile.customer
    except AttributeError:
        return render(request, 'inventory/picker.html', {'error': _('No customer profile found')})

    if not is_inventory_enabled(customer):
        return render(request, 'inventory/picker.html', {'error': _('Inventory management is not enabled')})

    device = get_device_from_request(request)

    # Get products as JSON for JavaScript search
    products = Product.objects.filter(
        customer=customer,
        active=True
    ).order_by('location', 'code').values(
        'product_id', 'code', 'description', 'location', 'inventory_quantity'
    )

    context = {
        'customer': customer,
        'device': device,
        'products_json': json.dumps(list(products)),
        'reasons': InventoryLog.Reason.choices,
        'change_types': InventoryLog.ChangeType.choices,
    }
    return render(request, 'inventory/picker.html', context)


@login_required
def inventory_product_search(request):
    """
    AJAX endpoint to search products by code or description.
    """
    try:
        customer = request.user.userprofile.customer
    except AttributeError:
        return JsonResponse({'status': 'error', 'message': _('No customer found')}, status=400)

    if not is_inventory_enabled(customer):
        return JsonResponse({'status': 'error', 'message': _('Inventory management not enabled')}, status=403)

    query = request.GET.get('q', '').strip()
    if not query:
        return JsonResponse({'products': []})

    products = Product.objects.filter(
        customer=customer,
        active=True
    ).filter(
        Q(code__icontains=query) | Q(description__icontains=query)
    ).order_by('code')[:20]

    return JsonResponse({
        'products': [
            {
                'product_id': p.product_id,
                'code': p.code,
                'description': p.description,
                'location': p.location,
                'inventory_quantity': p.inventory_quantity,
            }
            for p in products
        ]
    })


@login_required
def inventory_product_lookup(request, code):
    """
    AJAX endpoint to lookup product by exact code (for barcode scanning).
    """
    try:
        customer = request.user.userprofile.customer
    except AttributeError:
        return JsonResponse({'status': 'error', 'message': _('No customer found')}, status=400)

    if not is_inventory_enabled(customer):
        return JsonResponse({'status': 'error', 'message': _('Inventory management not enabled')}, status=403)

    try:
        product = Product.objects.get(
            customer=customer,
            code=code,
            active=True
        )
        return JsonResponse({
            'status': 'ok',
            'product': {
                'product_id': product.product_id,
                'code': product.code,
                'description': product.description,
                'location': product.location,
                'inventory_quantity': product.inventory_quantity,
            }
        })
    except Product.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': _('Product not found')
        }, status=404)


@login_required
@require_POST
def inventory_modify(request):
    """
    AJAX endpoint to modify product inventory.

    Expected JSON body:
    {
        "product_id": 123,
        "change_type": "set" | "adjust",
        "value": 10,
        "reason": "stock_count",
        "notes": "optional notes"
    }
    """
    try:
        customer = request.user.userprofile.customer
    except AttributeError:
        return JsonResponse({'status': 'error', 'message': _('No customer found')}, status=400)

    if not is_inventory_enabled(customer):
        return JsonResponse({'status': 'error', 'message': _('Inventory management not enabled')}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': _('Invalid request')}, status=400)

    product_id = data.get('product_id')
    change_type = data.get('change_type')
    value = data.get('value')
    reason = data.get('reason')
    notes = data.get('notes', '')

    # Validation
    if not all([product_id, change_type, value is not None, reason]):
        return JsonResponse({'status': 'error', 'message': _('Missing required fields')}, status=400)

    valid_change_types = [c[0] for c in InventoryLog.ChangeType.choices]
    if change_type not in valid_change_types:
        return JsonResponse({'status': 'error', 'message': _('Invalid change type')}, status=400)

    valid_reasons = [r[0] for r in InventoryLog.Reason.choices]
    if reason not in valid_reasons:
        return JsonResponse({'status': 'error', 'message': _('Invalid reason')}, status=400)

    try:
        value = int(value)
    except (TypeError, ValueError):
        return JsonResponse({'status': 'error', 'message': _('Value must be a number')}, status=400)

    try:
        product = Product.objects.get(
            product_id=product_id,
            customer=customer
        )
    except Product.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': _('Product not found')}, status=404)

    device = get_device_from_request(request)

    log = modify_inventory(
        product=product,
        user=request.user,
        change_type=change_type,
        reason=reason,
        value=value,
        device=device,
        notes=notes
    )

    return JsonResponse({
        'status': 'ok',
        'message': _('Inventory updated'),
        'new_quantity': log.new_quantity,
        'old_quantity': log.old_quantity,
        'log_id': log.log_id
    })
