from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from api.serializers import ProductPickSerializer, ProductPickUpdateSerializer
from orderpiqrApp.models import ProductPick
from rest_framework import filters
from django.db.models import Avg, Count
from django.db import transaction
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiResponse


@extend_schema_view(
    list=extend_schema(
        summary="List all product picks",
        description="""
        Retrieve a list of all product picks for pick lists belonging to the authenticated user's customer.

        **Search:** Use the `?search=` query parameter to filter by product description or code.

        **Filtering:**
        - `?picklist=1` - Filter by pick list ID
        - `?product=123` - Filter by product ID
        - `?successful=true` - Only successful picks
        - `?successful=false` - Only failed picks

        **Ordering:**
        - `?ordering=product__location` - Sort by product location (useful for picking order)
        - `?ordering=-successful` - Sort by success status

        Product picks represent individual products within a pick list.
        """
    ),
    retrieve=extend_schema(
        summary="Get product pick details",
        description="Retrieve details of a specific product pick with full product information."
    ),
    create=extend_schema(
        summary="Create a product pick",
        description="""
        Create a new product pick entry.

        **Note:** Product picks are typically created automatically when an order is claimed
        from the queue. Use this endpoint for manual adjustments or ad-hoc picking.
        """
    ),
    update=extend_schema(
        summary="Update a product pick",
        description="Update product pick details, such as marking it as successful or recording notes."
    ),
    partial_update=extend_schema(
        summary="Partially update a product pick",
        description="Update specific fields of a product pick (e.g., mark as successful)."
    ),
    destroy=extend_schema(
        summary="Delete a product pick",
        description="**Not allowed.** Product picks cannot be deleted to maintain audit trails."
    ),
)
@extend_schema(
    tags=["productpicks"],
    examples=[
        OpenApiExample(
            name="ProductPick Example",
            description="A product pick entry within a pick list",
            value={
                "picklist": 1,
                "product": 123,
                "quantity": 1,
                "successful": True,
                "notes": ""
            },
            request_only=True
        )
    ]
)
class ProductPickViewSet(viewsets.ModelViewSet):
    queryset = ProductPick.objects.none()  # Required for drf-spectacular
    serializer_class = ProductPickSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['product__description', 'product__code']
    ordering_fields = ['product__code', 'product__location', 'successful', 'quantity']
    ordering = ['product__location']

    def get_queryset(self):
        queryset = ProductPick.objects.filter(
            picklist__customer=self.request.user.userprofile.customer
        ).select_related('product', 'picklist')

        # Manual filtering
        picklist_id = self.request.query_params.get('picklist')
        if picklist_id:
            queryset = queryset.filter(picklist_id=picklist_id)

        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)

        successful = self.request.query_params.get('successful')
        if successful is not None:
            if successful.lower() == 'true':
                queryset = queryset.filter(successful=True)
            elif successful.lower() == 'false':
                queryset = queryset.filter(successful=False)

        return queryset

    def destroy(self, request, *args, **kwargs):
        return Response({'detail': 'Delete not allowed.'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @extend_schema(
        summary="Mark pick as successful",
        description="Quick action to mark a product pick as successful.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "notes": {"type": "string", "description": "Optional notes"}
                }
            }
        },
        responses={
            200: OpenApiResponse(
                description="Pick marked as successful",
                examples=[
                    OpenApiExample(
                        name="Success Response",
                        value={"status": "ok", "message": "Pick marked as successful"}
                    )
                ]
            )
        }
    )
    @action(detail=True, methods=['post'])
    def success(self, request, pk=None):
        """Mark a product pick as successful."""
        pick = self.get_object()
        pick.successful = True
        pick.notes = request.data.get('notes', pick.notes)
        pick.save(update_fields=['successful', 'notes'])

        return Response({
            'status': 'ok',
            'message': 'Pick marked as successful'
        })

    @extend_schema(
        summary="Mark pick as failed",
        description="Quick action to mark a product pick as failed.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "notes": {"type": "string", "description": "Reason for failure (recommended)"}
                }
            }
        },
        responses={
            200: OpenApiResponse(
                description="Pick marked as failed",
                examples=[
                    OpenApiExample(
                        name="Success Response",
                        value={"status": "ok", "message": "Pick marked as failed"}
                    )
                ]
            )
        }
    )
    @action(detail=True, methods=['post'])
    def fail(self, request, pk=None):
        """Mark a product pick as failed."""
        pick = self.get_object()
        pick.successful = False
        pick.notes = request.data.get('notes', pick.notes)
        pick.save(update_fields=['successful', 'notes'])

        return Response({
            'status': 'ok',
            'message': 'Pick marked as failed'
        })

    @extend_schema(
        summary="Bulk update product picks",
        description="""
        Update multiple product picks at once. Useful for batch processing pick results.

        **Request body:**
        ```json
        {
            "picks": [
                {"id": 1, "successful": true},
                {"id": 2, "successful": true},
                {"id": 3, "successful": false, "notes": "Out of stock"}
            ]
        }
        ```
        """,
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "picks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer"},
                                "successful": {"type": "boolean"},
                                "notes": {"type": "string"}
                            },
                            "required": ["id", "successful"]
                        }
                    }
                },
                "required": ["picks"]
            }
        },
        responses={
            200: OpenApiResponse(
                description="Picks updated",
                examples=[
                    OpenApiExample(
                        name="Success Response",
                        value={"status": "ok", "updated_count": 3}
                    )
                ]
            )
        }
    )
    @action(detail=False, methods=['post'])
    def bulk_update(self, request):
        """Bulk update multiple product picks."""
        picks_data = request.data.get('picks', [])

        if not picks_data:
            return Response(
                {'detail': 'No picks provided'},
                status=status.HTTP_400_BAD_REQUEST
            )

        customer = request.user.userprofile.customer
        updated_count = 0

        with transaction.atomic():
            for pick_data in picks_data:
                pick_id = pick_data.get('id')
                if not pick_id:
                    continue

                try:
                    pick = ProductPick.objects.get(
                        id=pick_id,
                        picklist__customer=customer
                    )
                    pick.successful = pick_data.get('successful')
                    if 'notes' in pick_data:
                        pick.notes = pick_data['notes']
                    pick.save()
                    updated_count += 1
                except ProductPick.DoesNotExist:
                    continue

        return Response({
            'status': 'ok',
            'updated_count': updated_count
        })

    @extend_schema(
        summary="Get picks by picklist",
        description="Get all product picks for a specific pick list, sorted by product location for efficient picking.",
        responses={200: ProductPickSerializer(many=True)}
    )
    @action(detail=False, methods=['get'], url_path='by-picklist/(?P<picklist_id>[^/.]+)')
    def by_picklist(self, request, picklist_id=None):
        """Get all product picks for a specific pick list."""
        picks = ProductPick.objects.filter(
            picklist_id=picklist_id,
            picklist__customer=request.user.userprofile.customer
        ).select_related('product').order_by('product__location')

        serializer = ProductPickSerializer(picks, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Get product pick statistics",
        description="Get statistics about product picks including success rates.",
        responses={
            200: OpenApiResponse(
                description="Product pick statistics",
                examples=[
                    OpenApiExample(
                        name="Statistics Response",
                        value={
                            "total_picks": 1500,
                            "successful": 1450,
                            "failed": 30,
                            "pending": 20,
                            "success_rate": 98.0,
                            "avg_quantity": 1.2,
                            "problem_products": [
                                {"product_id": 5, "code": "PROD-005", "failure_count": 8}
                            ]
                        }
                    )
                ]
            )
        }
    )
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get product pick statistics."""
        customer = request.user.userprofile.customer
        picks = ProductPick.objects.filter(picklist__customer=customer)

        successful = picks.filter(successful=True).count()
        failed = picks.filter(successful=False).count()
        total_completed = successful + failed
        success_rate = round((successful / total_completed * 100) if total_completed > 0 else 0, 1)

        # Products with most failures
        problem_products = picks.filter(successful=False).values(
            'product__product_id', 'product__code', 'product__description'
        ).annotate(
            failure_count=Count('id')
        ).order_by('-failure_count')[:5]

        return Response({
            'total_picks': picks.count(),
            'successful': successful,
            'failed': failed,
            'pending': picks.filter(successful__isnull=True).count(),
            'success_rate': success_rate,
            'avg_quantity': picks.aggregate(avg=Avg('quantity'))['avg'] or 0,
            'problem_products': [
                {
                    'product_id': p['product__product_id'],
                    'code': p['product__code'],
                    'description': p['product__description'],
                    'failure_count': p['failure_count']
                }
                for p in problem_products
            ]
        })
