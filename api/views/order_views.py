from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from api.serializers import OrderSerializer, OrderDetailSerializer, OrderCreateSerializer
from orderpiqrApp.models import Order
from rest_framework import filters
from django.db.models import Count, Sum
from django.utils import timezone
from datetime import timedelta
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiResponse, OpenApiParameter


@extend_schema_view(
    list=extend_schema(
        summary="List all orders",
        description="""
        Retrieve a list of all orders for the authenticated user's customer.

        **Search:** Use the `?search=` query parameter to filter orders by order_code.

        **Filtering:**
        - `?status=draft` - Filter by status (draft, queued, in_progress, completed, cancelled)
        - `?created_at__gte=2025-01-01` - Orders created on or after date
        - `?created_at__lte=2025-01-31` - Orders created on or before date

        **Ordering:**
        - `?ordering=created_at` - Sort by creation date (ascending)
        - `?ordering=-created_at` - Sort by creation date (descending)
        - `?ordering=queue_position` - Sort by queue position
        - `?ordering=status` - Sort by status

        **Example:** `GET /api/orders/?status=queued&ordering=queue_position`
        """
    ),
    retrieve=extend_schema(
        summary="Get order details",
        description="Retrieve details of a specific order by its ID, including all order lines with product information."
    ),
    create=extend_schema(
        summary="Create a new order",
        description="""
        Create a new order with its order lines.

        The order will be created with status `draft`. Use the Queue API endpoints
        to add the order to the picking queue when ready.

        **Request body should include:**
        - `order_code`: A unique human-readable identifier for the order
        - `notes`: Optional special instructions for the picker
        - `lines`: Array of order lines, each with a product ID and quantity

        The `customer` field is automatically set based on the authenticated user's profile.
        """
    ),
    update=extend_schema(
        summary="Update an order",
        description="""
        Update all fields of an existing order.

        **Note:** Updating an order will replace all order lines if the `lines` field is provided.
        Orders with status `in_progress` or `completed` should not be modified.
        """
    ),
    partial_update=extend_schema(
        summary="Partially update an order",
        description="Update specific fields of an existing order without replacing all order lines."
    ),
    destroy=extend_schema(
        summary="Delete an order",
        description="**Not allowed.** Orders cannot be deleted via the API to maintain audit trails. Use the cancel action instead."
    ),
)
@extend_schema(
    tags=["orders"],
    examples=[
        OpenApiExample(
            name="Order Example",
            description="An example order payload. order_code serves as a human-friendly identifier, while lines lists "
                        "the products in the order. Each product value represents the product's ID.",
            value={
                "order_code": "ORDER-20250806-001",
                "notes": "Handle with care",
                "lines": [
                    {"quantity": 2, "product": 12345},
                    {"quantity": 5, "product": 67890}
                ]
            },
            request_only=True
        )
    ]
)
class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.none()  # Required for drf-spectacular
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['order_code', 'notes']
    ordering_fields = ['created_at', 'order_code', 'status', 'queue_position', 'completed_at']
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = Order.objects.filter(
            customer=self.request.user.userprofile.customer
        ).prefetch_related('lines__product')

        # Manual filtering
        order_status = self.request.query_params.get('status')
        if order_status:
            queryset = queryset.filter(status=order_status)

        created_after = self.request.query_params.get('created_at__gte')
        if created_after:
            queryset = queryset.filter(created_at__gte=created_after)

        created_before = self.request.query_params.get('created_at__lte')
        if created_before:
            queryset = queryset.filter(created_at__lte=created_before)

        in_queue = self.request.query_params.get('in_queue')
        if in_queue is not None:
            if in_queue.lower() == 'true':
                queryset = queryset.filter(queue_position__isnull=False)
            else:
                queryset = queryset.filter(queue_position__isnull=True)

        return queryset

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return OrderDetailSerializer
        if self.action == 'create':
            return OrderCreateSerializer
        return OrderSerializer

    def perform_create(self, serializer):
        serializer.save(customer=self.request.user.userprofile.customer)

    def destroy(self, request, *args, **kwargs):
        return Response({'detail': 'Delete not allowed. Use the cancel action instead.'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @extend_schema(
        summary="Cancel an order",
        description="""
        Cancel an order. Only orders with status `draft` or `queued` can be cancelled.
        Orders that are `in_progress` must be removed from the queue first.
        """,
        responses={
            200: OpenApiResponse(
                description="Order cancelled",
                examples=[
                    OpenApiExample(
                        name="Success Response",
                        value={"status": "ok", "message": "Order cancelled", "order_id": 1}
                    )
                ]
            ),
            400: OpenApiResponse(description="Order cannot be cancelled in its current state")
        }
    )
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel an order."""
        order = self.get_object()

        if order.status not in ['draft', 'queued']:
            return Response(
                {'detail': f'Cannot cancel order with status "{order.status}". Only draft or queued orders can be cancelled.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        order.status = 'cancelled'
        order.queue_position = None
        order.save(update_fields=['status', 'queue_position'])

        return Response({
            'status': 'ok',
            'message': 'Order cancelled',
            'order_id': order.order_id
        })

    @extend_schema(
        summary="Get order statistics",
        description="Get statistics about orders including counts by status and recent activity.",
        responses={
            200: OpenApiResponse(
                description="Order statistics",
                examples=[
                    OpenApiExample(
                        name="Statistics Response",
                        value={
                            "total_orders": 250,
                            "by_status": {
                                "draft": 45,
                                "queued": 12,
                                "in_progress": 3,
                                "completed": 180,
                                "cancelled": 10
                            },
                            "today": {
                                "created": 8,
                                "completed": 15
                            },
                            "this_week": {
                                "created": 42,
                                "completed": 67
                            },
                            "avg_items_per_order": 4.5
                        }
                    )
                ]
            )
        }
    )
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get order statistics for the customer."""
        customer = request.user.userprofile.customer
        orders = Order.objects.filter(customer=customer)

        today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = today - timedelta(days=7)

        # Count by status
        status_counts = {}
        for status_choice in Order.STATUS_CHOICES:
            status_counts[status_choice[0]] = orders.filter(status=status_choice[0]).count()

        # Average items per order
        avg_items = orders.annotate(
            item_count=Sum('lines__quantity')
        ).aggregate(avg=Sum('lines__quantity'))

        total_orders = orders.count()
        total_items = avg_items['avg'] or 0
        avg_per_order = round(total_items / total_orders, 1) if total_orders > 0 else 0

        return Response({
            'total_orders': total_orders,
            'by_status': status_counts,
            'today': {
                'created': orders.filter(created_at__gte=today).count(),
                'completed': orders.filter(completed_at__gte=today).count(),
            },
            'this_week': {
                'created': orders.filter(created_at__gte=week_ago).count(),
                'completed': orders.filter(completed_at__gte=week_ago).count(),
            },
            'avg_items_per_order': avg_per_order
        })

    @extend_schema(
        summary="Lookup order by code",
        description="Find an order by its exact order code.",
        parameters=[
            OpenApiParameter(
                name='code',
                description='The exact order code to look up',
                required=True,
                type=str
            )
        ],
        responses={
            200: OrderDetailSerializer,
            404: OpenApiResponse(description="Order not found")
        }
    )
    @action(detail=False, methods=['get'])
    def lookup(self, request):
        """Look up an order by its exact code."""
        code = request.query_params.get('code')
        if not code:
            return Response(
                {'detail': 'Code parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            order = Order.objects.get(
                order_code=code,
                customer=request.user.userprofile.customer
            )
            serializer = OrderDetailSerializer(order)
            return Response(serializer.data)
        except Order.DoesNotExist:
            return Response(
                {'detail': 'Order not found'},
                status=status.HTTP_404_NOT_FOUND
            )

    @extend_schema(
        summary="Bulk create orders",
        description="Create multiple orders at once. Useful for importing orders from external systems.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "orders": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "order_code": {"type": "string"},
                                "notes": {"type": "string"},
                                "lines": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "product": {"type": "integer"},
                                            "quantity": {"type": "integer"}
                                        }
                                    }
                                }
                            },
                            "required": ["order_code", "lines"]
                        }
                    }
                },
                "required": ["orders"]
            }
        },
        responses={
            201: OpenApiResponse(
                description="Orders created",
                examples=[
                    OpenApiExample(
                        name="Success Response",
                        value={
                            "created_count": 5,
                            "orders": [
                                {"order_id": 1, "order_code": "ORD-001"},
                                {"order_id": 2, "order_code": "ORD-002"}
                            ]
                        }
                    )
                ]
            ),
            400: OpenApiResponse(description="Validation error")
        }
    )
    @action(detail=False, methods=['post'])
    def bulk_create(self, request):
        """Bulk create multiple orders."""
        orders_data = request.data.get('orders', [])
        customer = request.user.userprofile.customer

        if not orders_data:
            return Response(
                {'detail': 'No orders provided'},
                status=status.HTTP_400_BAD_REQUEST
            )

        created_orders = []
        errors = []

        for i, order_data in enumerate(orders_data):
            serializer = OrderCreateSerializer(data=order_data)
            if serializer.is_valid():
                order = serializer.save(customer=customer)
                created_orders.append({
                    'order_id': order.order_id,
                    'order_code': order.order_code
                })
            else:
                errors.append({
                    'index': i,
                    'order_code': order_data.get('order_code'),
                    'errors': serializer.errors
                })

        response_data = {
            'created_count': len(created_orders),
            'orders': created_orders
        }

        if errors:
            response_data['errors'] = errors
            return Response(response_data, status=status.HTTP_207_MULTI_STATUS)

        return Response(response_data, status=status.HTTP_201_CREATED)
