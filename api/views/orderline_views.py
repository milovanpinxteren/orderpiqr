from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from api.serializers import OrderLineSerializer, OrderLineDetailSerializer
from orderpiqrApp.models import OrderLine
from rest_framework import filters
from django.db.models import Sum

from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiResponse


@extend_schema_view(
    list=extend_schema(
        summary="List all order lines",
        description="""
        Retrieve a list of all order lines for orders belonging to the authenticated user's customer.

        **Search:** Use the `?search=` query parameter to filter by product description or code.

        **Filtering:**
        - `?order=42` - Filter by order ID
        - `?product=123` - Filter by product ID
        - `?quantity__gte=5` - Filter by minimum quantity

        **Ordering:**
        - `?ordering=quantity` - Sort by quantity
        - `?ordering=product__location` - Sort by product location

        Order lines represent individual items within an order.
        """
    ),
    retrieve=extend_schema(
        summary="Get order line details",
        description="Retrieve details of a specific order line with full product information."
    ),
    create=extend_schema(
        summary="Create an order line",
        description="""
        Create a new order line.

        **Note:** Order lines are typically created as part of an order via `POST /api/orders/`.
        Use this endpoint only to add additional lines to an existing order.

        **Important:** The order must have status 'draft' or 'queued' to add lines.
        """
    ),
    update=extend_schema(
        summary="Update an order line",
        description="Update order line details, such as the quantity."
    ),
    partial_update=extend_schema(
        summary="Partially update an order line",
        description="Update specific fields of an order line."
    ),
    destroy=extend_schema(
        summary="Delete an order line",
        description="**Not allowed.** Order lines cannot be deleted to maintain order integrity."
    ),
)
@extend_schema(
    tags=["orderlines"],
    examples=[
        OpenApiExample(
            name="OrderLine Example",
            description="An order line specifying a product and quantity",
            value={
                "order": 42,
                "product": 123,
                "quantity": 5
            },
            request_only=True
        )
    ]
)
class OrderLineViewSet(viewsets.ModelViewSet):
    queryset = OrderLine.objects.none()  # Required for drf-spectacular
    serializer_class = OrderLineSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['product__description', 'product__code']
    ordering_fields = ['quantity', 'product__code', 'product__location', 'order__created_at']
    ordering = ['order', 'product__location']

    def get_queryset(self):
        queryset = OrderLine.objects.filter(
            order__customer=self.request.user.userprofile.customer
        ).select_related('product', 'order')

        # Manual filtering
        order_id = self.request.query_params.get('order')
        if order_id:
            queryset = queryset.filter(order_id=order_id)

        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)

        min_quantity = self.request.query_params.get('quantity__gte')
        if min_quantity:
            queryset = queryset.filter(quantity__gte=int(min_quantity))

        return queryset

    def get_serializer_class(self):
        if self.action in ['retrieve', 'list']:
            return OrderLineDetailSerializer
        return OrderLineSerializer

    def create(self, request, *args, **kwargs):
        """Create an order line with validation."""
        order_id = request.data.get('order')

        # Validate order status
        from orderpiqrApp.models import Order
        try:
            order = Order.objects.get(
                order_id=order_id,
                customer=request.user.userprofile.customer
            )
            if order.status not in ['draft', 'queued']:
                return Response(
                    {'detail': f'Cannot add lines to order with status "{order.status}"'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Order.DoesNotExist:
            return Response(
                {'detail': 'Order not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        return super().create(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        return Response({'detail': 'Delete not allowed.'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @extend_schema(
        summary="Get order lines by order",
        description="Get all order lines for a specific order with product details.",
        responses={
            200: OrderLineDetailSerializer(many=True)
        }
    )
    @action(detail=False, methods=['get'], url_path='by-order/(?P<order_id>[^/.]+)')
    def by_order(self, request, order_id=None):
        """Get all order lines for a specific order."""
        lines = OrderLine.objects.filter(
            order_id=order_id,
            order__customer=request.user.userprofile.customer
        ).select_related('product').order_by('product__location')

        serializer = OrderLineDetailSerializer(lines, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Get order lines summary",
        description="Get summary of order lines grouped by product.",
        responses={
            200: OpenApiResponse(
                description="Order lines summary",
                examples=[
                    OpenApiExample(
                        name="Summary Response",
                        value={
                            "total_lines": 150,
                            "total_quantity": 450,
                            "unique_products": 85,
                            "top_products": [
                                {"product_id": 1, "code": "PROD-001", "total_quantity": 25},
                                {"product_id": 2, "code": "PROD-002", "total_quantity": 20}
                            ]
                        }
                    )
                ]
            )
        }
    )
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get summary of order lines."""
        customer = request.user.userprofile.customer
        lines = OrderLine.objects.filter(order__customer=customer)

        # Top products by quantity
        top_products = lines.values(
            'product__product_id', 'product__code', 'product__description'
        ).annotate(
            total_quantity=Sum('quantity')
        ).order_by('-total_quantity')[:10]

        return Response({
            'total_lines': lines.count(),
            'total_quantity': lines.aggregate(total=Sum('quantity'))['total'] or 0,
            'unique_products': lines.values('product').distinct().count(),
            'top_products': [
                {
                    'product_id': p['product__product_id'],
                    'code': p['product__code'],
                    'description': p['product__description'],
                    'total_quantity': p['total_quantity']
                }
                for p in top_products
            ]
        })
