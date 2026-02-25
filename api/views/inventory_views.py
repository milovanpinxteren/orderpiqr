from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiParameter

from api.serializers import InventoryLogSerializer, InventoryModifySerializer
from orderpiqrApp.models import InventoryLog, Product
from orderpiqrApp.utils.inventory import is_inventory_enabled, modify_inventory


@extend_schema_view(
    list=extend_schema(
        summary="List inventory logs",
        description="""
        Retrieve a list of all inventory changes for the authenticated user's customer.

        **Filtering:**
        - `?product=123` - Filter by product ID
        - `?reason=stock_count` - Filter by reason code
        - `?change_type=set` - Filter by change type (set or adjust)

        **Ordering:**
        - `?ordering=-created_at` - Sort by date descending (default)
        - `?ordering=created_at` - Sort by date ascending
        - `?ordering=product__code` - Sort by product code

        **Note:** Only available when inventory management is enabled for the customer.
        """
    ),
    retrieve=extend_schema(
        summary="Get inventory log details",
        description="Retrieve details of a specific inventory log entry."
    ),
)
@extend_schema(tags=["inventory"])
class InventoryLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing inventory log entries.

    Inventory logs are read-only - modifications should be made
    through the modify endpoint.
    """
    queryset = InventoryLog.objects.none()
    serializer_class = InventoryLogSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.OrderingFilter, filters.SearchFilter]
    ordering_fields = ['created_at', 'product__code']
    ordering = ['-created_at']
    search_fields = ['product__code', 'product__description', 'notes']

    def get_queryset(self):
        """Filter logs to the current user's customer."""
        try:
            customer = self.request.user.userprofile.customer
        except AttributeError:
            return InventoryLog.objects.none()

        if not is_inventory_enabled(customer):
            return InventoryLog.objects.none()

        queryset = InventoryLog.objects.filter(
            product__customer=customer
        ).select_related('product', 'user', 'device')

        # Manual filtering by query params
        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)

        reason = self.request.query_params.get('reason')
        if reason:
            queryset = queryset.filter(reason=reason)

        change_type = self.request.query_params.get('change_type')
        if change_type:
            queryset = queryset.filter(change_type=change_type)

        return queryset

    @extend_schema(
        summary="Modify product inventory",
        description="""
        Create a new inventory modification.

        **Change Types:**
        - `set`: Set the inventory to an absolute value (e.g., after a stock count)
        - `adjust`: Add or subtract from current inventory (e.g., received goods, damaged items)

        **Reason Codes:**
        - `stock_count`: Physical stock count
        - `received`: Goods received
        - `damaged`: Damaged items
        - `returned`: Customer returns
        - `correction`: Manual correction
        - `other`: Other reason

        **Example - Set inventory to 100:**
        ```json
        {
            "product_id": 123,
            "change_type": "set",
            "value": 100,
            "reason": "stock_count",
            "notes": "Monthly inventory count"
        }
        ```

        **Example - Add 10 items:**
        ```json
        {
            "product_id": 123,
            "change_type": "adjust",
            "value": 10,
            "reason": "received",
            "notes": "Shipment #12345"
        }
        ```

        **Example - Remove 5 items:**
        ```json
        {
            "product_id": 123,
            "change_type": "adjust",
            "value": -5,
            "reason": "damaged"
        }
        ```
        """,
        request=InventoryModifySerializer,
        responses={
            200: InventoryLogSerializer,
            400: OpenApiExample(
                name="Validation error",
                value={"detail": "Invalid request"}
            ),
            403: OpenApiExample(
                name="Feature disabled",
                value={"detail": "Inventory management is not enabled"}
            ),
            404: OpenApiExample(
                name="Product not found",
                value={"detail": "Product not found"}
            ),
        }
    )
    @action(detail=False, methods=['post'])
    def modify(self, request):
        """Modify inventory for a product."""
        try:
            customer = request.user.userprofile.customer
        except AttributeError:
            return Response(
                {'detail': 'No customer found'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not is_inventory_enabled(customer):
            return Response(
                {'detail': 'Inventory management is not enabled'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = InventoryModifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            product = Product.objects.get(
                product_id=serializer.validated_data['product_id'],
                customer=customer
            )
        except Product.DoesNotExist:
            return Response(
                {'detail': 'Product not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        log = modify_inventory(
            product=product,
            user=request.user,
            change_type=serializer.validated_data['change_type'],
            reason=serializer.validated_data['reason'],
            value=serializer.validated_data['value'],
            notes=serializer.validated_data.get('notes', '')
        )

        return Response(InventoryLogSerializer(log).data)

    @extend_schema(
        summary="Get product inventory",
        description="Get current inventory quantity for a specific product.",
        parameters=[
            OpenApiParameter(
                name='product_id',
                description='Product ID',
                required=True,
                type=int
            )
        ],
        responses={
            200: OpenApiExample(
                name="Product inventory",
                value={
                    "product_id": 123,
                    "code": "SKU-001",
                    "description": "Example Product",
                    "inventory_quantity": 50
                }
            ),
        }
    )
    @action(detail=False, methods=['get'])
    def product(self, request):
        """Get inventory for a specific product."""
        try:
            customer = request.user.userprofile.customer
        except AttributeError:
            return Response(
                {'detail': 'No customer found'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not is_inventory_enabled(customer):
            return Response(
                {'detail': 'Inventory management is not enabled'},
                status=status.HTTP_403_FORBIDDEN
            )

        product_id = request.query_params.get('product_id')
        if not product_id:
            return Response(
                {'detail': 'product_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            product = Product.objects.get(
                product_id=product_id,
                customer=customer
            )
            return Response({
                'product_id': product.product_id,
                'code': product.code,
                'description': product.description,
                'inventory_quantity': product.inventory_quantity,
            })
        except Product.DoesNotExist:
            return Response(
                {'detail': 'Product not found'},
                status=status.HTTP_404_NOT_FOUND
            )
