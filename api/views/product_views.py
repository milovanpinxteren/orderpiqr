from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from api.serializers import ProductSerializer, ProductDetailSerializer
from orderpiqrApp.models import Product, OrderLine
from rest_framework import filters
from django.db.models import Count

from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiParameter, OpenApiResponse


@extend_schema_view(
    list=extend_schema(
        summary="List all products",
        description="""
        Retrieve a list of all products for the authenticated user's customer.

        **Search:** Use the `?search=` query parameter to filter products by code or description.

        **Filtering:**
        - `?active=true` - Only active products
        - `?active=false` - Only inactive products
        - `?location=A1` - Filter by location (partial match)

        **Ordering:**
        - `?ordering=code` - Sort by code ascending
        - `?ordering=-code` - Sort by code descending
        - `?ordering=location` - Sort by location
        - `?ordering=description` - Sort by description

        **Example:** `GET /api/products/?search=widget&active=true&ordering=location`
        """
    ),
    retrieve=extend_schema(
        summary="Get product details",
        description="Retrieve details of a specific product by its ID, including recent order history."
    ),
    create=extend_schema(
        summary="Create a new product",
        description="""
        Create a new product in the system.

        The `code` field should contain the product's barcode or QR code that will be
        scanned during picking operations. The `location` field describes where the
        product is stored in the warehouse (e.g., "A1-RIJ16-12").

        The `customer` field is automatically set based on the authenticated user's profile.
        """
    ),
    update=extend_schema(
        summary="Update a product",
        description="Update all fields of an existing product."
    ),
    partial_update=extend_schema(
        summary="Partially update a product",
        description="Update specific fields of an existing product."
    ),
    destroy=extend_schema(
        summary="Delete a product",
        description="Delete a product from the system. Note: Products that are used in order lines cannot be deleted."
    ),
)
@extend_schema(
    tags=["products"],
    examples=[
        OpenApiExample(
            name="Product example",
            description="An example product object. code contains the barcode or QR code used to identify the product. "
                        "location describes the product's physical storage location within the warehouse.",
            value={
                "code": "1234567",
                "description": "An example product",
                "location": "A1-RIJ16-12",
                "active": True
            },
            request_only=True
        )
    ]
)
class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.none()  # Required for drf-spectacular
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['code', 'description']
    ordering_fields = ['code', 'description', 'location', 'active', 'product_id']
    ordering = ['location', 'code']

    def get_queryset(self):
        queryset = Product.objects.filter(customer=self.request.user.userprofile.customer)

        # Manual filtering
        active = self.request.query_params.get('active')
        if active is not None:
            queryset = queryset.filter(active=active.lower() == 'true')

        location = self.request.query_params.get('location')
        if location:
            queryset = queryset.filter(location__icontains=location)

        return queryset

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ProductDetailSerializer
        return ProductSerializer

    def perform_create(self, serializer):
        serializer.save(customer=self.request.user.userprofile.customer)

    @extend_schema(
        summary="Get product statistics",
        description="Get statistics about products including counts by status and location.",
        responses={
            200: OpenApiResponse(
                description="Product statistics",
                examples=[
                    OpenApiExample(
                        name="Statistics Response",
                        value={
                            "total_products": 150,
                            "active_products": 142,
                            "inactive_products": 8,
                            "products_in_orders": 98,
                            "locations": [
                                {"location": "A1", "count": 45},
                                {"location": "A2", "count": 38}
                            ]
                        }
                    )
                ]
            )
        }
    )
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get product statistics for the customer."""
        customer = request.user.userprofile.customer
        products = Product.objects.filter(customer=customer)

        # Products that are in at least one order
        products_in_orders = products.filter(
            product_id__in=OrderLine.objects.values('product_id').distinct()
        ).count()

        # Group by location prefix (first part before dash)
        location_stats = products.values('location').annotate(
            count=Count('product_id')
        ).order_by('-count')[:10]

        return Response({
            'total_products': products.count(),
            'active_products': products.filter(active=True).count(),
            'inactive_products': products.filter(active=False).count(),
            'products_in_orders': products_in_orders,
            'locations': list(location_stats)
        })

    @extend_schema(
        summary="Lookup product by code",
        description="Find a product by its exact barcode/QR code. Useful for scanning operations.",
        parameters=[
            OpenApiParameter(
                name='code',
                description='The exact product code to look up',
                required=True,
                type=str
            )
        ],
        responses={
            200: ProductDetailSerializer,
            404: OpenApiResponse(description="Product not found")
        }
    )
    @action(detail=False, methods=['get'])
    def lookup(self, request):
        """Look up a product by its exact code."""
        code = request.query_params.get('code')
        if not code:
            return Response(
                {'detail': 'Code parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            product = Product.objects.get(
                code=code,
                customer=request.user.userprofile.customer
            )
            serializer = ProductDetailSerializer(product)
            return Response(serializer.data)
        except Product.DoesNotExist:
            return Response(
                {'detail': 'Product not found'},
                status=status.HTTP_404_NOT_FOUND
            )

    @extend_schema(
        summary="Bulk activate/deactivate products",
        description="Activate or deactivate multiple products at once.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "List of product IDs to update"
                    },
                    "active": {
                        "type": "boolean",
                        "description": "Set to true to activate, false to deactivate"
                    }
                },
                "required": ["product_ids", "active"]
            }
        },
        responses={
            200: OpenApiResponse(
                description="Products updated",
                examples=[
                    OpenApiExample(
                        name="Success Response",
                        value={"updated_count": 5, "message": "Products updated successfully"}
                    )
                ]
            )
        }
    )
    @action(detail=False, methods=['post'])
    def bulk_update_status(self, request):
        """Bulk activate or deactivate products."""
        product_ids = request.data.get('product_ids', [])
        active = request.data.get('active')

        if active is None:
            return Response(
                {'detail': 'active field is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        updated = Product.objects.filter(
            product_id__in=product_ids,
            customer=request.user.userprofile.customer
        ).update(active=active)

        return Response({
            'updated_count': updated,
            'message': 'Products updated successfully'
        })
