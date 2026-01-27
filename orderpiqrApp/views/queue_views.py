from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Max
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from orderpiqrApp.models import Order, Device, UserProfile, PickList, ProductPick
from orderpiqrApp.utils.decorators import company_admin_required


def get_queue_orders(customer, include_lines=False):
    """
    Get orders for the queue display.
    Includes: queued, in_progress, and recently completed (within 30 seconds).

    Args:
        customer: The customer to get orders for
        include_lines: If True, prefetch order lines with product data for display
    """
    cutoff = timezone.now() - timedelta(seconds=30)

    # Get queued and in_progress orders
    active_orders = Order.objects.filter(
        customer=customer,
        status__in=['queued', 'in_progress']
    )

    # Get recently completed orders (for fade-out display)
    recently_completed = Order.objects.filter(
        customer=customer,
        status='completed',
        completed_at__gte=cutoff
    )

    # Combine and order by queue_position, then created_at
    orders = (active_orders | recently_completed).annotate(
        item_count=Count('lines')
    ).order_by('queue_position', 'created_at')

    # Prefetch order lines if needed for display
    if include_lines:
        orders = orders.prefetch_related('lines__product')

    return orders


@login_required
def queue_display(request):
    """
    Tablet/PC view showing the queue with QR codes.
    This is the main display that refreshes via HTMX.
    """
    try:
        customer = request.user.userprofile.customer
    except UserProfile.DoesNotExist:
        return render(request, 'queue/display.html', {'error': 'No customer profile found'})

    orders = get_queue_orders(customer, include_lines=True)

    context = {
        'orders': orders,
        'customer': customer,
    }
    return render(request, 'queue/display.html', context)


@login_required
def queue_display_partial(request):
    """
    HTMX partial view - returns only the order cards for refreshing.
    """
    try:
        customer = request.user.userprofile.customer
    except UserProfile.DoesNotExist:
        return render(request, 'queue/_order_cards.html', {'orders': []})

    orders = get_queue_orders(customer, include_lines=True)

    context = {
        'orders': orders,
    }
    return render(request, 'queue/_order_cards.html', context)


@login_required
def queue_picker(request):
    """
    Mobile/phone view for pickers to see and select orders from the queue.
    """
    try:
        customer = request.user.userprofile.customer
    except UserProfile.DoesNotExist:
        return render(request, 'queue/picker.html', {'error': 'No customer profile found'})

    # Get device for this session
    device_fingerprint = request.session.get('device_fingerprint')
    device = Device.objects.filter(
        user=request.user,
        device_fingerprint=device_fingerprint
    ).first()

    orders = get_queue_orders(customer, include_lines=True)

    context = {
        'orders': orders,
        'customer': customer,
        'device': device,
    }
    return render(request, 'queue/picker.html', context)


@login_required
def queue_picker_partial(request):
    """
    HTMX partial view for picker queue - returns only the order list.
    """
    try:
        customer = request.user.userprofile.customer
    except UserProfile.DoesNotExist:
        return render(request, 'queue/_picker_orders.html', {'orders': []})

    orders = get_queue_orders(customer, include_lines=True)

    context = {
        'orders': orders,
    }
    return render(request, 'queue/_picker_orders.html', context)


@login_required
@require_POST
def queue_claim_order(request, order_id):
    """
    Claim an order from the queue (mobile picker tap-to-select).
    Returns JSON with order data for the picking interface.
    """
    import json

    print(f"[Queue Claim] Starting claim for order_id: {order_id}")

    try:
        customer = request.user.userprofile.customer
        print(f"[Queue Claim] Customer: {customer}")
    except UserProfile.DoesNotExist:
        print("[Queue Claim] ERROR: No customer profile")
        return JsonResponse({'status': 'error', 'message': 'No customer profile'}, status=400)

    # Get device fingerprint from request
    try:
        data = json.loads(request.body) if request.body else {}
        device_fingerprint = data.get('deviceFingerprint', '')
        print(f"[Queue Claim] Device fingerprint from body: {device_fingerprint}")
    except json.JSONDecodeError:
        device_fingerprint = ''
        print("[Queue Claim] No device fingerprint in body")

    device = None
    if device_fingerprint:
        device = Device.objects.filter(device_fingerprint=device_fingerprint).first()
        print(f"[Queue Claim] Device from fingerprint: {device}")

    if not device:
        # Try to get device from session
        session_fingerprint = request.session.get('device_fingerprint')
        print(f"[Queue Claim] Session fingerprint: {session_fingerprint}")
        if session_fingerprint:
            device = Device.objects.filter(device_fingerprint=session_fingerprint).first()
            print(f"[Queue Claim] Device from session: {device}")

    if not device:
        print("[Queue Claim] ERROR: Device not found")
        return JsonResponse({
            'status': 'error',
            'message': 'Device not found. Please log in again.'
        }, status=400)

    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(
                order_id=order_id,
                customer=customer
            )

            if order.status == 'in_progress':
                return JsonResponse({
                    'status': 'error',
                    'message': 'This order is already being picked'
                }, status=409)

            if order.status == 'completed':
                return JsonResponse({
                    'status': 'error',
                    'message': 'This order has already been completed'
                }, status=409)

            if order.status != 'queued':
                return JsonResponse({
                    'status': 'error',
                    'message': 'This order is not available for picking'
                }, status=400)

            # Lock the order
            order.status = 'in_progress'
            order.save(update_fields=['status'])

            # Create PickList for this order
            local_time = timezone.now()
            pick_list, created = PickList.objects.get_or_create(
                picklist_code=order.order_code,
                customer=customer,
                defaults={
                    'device': device,
                    'order': order,
                    'pick_started': True,
                    'updated_at': local_time,
                }
            )

            if not created:
                # Update existing picklist
                pick_list.device = device
                pick_list.updated_at = local_time
                pick_list.pick_started = True
                pick_list.order = order
                pick_list.save()
                # Clear existing product picks
                ProductPick.objects.filter(picklist=pick_list).delete()

            # Create ProductPick entries from order lines
            picklist_products = []
            lines = order.lines.select_related('product').all()
            print(f"[Queue Claim] Order {order.order_code} has {lines.count()} lines")
            for line in lines:
                print(f"[Queue Claim] Line: {line.quantity}x {line.product.code}")
                for _ in range(line.quantity):
                    ProductPick.objects.create(
                        product=line.product,
                        picklist=pick_list,
                        quantity=1,
                    )
                    picklist_products.append(line.product.code)

            print(f"[Queue Claim] Returning picklist_products: {picklist_products}")
            return JsonResponse({
                'status': 'ok',
                'message': 'Order claimed successfully',
                'order_code': order.order_code,
                'picklist': picklist_products,
                'redirect_url': '/'
            })

    except Order.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Order not found'
        }, status=404)


# ============================================
# Queue Management Views (Admin)
# ============================================

def get_customer_for_staff(request):
    """Get customer for staff member (superuser or company admin)."""
    if request.user.is_superuser:
        # For superusers, get from query param or user profile
        customer_id = request.GET.get('customer_id')
        if customer_id:
            from orderpiqrApp.models import Customer
            return Customer.objects.filter(customer_id=customer_id).first()
    try:
        return request.user.userprofile.customer
    except UserProfile.DoesNotExist:
        return None


@company_admin_required
def queue_manage(request):
    """
    Admin view to manage the order queue.
    Shows all orders and allows reordering, adding to queue, removing from queue.
    """
    customer = get_customer_for_staff(request)
    if not customer:
        return render(request, 'queue/manage.html', {'error': 'No customer profile found'})

    # Get all orders for this customer
    all_orders = Order.objects.filter(customer=customer).annotate(
        item_count=Count('lines')
    ).order_by('queue_position', '-created_at')

    # Separate queued/in_progress from others
    queue_orders = all_orders.filter(status__in=['queued', 'in_progress'])
    available_orders = all_orders.filter(status='draft')
    completed_orders = all_orders.filter(status='completed').order_by('-completed_at')[:20]

    context = {
        'customer': customer,
        'queue_orders': queue_orders,
        'available_orders': available_orders,
        'completed_orders': completed_orders,
    }
    return render(request, 'queue/manage.html', context)


@company_admin_required
def queue_manage_partial(request):
    """HTMX partial for queue management - refreshes queue list."""
    customer = get_customer_for_staff(request)
    if not customer:
        return render(request, 'queue/_manage_queue_list.html', {'queue_orders': []})

    queue_orders = Order.objects.filter(
        customer=customer,
        status__in=['queued', 'in_progress']
    ).annotate(item_count=Count('lines')).order_by('queue_position', 'created_at')

    return render(request, 'queue/_manage_queue_list.html', {'queue_orders': queue_orders})


@company_admin_required
@require_POST
def queue_add_order(request, order_id):
    """Add an order to the queue."""
    customer = get_customer_for_staff(request)
    if not customer:
        return JsonResponse({'status': 'error', 'message': 'No customer'}, status=400)

    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(
                order_id=order_id,
                customer=customer
            )

            if order.status != 'draft':
                return JsonResponse({
                    'status': 'error',
                    'message': 'Only draft orders can be added to queue'
                }, status=400)

            # Get next queue position
            max_pos = Order.objects.filter(
                customer=customer,
                status__in=['queued', 'in_progress']
            ).aggregate(max_pos=Max('queue_position'))['max_pos']

            order.queue_position = (max_pos or 0) + 1
            order.status = 'queued'
            order.save(update_fields=['queue_position', 'status'])

            return JsonResponse({
                'status': 'ok',
                'message': 'Order added to queue'
            })

    except Order.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Order not found'}, status=404)


@company_admin_required
@require_POST
def queue_remove_order(request, order_id):
    """Remove an order from the queue (back to draft)."""
    customer = get_customer_for_staff(request)
    if not customer:
        return JsonResponse({'status': 'error', 'message': 'No customer'}, status=400)

    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(
                order_id=order_id,
                customer=customer
            )

            if order.status not in ['queued', 'in_progress']:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Order is not in queue'
                }, status=400)

            order.queue_position = None
            order.status = 'draft'
            order.save(update_fields=['queue_position', 'status'])

            return JsonResponse({
                'status': 'ok',
                'message': 'Order removed from queue'
            })

    except Order.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Order not found'}, status=404)


@company_admin_required
@require_POST
def queue_reorder(request):
    """Reorder the queue based on provided order IDs."""
    import json

    customer = get_customer_for_staff(request)
    if not customer:
        return JsonResponse({'status': 'error', 'message': 'No customer'}, status=400)

    try:
        data = json.loads(request.body)
        order_ids = data.get('order_ids', [])
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    if not order_ids:
        return JsonResponse({'status': 'error', 'message': 'No order IDs provided'}, status=400)

    try:
        with transaction.atomic():
            for position, order_id in enumerate(order_ids, start=1):
                Order.objects.filter(
                    order_id=order_id,
                    customer=customer,
                    status__in=['queued', 'in_progress']
                ).update(queue_position=position)

            return JsonResponse({
                'status': 'ok',
                'message': 'Queue reordered'
            })

    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error reordering: {str(e)}'
        }, status=500)


@company_admin_required
@require_POST
def queue_move_order(request, order_id, direction):
    """Move an order up or down in the queue."""
    customer = get_customer_for_staff(request)
    if not customer:
        return JsonResponse({'status': 'error', 'message': 'No customer'}, status=400)

    if direction not in ['up', 'down']:
        return JsonResponse({'status': 'error', 'message': 'Invalid direction'}, status=400)

    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(
                order_id=order_id,
                customer=customer,
                status__in=['queued', 'in_progress']
            )

            current_pos = order.queue_position or 0

            # Find the adjacent order
            if direction == 'up':
                adjacent = Order.objects.filter(
                    customer=customer,
                    status__in=['queued', 'in_progress'],
                    queue_position__lt=current_pos
                ).order_by('-queue_position').first()
            else:
                adjacent = Order.objects.filter(
                    customer=customer,
                    status__in=['queued', 'in_progress'],
                    queue_position__gt=current_pos
                ).order_by('queue_position').first()

            if adjacent:
                # Swap positions
                order.queue_position, adjacent.queue_position = adjacent.queue_position, order.queue_position
                order.save(update_fields=['queue_position'])
                adjacent.save(update_fields=['queue_position'])

            return JsonResponse({
                'status': 'ok',
                'message': f'Order moved {direction}'
            })

    except Order.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Order not found'}, status=404)
