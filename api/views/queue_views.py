from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone
from datetime import timedelta
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter, OpenApiResponse

from orderpiqrApp.models import Order, Device, UserProfile, PickList, ProductPick


def get_customer_from_request(request):
    """Get customer from authenticated user's profile."""
    try:
        return request.user.userprofile.customer
    except UserProfile.DoesNotExist:
        return None


# =============================================================================
# Queue Display Endpoints
# =============================================================================

@extend_schema(
    tags=["queue"],
    summary="Get queue orders",
    description="""
    Retrieve all orders currently in the queue for the authenticated user's customer.

    Returns orders with status 'queued' or 'in_progress', plus any orders completed
    within the last 30 seconds (for UI fade-out effects).

    Orders are sorted by queue_position (ascending), then by created_at.
    Each order includes an item_count showing the number of order lines.
    """,
    responses={
        200: OpenApiResponse(
            description="List of queue orders",
            examples=[
                OpenApiExample(
                    name="Queue Orders Response",
                    value={
                        "count": 3,
                        "orders": [
                            {
                                "order_id": 1,
                                "order_code": "ORDER-2025-001",
                                "status": "queued",
                                "queue_position": 1,
                                "created_at": "2025-01-28T10:00:00Z",
                                "notes": "Priority order",
                                "item_count": 5
                            },
                            {
                                "order_id": 2,
                                "order_code": "ORDER-2025-002",
                                "status": "in_progress",
                                "queue_position": 2,
                                "created_at": "2025-01-28T10:15:00Z",
                                "notes": None,
                                "item_count": 3
                            }
                        ]
                    }
                )
            ]
        ),
        400: OpenApiResponse(description="No customer profile found")
    }
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def queue_list(request):
    """
    Get all orders in the queue (queued, in_progress, recently completed).
    """
    customer = get_customer_from_request(request)
    if not customer:
        return Response(
            {'detail': 'No customer profile found'},
            status=status.HTTP_400_BAD_REQUEST
        )

    cutoff = timezone.now() - timedelta(seconds=30)

    # Get active orders
    active_orders = Order.objects.filter(
        customer=customer,
        status__in=['queued', 'in_progress']
    )

    # Get recently completed orders
    recently_completed = Order.objects.filter(
        customer=customer,
        status='completed',
        completed_at__gte=cutoff
    )

    # Combine and annotate
    orders = (active_orders | recently_completed).annotate(
        item_count=Count('lines')
    ).order_by('queue_position', 'created_at')

    # Serialize
    orders_data = []
    for order in orders:
        orders_data.append({
            'order_id': order.order_id,
            'order_code': order.order_code,
            'status': order.status,
            'queue_position': order.queue_position,
            'created_at': order.created_at.isoformat(),
            'completed_at': order.completed_at.isoformat() if order.completed_at else None,
            'notes': order.notes,
            'item_count': order.item_count,
        })

    return Response({
        'count': len(orders_data),
        'orders': orders_data
    })


@extend_schema(
    tags=["queue"],
    summary="Get queue statistics",
    description="""
    Get statistics about the current queue state.

    Returns counts for each order status and the total number of items
    (order lines) waiting to be picked.
    """,
    responses={
        200: OpenApiResponse(
            description="Queue statistics",
            examples=[
                OpenApiExample(
                    name="Queue Stats Response",
                    value={
                        "queued_count": 5,
                        "in_progress_count": 1,
                        "draft_count": 12,
                        "completed_today_count": 8,
                        "total_items_in_queue": 42
                    }
                )
            ]
        )
    }
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def queue_stats(request):
    """
    Get queue statistics for the customer.
    """
    customer = get_customer_from_request(request)
    if not customer:
        return Response(
            {'detail': 'No customer profile found'},
            status=status.HTTP_400_BAD_REQUEST
        )

    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    queued_orders = Order.objects.filter(customer=customer, status='queued')
    in_progress_orders = Order.objects.filter(customer=customer, status='in_progress')

    # Count total items in queue
    total_items = queued_orders.annotate(
        item_count=Count('lines')
    ).aggregate(total=Count('lines'))['total'] or 0

    return Response({
        'queued_count': queued_orders.count(),
        'in_progress_count': in_progress_orders.count(),
        'draft_count': Order.objects.filter(customer=customer, status='draft').count(),
        'completed_today_count': Order.objects.filter(
            customer=customer,
            status='completed',
            completed_at__gte=today_start
        ).count(),
        'total_items_in_queue': total_items
    })


# =============================================================================
# Queue Management Endpoints (Admin)
# =============================================================================

@extend_schema(
    tags=["queue"],
    summary="Add order to queue",
    description="""
    Add a draft order to the picking queue.

    The order will be assigned the next available queue position (at the end of the queue)
    and its status will change from 'draft' to 'queued'.

    **Requirements:**
    - Order must have status 'draft'
    - Order must belong to the authenticated user's customer
    """,
    responses={
        200: OpenApiResponse(
            description="Order added to queue",
            examples=[
                OpenApiExample(
                    name="Success Response",
                    value={
                        "status": "ok",
                        "message": "Order added to queue",
                        "order_id": 1,
                        "queue_position": 5
                    }
                )
            ]
        ),
        400: OpenApiResponse(description="Order is not in draft status"),
        404: OpenApiResponse(description="Order not found")
    }
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def queue_add_order(request, order_id):
    """
    Add a draft order to the queue.
    """
    customer = get_customer_from_request(request)
    if not customer:
        return Response(
            {'detail': 'No customer profile found'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(
                order_id=order_id,
                customer=customer
            )

            if order.status != 'draft':
                return Response(
                    {'detail': 'Only draft orders can be added to queue'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Get next queue position
            max_pos = Order.objects.filter(
                customer=customer,
                status__in=['queued', 'in_progress']
            ).aggregate(max_pos=Max('queue_position'))['max_pos']

            order.queue_position = (max_pos or 0) + 1
            order.status = 'queued'
            order.save(update_fields=['queue_position', 'status'])

            return Response({
                'status': 'ok',
                'message': 'Order added to queue',
                'order_id': order.order_id,
                'queue_position': order.queue_position
            })

    except Order.DoesNotExist:
        return Response(
            {'detail': 'Order not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@extend_schema(
    tags=["queue"],
    summary="Remove order from queue",
    description="""
    Remove an order from the picking queue.

    The order's status will change back to 'draft' and its queue_position will be cleared.

    **Requirements:**
    - Order must have status 'queued' or 'in_progress'
    - Order must belong to the authenticated user's customer
    """,
    responses={
        200: OpenApiResponse(
            description="Order removed from queue",
            examples=[
                OpenApiExample(
                    name="Success Response",
                    value={
                        "status": "ok",
                        "message": "Order removed from queue",
                        "order_id": 1
                    }
                )
            ]
        ),
        400: OpenApiResponse(description="Order is not in queue"),
        404: OpenApiResponse(description="Order not found")
    }
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def queue_remove_order(request, order_id):
    """
    Remove an order from the queue (back to draft).
    """
    customer = get_customer_from_request(request)
    if not customer:
        return Response(
            {'detail': 'No customer profile found'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(
                order_id=order_id,
                customer=customer
            )

            if order.status not in ['queued', 'in_progress']:
                return Response(
                    {'detail': 'Order is not in queue'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            order.queue_position = None
            order.status = 'draft'
            order.save(update_fields=['queue_position', 'status'])

            return Response({
                'status': 'ok',
                'message': 'Order removed from queue',
                'order_id': order.order_id
            })

    except Order.DoesNotExist:
        return Response(
            {'detail': 'Order not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@extend_schema(
    tags=["queue"],
    summary="Claim order for picking",
    description="""
    Claim an order from the queue to start picking.

    This transitions the order from 'queued' to 'in_progress' and creates a PickList
    with ProductPick entries for each order line.

    **Requirements:**
    - Order must have status 'queued'
    - A valid device fingerprint must be provided in the request body
    - Order must belong to the authenticated user's customer

    **Request Body:**
    ```json
    {
        "deviceFingerprint": "abc123..."
    }
    ```
    """,
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "deviceFingerprint": {
                    "type": "string",
                    "description": "The device fingerprint from the picking device"
                }
            },
            "required": ["deviceFingerprint"]
        }
    },
    responses={
        200: OpenApiResponse(
            description="Order claimed successfully",
            examples=[
                OpenApiExample(
                    name="Success Response",
                    value={
                        "status": "ok",
                        "message": "Order claimed successfully",
                        "order_code": "ORDER-2025-001",
                        "picklist": ["PROD001", "PROD001", "PROD002"],
                        "redirect_url": "/"
                    }
                )
            ]
        ),
        400: OpenApiResponse(description="Device not found or order not available"),
        404: OpenApiResponse(description="Order not found"),
        409: OpenApiResponse(description="Order already being picked or completed")
    }
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def queue_claim_order(request, order_id):
    """
    Claim an order from the queue (start picking).
    """
    customer = get_customer_from_request(request)
    if not customer:
        return Response(
            {'detail': 'No customer profile found'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Get device fingerprint from request
    device_fingerprint = request.data.get('deviceFingerprint', '')

    device = None
    if device_fingerprint:
        device = Device.objects.filter(device_fingerprint=device_fingerprint).first()

    if not device:
        return Response(
            {'detail': 'Device not found. Please register your device first.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(
                order_id=order_id,
                customer=customer
            )

            if order.status == 'in_progress':
                return Response(
                    {'detail': 'This order is already being picked'},
                    status=status.HTTP_409_CONFLICT
                )

            if order.status == 'completed':
                return Response(
                    {'detail': 'This order has already been completed'},
                    status=status.HTTP_409_CONFLICT
                )

            if order.status != 'queued':
                return Response(
                    {'detail': 'This order is not available for picking'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Update order status
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
            for line in lines:
                for _ in range(line.quantity):
                    ProductPick.objects.create(
                        product=line.product,
                        picklist=pick_list,
                        quantity=1,
                    )
                    picklist_products.append(line.product.code)

            return Response({
                'status': 'ok',
                'message': 'Order claimed successfully',
                'order_code': order.order_code,
                'picklist': picklist_products,
                'redirect_url': '/'
            })

    except Order.DoesNotExist:
        return Response(
            {'detail': 'Order not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@extend_schema(
    tags=["queue"],
    summary="Reorder queue",
    description="""
    Bulk reorder the queue by providing order IDs in the desired sequence.

    The first order in the list will get queue_position 1, the second gets 2, etc.
    Only orders with status 'queued' or 'in_progress' will be updated.

    **Request Body:**
    ```json
    {
        "order_ids": [5, 3, 1, 2, 4]
    }
    ```
    """,
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "order_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of order IDs in desired queue order"
                }
            },
            "required": ["order_ids"]
        }
    },
    responses={
        200: OpenApiResponse(
            description="Queue reordered successfully",
            examples=[
                OpenApiExample(
                    name="Success Response",
                    value={
                        "status": "ok",
                        "message": "Queue reordered"
                    }
                )
            ]
        ),
        400: OpenApiResponse(description="Invalid request or no order IDs provided")
    }
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def queue_reorder(request):
    """
    Reorder the queue based on provided order IDs.
    """
    customer = get_customer_from_request(request)
    if not customer:
        return Response(
            {'detail': 'No customer profile found'},
            status=status.HTTP_400_BAD_REQUEST
        )

    order_ids = request.data.get('order_ids', [])

    if not order_ids:
        return Response(
            {'detail': 'No order IDs provided'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        with transaction.atomic():
            for position, order_id in enumerate(order_ids, start=1):
                Order.objects.filter(
                    order_id=order_id,
                    customer=customer,
                    status__in=['queued', 'in_progress']
                ).update(queue_position=position)

            return Response({
                'status': 'ok',
                'message': 'Queue reordered'
            })

    except Exception as e:
        return Response(
            {'detail': f'Error reordering: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    tags=["queue"],
    summary="Move order in queue",
    description="""
    Move a single order up or down one position in the queue.

    This swaps the queue_position of the target order with its adjacent neighbor.

    **Path Parameters:**
    - `order_id`: The ID of the order to move
    - `direction`: Either 'up' (towards position 1) or 'down' (towards higher positions)
    """,
    parameters=[
        OpenApiParameter(
            name="direction",
            description="Direction to move: 'up' or 'down'",
            required=True,
            type=str,
            enum=['up', 'down']
        )
    ],
    responses={
        200: OpenApiResponse(
            description="Order moved successfully",
            examples=[
                OpenApiExample(
                    name="Success Response",
                    value={
                        "status": "ok",
                        "message": "Order moved up",
                        "new_position": 2
                    }
                )
            ]
        ),
        400: OpenApiResponse(description="Invalid direction"),
        404: OpenApiResponse(description="Order not found")
    }
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def queue_move_order(request, order_id, direction):
    """
    Move an order up or down in the queue.
    """
    customer = get_customer_from_request(request)
    if not customer:
        return Response(
            {'detail': 'No customer profile found'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if direction not in ['up', 'down']:
        return Response(
            {'detail': 'Invalid direction. Use "up" or "down".'},
            status=status.HTTP_400_BAD_REQUEST
        )

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

            return Response({
                'status': 'ok',
                'message': f'Order moved {direction}',
                'new_position': order.queue_position
            })

    except Order.DoesNotExist:
        return Response(
            {'detail': 'Order not found or not in queue'},
            status=status.HTTP_404_NOT_FOUND
        )
